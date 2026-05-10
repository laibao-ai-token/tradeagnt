"""YAML strategy loader with search-path resolution."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tradecat.core.signals.models import StrategyConfig


class StrategyLoader:
    """YAML strategy loader."""

    _SEARCH_PATHS: list[Path] = [
        Path.cwd() / "config" / "strategies",
        Path(__file__).parent.parent.parent.parent.parent / "config" / "strategies",
    ]

    @staticmethod
    def load(path: str) -> StrategyConfig:
        """Load strategy from YAML file.

        If *path* is not absolute and does not exist in CWD, search
        ``config/strategies/`` under both the current working directory
        and the project root.
        """
        p = Path(path)
        if not p.is_file():
            for base in StrategyLoader._SEARCH_PATHS:
                candidate = base / path
                if candidate.is_file():
                    p = candidate
                    break
        if not p.is_file():
            raise FileNotFoundError(f"Strategy file not found: {path}")

        with p.open("r", encoding="utf-8") as fh:
            data: dict[str, Any] = yaml.safe_load(fh)

        return StrategyConfig.model_validate(data)
