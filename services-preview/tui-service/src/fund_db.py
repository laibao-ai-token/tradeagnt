"""Fund database reader for tui-service.

Reads fund data from TimescaleDB tables:
- market_data.fund_cn_etf: Exchange-traded funds (ETF/LOF)
- market_data.fund_cn_offmarket: Off-market fund valuations

Uses psql CLI subprocess (same pattern as news_db.py) to avoid psycopg dependency.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class FundDbRow:
    """Represents an ETF/LOF fund row from database."""
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    source: str


@dataclass(frozen=True)
class OffMarketFundDbRow:
    """Represents an off-market fund row from database."""
    fund_code: str
    timestamp: str
    estimated_nav: float
    estimated_change_pct: float


def _get_database_url() -> str:
    """Get database URL from environment or config file."""
    candidates = [
        os.environ.get("TUI_FUND_DATABASE_URL"),
        os.environ.get("TUI_NEWS_DATABASE_URL"),
        os.environ.get("MARKETS_SERVICE_DATABASE_URL"),
        os.environ.get("DATABASE_URL"),
    ]
    for url in candidates:
        if url and "postgresql" in url:
            return url
    
    # Try reading from config/.env
    config_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", ".env")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key in ("DATABASE_URL", "MARKETS_SERVICE_DATABASE_URL") and "postgresql" in value:
                            return value
        except Exception:
            pass
    
    # Default with port priority
    for port in (5434, 5433, 5432):
        return f"postgresql://postgres:postgres@localhost:{port}/market_data"
    
    return "postgresql://postgres:postgres@localhost:5434/market_data"


def _run_copy_query(sql: str, db_url: Optional[str] = None, timeout_s: float = 5.0) -> str:
    """Run a COPY query via psql CLI and return CSV output."""
    url = db_url or _get_database_url()
    
    cmd = [
        "psql",
        url,
        "-X", "-q",
        "-v", "ON_ERROR_STOP=1",
        "-c", sql,
    ]
    
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if proc.returncode != 0:
            return ""
        return proc.stdout
    except Exception:
        return ""


def fetch_fund_cn_etf_from_db(
    symbols: List[str],
    db_url: Optional[str] = None,
    limit: int = 1,
    timeout_s: float = 5.0,
) -> Dict[str, FundDbRow]:
    """Fetch ETF/LOF fund data from market_data.fund_cn_etf.
    
    Args:
        symbols: List of fund symbols (e.g., SH510300, SZ159915)
        db_url: Optional database URL
        limit: Max rows per symbol
        timeout_s: Query timeout in seconds
    
    Returns:
        Dict mapping symbol to FundDbRow
    """
    if not symbols:
        return {}
    
    # Build safe symbol list
    safe_symbols = []
    for s in symbols:
        s = (s or "").strip().upper()
        if s and s.startswith(("SH", "SZ")) and len(s) <= 12:
            safe_symbols.append("'{0}'".format(s))
    
    if not safe_symbols:
        return {}
    
    sql = (
        "COPY ("
        "SELECT symbol, timestamp, open, high, low, close, volume, amount "
        "FROM market_data.fund_cn_etf "
        "WHERE symbol IN ({0}) "
        "ORDER BY timestamp DESC "
        "LIMIT {1}"
        ") TO STDOUT WITH (FORMAT CSV, HEADER TRUE)"
    ).format(", ".join(safe_symbols), limit * len(symbols))
    
    output = _run_copy_query(sql, db_url, timeout_s)
    if not output:
        return {}
    
    rows: Dict[str, FundDbRow] = {}
    lines = output.strip().split("\n")
    if len(lines) < 2:
        return {}
    
    # Skip header
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < 8:
            continue
        try:
            symbol = parts[0]
            rows[symbol] = FundDbRow(
                symbol=symbol,
                timestamp=parts[1],
                open=float(parts[2]) if parts[2] else 0.0,
                high=float(parts[3]) if parts[3] else 0.0,
                low=float(parts[4]) if parts[4] else 0.0,
                close=float(parts[5]) if parts[5] else 0.0,
                volume=float(parts[6]) if parts[6] else 0.0,
                amount=float(parts[7]) if parts[7] else 0.0,
                source="timescaledb",
            )
        except Exception:
            continue
    
    return rows


def fetch_fund_cn_offmarket_from_db(
    fund_codes: List[str],
    db_url: Optional[str] = None,
    limit: int = 1,
    timeout_s: float = 5.0,
) -> Dict[str, OffMarketFundDbRow]:
    """Fetch off-market fund valuation from market_data.fund_cn_offmarket.
    
    Args:
        fund_codes: List of fund codes (e.g., 024389, 010955)
        db_url: Optional database URL
        limit: Max rows per code
        timeout_s: Query timeout in seconds
    
    Returns:
        Dict mapping fund_code to OffMarketFundDbRow
    """
    if not fund_codes:
        return {}
    
    # Build safe code list
    safe_codes = []
    for c in fund_codes:
        c = (c or "").strip()
        if c and len(c) == 6 and c.isdigit():
            safe_codes.append("'{0}'".format(c))
    
    if not safe_codes:
        return {}
    
    sql = (
        "COPY ("
        "SELECT fund_code, timestamp, estimated_nav, estimated_change_pct "
        "FROM market_data.fund_cn_offmarket "
        "WHERE fund_code IN ({0}) "
        "ORDER BY timestamp DESC "
        "LIMIT {1}"
        ") TO STDOUT WITH (FORMAT CSV, HEADER TRUE)"
    ).format(", ".join(safe_codes), limit * len(fund_codes))
    
    output = _run_copy_query(sql, db_url, timeout_s)
    if not output:
        return {}
    
    rows: Dict[str, OffMarketFundDbRow] = {}
    lines = output.strip().split("\n")
    if len(lines) < 2:
        return {}
    
    # Skip header
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < 4:
            continue
        try:
            fund_code = parts[0]
            rows[fund_code] = OffMarketFundDbRow(
                fund_code=fund_code,
                timestamp=parts[1],
                estimated_nav=float(parts[2]) if parts[2] else 0.0,
                estimated_change_pct=float(parts[3]) if parts[3] else 0.0,
            )
        except Exception:
            continue
    
    return rows