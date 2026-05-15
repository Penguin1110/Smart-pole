"""Tier 2 weighted 模型——import 觸發各模型 @register。"""
from __future__ import annotations

from . import idw  # noqa: F401
from . import corr_weighted  # noqa: F401
from . import gaussian_kernel  # noqa: F401
from . import weighted_ridge  # noqa: F401
