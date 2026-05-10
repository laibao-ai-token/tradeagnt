"""Unified settings loader from ``.env`` files."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from tradecat.common.config_loader import find_repo_root

Mode = Literal["tui", "daemon", "backtest", "analyze"]


class _Settings:
    """Simple settings container backed by environment variables."""

    def __init__(self) -> None:
        self._load()

    def _load(self) -> None:
        root = find_repo_root()
        # 优先加载根目录 .env，fallback 到 config/.env
        for rel in (".env", "config/.env"):
            env_path = root / rel
            if env_path.exists():
                load_dotenv(dotenv_path=str(env_path), override=False)
                break

    # -------- general --------

    @property
    def mode(self) -> str:
        return os.getenv("TRADECAT_MODE", "tui")

    @property
    def debug(self) -> bool:
        return os.getenv("TRADECAT_DEBUG", "").lower() in ("1", "true", "yes")

    @property
    def log_level(self) -> str:
        return os.getenv("TRADECAT_LOG_LEVEL", "INFO")

    # -------- paths --------

    @property
    def repo_root(self) -> Path:
        return find_repo_root()

    @property
    def config_path(self) -> Path:
        return self.repo_root / "config"

    # -------- database --------

    @property
    def database_url(self) -> str:
        return os.getenv("DATABASE_URL", "postgresql://postgres:***@localhost:5434/market_data")

    # -------- API / Proxy --------

    @property
    def proxy(self) -> str | None:
        return os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or None


settings = _Settings()
