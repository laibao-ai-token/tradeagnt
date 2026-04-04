"""Gate spot REST adapter used by collector-service fallback polling."""

from __future__ import absolute_import

import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime


logger = logging.getLogger(__name__)

GATE_BASE_URL = "https://api.gateio.ws/api/v4"


class GateSpotCandle(object):
    """1m candle payload returned by Gate spot REST."""

    def __init__(self, ts, quote_volume, close, high, low, open, volume, is_closed):
        self.ts = int(ts)
        self.quote_volume = float(quote_volume)
        self.close = float(close)
        self.high = float(high)
        self.low = float(low)
        self.open = float(open)
        self.volume = float(volume)
        self.is_closed = self._parse_closed_flag(is_closed)

    @staticmethod
    def _parse_closed_flag(value):
        if isinstance(value, str):
            return value.strip().lower() == "true"
        return bool(value)

    @property
    def bucket_ts(self):
        return datetime.utcfromtimestamp(self.ts)


def _http_get_json(url, timeout_s=10.0):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "TradeCat/collector-service", "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as response:
        data = response.read()
    return json.loads(data.decode("utf-8"))


def fetch_spot_candles(currency_pair, interval="1m", limit=2, timeout_s=10.0):
    pair = (currency_pair or "").strip().upper()
    if not pair or "_" not in pair:
        return []

    query = urllib.parse.urlencode(
        {"currency_pair": pair, "interval": interval, "limit": str(int(limit))}
    )
    url = "{0}/spot/candlesticks?{1}".format(GATE_BASE_URL, query)

    try:
        raw = _http_get_json(url, timeout_s=timeout_s)
    except Exception as exc:
        logger.debug("gate spot fetch failed %s %s: %s", pair, interval, exc)
        return []

    if not isinstance(raw, list):
        return []

    results = []
    for item in raw:
        if not isinstance(item, list) or len(item) < 8:
            continue
        try:
            results.append(
                GateSpotCandle(
                    ts=item[0],
                    quote_volume=item[1],
                    close=item[2],
                    high=item[3],
                    low=item[4],
                    open=item[5],
                    volume=item[6],
                    is_closed=str(item[7]).lower() == "true",
                )
            )
        except Exception:
            continue
    return results


def to_candle_row(exchange, symbol, candle, source="gate_spot"):
    return {
        "exchange": exchange,
        "symbol": (symbol or "").upper(),
        "bucket_ts": candle.bucket_ts,
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": candle.volume,
        "quote_volume": candle.quote_volume,
        "trade_count": None,
        "taker_buy_volume": None,
        "taker_buy_quote_volume": None,
        "is_closed": True,
        "source": source,
    }
