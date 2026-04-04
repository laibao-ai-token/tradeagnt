"""Unified Timescale adapter for collector-service.

This module keeps local verification compatible with the current Python 3.6
environment while preserving the safety goals from the merge plan:
- shared/private connection pool management
- COPY-based bulk upsert
- validated identifiers + placeholder parameters
- raw/legacy write-mode support
"""

from __future__ import absolute_import

import time
from contextlib import contextmanager
from datetime import datetime
from threading import Lock
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

try:
    from psycopg.rows import dict_row
except Exception:
    dict_row = None

try:
    from psycopg import sql as psycopg_sql
except Exception:
    psycopg_sql = None

try:
    from psycopg_pool import ConnectionPool
except Exception:
    ConnectionPool = None

from src.config import load_config
from src.adapters.schema_adapter import KlineAdapter, MetricsAdapter, SchemaAdapter


class _RuntimeState(object):
    def __init__(self):
        # type: () -> None
        self.shared_pool = None
        self.shared_pool_key = None
        self.shared_pool_lock = Lock()


_RUNTIME_STATE = _RuntimeState()


def reset_shared_pool():
    # type: () -> None
    pool = _RUNTIME_STATE.shared_pool
    if pool is not None:
        try:
            pool.close()
        except Exception:
            pass
    _RUNTIME_STATE.shared_pool = None
    _RUNTIME_STATE.shared_pool_key = None


def _normalize_write_mode(value):
    # type: (Optional[str]) -> str
    mode = (value or "raw").strip().lower()
    if mode not in ("raw", "legacy"):
        raise ValueError("Invalid write mode: {0}".format(value))
    return mode


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


def _quote_identifier(value, label):
    # type: (str, str) -> str
    safe = _validate_identifier(value, label)
    return '"{0}"'.format(safe)


def _identifier_part(value, label):
    # type: (str, str) -> Any
    safe = _validate_identifier(value, label)
    if psycopg_sql is not None:
        return psycopg_sql.Identifier(safe)
    return '"{0}"'.format(safe)


def _quote_columns(columns):
    # type: (Sequence[str]) -> Any
    if psycopg_sql is not None:
        return psycopg_sql.SQL(", ").join([_identifier_part(column, "column") for column in columns])
    return ", ".join([_quote_identifier(column, "column") for column in columns])


def _render_update_assignments(columns):
    # type: (Sequence[str]) -> Any
    if psycopg_sql is not None:
        return psycopg_sql.SQL(", ").join(
            [
                psycopg_sql.SQL("{col} = EXCLUDED.{col}").format(col=_identifier_part(column, "column"))
                for column in columns
            ]
        )
    assignments = []
    for column in columns:
        quoted = _quote_identifier(column, "column")
        assignments.append("{0} = EXCLUDED.{0}".format(quoted))
    return ", ".join(assignments)


def _now_millis():
    # type: () -> int
    return int(time.time() * 1000)


def _get_shared_pool(db_url, pool_factory, pool_kwargs):
    # type: (str, Any, Dict[str, Any]) -> Any
    key = (db_url, tuple(sorted(pool_kwargs.items())))
    if _RUNTIME_STATE.shared_pool is None or _RUNTIME_STATE.shared_pool_key != key:
        with _RUNTIME_STATE.shared_pool_lock:
            if _RUNTIME_STATE.shared_pool is None or _RUNTIME_STATE.shared_pool_key != key:
                if _RUNTIME_STATE.shared_pool is not None:
                    try:
                        _RUNTIME_STATE.shared_pool.close()
                    except Exception:
                        pass
                _RUNTIME_STATE.shared_pool = pool_factory(db_url, **pool_kwargs)
                _RUNTIME_STATE.shared_pool_key = key
    return _RUNTIME_STATE.shared_pool


