"""Adapter exports for collector-service."""

from .cryptofeed import BinanceWSAdapter, CandleEvent, preload_symbols
from .eastmoney import SAFE_CN_FUND_CODE_RE, fetch_fundgz_quote, parse_fundgz_jsonp
from .gate_spot import GateSpotCandle, fetch_spot_candles, to_candle_row
from .metrics import Timer, metrics
from .schema_adapter import KlineAdapter, MetricsAdapter, SchemaAdapter
from .tencent import fetch_tencent_cn_quotes, normalize_cn_symbol, parse_tencent_cn_quote_line
from .timescale import TimescaleAdapter, reset_shared_pool

__all__ = [
    "BinanceWSAdapter",
    "CandleEvent",
    "GateSpotCandle",
    "KlineAdapter",
    "MetricsAdapter",
    "SAFE_CN_FUND_CODE_RE",
    "SchemaAdapter",
    "Timer",
    "TimescaleAdapter",
    "fetch_fundgz_quote",
    "fetch_spot_candles",
    "fetch_tencent_cn_quotes",
    "metrics",
    "normalize_cn_symbol",
    "parse_fundgz_jsonp",
    "parse_tencent_cn_quote_line",
    "preload_symbols",
    "reset_shared_pool",
    "to_candle_row",
]
