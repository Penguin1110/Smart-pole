"""Models 套件——import 此 package 會觸發各 tier 子套件,讓 @register 完成註冊。"""
from __future__ import annotations

from . import baseline  # noqa: F401  觸發 baseline 模型註冊
from . import weighted  # noqa: F401  觸發 weighted 模型註冊
