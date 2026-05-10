from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tradecat.core.models.signal import Strategy


class StrategyLoader:
    """YAML 策略加载器."""

    @staticmethod
    def load(path: str) -> Strategy:
        """从 YAML 文件加载策略并返回 Strategy 模型."""
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Strategy file not found: {path}")

        with p.open("r", encoding="utf-8") as fh:
            data: dict[str, Any] = yaml.safe_load(fh)

        return Strategy.model_validate(data)
