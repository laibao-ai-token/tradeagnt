"""Crypto backfill helpers for collector-service."""

from __future__ import absolute_import

import calendar
import csv
import logging
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import requests

try:
    from psycopg import sql as psycopg_sql
except Exception:
    psycopg_sql = None

from src.adapters.metrics import Timer, metrics
from src.adapters.schema_adapter import SchemaAdapter
from src.adapters.timescale import TimescaleAdapter
from src.collectors.crypto.ws import load_symbols
from src.config import PROJECT_ROOT, load_config


logger = logging.getLogger(__name__)

BINANCE_DATA_URL = "https://data.binance.vision"
EXPECTED_1M_PER_DAY = 1440
EXPECTED_5M_PER_DAY = 288

INTERVAL_TO_MS = {
    "1m": 60 * 1000,
    "3m": 3 * 60 * 1000,
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "30m": 30 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "2h": 2 * 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "6h": 6 * 60 * 60 * 1000,
    "12h": 12 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
    "1w": 7 * 24 * 60 * 60 * 1000,
}

_CCXT_CLIENTS = {}


def _expected_per_day(interval):
    if interval == "1m":
        return EXPECTED_1M_PER_DAY
    value = INTERVAL_TO_MS.get(interval)
    if not value:
        raise ValueError("Unsupported interval: {0}".format(interval))
    return int((24 * 60 * 60 * 1000) / value)


def _build_ccxt_client(exchange, http_proxy=""):
    key = (exchange, http_proxy or "")
    if key in _CCXT_CLIENTS:
        return _CCXT_CLIENTS[key]

    import ccxt

    exchange_cls = getattr(ccxt, exchange, None)
    if exchange_cls is None:
        raise ValueError("unsupported exchange: {0}".format(exchange))

    kwargs = {
        "enableRateLimit": True,
        "timeout": 30000,
        "options": {"defaultType": "swap"},
    }
    if http_proxy:
        kwargs["proxies"] = {"http": http_proxy, "https": http_proxy}
    _CCXT_CLIENTS[key] = exchange_cls(kwargs)
    return _CCXT_CLIENTS[key]


def fetch_ohlcv(exchange, symbol, interval="1m", since_ms=None, limit=1000, http_proxy=""):
    if not (symbol or "").upper().endswith("USDT"):
        return []

    market_symbol = "{0}/USDT:USDT".format(symbol.upper()[:-4])
    try:
        client = _build_ccxt_client(exchange, http_proxy=http_proxy)
        return client.fetch_ohlcv(market_symbol, interval, since=since_ms, limit=limit) or []
    except Exception as exc:
        logger.debug("fetch_ohlcv failed exchange=%s symbol=%s error=%s", exchange, symbol, exc)
        return []


def to_candle_rows(exchange, symbol, candles, source="ccxt_gap"):
    rows = []
    for candle in list(candles or []):
        if len(candle) < 6:
            continue
        rows.append(
            {
                "exchange": exchange,
                "symbol": symbol.upper(),
                "bucket_ts": datetime.utcfromtimestamp(int(candle[0]) / 1000),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
                "source": source,
                "is_closed": True,
            }
        )
    return rows


def _safe_list(payload):
    return payload if isinstance(payload, list) else []


def _split_table_name(qualified_name):
    value = (qualified_name or "").strip()
    if "." not in value:
        raise ValueError("Expected qualified table name: {0}".format(qualified_name))
    return value.split(".", 1)


def _qualified_table_sql(qualified_name):
    schema_name, table_name = _split_table_name(qualified_name)
    if psycopg_sql is not None:
        return psycopg_sql.SQL("{schema}.{table}").format(
            schema=psycopg_sql.Identifier(schema_name),
            table=psycopg_sql.Identifier(table_name),
        )
    return '"{0}"."{1}"'.format(schema_name, table_name)


def _parse_start_date(value):
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except Exception:
        logger.warning("invalid BACKFILL_START_DATE: %s", value)
        return None


def get_backfill_config(config=None):
    cfg = config or load_config()
    start_date = _parse_start_date(getattr(cfg.runtime, "backfill_start_date", ""))
    return (
        getattr(cfg.runtime, "backfill_mode", "days"),
        int(getattr(cfg.runtime, "backfill_days", 30)),
        start_date,
    )


