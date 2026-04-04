"""Schema and field mapping helpers for collector-service."""

from __future__ import absolute_import

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple


INTERVAL_TO_DELTA = {
    "1m": timedelta(minutes=1),
    "3m": timedelta(minutes=3),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "2h": timedelta(hours=2),
    "4h": timedelta(hours=4),
    "6h": timedelta(hours=6),
    "12h": timedelta(hours=12),
    "1d": timedelta(days=1),
    "1w": timedelta(days=7),
    "1M": timedelta(days=30),
}


def _normalize_write_mode(value):
    # type: (Optional[str]) -> str
    mode = (value or "raw").strip().lower()
    if mode not in ("raw", "legacy"):
        raise ValueError("Invalid write mode: {0}".format(value))
    return mode


def _normalize_interval(interval):
    # type: (str) -> str
    value = (interval or "").strip()
    if value == "1M":
        return "1M"
    value = value.lower()
    if value not in INTERVAL_TO_DELTA:
        raise ValueError("Unsupported interval: {0}".format(interval))
    return value


def _validate_identifier(value, label):
    # type: (str, str) -> str
    text = (value or "").strip()
    if not text:
        raise ValueError("Missing {0}".format(label))
    first = text[0]
    if not (first.isalpha() or first == "_"):
        raise ValueError("Invalid {0}: {1}".format(label, value))
    for char in text[1:]:
        if not (char.isalnum() or char == "_"):
            raise ValueError("Invalid {0}: {1}".format(label, value))
    return text


def _coerce_datetime(value, tzinfo=None):
    # type: (Any, Optional[Any]) -> Any
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        if tzinfo is not None:
            return datetime.fromtimestamp(value, tz=tzinfo)
        # Normalize epoch inputs to naive UTC so behavior is host-independent.
        return datetime.utcfromtimestamp(value)
    return value


def _first_value(row, keys):
    # type: (Dict[str, Any], Sequence[str]) -> Any
    for key in keys:
        if key in row and row.get(key) is not None:
            return row.get(key)
    return None


class SchemaAdapter(object):
    """Resolve table names and conflict keys for raw/legacy modes."""

    def __init__(self, write_mode, market_db_schema, raw_db_schema):
        # type: (Optional[str], str, str) -> None
        self.write_mode = _normalize_write_mode(write_mode)
        self.market_db_schema = _validate_identifier(market_db_schema, "schema")
        self.raw_db_schema = _validate_identifier(raw_db_schema, "schema")

    @property
    def is_raw_mode(self):
        # type: () -> bool
        return self.write_mode == "raw"

    def get_kline_table(self, interval):
        # type: (str) -> str
        normalized = _normalize_interval(interval)
        if self.is_raw_mode:
            if normalized != "1m":
                raise ValueError("Raw mode only supports 1m candles")
            return "{0}.crypto_kline_1m".format(self.raw_db_schema)
        return "{0}.candles_{1}".format(self.market_db_schema, normalized)

    def get_metrics_table(self):
        # type: () -> str
        if self.is_raw_mode:
            return "{0}.crypto_metrics_5m".format(self.raw_db_schema)
        return "{0}.binance_futures_metrics_5m".format(self.market_db_schema)

    def get_kline_conflict_keys(self):
        # type: () -> Tuple[str, str, str]
        if self.is_raw_mode:
            return ("exchange", "symbol", "open_time")
        return ("exchange", "symbol", "bucket_ts")

    def get_metrics_conflict_keys(self):
        # type: () -> Tuple[str, ...]
        if self.is_raw_mode:
            return ("exchange", "symbol", "timestamp")
        return ("symbol", "create_time")

    def get_kline_time_field(self):
        # type: () -> str
        return "open_time" if self.is_raw_mode else "bucket_ts"

    def get_metrics_time_field(self):
        # type: () -> str
        return "timestamp" if self.is_raw_mode else "create_time"

    def kline_has_updated_at(self):
        # type: () -> bool
        return True

    def metrics_has_updated_at(self):
        # type: () -> bool
        return not self.is_raw_mode


