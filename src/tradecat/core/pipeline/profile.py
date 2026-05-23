"""Load ``config/pipeline/*.yaml`` and apply runtime env for TUI/daemon."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tradecat.core.paper_trading.paths import default_signal_db_path, find_tradeagnt_repo_root


@dataclass(frozen=True)
class PipelineProfile:
    name: str
    description: str
    strategy_paths: tuple[str, ...]
    poll_interval_s: int
    min_strength: int
    signal_db_path: str
    paper_enabled: bool
    paper_markets: str
    paper_notional_pct: float
    paper_trade_cooldown_s: int
    paper_min_strength: int
    paper_min_equity_ratio: float

    @property
    def primary_strategy(self) -> str:
        return self.strategy_paths[0] if self.strategy_paths else "current/fast_1m.yaml"

    @property
    def extra_strategy(self) -> str:
        return self.strategy_paths[1] if len(self.strategy_paths) > 1 else ""


def _repo_root() -> Path:
    return find_tradeagnt_repo_root()


def _profile_path(name: str, repo_root: Path | None = None) -> Path:
    root = repo_root or _repo_root()
    token = (name or "").strip()
    if not token:
        raise ValueError("pipeline profile name is empty")
    if token.endswith(".yaml"):
        path = Path(token)
        if not path.is_absolute():
            path = root / "config" / "pipeline" / path.name
        return path
    return root / "config" / "pipeline" / f"{token}.yaml"


def _coerce_markets(raw: Any) -> str:
    if raw is None:
        return "crypto"
    if isinstance(raw, list):
        items = [str(x).strip().lower() for x in raw if str(x).strip()]
        if not items:
            return "crypto"
        if len(items) > 1:
            return "all"
        one = items[0]
        if one in {"all", "*", "both", "dual"}:
            return "all"
        return one
    text = str(raw).strip().lower()
    if text in {"all", "*", "both", "dual"}:
        return "all"
    return text or "crypto"


def _strategy_paths(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ("current/fast_1m.yaml",)
    paths: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            path = str(item.get("path") or "").strip()
            if path and item.get("enabled", True) is not False:
                paths.append(path)
        elif isinstance(item, str) and item.strip():
            paths.append(item.strip())
    return tuple(paths) if paths else ("current/fast_1m.yaml",)


def load_pipeline_profile(name: str, *, repo_root: Path | None = None) -> PipelineProfile:
    """Load a pipeline profile YAML by name (e.g. ``tui_dual``)."""
    path = _profile_path(name, repo_root)
    if not path.is_file():
        raise FileNotFoundError(f"pipeline profile not found: {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"invalid pipeline profile (not a mapping): {path}")

    runtime = data.get("runtime") if isinstance(data.get("runtime"), dict) else {}
    stores = data.get("stores") if isinstance(data.get("stores"), dict) else {}
    signal_store = stores.get("signal_history") if isinstance(stores.get("signal_history"), dict) else {}
    consumers = data.get("consumers") if isinstance(data.get("consumers"), dict) else {}
    paper = consumers.get("paper") if isinstance(consumers.get("paper"), dict) else {}

    db_path = str(signal_store.get("path") or "").strip()
    if not db_path:
        db_path = str(default_signal_db_path(repo_root or _repo_root()))

    return PipelineProfile(
        name=str(data.get("name") or name),
        description=str(data.get("description") or ""),
        strategy_paths=_strategy_paths(data.get("strategies")),
        poll_interval_s=int(float(runtime.get("poll_interval_s") or 60)),
        min_strength=int(runtime.get("min_strength") or 50),
        signal_db_path=db_path,
        paper_enabled=bool(paper.get("enabled", False)),
        paper_markets=_coerce_markets(paper.get("markets")),
        paper_notional_pct=float(paper.get("notional_pct") or 0.15),
        paper_trade_cooldown_s=int(paper.get("trade_cooldown_s") or 180),
        paper_min_strength=int(paper.get("min_strength") or runtime.get("min_strength") or 50),
        paper_min_equity_ratio=float(paper.get("min_equity_ratio") or 0.20),
    )


def apply_pipeline_profile(profile: PipelineProfile, *, only_if_unset: bool = True) -> None:
    """Apply profile fields to process env (TUI/daemon read these)."""

    def _set(key: str, value: str) -> None:
        if only_if_unset and os.getenv(key):
            return
        os.environ[key] = value

    _set("TUI_SIGNAL_STRATEGY", profile.primary_strategy)
    if profile.extra_strategy:
        _set("TUI_SIGNAL_STRATEGY_EXTRA", profile.extra_strategy)
    _set("TUI_SIGNAL_POLL_INTERVAL_S", str(profile.poll_interval_s))
    _set("TUI_SIGNAL_MIN_STRENGTH", str(profile.min_strength))

    if profile.paper_enabled:
        _set("PAPER_AUTO_MARKET", profile.paper_markets)
        _set("PAPER_AUTO_NOTIONAL_PCT", str(profile.paper_notional_pct))
        _set("PAPER_AUTO_TRADE_COOLDOWN_S", str(profile.paper_trade_cooldown_s))
        _set("PAPER_AUTO_MIN_STRENGTH", str(profile.paper_min_strength))
        _set("PAPER_AUTO_MIN_EQUITY_RATIO", str(profile.paper_min_equity_ratio))


def bootstrap_pipeline_profile(
    *,
    profile_name: str | None = None,
    repo_root: Path | None = None,
    only_if_unset: bool = True,
) -> PipelineProfile | None:
    """Load profile from ``TRADECAT_PIPELINE_PROFILE`` when set; return profile or None."""
    name = (profile_name or os.getenv("TRADECAT_PIPELINE_PROFILE") or "").strip()
    if not name:
        return None
    profile = load_pipeline_profile(name, repo_root=repo_root)
    apply_pipeline_profile(profile, only_if_unset=only_if_unset)
    return profile


def resolve_signal_db_path(profile: PipelineProfile | None = None) -> str:
    if profile and profile.signal_db_path:
        return profile.signal_db_path
    return str(default_signal_db_path())