def compute_lookback(mode, days, start_date=None, today=None):
    current_date = today or date.today()
    normalized = (mode or "days").lower()

    if normalized == "none":
        return 0
    if normalized == "all":
        if start_date:
            return max((current_date - start_date).days, 1)
        return 3650
    return max(int(days), 1)


def _parse_metrics_timestamp(raw_value):
    text = (raw_value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    try:
        dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None
    return int(calendar.timegm(dt.timetuple()) * 1000)


class GapInfo(object):
    """Gap metadata for one symbol on one day."""

    def __init__(self, symbol, day, expected, actual):
        self.symbol = symbol
        self.date = day
        self.expected = int(expected)
        self.actual = int(actual)
        self.missing = self.expected - self.actual


class GapScanner(object):
    """Daily completeness scanner for candles and futures metrics."""

    def __init__(self, timescale, config=None):
        self._ts = timescale
        self._config = config or load_config()
        self._schema_adapter = SchemaAdapter(
            write_mode=getattr(timescale, "write_mode", "raw"),
            market_db_schema=getattr(timescale, "market_db_schema", "market_data"),
            raw_db_schema=getattr(timescale, "raw_db_schema", "raw"),
        )

    def _db_exchange(self):
        return getattr(self._config.crypto_kline, "db_exchange", "binance_futures_um")

    def scan_klines(self, symbols, start, end, interval="1m", threshold=0.95):
        expected = _expected_per_day(interval)
        min_count = int(expected * float(threshold))
        table_name = self._schema_adapter.get_kline_table(interval)
        time_field = self._schema_adapter.get_kline_time_field()
        start_ts = datetime.combine(start, datetime.min.time())
        end_ts = datetime.combine(end + timedelta(days=1), datetime.min.time())

        if psycopg_sql is not None:
            query = psycopg_sql.SQL(
                "SELECT symbol, DATE({time_field} AT TIME ZONE 'UTC') AS d, COUNT(*) AS c "
                "FROM {table} "
                "WHERE exchange = %s AND symbol = ANY(%s) "
                "AND {time_field} >= %s AND {time_field} < %s "
                "GROUP BY symbol, DATE({time_field} AT TIME ZONE 'UTC')"
            ).format(
                time_field=psycopg_sql.SQL(time_field),
                table=_qualified_table_sql(table_name),
            )
        else:
            query = (
                "SELECT symbol, DATE({time_field} AT TIME ZONE 'UTC') AS d, COUNT(*) AS c "
                "FROM {table} "
                "WHERE exchange = %s AND symbol = ANY(%s) "
                "AND {time_field} >= %s AND {time_field} < %s "
                "GROUP BY symbol, DATE({time_field} AT TIME ZONE 'UTC')"
            ).format(time_field=time_field, table=_qualified_table_sql(table_name))

        counts = {}
        with self._ts.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (self._db_exchange(), list(symbols), start_ts, end_ts))
                for symbol, day_value, count in cur.fetchall():
                    counts[(symbol, day_value)] = count

        gaps = {}
        for symbol in list(symbols or []):
            symbol_gaps = []
            for offset in range((end - start).days + 1):
                day_value = start + timedelta(days=offset)
                actual = counts.get((symbol, day_value), 0)
                if actual < min_count:
                    symbol_gaps.append(GapInfo(symbol, day_value, expected, actual))
            if symbol_gaps:
                gaps[symbol] = symbol_gaps
        return gaps

    def scan_metrics(self, symbols, start, end, threshold=0.95):
        min_count = int(EXPECTED_5M_PER_DAY * float(threshold))
        table_name = self._schema_adapter.get_metrics_table()
        time_field = self._schema_adapter.get_metrics_time_field()
        start_ts = datetime.combine(start, datetime.min.time())
        end_ts = datetime.combine(end + timedelta(days=1), datetime.min.time())

        if psycopg_sql is not None:
            query = psycopg_sql.SQL(
                "SELECT symbol, DATE({time_field}) AS d, COUNT(*) AS c "
                "FROM {table} "
                "WHERE exchange = %s AND symbol = ANY(%s) "
                "AND {time_field} >= %s AND {time_field} < %s "
                "GROUP BY symbol, DATE({time_field})"
            ).format(
                time_field=psycopg_sql.SQL(time_field),
                table=_qualified_table_sql(table_name),
            )
        else:
            query = (
                "SELECT symbol, DATE({time_field}) AS d, COUNT(*) AS c "
                "FROM {table} "
                "WHERE exchange = %s AND symbol = ANY(%s) "
                "AND {time_field} >= %s AND {time_field} < %s "
                "GROUP BY symbol, DATE({time_field})"
            ).format(time_field=time_field, table=_qualified_table_sql(table_name))

        counts = {}
        with self._ts.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (self._db_exchange(), list(symbols), start_ts, end_ts))
                for symbol, day_value, count in cur.fetchall():
                    counts[(symbol, day_value)] = count

        gaps = {}
        for symbol in list(symbols or []):
            symbol_gaps = []
            for offset in range((end - start).days + 1):
                day_value = start + timedelta(days=offset)
                actual = counts.get((symbol, day_value), 0)
                if actual < min_count:
                    symbol_gaps.append(GapInfo(symbol, day_value, EXPECTED_5M_PER_DAY, actual))
            if symbol_gaps:
                gaps[symbol] = symbol_gaps
        return gaps


