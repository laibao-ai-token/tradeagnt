"""collector-service configuration loader with legacy key compatibility."""

import os
from pathlib import Path

try:
    from common.config_loader import load_repo_env
except (ImportError, SyntaxError):
    def load_repo_env(*args, **kwargs):
        return {}

try:
    from common.db_url import DEFAULT_DATABASE_URL
except (ImportError, SyntaxError):
    DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5434/market_data"

SERVICE_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = SERVICE_ROOT.parent.parent

load_repo_env(repo_root=PROJECT_ROOT, set_os_env=True, override=False)


def _first_non_empty(environ, keys, default=""):
    for key in keys:
        value = (environ.get(key) or "").strip()
        if value:
            return value
    return default


def _parse_bool(environ, keys, default=False):
    raw = _first_non_empty(environ, keys, "")
    if not raw:
        return bool(default)

    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ValueError("Invalid boolean for {0}: {1}".format(keys[0], raw))


def _parse_int(environ, keys, default, minimum=None):
    raw = _first_non_empty(environ, keys, "")
    if not raw:
        value = int(default)
    else:
        try:
            value = int(raw)
        except Exception:
            raise ValueError("Invalid integer for {0}: {1}".format(keys[0], raw))

    if minimum is not None and value < minimum:
        raise ValueError("Invalid integer for {0}: {1} < {2}".format(keys[0], value, minimum))
    return value


def _parse_list(environ, keys, default=None):
    raw = _first_non_empty(environ, keys, "")
    if not raw:
        return list(default or [])

    values = []
    seen = set()
    for chunk in raw.replace("\n", ",").split(","):
        item = chunk.strip()
        if not item or item in seen:
            continue
        values.append(item)
        seen.add(item)
    return values


def _normalize_backfill_mode(raw):
    value = (raw or "").strip().lower() or "all"
    if value == "full":
        value = "all"
    if value not in ("all", "days", "none"):
        raise ValueError("Invalid backfill mode: {0}".format(raw))
    return value


def _normalize_crypto_write_mode(raw):
    value = (raw or "").strip().lower() or "raw"
    if value not in ("raw", "legacy"):
        raise ValueError("Invalid crypto write mode: {0}".format(raw))
    return value


class ConfigSection(object):
    """Simple configuration section with dict export."""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def to_dict(self):
        payload = {}
        for key in sorted(self.__dict__.keys()):
            value = getattr(self, key)
            if isinstance(value, ConfigSection):
                payload[key] = value.to_dict()
            else:
                payload[key] = value
        return payload


class CollectorConfig(object):
    """Top-level collector configuration."""

    def __init__(
        self,
        database,
        runtime,
        crypto_kline,
        crypto_metrics,
        crypto_orderbook,
        equity,
        fund_cn,
        news,
    ):
        self.database = database
        self.runtime = runtime
        self.crypto_kline = crypto_kline
        self.crypto_metrics = crypto_metrics
        self.crypto_orderbook = crypto_orderbook
        self.equity = equity
        self.fund_cn = fund_cn
        self.news = news

    def to_public_dict(self):
        payload = {
            "database": self.database.to_dict(),
            "runtime": self.runtime.to_dict(),
            "crypto_kline": self.crypto_kline.to_dict(),
            "crypto_metrics": self.crypto_metrics.to_dict(),
            "crypto_orderbook": self.crypto_orderbook.to_dict(),
            "equity": self.equity.to_dict(),
            "fund_cn": self.fund_cn.to_dict(),
            "news": self.news.to_dict(),
        }
        if payload["database"].get("database_url"):
            payload["database"]["database_url"] = "<redacted>"
        return payload


