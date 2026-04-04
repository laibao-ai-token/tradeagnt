from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import time
from typing import Protocol

from .fund_symbols import cn_fund_exchange_candidates, normalize_cn_fund_symbol
from .micro import Candle
from .quote import fetch_daily_curve_1d, fetch_quotes, Quote


@dataclass(frozen=True)
class FundQuoteRow:
    request_symbol: str
    quote_symbol: str
    name: str
    price: float
    prev_close: float
    open: float
    high: float
    low: float
    volume: float
    amount: float
    ts: str
    source: str
    last_fetch_at: float


class FundBridge(Protocol):
    def fetch_quote_rows(self, symbols: list[str], *, now_ts: float | None = None) -> dict[str, FundQuoteRow]:
        raise NotImplementedError

    def fetch_daily_candles(self, symbol: str, *, limit: int = 15) -> list[Candle]:
        raise NotImplementedError


class DirectFundBridge(FundBridge):
    def __init__(self, *, provider: str = "tencent", market: str = "cn_fund", timeout_s: float = 6.0) -> None:
        self._provider = provider
        self._market = market
        self._timeout_s = timeout_s

    def fetch_quote_rows(self, symbols: list[str], *, now_ts: float | None = None) -> dict[str, FundQuoteRow]:
        request_map: dict[str, str] = {}
        normalized_order: list[str] = []
        normalized_seen: set[str] = set()
        for sym in symbols:
            trimmed = (sym or "").strip()
            if not trimmed:
                continue
            norm = normalize_cn_fund_symbol(trimmed)
            if not norm:
                continue
            if trimmed in request_map:
                continue
            request_map[trimmed] = norm
            if norm not in normalized_seen:
                normalized_order.append(norm)
                normalized_seen.add(norm)

        if not request_map:
            return {}

        rows: dict[str, FundQuoteRow] = {}
        raw = fetch_quotes(self._provider, self._market, normalized_order, timeout_s=self._timeout_s)
        ts = float(now_ts) if now_ts is not None else float(time.time())

        for request_symbol, norm in request_map.items():
            quote = raw.get(norm)
            if quote is None:
                continue
            rows[request_symbol] = FundQuoteRow(
                request_symbol=request_symbol,
                quote_symbol=quote.symbol,
                name=quote.name,
                price=float(quote.price),
                prev_close=float(quote.prev_close),
                open=float(quote.open),
                high=float(quote.high),
                low=float(quote.low),
                volume=float(quote.volume),
                amount=float(quote.amount),
                ts=quote.ts,
                source=quote.source,
                last_fetch_at=ts,
            )
        return rows

    def fetch_daily_candles(self, symbol: str, *, limit: int = 15) -> list[Candle]:
        norm = normalize_cn_fund_symbol(symbol)
        if not norm:
            return []

        rows = fetch_daily_curve_1d(
            provider=self._provider,
            market=self._market,
            symbol=norm,
            timeout_s=self._timeout_s,
            limit=limit,
        )
        candles: list[Candle] = []
        for ts_open, open_px, high_px, low_px, close_px, volume in rows:
            try:
                ts_float = float(ts_open)
                o = float(open_px)
                h = float(high_px)
                l = float(low_px)
                c = float(close_px)
                v = float(volume)
            except Exception:
                continue
            if not all(math.isfinite(value) for value in (ts_float, o, h, l, c, v)):
                continue
            ts_int = int(ts_float)
            if ts_int <= 0 or o <= 0 or h <= 0 or l <= 0 or c <= 0:
                continue
            candles.append(
                Candle(
                    ts_open=ts_int,
                    open=o,
                    high=max(h, o, c),
                    low=min(l, o, c),
                    close=c,
                    volume_est=max(0.0, v),
                    notional_est=max(0.0, v) * c,
                )
            )
        return candles


def seed_curve_from_daily_candles(
    curves: dict[str, deque[Candle]],
    symbol: str,
    candles: list[Candle],
    *,
    max_points: int = 90,
) -> bool:
    norm = normalize_cn_fund_symbol(symbol)
    if norm and not norm.startswith(("SH", "SZ")):
        cands = cn_fund_exchange_candidates(norm)
        if cands:
            norm = cands[0]
    if not norm or not candles:
        return False

    limit = max(1, int(max_points))
    buffer = deque(maxlen=limit)
    buffer.extend(candles)
    curves[norm] = buffer
    return True