class RestBackfiller(object):
    """REST gap filler for kline holes."""

    def __init__(self, timescale, config=None, workers=8):
        self._ts = timescale
        self._config = config or load_config()
        self._workers = int(workers)

    def _db_exchange(self):
        return getattr(self._config.crypto_kline, "db_exchange", "binance_futures_um")

    def _ccxt_exchange(self):
        return getattr(self._config.crypto_kline, "ccxt_exchange", "binance")

    def _http_proxy(self):
        return getattr(self._config.runtime, "http_proxy", "") or ""

    def fill_kline_gap(self, symbol, gap, interval="1m"):
        start_ts = datetime.combine(gap.date, datetime.min.time())
        end_ts = datetime.combine(gap.date + timedelta(days=1), datetime.min.time())
        since_ms = int(calendar.timegm(start_ts.timetuple()) * 1000)
        target_ms = int(calendar.timegm(end_ts.timetuple()) * 1000)
        all_rows = []

        for _ in range(100):
            candles = fetch_ohlcv(
                self._ccxt_exchange(),
                symbol,
                interval=interval,
                since_ms=since_ms,
                limit=1000,
                http_proxy=self._http_proxy(),
            )
            if not candles:
                break

            rows = [
                row
                for row in to_candle_rows(self._db_exchange(), symbol, candles, source="ccxt_gap")
                if start_ts <= row["bucket_ts"] < end_ts
            ]
            all_rows.extend(rows)
            last_ms = int(candles[-1][0])
            if last_ms == since_ms or last_ms >= target_ms:
                break
            since_ms = last_ms + INTERVAL_TO_MS.get(interval, 60000)

        if all_rows:
            self._ts.upsert_candles(interval, all_rows)
        return len(all_rows)

    def fill_gaps(self, gaps, interval="1m"):
        tasks = []
        for symbol, symbol_gaps in gaps.items():
            for gap in symbol_gaps:
                tasks.append((symbol, gap, interval))
        if not tasks:
            return 0

        total = 0
        with ThreadPoolExecutor(max_workers=max(1, self._workers)) as pool:
            futures = dict((pool.submit(self.fill_kline_gap, symbol, gap, interval_value), (symbol, gap.date)) for symbol, gap, interval_value in tasks)
            for future in as_completed(futures):
                try:
                    total += int(future.result() or 0)
                except Exception as exc:
                    symbol, day_value = futures[future]
                    logger.warning("[%s] %s REST backfill failed: %s", symbol, day_value, exc)
        return total


