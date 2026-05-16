"""模型 registry——`@register` decorator 把 BaseImputer 子類掛進全域表,
config YAML 用 ``model.name`` 字串即可取得 class。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BaseImputer


_REGISTRY: dict[str, type["BaseImputer"]] = {}


def register(cls: type["BaseImputer"]) -> type["BaseImputer"]:
    """把模型 class 註冊進 registry,key 用 ``cls.name``。

    Phase 3 規則:``tier >= 3`` 的模型必須宣告 ``explainability >= 8``,
    否則直接拒絕(CLAUDE.md 硬規定)。
    """
    name = getattr(cls, "name", None)
    if not name or name == "base":
        raise ValueError(
            f"模型 {cls.__name__} 必須設定 class-level `name` 屬性,且不可為 'base'"
        )
    if name in _REGISTRY and _REGISTRY[name] is not cls:
        raise ValueError(
            f"模型名稱 '{name}' 已被 {_REGISTRY[name].__name__} 佔用,"
            f"無法重複註冊到 {cls.__name__}"
        )
    tier = int(getattr(cls, "tier", 0))
    expl = int(getattr(cls, "explainability", 0))
    if tier >= 3 and expl < 8:
        raise ValueError(
            f"模型 {cls.__name__} (name={name!r}, tier={tier}) 的 explainability={expl} < 8,"
            f"違反 Phase 3 規範。請先把可解釋性提到 8 再說(CLAUDE.md 硬規定)"
        )
    _REGISTRY[name] = cls
    return cls


def get_model(name: str) -> type["BaseImputer"]:
    """依名稱取出模型 class。找不到時列出所有已註冊的 key。"""
    if name not in _REGISTRY:
        raise KeyError(
            f"找不到模型 '{name}'。已註冊:{sorted(_REGISTRY.keys())}。"
            f"確認:(1) 模型檔有 import,(2) 有 @register decorator,(3) class.name 拼字正確"
        )
    return _REGISTRY[name]


def list_models() -> list[str]:
    return sorted(_REGISTRY.keys())
