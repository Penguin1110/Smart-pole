"""BaseImputer 契約測試——確保任何子類都能被 runner 安全呼叫。

涵蓋:
  - 抽象方法不實作 → 不可實例化
  - @register 必須要有非預設 name
  - @register 重複名稱拒絕
  - 子類能正常 fit / predict / get_config
"""
from __future__ import annotations

import numpy as np
import pytest

from smart_pole.models.base import BaseImputer
from smart_pole.models.registry import _REGISTRY, get_model, list_models, register


def test_cannot_instantiate_base() -> None:
    with pytest.raises(TypeError):
        BaseImputer()  # type: ignore[abstract]


def test_registry_rejects_unset_name() -> None:
    class Bad(BaseImputer):
        # 沒覆寫 name,預設為 'base'
        def fit(self, X, y, meta): return self
        def predict(self, X, meta): return np.zeros(len(X))

    with pytest.raises(ValueError, match="name"):
        register(Bad)


def test_registry_rejects_duplicate() -> None:
    @register
    class _Dup1(BaseImputer):
        name = "_test_dup"; tier = 1
        def fit(self, X, y, meta): return self
        def predict(self, X, meta): return np.zeros(len(X))

    try:
        with pytest.raises(ValueError, match="已被"):
            class _Dup2(BaseImputer):
                name = "_test_dup"; tier = 1
                def fit(self, X, y, meta): return self
                def predict(self, X, meta): return np.zeros(len(X))
            register(_Dup2)
    finally:
        _REGISTRY.pop("_test_dup", None)


def test_get_model_unknown_lists_options() -> None:
    with pytest.raises(KeyError, match="找不到模型"):
        get_model("definitely-not-a-real-model")


def test_subclass_full_lifecycle() -> None:
    @register
    class Const(BaseImputer):
        name = "_test_const"; tier = 1
        def fit(self, X, y, meta):
            self._fitted = True
            return self
        def predict(self, X, meta):
            return np.full(len(X), self.params.get("c", 0.0))

    try:
        m = Const(c=3.14)
        m.fit(np.zeros((5, 3)), np.zeros(5), meta={"target_station_id": "x"})
        assert m._fitted is True
        out = m.predict(np.zeros((4, 3)), meta={})
        assert out.shape == (4,)
        np.testing.assert_allclose(out, 3.14)
        cfg = m.get_config()
        assert cfg["name"] == "_test_const"
        assert cfg["tier"] == 1
        assert cfg["params"] == {"c": 3.14}
        assert "_test_const" in list_models()
    finally:
        _REGISTRY.pop("_test_const", None)