class DbFundBridge(FundBridge):
    """Fund bridge that reads from TimescaleDB instead of direct API calls.
    
    Reads from:
    - market_data.fund_cn_etf (ETF/LOF)
    - market_data.fund_cn_offmarket (off-market fund valuations)
    
    Falls back to DirectFundBridge if database query fails.
    """
    
    def __init__(
        self,
        *,
        provider: str = "tencent",
        market: str = "cn_fund",
        timeout_s: float = 6.0,
        fallback_to_api: bool = True,
    ) -> None:
        self._provider = provider
        self._market = market
        self._timeout_s = timeout_s
        self._fallback_to_api = fallback_to_api
        self._api_bridge = DirectFundBridge(
            provider=provider,
            market=market,
            timeout_s=timeout_s,
        ) if fallback_to_api else None
    
    def fetch_quote_rows(self, symbols: list[str], *, now_ts: float | None = None) -> dict[str, FundQuoteRow]:
        from .fund_db import fetch_fund_cn_etf_from_db, fetch_fund_cn_offmarket_from_db
        
        if not symbols:
            return {}
        
        ts = float(now_ts) if now_ts is not None else float(time.time())
        rows: dict[str, FundQuoteRow] = {}
        
        # Separate ETF and off-market codes
        etf_symbols = []
        offmarket_codes = []
        symbol_map: dict[str, str] = {}  # normalized -> original
        
        for sym in symbols:
            trimmed = (sym or "").strip()
            if not trimmed:
                continue
            norm = normalize_cn_fund_symbol(trimmed)
            if not norm:
                continue
            symbol_map[norm] = trimmed
            
            # Check if it's an exchange-traded fund
            candidates = cn_fund_exchange_candidates(norm)
            if candidates:
                etf_symbols.append(candidates[0])
            else:
                # Assume off-market fund
                offmarket_codes.append(norm)
        
        # Fetch ETF data from database
        if etf_symbols:
            try:
                etf_rows = fetch_fund_cn_etf_from_db(etf_symbols, timeout_s=self._timeout_s)
                for symbol, db_row in etf_rows.items():
                    original = symbol_map.get(symbol, symbol)
                    rows[original] = FundQuoteRow(
                        request_symbol=original,
                        quote_symbol=symbol,
                        name="",  # DB doesn't have name
                        price=db_row.close,
                        prev_close=db_row.open,  # Approximate
                        open=db_row.open,
                        high=db_row.high,
                        low=db_row.low,
                        volume=db_row.volume,
                        amount=db_row.amount,
                        ts=db_row.timestamp,
                        source="timescaledb",
                        last_fetch_at=ts,
                    )
            except Exception:
                pass
        
        # Fetch off-market fund data from database
        if offmarket_codes:
            try:
                off_rows = fetch_fund_cn_offmarket_from_db(offmarket_codes, timeout_s=self._timeout_s)
                for code, db_row in off_rows.items():
                    original = symbol_map.get(code, code)
                    rows[original] = FundQuoteRow(
                        request_symbol=original,
                        quote_symbol=code,
                        name="",  # DB doesn't have name
                        price=db_row.estimated_nav,
                        prev_close=0.0,  # Not available
                        open=0.0,
                        high=0.0,
                        low=0.0,
                        volume=0.0,
                        amount=0.0,
                        ts=db_row.timestamp,
                        source="timescaledb",
                        last_fetch_at=ts,
                    )
            except Exception:
                pass
        
        # Fallback to API for missing symbols
        if self._api_bridge and len(rows) < len(symbols):
            missing = [s for s in symbols if s not in rows]
            try:
                api_rows = self._api_bridge.fetch_quote_rows(missing, now_ts=now_ts)
                rows.update(api_rows)
            except Exception:
                pass
        
        return rows
    
    def fetch_daily_candles(self, symbol: str, *, limit: int = 15) -> list[Candle]:
        # Database doesn't have daily candles yet, fallback to API
        if self._api_bridge:
            return self._api_bridge.fetch_daily_candles(symbol, limit=limit)
        return []
