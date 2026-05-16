"""Phase 3 時空特徵工程套件。

目前只有 ``temporal.TemporalFeatureBuilder``——給 Phase 3c / 3b 線性時空模型用。
``features.enabled=false``(預設)時整個包不會被 import,Phase 1/2 行為完全不受影響。
"""
from __future__ import annotations

from .temporal import TemporalFeatureBuilder

__all__ = ["TemporalFeatureBuilder"]
