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
    def resolve_path(path: str) -> Path:
        """Resolve strategy YAML path (supports ``current/`` and ``releases/<id>/``)."""
        raw = (path or "").strip()
        if not raw:
            raise FileNotFoundError("Strategy path is empty")

        p = Path(raw)
        if p.is_file():
            return p.resolve()

        name = p.name
        rel_parts = p.parts

        candidates: list[Path] = []
        for base in StrategyLoader._SEARCH_PATHS:
            if not base.is_dir():
                continue
            candidates.append(base / raw)
            if len(rel_parts) == 1:
                candidates.append(base / "current" / name)
            candidates.append(base / "current" / raw)

        seen: set[Path] = set()
        for candidate in candidates:
            c = candidate.resolve()
            if c in seen:
                continue
            seen.add(c)
            if c.is_file():
                return c

        raise FileNotFoundError(f"Strategy file not found: {path}")

    @staticmethod
    def load(path: str) -> StrategyConfig:
        """Load strategy from YAML file.

        Search order: absolute/explicit path → ``config/strategies/<path>`` →
        ``config/strategies/current/<file>`` (when *path* is a bare filename).
        """
        p = StrategyLoader.resolve_path(path)

        with p.open("r", encoding="utf-8") as fh:
            data: dict[str, Any] = yaml.safe_load(fh)

        return StrategyConfig.model_validate(data)
