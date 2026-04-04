"""Raw schema writers for collector-service."""

from __future__ import absolute_import

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.adapters.schema_adapter import KlineAdapter, MetricsAdapter
from src.config import load_config
from src.storage.timescale import TimescaleStorage, reset_shared_pool


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
        return datetime.utcfromtimestamp(value)
    return value


def _require_positive_batch_id(value):
    # type: (Any) -> int
    batch_id = int(value)
    if batch_id <= 0:
        raise ValueError("ingest_batch_id must be positive")
    return batch_id


class TimescaleRawWriter(TimescaleStorage):
    """Write raw crypto/equity rows using the shared storage pool."""

    def __init__(
        self,
        db_url=None,
        default_db_url=None,
        raw_db_schema=None,
        pool_factory=None,
    ):
        # type: (Optional[str], Optional[str], Optional[str], Optional[Any]) -> None
        cfg = load_config()
        super(TimescaleRawWriter, self).__init__(
            db_url=db_url,
            default_db_url=default_db_url,
            pool_factory=pool_factory,
        )
        self.raw_db_schema = _validate_identifier(raw_db_schema or cfg.database.raw_db_schema, "schema")
        self._batch_counter = 0

    def start_batch(self, market="unknown"):
        # type: (str) -> int
        """Start a new ingest batch and return batch_id.

        Args:
            market: Market identifier (e.g., 'crypto', 'equity', 'fund_cn')

        Returns:
            A positive batch_id for tracking this ingest batch.
        """
        self._batch_counter += 1
        # Use a simple incremental batch ID
        # In production, this could be replaced with a database sequence
        import time
        return int(time.time() * 1000) % 1000000000 + self._batch_counter

    def _executemany(self, table_name, columns, values, conflict_sql):
        # type: (str, Sequence[str], Sequence[Tuple[Any, ...]], str) -> int
        if not values:
            return 0
        placeholders = ", ".join(["%s"] * len(columns))
        query = (
            'INSERT INTO "{schema}"."{table}" ({columns}) '
            "VALUES ({placeholders}) "
            "ON CONFLICT {conflict_sql}"
        ).format(
            schema=self.raw_db_schema,
            table=table_name,
            columns=", ".join(['"{0}"'.format(column) for column in columns]),
            placeholders=placeholders,
            conflict_sql=conflict_sql,
        )
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(query, values)
                conn.commit()
                return int(cur.rowcount or 0)

    def upsert_kline_1m(self, rows, ingest_batch_id, source="binance_ws"):
        # type: (Sequence[Dict[str, Any]], int, str) -> int
        batch_id = _require_positive_batch_id(ingest_batch_id)
        if not rows:
            return 0

        transformed = KlineAdapter.to_new_schema(rows, batch_id=batch_id, interval="1m")
        for original, mapped in zip(rows, transformed):
            if original.get("source") is None:
                mapped["source"] = source

        columns = [
            "exchange",
            "symbol",
            "open_time",
            "close_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "trades",
            "taker_buy_volume",
            "taker_buy_quote_volume",
            "is_closed",
            "source",
            "ingest_batch_id",
        ]
        values = [tuple(mapped.get(column) for column in columns) for mapped in transformed]
        conflict_sql = (
            '(exchange, symbol, open_time) DO UPDATE SET '
            'close_time = EXCLUDED.close_time, '
            'open = EXCLUDED.open, '
            'high = EXCLUDED.high, '
            'low = EXCLUDED.low, '
            'close = EXCLUDED.close, '
            'volume = EXCLUDED.volume, '
            'quote_volume = EXCLUDED.quote_volume, '
            'trades = EXCLUDED.trades, '
            'taker_buy_volume = EXCLUDED.taker_buy_volume, '
            'taker_buy_quote_volume = EXCLUDED.taker_buy_quote_volume, '
            'is_closed = EXCLUDED.is_closed, '
            'source = EXCLUDED.source, '
            'ingest_batch_id = EXCLUDED.ingest_batch_id, '
            'updated_at = NOW()'
        )
        return self._executemany("crypto_kline_1m", columns, values, conflict_sql)

    def upsert_metrics_5m(self, rows, ingest_batch_id, source="binance_api"):
        # type: (Sequence[Dict[str, Any]], int, str) -> int
        batch_id = _require_positive_batch_id(ingest_batch_id)
        if not rows:
            return 0

        transformed = MetricsAdapter.to_new_schema(rows, batch_id=batch_id)
        for original, mapped in zip(rows, transformed):
            if original.get("source") is None:
                mapped["source"] = source

        columns = [
            "exchange",
            "symbol",
            "timestamp",
            "open_interest",
            "open_interest_value",
            "long_short_ratio",
            "top_long_short_ratio",
            "taker_buy_sell_ratio",
            "source",
            "ingest_batch_id",
        ]
        values = [tuple(mapped.get(column) for column in columns) for mapped in transformed]
        conflict_sql = (
            '(exchange, symbol, timestamp) DO UPDATE SET '
            'open_interest = EXCLUDED.open_interest, '
            'open_interest_value = EXCLUDED.open_interest_value, '
            'long_short_ratio = EXCLUDED.long_short_ratio, '
            'top_long_short_ratio = EXCLUDED.top_long_short_ratio, '
            'taker_buy_sell_ratio = EXCLUDED.taker_buy_sell_ratio, '
            'source = EXCLUDED.source, '
            'ingest_batch_id = EXCLUDED.ingest_batch_id'
        )
        return self._executemany("crypto_metrics_5m", columns, values, conflict_sql)

    def upsert_equity_1m(self, market, rows, ingest_batch_id, source):
        # type: (str, Sequence[Dict[str, Any]], int, str) -> int
        batch_id = _require_positive_batch_id(ingest_batch_id)
        market_to_table = {
            "us_stock": "us_equity_1m",
            "cn_stock": "cn_equity_1m",
            "hk_stock": "hk_equity_1m",
        }
        table_name = market_to_table.get(market)
        if not table_name:
            raise ValueError("Unsupported market: {0}".format(market))
        if not rows:
            return 0

        columns = [
            "exchange",
            "symbol",
            "open_time",
            "close_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "source",
            "ingest_batch_id",
            "source_event_time",
        ]
        values = []
        for row in rows:
            open_time = _coerce_datetime(row.get("open_time"), row.get("tz"))
            close_time = _coerce_datetime(row.get("close_time"), row.get("tz")) or (open_time + timedelta(minutes=1))
            values.append(
                (
                    row["exchange"],
                    row["symbol"],
                    open_time,
                    close_time,
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                    row.get("volume", 0),
                    row.get("amount"),
                    row.get("source", source),
                    batch_id,
                    row.get("source_event_time"),
                )
            )
        conflict_sql = (
            '(exchange, symbol, open_time) DO UPDATE SET '
            'close_time = EXCLUDED.close_time, '
            'open = EXCLUDED.open, '
            'high = EXCLUDED.high, '
            'low = EXCLUDED.low, '
            'close = EXCLUDED.close, '
            'volume = EXCLUDED.volume, '
            'amount = EXCLUDED.amount, '
            'source = EXCLUDED.source, '
            'ingest_batch_id = EXCLUDED.ingest_batch_id, '
            'source_event_time = EXCLUDED.source_event_time, '
            'updated_at = NOW()'
        )
        return self._executemany(table_name, columns, values, conflict_sql)

    def upsert_fund_cn_etf(self, rows, ingest_batch_id, source="tencent"):
        # type: (Sequence[Dict[str, Any]], int, str) -> int
        """Write CN ETF/LOF fund snapshots to market_data.fund_cn_etf."""
        batch_id = _require_positive_batch_id(ingest_batch_id)
        if not rows:
            return 0

        columns = [
            "symbol",
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
        ]
        values = []
        for row in rows:
            ts = _coerce_datetime(row.get("ts") or row.get("timestamp") or row.get("open_time"))
            if ts is None:
                ts = datetime.utcnow()
            values.append(
                (
                    row["symbol"],
                    ts,
                    row.get("open"),
                    row.get("high"),
                    row.get("low"),
                    row.get("close") or row.get("price"),
                    row.get("volume"),
                    row.get("amount"),
                )
            )
        conflict_sql = (
            '(symbol, timestamp) DO UPDATE SET '
            'open = EXCLUDED.open, '
            'high = EXCLUDED.high, '
            'low = EXCLUDED.low, '
            'close = EXCLUDED.close, '
            'volume = EXCLUDED.volume, '
            'amount = EXCLUDED.amount'
        )
        return self._executemany("fund_cn_etf", columns, values, conflict_sql, schema="market_data")

    def upsert_fund_cn_offmarket(self, rows, ingest_batch_id, source="fundgz"):
        # type: (Sequence[Dict[str, Any]], int, str) -> int
        """Write CN off-market fund valuations to market_data.fund_cn_offmarket."""
        batch_id = _require_positive_batch_id(ingest_batch_id)
        if not rows:
            return 0

        columns = [
            "fund_code",
            "timestamp",
            "estimated_nav",
            "estimated_change_pct",
        ]
        values = []
        for row in rows:
            ts = _coerce_datetime(row.get("ts") or row.get("timestamp"))
            if ts is None:
                ts = datetime.utcnow()
            values.append(
                (
                    row.get("symbol") or row.get("fund_code"),
                    ts,
                    row.get("price") or row.get("estimated_nav"),
                    row.get("estimated_change_pct"),
                )
            )
        conflict_sql = (
            '(fund_code, timestamp) DO UPDATE SET '
            'estimated_nav = EXCLUDED.estimated_nav, '
            'estimated_change_pct = EXCLUDED.estimated_change_pct'
        )
        return self._executemany("fund_cn_offmarket", columns, values, conflict_sql, schema="market_data")

    def _executemany(self, table_name, columns, values, conflict_sql, schema=None):
        # type: (str, Sequence[str], Sequence[Tuple[Any, ...]], str, Optional[str]) -> int
        if not values:
            return 0
        target_schema = schema or self.raw_db_schema
        placeholders = ", ".join(["%s"] * len(columns))
        query = (
            'INSERT INTO "{schema}"."{table}" ({columns}) '
            "VALUES ({placeholders}) "
            "ON CONFLICT {conflict_sql}"
        ).format(
            schema=target_schema,
            table=table_name,
            columns=", ".join(['"{0}"'.format(column) for column in columns]),
            placeholders=placeholders,
            conflict_sql=conflict_sql,
        )
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(query, values)
                conn.commit()
                return int(cur.rowcount or 0)