class MetricsRestBackfiller(object):
    """REST filler for daily futures metrics gaps."""

    FAPI = "https://fapi.binance.com"

    def __init__(self, timescale, config=None, workers=3, session=None):
        self._ts = timescale
        self._config = config or load_config()
        self._workers = int(workers)
        self._session = session or requests.Session()
        self._owns_session = session is None
        proxy = getattr(self._config.runtime, "http_proxy", "") or ""
        self._proxies = {"http": proxy, "https": proxy} if proxy else {}

    def _period(self):
        return getattr(self._config.crypto_metrics, "interval", "5m") or "5m"

    def _db_exchange(self):
        return getattr(self._config.crypto_kline, "db_exchange", "binance_futures_um")

    def _get(self, url, params):
        try:
            response = self._session.get(url, params=params, proxies=self._proxies, timeout=15)
            if response.status_code in (418, 429):
                return None
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            logger.debug("metrics backfill request failed symbol=%s error=%s", params.get("symbol"), exc)
            return None

    def _fetch_day(self, symbol, day_value):
        start_ms = int(calendar.timegm(datetime.combine(day_value, datetime.min.time()).timetuple()) * 1000)
        end_ms = start_ms + (24 * 60 * 60 * 1000) - 1
        period = self._period()
        apis = [
            ("oi", "{0}/futures/data/openInterestHist".format(self.FAPI), {"symbol": symbol, "period": period, "startTime": start_ms, "endTime": end_ms, "limit": 500}),
            ("pos", "{0}/futures/data/topLongShortPositionRatio".format(self.FAPI), {"symbol": symbol, "period": period, "startTime": start_ms, "endTime": end_ms, "limit": 500}),
            ("acc", "{0}/futures/data/topLongShortAccountRatio".format(self.FAPI), {"symbol": symbol, "period": period, "startTime": start_ms, "endTime": end_ms, "limit": 500}),
            ("glb", "{0}/futures/data/globalLongShortAccountRatio".format(self.FAPI), {"symbol": symbol, "period": period, "startTime": start_ms, "endTime": end_ms, "limit": 500}),
            ("taker", "{0}/futures/data/takerlongshortRatio".format(self.FAPI), {"symbol": symbol, "period": period, "startTime": start_ms, "endTime": end_ms, "limit": 500}),
        ]

        results = {}
        for key, url, params in apis:
            results[key] = _safe_list(self._get(url, params))

        oi_list = results.get("oi", [])
        if not oi_list:
            return []

        pos_map = dict((row.get("timestamp"), row) for row in results.get("pos", []) if isinstance(row, dict))
        acc_map = dict((row.get("timestamp"), row) for row in results.get("acc", []) if isinstance(row, dict))
        glb_map = dict((row.get("timestamp"), row) for row in results.get("glb", []) if isinstance(row, dict))
        taker_map = dict((row.get("timestamp"), row) for row in results.get("taker", []) if isinstance(row, dict))

        rows = []
        for oi_row in oi_list:
            if not isinstance(oi_row, dict):
                continue
            timestamp = int(oi_row.get("timestamp", 0))
            aligned = (timestamp // 300000) * 300000
            pos_row = pos_map.get(timestamp, {})
            acc_row = acc_map.get(timestamp, {})
            glb_row = glb_map.get(timestamp, {})
            taker_row = taker_map.get(timestamp, {})

            rows.append(
                {
                    "create_time": datetime.utcfromtimestamp(aligned / 1000),
                    "symbol": symbol.upper(),
                    "exchange": self._db_exchange(),
                    "sum_open_interest": _to_decimal(oi_row.get("sumOpenInterest")),
                    "sum_open_interest_value": _to_decimal(oi_row.get("sumOpenInterestValue")),
                    "count_toptrader_long_short_ratio": _to_decimal(acc_row.get("longShortRatio")),
                    "sum_toptrader_long_short_ratio": _to_decimal(pos_row.get("longShortRatio")),
                    "count_long_short_ratio": _to_decimal(glb_row.get("longShortRatio")),
                    "sum_taker_long_short_vol_ratio": _to_decimal(taker_row.get("buySellRatio")),
                    "source": "binance_rest",
                    "is_closed": True,
                }
            )
        return rows

    def fill_gap(self, symbol, gap):
        rows = self._fetch_day(symbol, gap.date)
        if rows:
            self._ts.upsert_metrics(rows)
            return len(rows)
        return 0

    def fill_gaps(self, gaps):
        tasks = []
        for symbol, symbol_gaps in gaps.items():
            for gap in symbol_gaps:
                tasks.append((symbol, gap))
        if not tasks:
            return 0

        total = 0
        with ThreadPoolExecutor(max_workers=max(1, self._workers)) as pool:
            futures = dict((pool.submit(self.fill_gap, symbol, gap), (symbol, gap.date)) for symbol, gap in tasks)
            for future in as_completed(futures):
                try:
                    total += int(future.result() or 0)
                except Exception as exc:
                    symbol, day_value = futures[future]
                    logger.warning("[%s] %s metrics REST backfill failed: %s", symbol, day_value, exc)
        return total

    def close(self):
        if self._owns_session and hasattr(self._session, "close"):
            self._session.close()


class ZipBackfiller(object):
    """ZIP downloader/importer for Binance Vision historical data."""

    MAX_CACHE_DAYS = 7

    def __init__(self, timescale, config=None, workers=8, data_dir=None, metrics_client=None):
        self._ts = timescale
        self._config = config or load_config()
        self._workers = int(workers)
        self._metrics = metrics_client or metrics
        root_dir = Path(data_dir) if data_dir else (PROJECT_ROOT / "libs" / "database" / "csv")
        self._kline_dir = root_dir / "downloads" / "klines"
        self._metrics_dir = root_dir / "downloads" / "metrics"
        self._kline_dir.mkdir(parents=True, exist_ok=True)
        self._metrics_dir.mkdir(parents=True, exist_ok=True)
        proxy = getattr(self._config.runtime, "http_proxy", "") or ""
        self._proxy_options = [{}]
        if proxy:
            self._proxy_options.append({"http": proxy, "https": proxy})

    def _db_exchange(self):
        return getattr(self._config.crypto_kline, "db_exchange", "binance_futures_um")

    def cleanup_old_files(self, max_age_days=None):
        cutoff = time.time() - int(max_age_days or self.MAX_CACHE_DAYS) * 86400
        removed = 0
        for directory in (self._kline_dir, self._metrics_dir):
            for path in directory.glob("*.zip"):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                        removed += 1
                except OSError:
                    pass
        return removed

    def _download_with_retry(self, url, path):
        for proxies in self._proxy_options:
            try:
                response = requests.get(url, proxies=proxies or None, timeout=60)
                if response.status_code == 404:
                    return False
                if response.status_code in (418, 429):
                    return False
                response.raise_for_status()
                path.write_bytes(response.content)
                self._metrics.inc("zip_downloads")
                return True
            except Exception as exc:
                logger.debug("zip download failed url=%s error=%s", url, exc)
        return False

    def _download_kline_month(self, symbol, month, dates, interval):
        total = 0
        upper_symbol = symbol.upper()
        current_month = date.today().strftime("%Y-%m")

        if month == current_month:
            for day_value in dates:
                day_text = day_value.strftime("%Y-%m-%d")
                file_name = "{0}-{1}-{2}.zip".format(upper_symbol, interval, day_text)
                file_path = self._kline_dir / file_name
                if not file_path.exists():
                    url = "{0}/data/futures/um/daily/klines/{1}/{2}/{3}".format(
                        BINANCE_DATA_URL,
                        upper_symbol,
                        interval,
                        file_name,
                    )
                    if not self._download_with_retry(url, file_path):
                        continue
                total += self._import_kline_zip(str(file_path), symbol, interval)
            return total

        month_name = "{0}-{1}-{2}.zip".format(upper_symbol, interval, month)
        month_path = self._kline_dir / month_name
        if not month_path.exists():
            url = "{0}/data/futures/um/monthly/klines/{1}/{2}/{3}".format(
                BINANCE_DATA_URL,
                upper_symbol,
                interval,
                month_name,
            )
            self._download_with_retry(url, month_path)
        if month_path.exists():
            for day_value in dates:
                total += self._import_kline_zip(str(month_path), symbol, interval, filter_date=day_value)
            return total

        for day_value in dates:
            day_text = day_value.strftime("%Y-%m-%d")
            file_name = "{0}-{1}-{2}.zip".format(upper_symbol, interval, day_text)
            file_path = self._kline_dir / file_name
            if not file_path.exists():
                url = "{0}/data/futures/um/daily/klines/{1}/{2}/{3}".format(
                    BINANCE_DATA_URL,
                    upper_symbol,
                    interval,
                    file_name,
                )
                if not self._download_with_retry(url, file_path):
                    continue
            total += self._import_kline_zip(str(file_path), symbol, interval)
        return total

    def _download_metrics_month(self, symbol, month, dates):
        total = 0
        upper_symbol = symbol.upper()
        current_month = date.today().strftime("%Y-%m")

        if month == current_month:
            for day_value in dates:
                day_text = day_value.strftime("%Y-%m-%d")
                file_name = "{0}-metrics-{1}.zip".format(upper_symbol, day_text)
                file_path = self._metrics_dir / file_name
                if not file_path.exists():
                    url = "{0}/data/futures/um/daily/metrics/{1}/{2}".format(BINANCE_DATA_URL, upper_symbol, file_name)
                    if not self._download_with_retry(url, file_path):
                        continue
                total += self._import_metrics_zip(str(file_path), symbol)
            return total

        month_name = "{0}-metrics-{1}.zip".format(upper_symbol, month)
        month_path = self._metrics_dir / month_name
        if not month_path.exists():
            url = "{0}/data/futures/um/monthly/metrics/{1}/{2}".format(BINANCE_DATA_URL, upper_symbol, month_name)
            self._download_with_retry(url, month_path)
        if month_path.exists():
            for day_value in dates:
                total += self._import_metrics_zip(str(month_path), symbol, filter_date=day_value)
            return total

        for day_value in dates:
            day_text = day_value.strftime("%Y-%m-%d")
            file_name = "{0}-metrics-{1}.zip".format(upper_symbol, day_text)
            file_path = self._metrics_dir / file_name
            if not file_path.exists():
                url = "{0}/data/futures/um/daily/metrics/{1}/{2}".format(BINANCE_DATA_URL, upper_symbol, file_name)
                if not self._download_with_retry(url, file_path):
                    continue
            total += self._import_metrics_zip(str(file_path), symbol)
        return total

    def fill_kline_gaps(self, gaps, interval="1m"):
        tasks = {}
        for symbol, symbol_gaps in gaps.items():
            for gap in symbol_gaps:
                key = (symbol, gap.date.strftime("%Y-%m"))
                tasks.setdefault(key, []).append(gap.date)
        if not tasks:
            return 0

        total = 0
        with ThreadPoolExecutor(max_workers=max(1, self._workers)) as pool:
            futures = dict(
                (
                    pool.submit(self._download_kline_month, symbol, month, dates, interval),
                    (symbol, month),
                )
                for (symbol, month), dates in tasks.items()
            )
            for future in as_completed(futures):
                try:
                    total += int(future.result() or 0)
                except Exception as exc:
                    symbol, month = futures[future]
                    logger.warning("[%s] %s zip kline backfill failed: %s", symbol, month, exc)
        return total

    def fill_metrics_gaps(self, gaps):
        tasks = {}
        for symbol, symbol_gaps in gaps.items():
            for gap in symbol_gaps:
                key = (symbol, gap.date.strftime("%Y-%m"))
                tasks.setdefault(key, []).append(gap.date)
        if not tasks:
            return 0

        total = 0
        with ThreadPoolExecutor(max_workers=max(1, self._workers)) as pool:
            futures = dict(
                (
                    pool.submit(self._download_metrics_month, symbol, month, dates),
                    (symbol, month),
                )
                for (symbol, month), dates in tasks.items()
            )
            for future in as_completed(futures):
                try:
                    total += int(future.result() or 0)
                except Exception as exc:
                    symbol, month = futures[future]
                    logger.warning("[%s] %s zip metrics backfill failed: %s", symbol, month, exc)
        return total

    def _import_kline_zip(self, path, symbol, interval, filter_date=None):
        rows = []
        archive = None
        try:
            archive = zipfile.ZipFile(path)
            for name in archive.namelist():
                if not name.endswith(".csv"):
                    continue
                with archive.open(name) as handle:
                    reader = csv.reader(line.decode("utf-8") for line in handle)
                    for row in reader:
                        if len(row) < 6:
                            continue
                        try:
                            timestamp = datetime.utcfromtimestamp(int(row[0]) / 1000)
                            if filter_date and timestamp.date() != filter_date:
                                continue
                            rows.append(
                                {
                                    "exchange": self._db_exchange(),
                                    "symbol": symbol.upper(),
                                    "bucket_ts": timestamp,
                                    "open": float(row[1]),
                                    "high": float(row[2]),
                                    "low": float(row[3]),
                                    "close": float(row[4]),
                                    "volume": float(row[5]),
                                    "quote_volume": float(row[7]) if len(row) > 7 and row[7] else None,
                                    "trade_count": int(row[8]) if len(row) > 8 and row[8] else None,
                                    "taker_buy_volume": float(row[9]) if len(row) > 9 and row[9] else None,
                                    "taker_buy_quote_volume": float(row[10]) if len(row) > 10 and row[10] else None,
                                    "source": "binance_zip",
                                    "is_closed": True,
                                }
                            )
                        except Exception:
                            continue
        except Exception as exc:
            logger.error("failed to parse kline zip %s: %s", path, exc)
            return 0
        finally:
            if archive is not None:
                archive.close()

        if rows:
            return self._ts.upsert_candles(interval, rows)
        return 0

    def _import_metrics_zip(self, path, symbol, filter_date=None):
        rows = []
        archive = None
        try:
            archive = zipfile.ZipFile(path)
            for name in archive.namelist():
                if not name.endswith(".csv"):
                    continue
                with archive.open(name) as handle:
                    reader = csv.reader(line.decode("utf-8") for line in handle)
                    for row in reader:
                        if len(row) < 4:
                            continue
                        try:
                            timestamp = _parse_metrics_timestamp(row[0])
                            if timestamp is None:
                                continue
                            aligned = (timestamp // 300000) * 300000
                            create_time = datetime.utcfromtimestamp(aligned / 1000)
                            if filter_date and create_time.date() != filter_date:
                                continue
                            rows.append(
                                {
                                    "create_time": create_time,
                                    "symbol": symbol.upper(),
                                    "exchange": self._db_exchange(),
                                    "sum_open_interest": Decimal(row[2]) if len(row) > 2 and row[2] else None,
                                    "sum_open_interest_value": Decimal(row[3]) if len(row) > 3 and row[3] else None,
                                    "sum_toptrader_long_short_ratio": Decimal(row[4]) if len(row) > 4 and row[4] else None,
                                    "count_toptrader_long_short_ratio": Decimal(row[5]) if len(row) > 5 and row[5] else None,
                                    "count_long_short_ratio": Decimal(row[6]) if len(row) > 6 and row[6] else None,
                                    "sum_taker_long_short_vol_ratio": Decimal(row[7]) if len(row) > 7 and row[7] else None,
                                    "source": "binance_zip",
                                    "is_closed": True,
                                }
                            )
                        except Exception:
                            continue
        except Exception as exc:
            logger.error("failed to parse metrics zip %s: %s", path, exc)
            return 0
        finally:
            if archive is not None:
                archive.close()

        if rows:
            written = self._ts.upsert_metrics(rows)
            self._metrics.inc("rows_written", written)
            return written
        return 0


class DataBackfiller(object):
    """Coordinator for ZIP + REST backfill workflows."""

    def __init__(self, lookback_days=10, workers=8, threshold=0.95, config=None, timescale=None, data_dir=None, metrics_client=None):
        self._config = config or load_config()
        self.lookback_days = int(lookback_days)
        self.workers = int(workers)
        self.threshold = float(threshold)
        self._metrics = metrics_client or metrics
        self._ts = timescale or TimescaleAdapter()
        self._scanner = GapScanner(self._ts, config=self._config)
        self._rest = RestBackfiller(self._ts, config=self._config, workers=self.workers)
        self._zip = ZipBackfiller(self._ts, config=self._config, workers=self.workers, data_dir=data_dir, metrics_client=self._metrics)

    def _resolved_symbols(self, symbols):
        return list(symbols or load_symbols(getattr(self._config.crypto_kline, "ccxt_exchange", "binance")))

    def run_klines(self, symbols=None, interval="1m"):
        with Timer("last_backfill_duration", metrics_client=self._metrics):
            resolved_symbols = self._resolved_symbols(symbols)
            end = date.today() - timedelta(days=1)
            start = end - timedelta(days=self.lookback_days)
            gaps = self._scanner.scan_klines(resolved_symbols, start, end, interval, self.threshold)
            if not gaps:
                return {"scanned": len(resolved_symbols), "gaps": 0, "filled": 0, "remaining": 0}

            total_gaps = sum(len(items) for items in gaps.values())
            self._metrics.inc("gaps_found", total_gaps)
            filled = self._zip.fill_kline_gaps(gaps, interval)
            remaining = self._scanner.scan_klines(list(gaps.keys()), start, end, interval, self.threshold)
            if remaining:
                filled += self._rest.fill_gaps(remaining, interval)
            final = self._scanner.scan_klines(list(gaps.keys()), start, end, interval, self.threshold)
            final_gaps = sum(len(items) for items in final.values()) if final else 0
            self._metrics.inc("gaps_filled", filled)
            return {"scanned": len(resolved_symbols), "gaps": total_gaps, "filled": filled, "remaining": final_gaps}

    def run_metrics(self, symbols=None):
        resolved_symbols = self._resolved_symbols(symbols)
        end = date.today() - timedelta(days=1)
        start = end - timedelta(days=self.lookback_days)
        gaps = self._scanner.scan_metrics(resolved_symbols, start, end, self.threshold)
        if not gaps:
            return {"scanned": len(resolved_symbols), "gaps": 0, "filled": 0, "remaining": 0}

        total_gaps = sum(len(items) for items in gaps.values())
        filled = self._zip.fill_metrics_gaps(gaps)
        remaining = self._scanner.scan_metrics(list(gaps.keys()), start, end, self.threshold)
        if remaining:
            rest_filler = MetricsRestBackfiller(self._ts, config=self._config, workers=self.workers)
            try:
                filled += rest_filler.fill_gaps(remaining)
            finally:
                rest_filler.close()
        final = self._scanner.scan_metrics(list(gaps.keys()), start, end, self.threshold)
        final_gaps = sum(len(items) for items in final.values()) if final else 0
        return {"scanned": len(resolved_symbols), "gaps": total_gaps, "filled": filled, "remaining": final_gaps}

    def run_all(self, symbols=None):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                "klines": pool.submit(self.run_klines, symbols, "1m"),
                "metrics": pool.submit(self.run_metrics, symbols),
            }
            return {"klines": futures["klines"].result(), "metrics": futures["metrics"].result()}

    def close(self):
        self._ts.close()


class GapFiller(object):
    """Compatibility shim for startup continuity checks."""

    def __init__(self, timescale, config=None):
        self._config = config or load_config()
        self._ts = timescale
        self._scanner = GapScanner(timescale, config=self._config)
        self._rest = RestBackfiller(timescale, config=self._config, workers=2)
        self._lookback = max(1, int(getattr(self._config.runtime, "gap_check_interval", 1440)))

    def set_lookback(self, minutes):
        self._lookback = max(1, int(minutes))

    def ensure_continuity(self, symbols):
        end = date.today()
        lookback_days = max(1, int((self._lookback + 1439) / 1440))
        start = end - timedelta(days=lookback_days)
        gaps = self._scanner.scan_klines(symbols, start, end, "1m", 0.95)
        if gaps:
            self._rest.fill_gaps(gaps, "1m")


def _to_decimal(value):
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


__all__ = [
    "BINANCE_DATA_URL",
    "DataBackfiller",
    "EXPECTED_1M_PER_DAY",
    "EXPECTED_5M_PER_DAY",
    "GapFiller",
    "GapInfo",
    "GapScanner",
    "MetricsRestBackfiller",
    "RestBackfiller",
    "ZipBackfiller",
    "compute_lookback",
    "fetch_ohlcv",
    "get_backfill_config",
    "to_candle_rows",
]