class KlineAdapter(object):
    """Map kline rows between legacy and raw schemas."""

    RAW_ONLY_FIELDS = ("close_time", "ingest_batch_id", "ingested_at", "updated_at", "source_event_time")

    @classmethod
    def to_new_schema(cls, rows, batch_id, interval="1m"):
        # type: (Sequence[Dict[str, Any]], int, str) -> List[Dict[str, Any]]
        delta = INTERVAL_TO_DELTA[_normalize_interval(interval)]
        result = []
        for row in rows:
            open_time = _coerce_datetime(_first_value(row, ("open_time", "bucket_ts")), row.get("tz"))
            if open_time is None:
                raise ValueError("Rows must contain open_time or bucket_ts")
            close_time = _coerce_datetime(_first_value(row, ("close_time",)), row.get("tz")) or (open_time + delta)
            result.append(
                {
                    "exchange": row.get("exchange", "binance"),
                    "symbol": row["symbol"],
                    "open_time": open_time,
                    "close_time": close_time,
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": row.get("volume"),
                    "quote_volume": row.get("quote_volume"),
                    "trades": _first_value(row, ("trades", "trade_count")),
                    "taker_buy_volume": row.get("taker_buy_volume"),
                    "taker_buy_quote_volume": row.get("taker_buy_quote_volume"),
                    "is_closed": bool(row.get("is_closed", True)),
                    "source": row.get("source", "collector"),
                    "ingest_batch_id": batch_id,
                }
            )
        return result

    @classmethod
    def to_legacy_schema(cls, rows):
        # type: (Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]
        result = []
        for row in rows:
            payload = {}
            bucket_ts = _coerce_datetime(_first_value(row, ("bucket_ts", "open_time")), row.get("tz"))
            if bucket_ts is not None:
                payload["bucket_ts"] = bucket_ts

            for field in ("exchange", "symbol", "open", "high", "low", "close", "volume", "quote_volume"):
                if field in row and row.get(field) is not None:
                    payload[field] = row.get(field)

            trade_count = _first_value(row, ("trade_count", "trades"))
            if trade_count is not None:
                payload["trade_count"] = trade_count

            for field in ("taker_buy_volume", "taker_buy_quote_volume", "is_closed", "source"):
                if field in row and row.get(field) is not None:
                    payload[field] = row.get(field)

            for key, value in row.items():
                if key in cls.RAW_ONLY_FIELDS or key in payload or key in ("open_time", "trades"):
                    continue
                payload[key] = value
            result.append(payload)
        return result


class MetricsAdapter(object):
    """Map futures metrics rows between legacy and raw schemas."""

    RAW_ONLY_FIELDS = ("ingest_batch_id", "ingested_at", "updated_at")

    @classmethod
    def to_new_schema(cls, rows, batch_id):
        # type: (Sequence[Dict[str, Any]], int) -> List[Dict[str, Any]]
        result = []
        for row in rows:
            timestamp = _coerce_datetime(_first_value(row, ("timestamp", "create_time")), row.get("tz"))
            if timestamp is None:
                raise ValueError("Rows must contain timestamp or create_time")
            result.append(
                {
                    "exchange": row.get("exchange", "binance"),
                    "symbol": row["symbol"],
                    "timestamp": timestamp,
                    "open_interest": _first_value(row, ("open_interest", "sum_open_interest", "sumOpenInterest")),
                    "open_interest_value": _first_value(
                        row, ("open_interest_value", "sum_open_interest_value", "sumOpenInterestValue")
                    ),
                    "long_short_ratio": _first_value(
                        row, ("long_short_ratio", "count_long_short_ratio", "globalLongShortRatio")
                    ),
                    "top_long_short_ratio": _first_value(
                        row,
                        (
                            "top_long_short_ratio",
                            "count_toptrader_long_short_ratio",
                            "sum_toptrader_long_short_ratio",
                            "topAccountLongShortRatio",
                            "topPositionLongShortRatio",
                        ),
                    ),
                    "taker_buy_sell_ratio": _first_value(
                        row, ("taker_buy_sell_ratio", "sum_taker_long_short_vol_ratio", "takerBuySellRatio")
                    ),
                    "source": row.get("source", "collector"),
                    "ingest_batch_id": batch_id,
                }
            )
        return result

    @classmethod
    def to_legacy_schema(cls, rows):
        # type: (Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]
        result = []
        for row in rows:
            payload = {}
            create_time = _coerce_datetime(_first_value(row, ("create_time", "timestamp")), row.get("tz"))
            if create_time is not None:
                payload["create_time"] = create_time

            if "symbol" in row:
                payload["symbol"] = row["symbol"]

            value = _first_value(row, ("sum_open_interest", "open_interest", "sumOpenInterest"))
            if value is not None:
                payload["sum_open_interest"] = value

            value = _first_value(row, ("sum_open_interest_value", "open_interest_value", "sumOpenInterestValue"))
            if value is not None:
                payload["sum_open_interest_value"] = value

            value = _first_value(
                row,
                (
                    "count_toptrader_long_short_ratio",
                    "top_long_short_ratio",
                    "topAccountLongShortRatio",
                    "topPositionLongShortRatio",
                ),
            )
            if value is not None:
                payload["count_toptrader_long_short_ratio"] = value

            value = _first_value(row, ("count_long_short_ratio", "long_short_ratio", "globalLongShortRatio"))
            if value is not None:
                payload["count_long_short_ratio"] = value

            value = _first_value(row, ("sum_taker_long_short_vol_ratio", "taker_buy_sell_ratio", "takerBuySellRatio"))
            if value is not None:
                payload["sum_taker_long_short_vol_ratio"] = value

            for field in ("exchange", "source", "is_closed"):
                if field in row and row.get(field) is not None:
                    payload[field] = row.get(field)

            for key, value in row.items():
                if key in cls.RAW_ONLY_FIELDS or key in payload or key == "timestamp":
                    continue
                payload[key] = value
            result.append(payload)
        return result
