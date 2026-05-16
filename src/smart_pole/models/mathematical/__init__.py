"""Tier 3 mathematical 模型——Phase 3a 純空間 + 3b 時空。

import 此 package 觸發各模型 @register。可解釋性 ≥ 8 是硬規定(registry 把關)。
"""
from __future__ import annotations

from . import idw_optimal     # noqa: F401
from . import kriging         # noqa: F401
from . import gp_spatial      # noqa: F401
from . import timelag_ridge   # noqa: F401
from . import elastic_net     # noqa: F401
from . import gls             # noqa: F401
from . import dineof          # noqa: F401
from . import st_gp           # noqa: F401
