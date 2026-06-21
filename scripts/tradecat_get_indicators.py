#!/usr/bin/env python3
"""Compute technical indicators on K-lines (same library as SignalEngine)."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

TOOL_NAME = "tradecat_get_indicators"
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

MIN_BARS = 30

DEFAULT_INDICATORS: list[dict[str, Any]] = [
    {"name": "rsi", "params": {"period": 14}},
    {"name": "ema", "params": {"fast": 7, "medium": 25, "slow": 99}},
    {"name": "macd", "params": {}},
]

MARKET_ALIASES = {
    "cn": "cn_stock",
    "cn_stock": "cn_stock",
    "hk": "hk_stock",
    "hk_stock": "hk_stock",
    "us": "us_stock",
    "us_stock": "us_stock",
    "crypto": "crypto_spot",
    "crypto_spot": "crypto_spot",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _infer_market(symbol: str, market_hint: str = "") -> str:
    hint = MARKET_ALIASES.get((market_hint or "").strip().lower(), (market_hint or "").strip().lower())
    if hint:
        return hint
    sym = (symbol or "").strip().upper()
    if sym.endswith("_USDT") or sym.endswith("USDT"):
        return "crypto_spot"
    if sym.startswith(("SH", "SZ")) and len(sym) >= 8:
        return "cn_stock"
    if sym.startswith("HK") and len(sym) >= 5:
        return "hk_stock"
    if sym.isalpha() and len(sym) <= 6:
        return "us_stock"
    return "crypto_spot"


def _is_daily_timeframe(timeframe: str) -> bool:
    tf = (timeframe or "").strip().lower()
    return tf in {"1d", "d", "day", "daily", "1day"}


def _daily_rows_to_df(rows: list[tuple[int, float, float, float, float, float]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    out = []
    for ts, o, h, l, c, v in rows:
        out.append(
            {
                "timestamp": pd.to_datetime(int(ts), unit="s", utc=True),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(v),
            }
        )
    return pd.DataFrame(out)


def _minute_triples_to_df(series: list[tuple[int, float, float]]) -> pd.DataFrame:
    if not series:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    rows = []
    prev_vol = 0.0
    for epoch_s, price, vol_cum in series:
        bar_vol = max(0.0, vol_cum - prev_vol) if vol_cum >= prev_vol else max(0.0, vol_cum)
        prev_vol = vol_cum
        p = float(price)
        rows.append(
            {
                "timestamp": pd.to_datetime(int(epoch_s), unit="s", utc=True),
                "open": p,
                "high": p,
                "low": p,
                "close": p,
                "volume": float(bar_vol),
            }
        )
    return pd.DataFrame(rows)


async def _fetch_klines_df(
    *,
    symbol: str,
    market: str,
    timeframe: str,
    limit: int,
    provider_name: str = "",
) -> tuple[pd.DataFrame, str, list[str]]:
    """Return (dataframe, source_note, warnings)."""
    warnings: list[str] = []
    src_path = str(REPO_ROOT / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    m = market
    tf = (timeframe or "5m").strip().lower()

    # A股/港股/基金：与 TUI 报价同源（东财日线 / 腾讯分钟），不走 Binance ProviderRegistry
    if m in {"cn_stock", "hk_stock", "cn_fund"}:
        from tradecat.tui.quote import fetch_daily_curve_1d, fetch_intraday_curve_1m

        minute_limit = max(MIN_BARS, min(limit, 240))

        def _minute_df() -> pd.DataFrame:
            series = fetch_intraday_curve_1m("tencent", m, symbol, timeout_s=8.0, limit=minute_limit)
            return _minute_triples_to_df(series)

        if _is_daily_timeframe(tf):
            rows = fetch_daily_curve_1d("tencent", m, symbol, timeout_s=8.0, limit=min(limit, 120))
            df = _daily_rows_to_df(rows)
            if len(df) >= MIN_BARS:
                return df, "tui.quote.eastmoney_daily", warnings
            warnings.append("eastmoney_daily_unavailable_fallback_tencent_minute")
            df = _minute_df()
            return df, "tui.quote.tencent_minute_daily_fallback", warnings

        df = _minute_df()
        if len(df) >= MIN_BARS:
            return df, "tui.quote.tencent_minute", warnings

        warnings.append("intraday_bars_insufficient_try_1d_or_retry")
        rows = fetch_daily_curve_1d("tencent", m, symbol, timeout_s=8.0, limit=min(max(limit, 60), 120))
        df = _daily_rows_to_df(rows)
        return df, "tui.quote.eastmoney_daily_fallback", warnings

    # 加密 / 美股：ProviderRegistry
    from tradecat.core.providers.registry import ProviderRegistry

    registry = ProviderRegistry()
    registry.auto_register()
    provider = registry.resolve_by_name(provider_name) if provider_name else registry.resolve(symbol)
    df = await provider.fetch_klines(symbol, tf, limit=limit)
    return df, f"provider.{getattr(provider, 'name', 'unknown')}", warnings


def _parse_indicator_specs(raw: str) -> list[dict[str, Any]]:
    if not raw.strip():
        return list(DEFAULT_INDICATORS)
    specs: list[dict[str, Any]] = []
    for part in raw.split(","):
        name = part.strip().lower()
        if name:
            specs.append({"name": name, "params": {}})
    return specs or list(DEFAULT_INDICATORS)


async def build_payload(
    *,
    symbol: str,
    market: str = "",
    timeframe: str,
    indicator_specs: list[dict[str, Any]],
    limit: int = 200,
    provider: str = "",
) -> dict[str, Any]:
    from tradecat.core.indicators import auto_register
    from tradecat.core.indicators.base import IndicatorRegistry

    auto_register()
    ind_registry = IndicatorRegistry()
    resolved_market = _infer_market(symbol, market)
    warnings: list[str] = []

    try:
        df, kline_source, kline_warnings = await _fetch_klines_df(
            symbol=symbol,
            market=resolved_market,
            timeframe=timeframe,
            limit=limit,
            provider_name=provider,
        )
        warnings.extend(kline_warnings)
    except Exception as exc:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "ts": _utc_now_iso(),
            "request": {
                "symbol": symbol,
                "market": resolved_market,
                "timeframe": timeframe,
                "provider": provider or None,
                "indicators": indicator_specs,
            },
            "data": None,
            "error": {"code": "klines_unavailable", "message": str(exc)},
        }

    if df is None or len(df) < MIN_BARS:
        hint = (
            "K线不足：A股/港股优先 --timeframe 5m（腾讯分钟，收盘后仍可重放）；"
            "1d 依赖东财 push2his，网络不可达时会自动回退分钟"
        )
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "ts": _utc_now_iso(),
            "request": {
                "symbol": symbol,
                "market": resolved_market,
                "timeframe": timeframe,
                "provider": provider or None,
                "indicators": indicator_specs,
            },
            "data": {"bars": len(df) if df is not None else 0, "hint": hint},
            "error": {
                "code": "insufficient_bars",
                "message": f"need>={MIN_BARS} bars, got {len(df) if df is not None else 0}",
            },
            "warnings": warnings,
        }

    base_cols = {"open", "high", "low", "close", "volume", "timestamp", "ts"}
    calc_errors: list[str] = []

    for spec in indicator_specs:
        name = str(spec.get("name") or "").strip().lower()
        params = spec.get("params") if isinstance(spec.get("params"), dict) else {}
        meta = ind_registry.get(name)
        if meta is None:
            calc_errors.append(f"unknown_indicator:{name}")
            continue
        try:
            df = meta.func(df, **params)
        except Exception as exc:
            calc_errors.append(f"{name}:{exc}")

    last = df.iloc[-1].to_dict()
    bar_ts = str(last.get("timestamp") or last.get("ts") or df.index[-1])

    computed: dict[str, Any] = {}
    for col in df.columns:
        if str(col).lower() in base_cols:
            continue
        val = _to_float(last.get(col))
        if val is not None:
            computed[str(col)] = val

    warnings.extend(calc_errors)
    return {
        "ok": True,
        "tool": TOOL_NAME,
        "ts": _utc_now_iso(),
        "source": {
            "mode": "tradecat_package",
            "script": "scripts/tradecat_get_indicators.py",
            "library": "tradecat.core.indicators",
            "kline_source": kline_source,
            "writes": False,
        },
        "request": {
            "symbol": symbol,
            "market": resolved_market,
            "timeframe": timeframe,
            "provider": provider or None,
            "indicators": indicator_specs,
            "limit": limit,
            "bars": len(df),
        },
        "data": {
            "symbol": symbol,
            "market": resolved_market,
            "timeframe": timeframe,
            "bar_ts": bar_ts,
            "close": _to_float(last.get("close")),
            "indicators": computed,
        },
        "warnings": warnings,
        "error": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute technical indicators from K-lines")
    parser.add_argument("--symbol", default="BTC_USDT", help="Symbol, e.g. BTC_USDT or SH688041")
    parser.add_argument("--market", default="", help="Optional: cn_stock, us_stock, crypto_spot, ...")
    parser.add_argument("--provider", default="", help="Optional provider override, e.g. gate")
    parser.add_argument("--timeframe", default="5m", help="Kline timeframe; cn_stock closed hours: use 1d")
    parser.add_argument("--indicator", default="", help="Comma-separated: rsi,ema,macd,...")
    parser.add_argument("--limit", type=int, default=200, help="Kline bar limit")
    args = parser.parse_args()

    specs = _parse_indicator_specs(args.indicator)
    payload = asyncio.run(
        build_payload(
            symbol=args.symbol.strip(),
            market=(args.market or "").strip(),
            timeframe=args.timeframe.strip(),
            indicator_specs=specs,
            limit=max(50, min(args.limit, 500)),
            provider=args.provider.strip(),
        )
    )
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
