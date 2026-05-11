
"""CSV-based provider for offline backtesting."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from tradecat.core.providers.base import DataProvider as BaseProvider


class CsvProvider(BaseProvider):
    """Read klines from a local CSV file."""

    name = "csv"

    def __init__(self, csv_path: str | Path) -> None:
        self.csv_path = Path(csv_path)

    def can_resolve(self, symbol: str) -> bool:
        return True

    def fetch_latest(self, symbol: str) -> dict:
        df = pd.read_csv(self.csv_path, parse_dates=["timestamp"])
        last = df.iloc[-1].to_dict()
        return last

    def supported_symbols(self) -> list[str]:
        return ["BTCUSDT"]

    async def fetch_klines(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
    ) -> pd.DataFrame:
        df = pd.read_csv(self.csv_path, parse_dates=["timestamp"])
        df = df.rename(columns={"timestamp": "datetime"})
        df = df.set_index("datetime")
        if limit:
            df = df.tail(limit)
        return df

    async def close(self) -> None:
        pass
