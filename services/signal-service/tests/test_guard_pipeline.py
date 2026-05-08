from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys


SERVICE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(SERVICE_SRC) not in sys.path:
    sys.path.insert(0, str(SERVICE_SRC))

from risk import GuardConfig, GuardPipeline


def test_guard_pipeline_passes_with_safe_input() -> None:
    now = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
    pipeline = GuardPipeline(
        GuardConfig(
            max_position_pct=0.5,
            max_single_symbol_pct=0.3,
            max_signal_age_seconds=600,
        )
    )

    result = pipeline.validate_trade_intent(
        symbol="BTCUSDT",
        side="LONG",
        size_pct=0.1,
        current_positions={"ETHUSDT": 0.1},
        current_equity=10000,
        peak_equity=11000,
        last_signal_ts=now - timedelta(seconds=30),
        now=now,
    )

    assert result.passed is True
    assert result.failed_rules == []
    assert result.risk_level == "low"


def test_guard_pipeline_blocks_blacklist_immediately() -> None:
    now = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
    pipeline = GuardPipeline(
        GuardConfig(
            blacklist=["BTCUSDT"],
            stop_on_high_risk=True,
        )
    )

    result = pipeline.validate_trade_intent(
        symbol="BTCUSDT",
        side="LONG",
        size_pct=0.1,
        current_positions={},
        current_equity=10000,
        peak_equity=10000,
        last_signal_ts=now,
        now=now,
    )

    assert result.passed is False
    assert result.failed_rules == ["blacklist"]
    assert result.risk_level == "high"


def test_guard_pipeline_reports_multiple_medium_failures() -> None:
    now = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
    pipeline = GuardPipeline(
        GuardConfig(
            whitelist=["ETHUSDT"],
            max_single_symbol_pct=0.2,
            cooldown_seconds=300,
            stop_on_high_risk=False,
        )
    )
    pipeline.record_trade("BTCUSDT", ts=now - timedelta(seconds=60))

    result = pipeline.validate_trade_intent(
        symbol="BTCUSDT",
        side="LONG",
        size_pct=0.15,
        current_positions={"BTCUSDT": 0.1},
        current_equity=10000,
        peak_equity=10000,
        last_signal_ts=now,
        now=now,
    )

    assert result.passed is False
    assert "whitelist" in result.failed_rules
    assert "max_single_symbol" in result.failed_rules
    assert "cooldown" in result.failed_rules
    assert result.risk_level == "medium"


def test_guard_pipeline_blocks_drawdown() -> None:
    now = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
    pipeline = GuardPipeline(GuardConfig(max_drawdown_pct=0.1))

    result = pipeline.validate_trade_intent(
        symbol="BTCUSDT",
        side="LONG",
        size_pct=0.1,
        current_positions={},
        current_equity=8000,
        peak_equity=10000,
        last_signal_ts=now,
        now=now,
    )

    assert result.passed is False
    assert "max_drawdown" in result.failed_rules
    assert result.risk_level == "high"


def test_guard_pipeline_blocks_stale_signal_data() -> None:
    now = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
    pipeline = GuardPipeline(GuardConfig(max_signal_age_seconds=120))

    result = pipeline.validate_trade_intent(
        symbol="BTCUSDT",
        side="LONG",
        size_pct=0.1,
        current_positions={},
        current_equity=10000,
        peak_equity=10000,
        last_signal_ts=now - timedelta(minutes=10),
        now=now,
    )

    assert result.passed is False
    assert "data_freshness" in result.failed_rules
    assert result.risk_level == "high"
