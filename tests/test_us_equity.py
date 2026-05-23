"""US equity symbol + provider unit tests."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pandas as pd
import pytest

from tradecat.core.providers.registry import ProviderRegistry
from tradecat.core.providers.us_equity import UsEquityProvider, _minute_series_to_df, _resample_ohlcv
from tradecat.core.symbols import (
    default_provider_for_market,
    default_symbols_for_market,
    infer_market_from_symbol,
    is_close_only_sell,
    normalize_symbol,
    normalize_symbols_for_strategy,
    signal_symbol_for_engine,
)
from tradecat.core.symbols.equity import normalize_us_ticker


def test_infer_market_from_symbol() -> None:
    assert infer_market_from_symbol("NVDA") == "us_stock"
    assert infer_market_from_symbol("BTC_USDT") == "crypto"
    assert infer_market_from_symbol("ETHUSDT") == "crypto"


def test_normalize_us_ticker() -> None:
    assert normalize_us_ticker("nvda") == "NVDA"
    assert normalize_us_ticker("NVDA.US") == "NVDA"
    assert normalize_us_ticker("BTC_USDT") == ""
    assert normalize_symbol("NVDA", "us_stock") == "NVDA"
    assert normalize_symbol("BTC_USDT", "crypto") == "BTC_USDT"
    assert normalize_symbol("NVDA") == "NVDA"
    assert normalize_symbol("BTC") == "BTC_USDT"
    assert normalize_symbol("BTCUSDT") == "BTC_USDT"


def test_default_provider_for_market() -> None:
    assert default_provider_for_market("us_stock") == "us_equity"
    assert default_provider_for_market("crypto") == "gate"


def test_strategy_symbols_us() -> None:
    syms = normalize_symbols_for_strategy(["nvda", "META.US", "BTC_USDT"], "us_stock")
    assert syms == ["NVDA", "META"]


def test_signal_symbol_for_engine() -> None:
    assert signal_symbol_for_engine("NVDA", "us_stock") == "NVDA"
    assert signal_symbol_for_engine("BTC_USDT", "crypto") == "BTCUSDT"


def test_minute_series_to_df_and_resample() -> None:
    series = [(1_700_000_000, 100.0, 1000.0), (1_700_000_060, 101.0, 1100.0), (1_700_000_120, 102.0, 1200.0)]
    df = _minute_series_to_df(series)
    assert len(df) == 3
    resampled = _resample_ohlcv(df, "5m")
    assert len(resampled) >= 1
    assert "close" in resampled.columns


@pytest.mark.asyncio
async def test_us_equity_provider_fetch_klines_mock() -> None:
    provider = UsEquityProvider()
    fake_series = [(1_700_000_000 + i * 60, 100.0 + i, 1000.0 + i * 10) for i in range(30)]
    with patch(
        "tradecat.core.providers.us_equity._fetch_us_minute_series_sync",
        return_value=fake_series,
    ):
        df = await provider.fetch_klines("NVDA", "5m", limit=10)
    assert isinstance(df, pd.DataFrame)
    assert len(df) >= 1


def test_market_helpers() -> None:
    assert is_close_only_sell("us_stock") is True
    assert is_close_only_sell("crypto") is False
    assert "NVDA" in default_symbols_for_market("us_stock")


def test_registry_includes_us_equity() -> None:
    reg = ProviderRegistry()
    reg.auto_register()
    names = [p.name for p in reg.list_providers()]
    assert "us_equity" in names
    assert reg.resolve_by_name("us_equity").can_resolve("NVDA")