class TimescaleAdapter(object):
    """Unified TimescaleDB adapter with shared pool and dual write-mode support."""

    def __init__(
        self,
        db_url=None,
        default_db_url=None,
        market_db_schema=None,
        raw_db_schema=None,
        quality_db_schema=None,
        write_mode=None,
        pool_min=2,
        pool_max=10,
        timeout=30.0,
        pool_factory=None,
    ):
        # type: (Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], int, int, float, Optional[Any]) -> None
        cfg = load_config()
        self.db_url = db_url or cfg.database.database_url
        self.default_db_url = default_db_url or cfg.database.database_url
        self.market_db_schema = market_db_schema or cfg.database.market_db_schema
        self.raw_db_schema = raw_db_schema or cfg.database.raw_db_schema
        self.quality_db_schema = quality_db_schema or cfg.database.quality_db_schema
        self.write_mode = _normalize_write_mode(write_mode or cfg.database.crypto_write_mode)
        self._schema_adapter = SchemaAdapter(
            write_mode=self.write_mode,
            market_db_schema=self.market_db_schema,
            raw_db_schema=self.raw_db_schema,
        )
        self.market_db_schema = self._schema_adapter.market_db_schema
        self.raw_db_schema = self._schema_adapter.raw_db_schema
        self._pool_min = int(pool_min)
        self._pool_max = int(pool_max)
        self._timeout = float(timeout)
        self._pool_factory = pool_factory or ConnectionPool
        self._pool = None

    @property
    def is_raw_mode(self):
        # type: () -> bool
        return self.write_mode == "raw"

    def _pool_kwargs(self):
        # type: () -> Dict[str, Any]
        return {
            "min_size": self._pool_min,
            "max_size": self._pool_max,
            "timeout": self._timeout,
            "max_idle": 300,
            "max_lifetime": 3600,
        }

    @property
    def pool(self):
        # type: () -> Any
        if self._pool_factory is None:
            raise RuntimeError("psycopg_pool is not available")
        if self.db_url == self.default_db_url:
            return _get_shared_pool(self.db_url, self._pool_factory, self._pool_kwargs())
        if self._pool is None:
            self._pool = self._pool_factory(self.db_url, **self._pool_kwargs())
        return self._pool

    def close(self):
        # type: () -> None
        if self._pool is not None and self.db_url != self.default_db_url:
            self._pool.close()
            self._pool = None

    @contextmanager
    def connection(self):
        # type: () -> Iterator[Any]
        with self.pool.connection() as conn:
            yield conn

    def _qualified_table(self, schema_name, table_name):
        # type: (str, str) -> str
        return "{0}.{1}".format(
            _quote_identifier(schema_name, "schema"),
            _quote_identifier(table_name, "table"),
        )

    def _qualified_table_sql(self, schema_name, table_name):
        # type: (str, str) -> Any
        if psycopg_sql is not None:
            return psycopg_sql.SQL("{schema}.{table}").format(
                schema=_identifier_part(schema_name, "schema"),
                table=_identifier_part(table_name, "table"),
            )
        return self._qualified_table(schema_name, table_name)

    def _split_table_name(self, qualified_name):
        # type: (str) -> Tuple[str, str]
        value = (qualified_name or "").strip()
        if "." not in value:
            raise ValueError("Expected qualified table name: {0}".format(qualified_name))
        schema_name, table_name = value.split(".", 1)
        return (
            _validate_identifier(schema_name, "schema"),
            _validate_identifier(table_name, "table"),
        )

    def _temp_table_name(self, prefix):
        # type: (str) -> str
        return _validate_identifier("{0}_{1}".format(prefix, _now_millis()), "temp table")

    def _table_columns(self, rows):
        # type: (Sequence[Dict[str, Any]]) -> List[str]
        columns = list(rows[0].keys())
        for column in columns:
            _validate_identifier(column, "column")
        return columns

    def _copy_query(self, table_name, columns):
        # type: (str, Sequence[str]) -> Any
        if psycopg_sql is not None:
            return psycopg_sql.SQL("COPY {table} ({cols}) FROM STDIN").format(
                table=_identifier_part(table_name, "temp table"),
                cols=_quote_columns(columns),
            )
        return "COPY {0} ({1}) FROM STDIN".format(
            _quote_identifier(table_name, "temp table"),
            _quote_columns(columns),
        )

    def _create_temp_table_query(self, temp_table_name, schema_name, table_name):
        # type: (str, str, str) -> Any
        if psycopg_sql is not None:
            return psycopg_sql.SQL(
                "CREATE TEMP TABLE {temp_table} (LIKE {target_table} INCLUDING DEFAULTS) ON COMMIT DROP;"
            ).format(
                temp_table=_identifier_part(temp_table_name, "temp table"),
                target_table=self._qualified_table_sql(schema_name, table_name),
            )
        return (
            "CREATE TEMP TABLE {temp_table} (LIKE {target_table} INCLUDING DEFAULTS) "
            "ON COMMIT DROP;"
        ).format(
            temp_table=_quote_identifier(temp_table_name, "temp table"),
            target_table=self._qualified_table(schema_name, table_name),
        )

    def _upsert_query(self, schema_name, table_name, temp_table_name, columns, conflict_keys, touch_updated_at=True):
        # type: (str, str, str, Sequence[str], Sequence[str], bool) -> Any
        update_columns = [column for column in columns if column not in conflict_keys]
        if not update_columns and not touch_updated_at:
            if psycopg_sql is not None:
                return psycopg_sql.SQL(
                    "INSERT INTO {target_table} ({columns}) "
                    "SELECT {columns} FROM {temp_table} "
                    "ON CONFLICT ({conflict_keys}) DO NOTHING;"
                ).format(
                    target_table=self._qualified_table_sql(schema_name, table_name),
                    columns=_quote_columns(columns),
                    temp_table=_identifier_part(temp_table_name, "temp table"),
                    conflict_keys=_quote_columns(conflict_keys),
                )
            return (
                "INSERT INTO {target_table} ({columns}) "
                "SELECT {columns} FROM {temp_table} "
                "ON CONFLICT ({conflict_keys}) DO NOTHING;"
            ).format(
                target_table=self._qualified_table(schema_name, table_name),
                columns=_quote_columns(columns),
                temp_table=_quote_identifier(temp_table_name, "temp table"),
                conflict_keys=_quote_columns(conflict_keys),
            )

        if psycopg_sql is not None:
            updates = []
            if update_columns:
                updates.append(_render_update_assignments(update_columns))
            if touch_updated_at:
                updates.append(psycopg_sql.SQL("updated_at = NOW()"))
            return psycopg_sql.SQL(
                "INSERT INTO {target_table} ({columns}) "
                "SELECT {columns} FROM {temp_table} "
                "ON CONFLICT ({conflict_keys}) DO UPDATE SET {updates};"
            ).format(
                target_table=self._qualified_table_sql(schema_name, table_name),
                columns=_quote_columns(columns),
                temp_table=_identifier_part(temp_table_name, "temp table"),
                conflict_keys=_quote_columns(conflict_keys),
                updates=psycopg_sql.SQL(", ").join(updates),
            )
        updates = []
        if update_columns:
            updates.append(_render_update_assignments(update_columns))
        if touch_updated_at:
            updates.append("updated_at = NOW()")
        return (
            "INSERT INTO {target_table} ({columns}) "
            "SELECT {columns} FROM {temp_table} "
            "ON CONFLICT ({conflict_keys}) DO UPDATE SET {updates};"
        ).format(
            target_table=self._qualified_table(schema_name, table_name),
            columns=_quote_columns(columns),
            temp_table=_quote_identifier(temp_table_name, "temp table"),
            conflict_keys=_quote_columns(conflict_keys),
            updates=", ".join(updates),
        )

    def _query_table_name(self, interval):
        # type: (str) -> Tuple[str, str]
        return self._split_table_name(self._schema_adapter.get_kline_table(interval))

    def _query_time_field(self):
        # type: () -> str
        return _validate_identifier(self._schema_adapter.get_kline_time_field(), "column")

    def _get_batch_id(self, data_type):
        # type: (str) -> int
        market = "crypto" if data_type in ("kline", "metrics") else None
        if psycopg_sql is not None:
            query = psycopg_sql.SQL("SELECT {schema}.start_batch(%s, %s, %s, %s, %s, %s)").format(
                schema=_identifier_part(self.quality_db_schema, "schema")
            )
        else:
            query = "SELECT {0}.start_batch(%s, %s, %s, %s, %s, %s)".format(
                _quote_identifier(self.quality_db_schema, "schema")
            )
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, ("collector-service", data_type, market, None, None, None))
                result = cur.fetchone()
                conn.commit()
                if not result:
                    return 0
                return int(result[0])

    def _get_batch_id_safe(self, data_type):
        # type: (str) -> Optional[int]
        try:
            value = self._get_batch_id(data_type)
            return value if value > 0 else None
        except Exception:
            return None

    def _transform_kline_rows(self, interval, rows):
        # type: (str, Sequence[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], str, str, Tuple[str, ...], bool]
        table_name = self._schema_adapter.get_kline_table(interval)
        if self.is_raw_mode:
            batch_id = self._get_batch_id_safe("kline") or 0
            transformed = KlineAdapter.to_new_schema(rows, batch_id=batch_id, interval=interval)
        else:
            transformed = KlineAdapter.to_legacy_schema(rows)
        schema_name, short_table_name = self._split_table_name(table_name)
        return (
            transformed,
            schema_name,
            short_table_name,
            self._schema_adapter.get_kline_conflict_keys(),
            self._schema_adapter.kline_has_updated_at(),
        )

    def _transform_metrics_rows(self, rows):
        # type: (Sequence[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], str, str, Tuple[str, ...], bool]
        table_name = self._schema_adapter.get_metrics_table()
        if self.is_raw_mode:
            batch_id = self._get_batch_id_safe("metrics") or 0
            transformed = MetricsAdapter.to_new_schema(rows, batch_id=batch_id)
        else:
            transformed = MetricsAdapter.to_legacy_schema(rows)
        schema_name, short_table_name = self._split_table_name(table_name)
        return (
            transformed,
            schema_name,
            short_table_name,
            self._schema_adapter.get_metrics_conflict_keys(),
            self._schema_adapter.metrics_has_updated_at(),
        )

    def _copy_upsert(self, rows, schema_name, table_name, conflict_keys, temp_prefix, batch_size, touch_updated_at=True):
        # type: (Sequence[Dict[str, Any]], str, str, Sequence[str], str, int, bool) -> int
        if not rows:
            return 0

        columns = self._table_columns(rows)
        temp_table_name = self._temp_table_name(temp_prefix)
        create_query = self._create_temp_table_query(temp_table_name, schema_name, table_name)
        upsert_query = self._upsert_query(
            schema_name,
            table_name,
            temp_table_name,
            columns,
            conflict_keys,
            touch_updated_at=touch_updated_at,
        )

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(create_query)
                for start in range(0, len(rows), batch_size):
                    batch = rows[start:start + batch_size]
                    with cur.copy(self._copy_query(temp_table_name, columns)) as copy:
                        for row in batch:
                            copy.write_row(tuple([row.get(column) for column in columns]))
                cur.execute(upsert_query)
                affected = cur.rowcount if cur.rowcount > 0 else len(rows)
            conn.commit()
        return affected

    def upsert_candles(self, interval, rows, batch_size=2000):
        # type: (str, Sequence[Dict[str, Any]], int) -> int
        if not rows:
            return 0
        transformed_rows, schema_name, table_name, conflict_keys, touch_updated_at = self._transform_kline_rows(
            interval,
            rows,
        )
        return self._copy_upsert(
            transformed_rows,
            schema_name,
            table_name,
            conflict_keys,
            "temp_candles",
            batch_size,
            touch_updated_at=touch_updated_at,
        )

    def upsert_metrics(self, rows, batch_size=2000):
        # type: (Sequence[Dict[str, Any]], int) -> int
        if not rows:
            return 0
        transformed_rows, schema_name, table_name, conflict_keys, touch_updated_at = self._transform_metrics_rows(rows)
        return self._copy_upsert(
            transformed_rows,
            schema_name,
            table_name,
            conflict_keys,
            "temp_metrics",
            batch_size,
            touch_updated_at=touch_updated_at,
        )

    def get_symbols(self, exchange, interval="1m"):
        # type: (str, str) -> List[str]
        schema_name, table_name = self._query_table_name(interval)
        if psycopg_sql is not None:
            query = psycopg_sql.SQL("SELECT DISTINCT symbol FROM {table} WHERE exchange = %s ORDER BY symbol").format(
                table=self._qualified_table_sql(schema_name, table_name)
            )
        else:
            query = "SELECT DISTINCT symbol FROM {0} WHERE exchange = %s ORDER BY symbol".format(
                self._qualified_table(schema_name, table_name)
            )
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (exchange,))
                return [row[0] for row in cur.fetchall()]

    def get_counts(self, exchange, interval, symbols):
        # type: (str, str, Sequence[str]) -> Dict[str, Any]
        if not symbols:
            return {}
        schema_name, table_name = self._query_table_name(interval)
        if psycopg_sql is not None:
            query = psycopg_sql.SQL(
                "SELECT symbol, COUNT(*) FROM {table} "
                "WHERE exchange = %s AND symbol = ANY(%s) GROUP BY symbol"
            ).format(table=self._qualified_table_sql(schema_name, table_name))
        else:
            query = (
                "SELECT symbol, COUNT(*) FROM {0} "
                "WHERE exchange = %s AND symbol = ANY(%s) GROUP BY symbol"
            ).format(self._qualified_table(schema_name, table_name))
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (exchange, list(symbols)))
                return dict(cur.fetchall())

    def detect_gaps(
        self,
        exchange,
        interval,
        symbols,
        lookback_min=10080,
        threshold_sec=120,
        limit=50,
    ):
        # type: (str, str, Sequence[str], int, int, int) -> List[Any]
        schema_name, table_name = self._query_table_name(interval)
        time_field = self._query_time_field()
        lookback_value = int(lookback_min)
        threshold_value = int(threshold_sec)
        limit_value = int(limit)
        if psycopg_sql is not None:
            query = psycopg_sql.SQL(
                "WITH ordered AS ("
                " SELECT symbol, {time_field}, LEAD({time_field}) OVER (PARTITION BY symbol ORDER BY {time_field}) AS next_ts"
                " FROM {table}"
                " WHERE exchange = %(exchange)s AND symbol = ANY(%(symbols)s)"
                "   AND {time_field} >= NOW() - INTERVAL {lookback}"
                ") "
                "SELECT symbol, {time_field}, next_ts FROM ordered "
                "WHERE next_ts IS NOT NULL AND next_ts - {time_field} >= INTERVAL {threshold} "
                "ORDER BY {time_field} LIMIT %(limit)s"
            ).format(
                time_field=psycopg_sql.SQL(time_field),
                table=self._qualified_table_sql(schema_name, table_name),
                lookback=psycopg_sql.Literal("{0} minutes".format(lookback_value)),
                threshold=psycopg_sql.Literal("{0} seconds".format(threshold_value)),
            )
        else:
            query = (
                "WITH ordered AS ("
                " SELECT symbol, {time_field}, LEAD({time_field}) OVER (PARTITION BY symbol ORDER BY {time_field}) AS next_ts"
                " FROM {table}"
                " WHERE exchange = %(exchange)s AND symbol = ANY(%(symbols)s)"
                "   AND {time_field} >= NOW() - INTERVAL '{lookback} minutes'"
                ") "
                "SELECT symbol, {time_field}, next_ts FROM ordered "
                "WHERE next_ts IS NOT NULL AND next_ts - {time_field} >= INTERVAL '{threshold} seconds' "
                "ORDER BY {time_field} LIMIT %(limit)s"
            ).format(
                time_field=time_field,
                table=self._qualified_table(schema_name, table_name),
                lookback=lookback_value,
                threshold=threshold_value,
            )
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    {"exchange": exchange, "symbols": list(symbols), "limit": limit_value},
                )
                return cur.fetchall()

    def query(self, exchange, symbol, interval, start=None, end=None, limit=1000):
        # type: (str, str, str, Optional[datetime], Optional[datetime], int) -> List[Any]
        schema_name, table_name = self._query_table_name(interval)
        time_field = self._query_time_field()
        conditions = ["exchange = %s", "symbol = %s"]
        params = [exchange, symbol]
        if start is not None:
            conditions.append("{0} >= %s".format(time_field))
            params.append(start)
        if end is not None:
            conditions.append("{0} <= %s".format(time_field))
            params.append(end)
        params.append(int(limit))
        if psycopg_sql is not None:
            query = psycopg_sql.SQL("SELECT * FROM {table} WHERE {conds} ORDER BY {time_field} DESC LIMIT %s").format(
                table=self._qualified_table_sql(schema_name, table_name),
                conds=psycopg_sql.SQL(" AND ").join([psycopg_sql.SQL(cond) for cond in conditions]),
                time_field=psycopg_sql.SQL(time_field),
            )
        else:
            query = "SELECT * FROM {table} WHERE {conds} ORDER BY {time_field} DESC LIMIT %s".format(
                table=self._qualified_table(schema_name, table_name),
                conds=" AND ".join(conditions),
                time_field=time_field,
            )
        with self.connection() as conn:
            row_factory = dict_row if dict_row is not None else None
            with conn.cursor(row_factory=row_factory) as cur:
                cur.execute(query, params)
                return cur.fetchall()