def load_config(environ=None):
    """Load collector-service config from new keys with legacy fallbacks."""

    env_map = os.environ if environ is None else environ
    database_url = _first_non_empty(
        env_map,
        ("COLLECTOR_DATABASE_URL", "MARKETS_SERVICE_DATABASE_URL", "DATABASE_URL"),
        DEFAULT_DATABASE_URL,
    )
    if database_url and not database_url.startswith("postgresql://"):
        raise ValueError("Invalid database URL: {0}".format(database_url))

    crypto_write_mode = _normalize_crypto_write_mode(
        _first_non_empty(env_map, ("COLLECTOR_CRYPTO_WRITE_MODE", "CRYPTO_WRITE_MODE"), "raw")
    )
    backfill_mode = _normalize_backfill_mode(
        _first_non_empty(env_map, ("COLLECTOR_BACKFILL_MODE", "BACKFILL_MODE"), "all")
    )

    database = ConfigSection(
        database_url=database_url,
        market_db_schema=_first_non_empty(env_map, ("COLLECTOR_MARKET_DB_SCHEMA", "MARKET_DB_SCHEMA"), "market_data"),
        raw_db_schema=_first_non_empty(env_map, ("COLLECTOR_RAW_DB_SCHEMA", "RAW_DB_SCHEMA"), "raw"),
        quality_db_schema=_first_non_empty(env_map, ("COLLECTOR_QUALITY_DB_SCHEMA", "QUALITY_DB_SCHEMA"), "quality"),
        alternative_db_schema=_first_non_empty(
            env_map, ("COLLECTOR_ALTERNATIVE_DB_SCHEMA", "ALTERNATIVE_DB_SCHEMA"), "alternative"
        ),
        crypto_write_mode=crypto_write_mode,
    )

    runtime = ConfigSection(
        http_proxy=_first_non_empty(env_map, ("COLLECTOR_HTTP_PROXY", "HTTP_PROXY", "HTTPS_PROXY"), ""),
        https_proxy=_first_non_empty(env_map, ("COLLECTOR_HTTPS_PROXY", "HTTPS_PROXY", "HTTP_PROXY"), ""),
        rate_limit_per_minute=_parse_int(env_map, ("COLLECTOR_RATE_LIMIT", "RATE_LIMIT_PER_MINUTE"), 1800, minimum=1),
        gap_check_interval=_parse_int(
            env_map, ("COLLECTOR_GAP_CHECK_INTERVAL", "BINANCE_WS_GAP_INTERVAL"), 600, minimum=1
        ),
        backfill_mode=backfill_mode,
        backfill_days=_parse_int(env_map, ("COLLECTOR_BACKFILL_DAYS", "BACKFILL_DAYS"), 30, minimum=0),
        backfill_start_date=_first_non_empty(
            env_map, ("COLLECTOR_BACKFILL_START_DATE", "BACKFILL_START_DATE"), ""
        ),
    )
    if backfill_mode == "days" and runtime.backfill_days < 1:
        raise ValueError("Invalid backfill_days for mode=days: {0}".format(runtime.backfill_days))

    crypto_kline = ConfigSection(
        enabled=_parse_bool(env_map, ("COLLECTOR_CRYPTO_KLINE_ENABLED",), False),
        websocket_enabled=_parse_bool(env_map, ("COLLECTOR_CRYPTO_KLINE_WS",), True),
        provider=_first_non_empty(
            env_map,
            ("COLLECTOR_CRYPTO_KLINE_PROVIDER", "DATA_CANDLE_PROVIDER"),
            "binance_futures_ws",
        ),
        write_mode=crypto_write_mode,
        backfill_mode=backfill_mode,
        backfill_days=runtime.backfill_days,
        backfill_start_date=runtime.backfill_start_date,
        rate_limit_per_minute=runtime.rate_limit_per_minute,
        gap_check_interval=runtime.gap_check_interval,
        ws_source=_first_non_empty(
            env_map,
            ("COLLECTOR_CRYPTO_KLINE_WS_SOURCE", "BINANCE_WS_SOURCE"),
            "binance_ws",
        ),
        db_exchange=_first_non_empty(
            env_map,
            ("COLLECTOR_CRYPTO_KLINE_DB_EXCHANGE", "BINANCE_WS_DB_EXCHANGE"),
            "binance_futures_um",
        ),
        ccxt_exchange=_first_non_empty(
            env_map,
            ("COLLECTOR_CRYPTO_KLINE_CCXT_EXCHANGE", "BINANCE_WS_CCXT_EXCHANGE"),
            "binance",
        ),
        gate_poll_interval_seconds=_parse_int(
            env_map,
            ("COLLECTOR_CRYPTO_KLINE_GATE_POLL_INTERVAL_SECONDS", "GATE_SPOT_POLL_INTERVAL"),
            10,
            minimum=1,
        ),
        gate_timeout_seconds=_parse_int(
            env_map,
            ("COLLECTOR_CRYPTO_KLINE_GATE_TIMEOUT_SECONDS", "GATE_SPOT_TIMEOUT"),
            10,
            minimum=1,
        ),
        gate_workers=_parse_int(
            env_map,
            ("COLLECTOR_CRYPTO_KLINE_GATE_WORKERS", "GATE_SPOT_WORKERS"),
            4,
            minimum=1,
        ),
        gate_db_exchange=_first_non_empty(
            env_map,
            ("COLLECTOR_CRYPTO_KLINE_GATE_DB_EXCHANGE", "GATE_SPOT_DB_EXCHANGE"),
            "gate_spot",
        ),
        symbols=_parse_list(env_map, ("COLLECTOR_CRYPTO_KLINE_SYMBOLS",)),
        intervals=_parse_list(
            env_map,
            ("COLLECTOR_CRYPTO_KLINE_INTERVALS",),
            default=["1m", "5m", "15m", "1h", "4h", "1d", "1w"],
        ),
    )

    crypto_metrics = ConfigSection(
        enabled=_parse_bool(env_map, ("COLLECTOR_CRYPTO_METRICS_ENABLED",), False),
        interval=_first_non_empty(env_map, ("COLLECTOR_CRYPTO_METRICS_INTERVAL",), "5m"),
    )

    crypto_orderbook = ConfigSection(
        enabled=_parse_bool(env_map, ("COLLECTOR_CRYPTO_ORDERBOOK_ENABLED",), False),
        tick_interval=_parse_int(
            env_map,
            ("COLLECTOR_ORDER_BOOK_TICK_INTERVAL", "COLLECTOR_CRYPTO_ORDERBOOK_TICK_INTERVAL", "ORDER_BOOK_TICK_INTERVAL"),
            1,
            minimum=1,
        ),
        full_interval=_parse_int(
            env_map,
            ("COLLECTOR_ORDER_BOOK_FULL_INTERVAL", "COLLECTOR_CRYPTO_ORDERBOOK_FULL_INTERVAL", "ORDER_BOOK_FULL_INTERVAL"),
            5,
            minimum=1,
        ),
        depth=_parse_int(
            env_map,
            ("COLLECTOR_ORDER_BOOK_DEPTH", "COLLECTOR_CRYPTO_ORDERBOOK_DEPTH", "ORDER_BOOK_DEPTH"),
            1000,
            minimum=1,
        ),
        retention_days=_parse_int(
            env_map,
            ("COLLECTOR_ORDER_BOOK_RETENTION_DAYS", "COLLECTOR_CRYPTO_ORDERBOOK_RETENTION_DAYS", "ORDER_BOOK_RETENTION_DAYS"),
            30,
            minimum=0,
        ),
        symbols=_parse_list(env_map, ("COLLECTOR_CRYPTO_ORDERBOOK_SYMBOLS", "ORDER_BOOK_SYMBOLS")),
    )

    equity = ConfigSection(
        enabled=_parse_bool(env_map, ("COLLECTOR_EQUITY_ENABLED",), False),
        markets=_parse_list(env_map, ("COLLECTOR_EQUITY_MARKETS",), default=["us", "cn", "hk"]),
        poll_interval_seconds=_parse_int(env_map, ("COLLECTOR_EQUITY_POLL_INTERVAL_SECONDS",), 60, minimum=1),
        interval=_first_non_empty(env_map, ("COLLECTOR_EQUITY_INTERVAL",), "1m"),
        limit=_parse_int(env_map, ("COLLECTOR_EQUITY_LIMIT",), 1, minimum=1),
        us_provider=_first_non_empty(env_map, ("COLLECTOR_EQUITY_US_PROVIDER",), "yfinance"),
        cn_provider=_first_non_empty(env_map, ("COLLECTOR_EQUITY_CN_PROVIDER",), "akshare"),
        hk_provider=_first_non_empty(env_map, ("COLLECTOR_EQUITY_HK_PROVIDER",), "tencent"),
        us_symbols=_parse_list(env_map, ("COLLECTOR_EQUITY_US_SYMBOLS",)),
        cn_symbols=_parse_list(env_map, ("COLLECTOR_EQUITY_CN_SYMBOLS",)),
        hk_symbols=_parse_list(env_map, ("COLLECTOR_EQUITY_HK_SYMBOLS",)),
    )

    fund_cn = ConfigSection(
        enabled=_parse_bool(env_map, ("COLLECTOR_FUND_CN_ENABLED",), False),
        interval_seconds=_parse_int(env_map, ("COLLECTOR_FUND_CN_INTERVAL",), 60, minimum=1),
        etf_symbols=_parse_list(env_map, ("COLLECTOR_FUND_CN_ETF_SYMBOLS",)),
        offmarket_codes=_parse_list(env_map, ("COLLECTOR_FUND_CN_OFFMARKET_CODES",)),
    )

    news = ConfigSection(
        enabled=_parse_bool(env_map, ("COLLECTOR_NEWS_ENABLED",), False),
        feeds=_parse_list(env_map, ("COLLECTOR_NEWS_FEEDS", "NEWS_RSS_FEEDS")),
        poll_interval_seconds=_parse_int(
            env_map, ("COLLECTOR_NEWS_RSS_POLL_INTERVAL_SECONDS", "NEWS_RSS_POLL_INTERVAL_SECONDS"), 2, minimum=1
        ),
        limit=_parse_int(env_map, ("COLLECTOR_NEWS_RSS_LIMIT", "NEWS_RSS_LIMIT"), 100, minimum=1),
        window_hours=_parse_int(
            env_map, ("COLLECTOR_NEWS_RSS_WINDOW_HOURS", "NEWS_RSS_WINDOW_HOURS"), 72, minimum=1
        ),
        timeout_seconds=_parse_int(
            env_map, ("COLLECTOR_NEWS_RSS_TIMEOUT_SECONDS", "NEWS_RSS_TIMEOUT_SECONDS"), 20, minimum=1
        ),
        retention_hours=_parse_int(
            env_map, ("COLLECTOR_NEWS_RETENTION_HOURS", "NEWS_RETENTION_HOURS"), 24, minimum=0
        ),
        retention_cleanup_interval_seconds=_parse_int(
            env_map,
            ("COLLECTOR_NEWS_RETENTION_CLEANUP_INTERVAL_SECONDS", "NEWS_RETENTION_CLEANUP_INTERVAL_SECONDS"),
            600,
            minimum=1,
        ),
        failure_threshold=_parse_int(
            env_map, ("COLLECTOR_NEWS_RSS_FAILURE_THRESHOLD", "NEWS_RSS_FAILURE_THRESHOLD"), 2, minimum=1
        ),
        failure_cooldown_seconds=_parse_int(
            env_map,
            ("COLLECTOR_NEWS_RSS_FAILURE_COOLDOWN_SECONDS", "NEWS_RSS_FAILURE_COOLDOWN_SECONDS"),
            300,
            minimum=1,
        ),
    )

    return CollectorConfig(
        database=database,
        runtime=runtime,
        crypto_kline=crypto_kline,
        crypto_metrics=crypto_metrics,
        crypto_orderbook=crypto_orderbook,
        equity=equity,
        fund_cn=fund_cn,
        news=news,
    )
