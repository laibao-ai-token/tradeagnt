"""Background signal poller: run SignalEngine and append to signal_history.db for TUI."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
import time
from pathlib import Path

from tradecat.core.indicators import auto_register as auto_register_indicators
from tradecat.core.indicators.base import IndicatorRegistry
from tradecat.core.providers.registry import ProviderRegistry
from tradecat.core.signals import CooldownManager, SignalEngine, StrategyLoader
from tradecat.core.symbols import (
    default_provider_for_market,
    normalize_market,
    normalize_symbols_for_strategy,
    signal_symbol_for_engine,
)
from tradecat.tui._helpers import _signal_timestamp_now


def _ensure_signal_db(db_path: str) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                strength INTEGER DEFAULT 0,
                message TEXT,
                timeframe TEXT,
                price REAL,
                source TEXT
            )
            """
        )
        conn.commit()


def _persist_signals(db_path: str, signals: list, *, timeframe: str, source: str, market: str) -> int:
    if not signals:
        return 0
    _ensure_signal_db(db_path)
    written = 0
    with sqlite3.connect(db_path, timeout=5) as conn:
        for s in signals:
            ts_text = _signal_timestamp_now()
            norm = (normalize_symbols_for_strategy([s.symbol], market) or [s.symbol])[0]
            conn.execute(
                """
                INSERT INTO signal_history
                (timestamp, symbol, signal_type, direction, strength, price, message, timeframe, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts_text,
                    norm,
                    (getattr(s, "rule_id", None) or s.rule_name or "signal")[:50],
                    s.direction,
                    int(s.strength),
                    float(s.price) if s.price is not None else 0.0,
                    (s.message or "")[:200],
                    timeframe,
                    source,
                ),
            )
            written += 1
        conn.commit()
    return written


def start_signal_poller(
    db_path: str,
    symbols: list[str],
    *,
    strategy: str = "current/fast_1m.yaml",
    provider: str = "",
    interval_s: float = 60.0,
    min_strength: int = 50,
) -> threading.Thread | None:
    """Start daemon thread scanning symbols and writing signals to SQLite."""
    enabled = os.getenv("TUI_SIGNAL_POLLER", "1").strip().lower() not in ("0", "false", "no", "off")
    if not enabled:
        return None

    strategy_name = os.getenv("TUI_SIGNAL_STRATEGY", strategy).strip() or strategy
    try:
        strat = StrategyLoader.load(strategy_name)
    except Exception:
        return None

    market = normalize_market(strat.market)
    symbol_list = normalize_symbols_for_strategy(symbols or list(strat.symbols), market)
    if not symbol_list:
        symbol_list = (
            normalize_symbols_for_strategy(["NVDA", "META"], "us_stock")
            if market == "us_stock"
            else normalize_symbols_for_strategy(["BTC_USDT", "ETH_USDT"], "crypto")
        )

    try:
        interval = float(os.getenv("TUI_SIGNAL_POLL_INTERVAL_S", str(interval_s)).strip() or interval_s)
    except Exception:
        interval = interval_s
    interval = max(30.0, interval)

    provider_name = (
        os.getenv("TUI_SIGNAL_PROVIDER", provider).strip() or provider or default_provider_for_market(market)
    )
    try:
        min_str = int(os.getenv("TUI_SIGNAL_MIN_STRENGTH", str(min_strength)).strip() or min_strength)
    except Exception:
        min_str = min_strength

    def _run() -> None:
        provider_registry = ProviderRegistry()
        provider_registry.auto_register()
        auto_register_indicators()
        indicator_registry = IndicatorRegistry()
        cooldown = CooldownManager()
        engine = SignalEngine(provider_registry, indicator_registry, cooldown)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        while True:
            try:
                for symbol in symbol_list:
                    try:
                        run_symbol = signal_symbol_for_engine(symbol, market)
                        signals = loop.run_until_complete(
                            engine.run(strat, run_symbol, provider_name)
                        )
                        strong = [s for s in signals if int(s.strength) >= min_str]
                        if strong:
                            _persist_signals(
                                db_path,
                                strong,
                                timeframe=strat.timeframe,
                                source="tui_poller",
                                market=market,
                            )
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(interval)

    t = threading.Thread(target=_run, name=f"signal-poller-{market}", daemon=True)
    t.start()
    return t


def start_signal_pollers(
    db_path: str,
    symbols: list[str],
    *,
    strategy: str = "current/fast_1m.yaml",
    provider: str = "",
    interval_s: float = 60.0,
    min_strength: int = 50,
) -> list[threading.Thread]:
    """Start primary (+ optional TUI_SIGNAL_STRATEGY_EXTRA) background pollers."""
    threads: list[threading.Thread] = []
    primary = (os.getenv("TUI_SIGNAL_STRATEGY", strategy).strip() or strategy)
    extra = (os.getenv("TUI_SIGNAL_STRATEGY_EXTRA") or "").strip()
    paths = [primary]
    if extra and extra not in paths:
        paths.append(extra)

    for idx, path in enumerate(paths):
        poll_syms = symbols if idx == 0 else []
        t = start_signal_poller(
            db_path,
            poll_syms,
            strategy=path,
            provider=provider,
            interval_s=interval_s,
            min_strength=min_strength,
        )
        if t is not None:
            threads.append(t)
    return threads
