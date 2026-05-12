"""CSV-based provider for offline backtesting."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from tradecat.core.providers.base import DataProvider as BaseProvider


class CsvProvider(BaseProvider):
    """Read klines from a local CSV file."""

    name = "csv"
    _REQUIRED_COLS = {"timestamp", "open", "high", "low", "close", "volume"}

    def __init__(self, csv_path: str | Path) -> None:
        self.csv_path = Path(csv_path)
        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV not found: {self.csv_path}")
        # Validate columns once at init
        try:
            df = pd.read_csv(self.csv_path, nrows=1, parse_dates=["timestamp"])
        except Exception as exc:
            raise RuntimeError(f"Failed to read CSV {self.csv_path}: {exc}") from exc
        missing = self._REQUIRED_COLS - set(df.columns)
        if missing:
            raise ValueError(f"CSV missing required columns: {missing}")
        self._columns = list(df.columns)

    def can_resolve(self, symbol: str) -> bool:
        return True

    def fetch_latest(self, symbol: str) -> dict:
        try:
            df = pd.read_csv(self.csv_path, parse_dates=["timestamp"])
        except Exception as exc:
            raise RuntimeError(f"Failed to read CSV {self.csv_path}: {exc}") from exc
        last = df.iloc[-1].to_dict()
        # Convert pandas Timestamp to ISO string
        for k, v in last.items():
            if hasattr(v, "isoformat"):
                last[k] = v.isoformat()
        return last

    def supported_symbols(self) -> list[str]:
        return ["BTCUSDT"]

    async def fetch_klines(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
    ) -> pd.DataFrame:
        try:
            df = pd.read_csv(self.csv_path, parse_dates=["timestamp"])
        except Exception as exc:
            raise RuntimeError(f"Failed to read CSV {self.csv_path}: {exc}") from exc
        df = df.rename(columns={"timestamp": "datetime"})
        df = df.set_index("datetime")
        if limit:
            df = df.tail(limit)
        return df

    async def close(self) -> None:
        pass
