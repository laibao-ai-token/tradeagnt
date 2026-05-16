from __future__ import annotations

import concurrent.futures
import csv
import curses
import hashlib
import html
import json
import locale
import math
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from tradecat.common.utils.scheduler import wait_seconds

from .db import SignalRow, fetch_recent, parse_ts, probe
from .etf_profiles import (
    get_all_domain_keys,
    get_domain_label,
    get_etf_domain_profile,
    load_dynamic_auto_driving_symbols,
)
from .etf_selector import select_etf_candidates
from .fund_symbols import (
    match_cn_fund_signal as _match_cn_fund_signal_shared,
    normalize_cn_fund_symbol as _normalize_cn_fund_symbol_shared,
)
from .micro import Candle, MicroConfig, MicroEngine, MicroSnapshot
from .draw_market import (
    MarketPanelConfig,
    draw_market_panel,
    quad_config as _quad_config,
    fund_config as _fund_config,
    micro_config as _micro_config,
)
from .news_db import (
    StoredNewsArticle,
    fetch_recent_news_articles,
    resolve_news_database_schema,
    resolve_news_database_url,
)
from .news_defaults import (
    CORE_GROUP,
    PRIMARY_TIER,
    SUPPLEMENTAL_TIER,
    UNKNOWN_GROUP,
    UNKNOWN_TIER,
    default_tui_news_rss_feeds_value,
    extract_source_meta_tags,
    news_source_code,
    news_source_group,
    news_source_tier,
)
from .news_events import NewsEvent, cluster_news_items
from .news_health import (
    NewsHealthSnapshot,
    build_live_news_health,
    load_news_collector_health,
    resolve_news_health_log_path,
)
from .fund_bridge import DirectFundBridge, seed_curve_from_daily_candles
from .quote import Quote, fetch_daily_curve_1d, fetch_intraday_curve_1m, fetch_quote
from ._helpers import _MARKET_TABS, _MARKET_TAB_LABELS, _PAGE_NEWS_VIEW
from .watchlists import (

    Watchlists,
    normalize_cn_fund_symbols,
    normalize_cn_symbols,
    normalize_crypto_symbols,
    normalize_hk_symbols,
    normalize_metals_symbols,
    normalize_us_symbols,
    save_watchlists,
)

# Page modules
from .pages.news import (
    NewsFeedSnapshot,
    NewsItem,
    NewsPageState,
    RssNewsPoller,
    NewsWatchItem,
    _collect_news_watch_items,
    _filter_news_items,
    _build_news_events,
    _news_source_filter_options,
    _news_counts,
    _news_source_options,

    _draw_market_news,
    _parse_rss_feeds_value,

)
from .pages.backtest import (
    BacktestCompareDelta,
    BacktestCompareSnapshot,
    BacktestRunStateSnapshot,
    BacktestSnapshot,
    BacktestSymbolContribution,
    _backtest_mode_text,
    _load_backtest_snapshot,
    _load_backtest_run_state,
    _format_backtest_state_line,
    _draw_backtest_curve,
    _draw_market_backtest,
)
from .pages.market import (
    _build_header_line,
    _draw,
    _draw_view_panel,
    _draw_header,
    _draw_paper_trading_page,
    _draw_market_master,
    _draw_quotes,
    _draw_signals,
    _draw_price_curve,
    _draw_market_quad,
    _draw_market_fund_two_panel,
    _draw_market_micro,
    _fmt_vol,
    _display_symbol,
    _display_name,
    _update_quote_curve,
    _snapshot_quote_curves,
    _curve_update_ts,
    _seed_curve_from_intraday_series,
    _seed_curve_from_daily_series,
    _maybe_seed_fund_curve_from_daily_history,
    _maybe_seed_closed_curve_from_history,
    _sample_candles_minmax,
    _fmt_signed,
)
@dataclass
class Filters:
    sources: set[str] = field(default_factory=lambda: {"pg", "sqlite"})
    directions: set[str] = field(default_factory=lambda: {"BUY", "SELL", "ALERT"})
    paused: bool = False

    def toggle_source(self, src: str) -> None:
        if src in self.sources:
            self.sources.remove(src)
        else:
            self.sources.add(src)

    def toggle_direction(self, d: str) -> None:
        if d in self.directions:
            self.directions.remove(d)
        else:
            self.directions.add(d)

@dataclass
class QuoteConfig:
    enabled: bool = True
    provider: str = "tencent"
    market: str = "us_stock"
    symbols: list[str] = field(default_factory=lambda: ["NVDA"])
    refresh_s: float = 1.0
    timeout_s: float = 2.0

@dataclass
class QuoteConfigs:
    us: QuoteConfig = field(default_factory=lambda: QuoteConfig(market="us_stock", symbols=["NVDA", "META", "ORCL"]))
    hk: QuoteConfig = field(default_factory=lambda: QuoteConfig(market="hk_stock", symbols=["00700", "01810", "03690"]))
    cn: QuoteConfig = field(default_factory=lambda: QuoteConfig(market="cn_stock", symbols=["SH600519", "SZ000001", "SH688256"]))
    fund_cn: QuoteConfig = field(
        default_factory=lambda: QuoteConfig(market="cn_fund", symbols=["SH510300", "SZ159915", "SH512100"])
    )
    crypto: QuoteConfig = field(
        default_factory=lambda: QuoteConfig(
            provider="auto",
            market="crypto_spot",
            symbols=["BTC_USDT", "ETH_USDT"],
            timeout_s=10.0,  # Gate API can be slower than tencent; keep a larger default.
        )
    )
    metals: QuoteConfig = field(
        default_factory=lambda: QuoteConfig(
            provider="auto",
            market="metals",
            symbols=["XAUUSD", "XAGUSD"],
            timeout_s=6.0,
        )
    )

@dataclass
class QuoteEntryState:
    quote: Quote | None = None
    last_error: str = ""
    # Timestamp of the last successful quote fetch (used for the "age" column).
    last_fetch_at: float = 0.0

@dataclass
class QuoteBookState:
    entries: dict[str, QuoteEntryState] = field(default_factory=dict)

@dataclass
class MasterPaneState:
    selected: int = 0
    left_scroll: int = 0
    right_scroll: int = 0
    focus: str = "left"

@dataclass
class FundDomainRuntimeState:
    keys: list[str] = field(default_factory=get_all_domain_keys)
    selected_idx: int = 0
    selected_key: str = ""

    def __post_init__(self) -> None:
        if not self.selected_key:
            self.selected_key = self.keys[0] if self.keys else "auto_driving_cn"
        if self.keys:
            try:
                self.selected_idx = self.keys.index(self.selected_key)
            except ValueError:
                self.selected_idx = 0
                self.selected_key = self.keys[0]
        else:
            self.selected_idx = 0

    def cycle(self, step: int) -> str | None:
        if not self.keys:
            return None
        self.selected_idx = (self.selected_idx + int(step)) % len(self.keys)
        self.selected_key = self.keys[self.selected_idx]
        return self.selected_key

@dataclass
class RuntimeState:
    fund_domain: FundDomainRuntimeState = field(default_factory=FundDomainRuntimeState)

@dataclass(frozen=True)
class ServiceStatus:
    data_running: int = 0
    data_total: int = 4
    signal_up: bool = False
    trading_up: bool = False
    signal_data_fresh: bool = False
    trading_data_fresh: bool = False
    signal_data_age_s: int | None = None
    trading_data_age_s: int | None = None
    checked_at: float = 0.0

@dataclass
class DirtyFlags:
    db: bool = False
    quotes: bool = False
    micro: bool = False
    ui: bool = False
    services: bool = False
    layout: bool = False
    forced: bool = False

    def any(self) -> bool:
        return self.db or self.quotes or self.micro or self.ui or self.services or self.layout or self.forced

@dataclass
class RenderState:
    db_sig: tuple | None = None
    quote_sig: tuple | None = None
    micro_sig: tuple | None = None
    ui_sig: tuple | None = None
    service_sig: tuple | None = None
    layout_sig: tuple[int, int] | None = None
    last_draw_at: float = 0.0

@dataclass
class DebounceSwitch:
    version: int = 0
    ready_at: float = 0.0

    def bump(self, now_ts: float, delay_s: float) -> None:
        self.version += 1
        self.ready_at = float(now_ts) + max(0.0, float(delay_s))

def _read_env_ratio(name: str, default: float, min_value: float = 0.25, max_value: float = 0.60) -> float:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except Exception:
        return float(default)
    if not math.isfinite(value):
        return float(default)
    return max(float(min_value), min(float(max_value), float(value)))

def _adaptive_left_min_width(total_width: int, *, base_min: int, floor_min: int, min_ratio: float) -> int:
    width = max(0, int(total_width))
    if width <= 0:
        return max(0, int(floor_min))
    ratio_bound = int(width * max(0.0, float(min_ratio)))
    return max(int(floor_min), min(int(base_min), ratio_bound))

_CLOSED_CURVE_STALE_SECONDS = 180
_CLOSED_CURVE_MIN_POINTS = 20
_CLOSED_CURVE_HISTORY_LIMIT = 60
_CLOSED_CURVE_RETRY_SECONDS = 120
_CLOSED_CURVE_TARGET_SPAN_SECONDS = 45 * 60
_FUND_CN_CURVE_DAYS = max(5, int(os.environ.get("TUI_FUND_CN_CURVE_DAYS", "15")))
_FUND_CN_CURVE_REFRESH_SECONDS = max(30.0, float(os.environ.get("TUI_FUND_CN_CURVE_REFRESH_SECONDS", "300")))
_MARKET_MICRO_LEFT_RATIO = _read_env_ratio("TUI_MARKET_MICRO_LEFT_RATIO", 0.36)
_MARKET_MICRO_LEFT_BASE_MIN_WIDTH = 34
_MARKET_MICRO_LEFT_FLOOR_MIN_WIDTH = 24
_MARKET_MICRO_LEFT_MIN_RATIO = 0.24
_MARKET_MICRO_RIGHT_MIN_WIDTH = 28
_RENDER_IDLE_REDRAW_S = 2.0
_RENDER_FRAME_INTERVAL_S = max(0.05, float(os.environ.get("TUI_RENDER_FRAME_INTERVAL_S", "0.10")))
_IDLE_POLL_SLEEP_S = max(0.02, float(os.environ.get("TUI_IDLE_POLL_SLEEP_S", "0.10")))
_SERVICE_STATUS_REFRESH_S = max(1.0, float(os.environ.get("TUI_SERVICE_STATUS_REFRESH_S", "3.0")))
_SWITCH_DEBOUNCE_S = 0.15
_PRIMARY_MARKET_VIEWS = ("market_us", "market_cn", "market_hk", "market_fund_cn", "market_micro", "market_news")
_BACKTEST_VIEW = "market_backtest"
_WORKSPACE_LEFT_RATIO = 0.42
_WORKSPACE_LEFT_MIN_WIDTH = 48
_WORKSPACE_LEFT_COMPACT_MIN_WIDTH = 32
_WORKSPACE_RIGHT_MIN_WIDTH = 36
_NEWS_CATEGORIES = ("全部", "宏观", "公司", "加密", "政策")
_NEWS_SOURCE_FILTER_ALL = "全部"
_NEWS_SOURCE_FILTER_PRIMARY = "主链"
_NEWS_SOURCE_FILTER_SUPPLEMENTAL = "补充"
_NEWS_WINDOWS_H = (1, 6, 24)

def _default_tui_news_rss_feeds_value() -> str:
    preset = (os.getenv("TUI_NEWS_RSS_PRESET", "") or os.getenv("NEWS_RSS_PRESET", "")).strip()
    return default_tui_news_rss_feeds_value(preset)

def _find_repo_root(start: Path) -> Path:
    cur = start.resolve()
    for _ in range(8):
        if (cur / "services").exists() and (cur / "services-preview").exists() and (cur / "config").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start.resolve()

_REPO_ROOT = _find_repo_root(Path(__file__).resolve().parent)
_DATA_PID_FILES = [
    _REPO_ROOT / "services" / "data-service" / "pids" / "daemon.pid",
    _REPO_ROOT / "services" / "data-service" / "pids" / "backfill.pid",
    _REPO_ROOT / "services" / "data-service" / "pids" / "metrics.pid",
    _REPO_ROOT / "services" / "data-service" / "pids" / "ws.pid",
]
_SIGNAL_PID_FILE = _REPO_ROOT / "services" / "signal-service" / "logs" / "signal-service.pid"
_TRADING_PID_FILE = _REPO_ROOT / "services" / "trading-service" / "pids" / "service.pid"
_SIGNAL_HISTORY_DB_FILE = _REPO_ROOT / "libs" / "database" / "services" / "signal-service" / "signal_history.db"
_TRADING_SQLITE_DB_FILE = _REPO_ROOT / "libs" / "database" / "services" / "telegram-service" / "market_data.db"
_SIGNAL_FRESH_MAX_AGE_S = max(300, int(float(os.environ.get("TUI_SIGNAL_FRESH_MAX_AGE_SECONDS", "43200"))))
_TRADING_FRESH_MAX_AGE_S = max(60, int(float(os.environ.get("TUI_TRADING_FRESH_MAX_AGE_SECONDS", "900"))))
_BACKTEST_LATEST_DIR = _REPO_ROOT / "artifacts" / "backtest" / "latest"
_BACKTEST_RUN_STATE_PATH = _REPO_ROOT / "artifacts" / "backtest" / "run_state.json"
_BACKTEST_MAX_EQUITY_POINTS = 600
_BACKTEST_RECENT_TRADES = 8
_BACKTEST_SHOW_COMPARE = str(os.environ.get("TUI_BACKTEST_SHOW_COMPARE", "")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

def _is_pid_file_running(pid_file: Path) -> bool:
    try:
        raw = pid_file.read_text(encoding="utf-8").strip().splitlines()[0]
    except Exception:
        return False
    if not raw:
        return False
    try:
        pid = int(raw)
    except ValueError:
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True

def _file_age_seconds(path: Path, now_ts: float) -> int | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return max(0, int(float(now_ts) - float(stat.st_mtime)))

def _collect_service_status(now_ts: float | None = None) -> ServiceStatus:
    checked_at = float(now_ts if now_ts is not None else time.time())
    signal_age_s = _file_age_seconds(_SIGNAL_HISTORY_DB_FILE, checked_at)
    trading_age_s = _file_age_seconds(_TRADING_SQLITE_DB_FILE, checked_at)
    signal_up = _is_pid_file_running(_SIGNAL_PID_FILE)
    trading_up = _is_pid_file_running(_TRADING_PID_FILE)
    return ServiceStatus(
        data_running=sum(1 for path in _DATA_PID_FILES if _is_pid_file_running(path)),
        data_total=len(_DATA_PID_FILES),
        signal_up=signal_up,
        trading_up=trading_up,
        signal_data_fresh=signal_age_s is not None and signal_age_s <= _SIGNAL_FRESH_MAX_AGE_S,
        trading_data_fresh=trading_age_s is not None and trading_age_s <= _TRADING_FRESH_MAX_AGE_S,
        signal_data_age_s=signal_age_s,
        trading_data_age_s=trading_age_s,
        checked_at=checked_at,
    )

def _format_service_status_bar(status: ServiceStatus) -> str:
    if status.data_running <= 0:
        data_txt = "数据离线"
    elif status.data_running >= max(1, status.data_total):
        data_txt = "数据在线"
    else:
        data_txt = f"数据{status.data_running}/{status.data_total}"
    if not status.signal_up:
        sig_txt = "信号离线"
    elif status.signal_data_fresh:
        sig_txt = "信号在线"
    else:
        sig_txt = "信号陈旧"
    if not status.trading_up:
        trd_txt = "交易离线"
    elif status.trading_data_fresh:
        trd_txt = "交易在线"
    else:
        trd_txt = "交易陈旧"
    return f"服务 {data_txt} | {sig_txt} | {trd_txt}"

def _view_display_name(view: str) -> str:
    mapping = {
        "market_us": "行情-美股",
        "market_cn": "行情-A股",
        "market_hk": "行情-港股",
        "market_fund_cn": "行情-基金",
        "market_micro": "行情-加密",
        "market_news": "资讯",
        "market_backtest": "回测",
        "quotes_us": "报价-美股",
        "quotes_cn": "报价-A股",
        "quotes_hk": "报价-港股",
        "quotes_crypto": "报价-加密",
        "quotes_metals": "报价-金属",
        "signals": "信号",
    }
    return mapping.get((view or "").strip().lower(), view)

def _market_display_name(market: str, fallback: str = "") -> str:
    mapping = {
        "us_stock": "美股",
        "hk_stock": "港股",
        "cn_stock": "A股",
        "cn_fund": "基金",
        "crypto_spot": "加密",
        "metals": "金属",
        "metals_spot": "金属",
    }
    return mapping.get((market or "").strip().lower(), fallback or market)

class _HotReloadRequested(RuntimeError):
    """Internal marker exception used to restart curses wrapper in dev mode."""

class _HotReloadWatcher:
    def __init__(self, roots: list[Path], poll_s: float = 1.0) -> None:
        self._roots = [r.resolve() for r in roots]
        self._poll_s = max(0.2, float(poll_s))
        self._last_check = 0.0
        self._fingerprint = self._snapshot()

    def _iter_files(self) -> Iterable[Path]:
        for root in self._roots:
            if root.is_file():
                yield root
                continue
            if not root.exists():
                continue
            for path in sorted(root.rglob("*.py")):
                if path.is_file():
                    yield path

    def _snapshot(self) -> tuple[tuple[str, int, int], ...]:
        files: list[tuple[str, int, int]] = []
        for path in self._iter_files():
            try:
                st = path.stat()
            except OSError:
                continue
            files.append((str(path), int(st.st_mtime_ns), int(st.st_size)))
        return tuple(files)

    def should_reload(self, now_ts: float | None = None) -> bool:
        now = float(time.time() if now_ts is None else now_ts)
        if (now - self._last_check) < self._poll_s:
            return False
        self._last_check = now
        current = self._snapshot()
        if current == self._fingerprint:
            return False
        self._fingerprint = current
        return True

def _build_hot_reload_watcher(enabled: bool, poll_s: float = 1.0) -> _HotReloadWatcher | None:
    if not enabled:
        return None
    src_root = Path(__file__).resolve().parent
    # Monitor only source files to avoid restart loops from runtime state writes.
    return _HotReloadWatcher([src_root], poll_s=poll_s)

class QuotePoller:
    def __init__(self, cfg: QuoteConfig) -> None:
        self._cfg = cfg
        self._cfg_lock = threading.Lock()
        self._lock = threading.Lock()
        self._state = QuoteBookState()
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._wake = threading.Event()
        self._t = threading.Thread(target=self._run, name="quote-poller", daemon=True)

    def start(self) -> None:
        if not self._cfg.enabled:
            return
        self._t.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        try:
            self._t.join(timeout=1.0)
        except Exception:
            pass

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._paused.set()
        else:
            self._paused.clear()
            self._wake.set()

    def snapshot(self) -> QuoteBookState:
        with self._lock:
            return QuoteBookState(entries=dict(self._state.entries))

    def set_symbols(self, symbols: list[str]) -> None:
        with self._cfg_lock:
            self._cfg.symbols = list(symbols)
        self._wake.set()

    def request_refresh(self) -> None:
        self._wake.set()

    def _set_one(self, symbol: str, quote: Quote | None, err: str) -> None:
        sym = (symbol or "").strip().upper()
        if not sym:
            return
        with self._lock:
            prev = self._state.entries.get(sym)
            now = time.time()
            if quote is None and prev and prev.quote is not None:
                # Keep last known quote on transient failures; preserve last_fetch_at to reflect staleness.
                self._state.entries[sym] = QuoteEntryState(quote=prev.quote, last_error=err, last_fetch_at=prev.last_fetch_at)
            else:
                # Success (or first-ever failure with no previous quote).
                last_ok = now if quote is not None else (prev.last_fetch_at if prev else 0.0)
                self._state.entries[sym] = QuoteEntryState(quote=quote, last_error=err, last_fetch_at=last_ok)

    def _run(self) -> None:
        # Poll in a background thread so the UI never blocks on network IO.
        while not self._stop.is_set():
            if self._paused.is_set():
                self._wake.clear()
                self._stop.wait(timeout=0.2)
                continue

            started = time.time()
            try:
                with self._cfg_lock:
                    cur_syms = list(self._cfg.symbols or [])
                syms = [s.strip().upper() for s in cur_syms if (s or "").strip()]
                if not syms:
                    self._stop.wait(timeout=0.5)
                    continue

                if str(self._cfg.market).strip().lower() == "crypto_spot":
                    # Per-symbol fetch so one flaky endpoint won't break the whole page,
                    # and we can attach per-symbol error messages. Run in parallel so a slow symbol/provider
                    # doesn't stall the whole watchlist refresh.
                    max_workers = min(8, max(1, len(syms)))
                    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
                        futs: dict[concurrent.futures.Future[Quote | None], str] = {}
                        for sym in syms:
                            futs[
                                ex.submit(
                                    fetch_quote,
                                    provider=self._cfg.provider,
                                    market=self._cfg.market,
                                    symbol=sym,
                                    timeout_s=self._cfg.timeout_s,
                                )
                            ] = sym
                        for fut in concurrent.futures.as_completed(futs):
                            sym = futs[fut]
                            try:
                                q = fut.result()
                                if q is None:
                                    self._set_one(sym, None, "no data")
                                else:
                                    self._set_one(sym, q, "")
                            except Exception as e:
                                self._set_one(sym, None, f"{type(e).__name__}: {e}")
                else:
                    res = fetch_quotes(
                        provider=self._cfg.provider,
                        market=self._cfg.market,
                        symbols=syms,
                        timeout_s=self._cfg.timeout_s,
                    )
                    for sym in syms:
                        q = res.get(sym)
                        if q is None:
                            self._set_one(sym, None, "no data")
                        else:
                            self._set_one(sym, q, "")
            except Exception as e:
                for sym in (self._cfg.symbols or []):
                    self._set_one(sym, None, f"{type(e).__name__}: {e}")

            # Sleep remaining interval (if any).
            elapsed = time.time() - started
            sleep_s = max(0.1, float(self._cfg.refresh_s) - elapsed)
            if sleep_s <= 0:
                continue
            deadline = time.time() + sleep_s
            while not self._stop.is_set():
                remain = deadline - time.time()
                if remain <= 0:
                    break
                if self._wake.wait(timeout=min(0.2, remain)):
                    self._wake.clear()
                    break

_RSS_TAG_RE = re.compile(r"<[^>]+>")

def _init_colors() -> dict[str, int]:
    if not curses.has_colors():
        return {}
    curses.start_color()
    try:
        curses.use_default_colors()
    except Exception:
        pass

    # Pair IDs must be 1..; keep small and stable.
    curses.init_pair(1, curses.COLOR_RED, -1)     # BUY / Up
    curses.init_pair(2, curses.COLOR_GREEN, -1)   # SELL / Down
    curses.init_pair(3, curses.COLOR_YELLOW, -1)  # ALERT / header accent
    curses.init_pair(4, curses.COLOR_CYAN, -1)    # source
    return {"BUY": 1, "SELL": 2, "ALERT": 3, "SRC": 4}

def _fmt_time(ts: str) -> str:
    dt = parse_ts(ts)
    if dt == datetime.min:
        return "--:--:--"
    return dt.strftime("%H:%M:%S")

def _fmt_date(ts: str) -> str:
    dt = parse_ts(ts)
    if dt == datetime.min:
        return "--:--:--"[:8]
    return dt.strftime("%y-%m-%d")

def _fmt_quote_ts(ts: str) -> str:
    """Compact quote timestamp for narrow TUI tables (YYYY -> YY)."""
    raw = (ts or "").strip()
    if not raw:
        return "--"

    dt = parse_ts(raw)
    if dt != datetime.min:
        return dt.strftime("%y-%m-%d %H:%M:%S")

    # Best effort fallback when provider returns non-ISO timestamps.
    if len(raw) >= 4 and raw[:4].isdigit():
        return raw[2:]
    return raw

def _fmt_quote_ts_date8(ts: str) -> str:
    """Date-only compact timestamp used by master pane (YY-MM-DD)."""
    s = _fmt_quote_ts(ts)
    if s == "--":
        return s
    if " " in s:
        return s.split(" ", 1)[0][:8]
    return s[:8]

def _crypto_signal_symbol_to_pair(symbol: str) -> str:
    """
    Convert signal symbol format (e.g. BTCUSDT) to quote pair format (e.g. BTC_USDT).
    This enables "signals <-> quotes" alignment in the TUI.
    """
    s = (symbol or "").strip().upper()
    if not s:
        return ""
    s = s.replace("/", "").replace("-", "").replace("_", "")
    # Common quotes
    for quote in ("USDT", "USDC", "USD", "BTC", "ETH"):
        if s.endswith(quote) and len(s) > len(quote):
            base = s[: -len(quote)]
            return f"{base}_{quote}"
    return s

def _build_latest_signal_map(rows: list[SignalRow]) -> dict[str, SignalRow]:
    """
    Build a map: crypto_pair -> latest signal row (newest wins).
    Uses best-effort symbol normalization.
    """
    out: dict[str, SignalRow] = {}
    for r in rows:
        pair = _crypto_signal_symbol_to_pair(r.symbol)
        if not pair or "_" not in pair:
            continue
        if pair not in out:
            out[pair] = r
    return out

def _normalize_cn_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s:
        return ""
    s = s.replace("/", "").replace("-", "").replace("_", "")
    if s.endswith(".SH") and len(s) >= 9:
        s = "SH" + s[:-3]
    elif s.endswith(".SZ") and len(s) >= 9:
        s = "SZ" + s[:-3]
    if s.startswith("SH") or s.startswith("SZ"):
        digits = "".join(ch for ch in s[2:] if ch.isdigit())
        if len(digits) == 6:
            return s[:2] + digits
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 6:
        if digits[0] in {"5", "6", "9"}:
            return "SH" + digits
        return "SZ" + digits
    return s

def _normalize_cn_fund_symbol(symbol: str) -> str:
    return _normalize_cn_fund_symbol_shared(symbol)

def _normalize_hk_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s:
        return ""
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return s
    return digits.zfill(5)

def _match_signal_to_symbol(signal_symbol: str, quote_symbol: str, market: str) -> bool:
    m = (market or "").strip().lower()
    qsym = (quote_symbol or "").strip().upper()
    if not qsym:
        return False
    if m == "crypto_spot":
        return _crypto_signal_symbol_to_pair(signal_symbol) == qsym
    if m == "us_stock":
        return (signal_symbol or "").strip().upper() == qsym
    if m == "hk_stock":
        return _normalize_hk_symbol(signal_symbol) == _normalize_hk_symbol(qsym)
    if m == "cn_stock":
        return _normalize_cn_symbol(signal_symbol) == _normalize_cn_symbol(qsym)
    if m == "cn_fund":
        return _match_cn_fund_signal_shared(signal_symbol, qsym)
    return False

def _signals_for_symbol(rows: list[SignalRow], quote_symbol: str, market: str) -> list[SignalRow]:
    out: list[SignalRow] = []
    for row in rows:
        if _match_signal_to_symbol(row.symbol, quote_symbol, market):
            out.append(row)
    return out

def _build_signal_radar_rows(
    rows: list[SignalRow],
    symbol: str,
    market: str,
    now_dt: datetime,
    *,
    window_minutes: int = 15,
    min_strength: int = 65,
) -> list[tuple[SignalRow, int]]:
    focus = (symbol or "").strip().upper()
    if not focus:
        return []

    out: list[tuple[SignalRow, int]] = []
    max_age_s = max(1, int(window_minutes)) * 60
    min_str = int(min_strength)
    for row in rows:
        if not _match_signal_to_symbol(row.symbol, focus, market):
            continue
        ts_dt = parse_ts(row.timestamp)
        if ts_dt == datetime.min:
            continue
        age_s = max(0, int((now_dt - ts_dt).total_seconds()))
        if age_s > max_age_s:
            continue
        try:
            strength = int(row.strength)
        except (TypeError, ValueError):
            continue
        if strength < min_str:
            continue
        out.append((row, age_s))
    return out

def _fmt_freshness(ts: str, now_dt: datetime) -> str:
    dt = parse_ts(ts)
    if dt == datetime.min:
        return "--"
    return f"{max(0, int((now_dt - dt).total_seconds()))}s"

def _fmt_duration_compact(seconds: int | None) -> str:
    if seconds is None:
        return "--"
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{m}m"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h{m:02d}m"
    d, h = divmod(h, 24)
    return f"{d}d{h:02d}h"

def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)

def _is_finite_number(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except Exception:
        return False

def _window_signal_stats(
    rows: list[SignalRow],
    now_dt: datetime,
    *,
    windows_minutes: tuple[int, ...] = (60, 24 * 60),
) -> tuple[dict[int, dict[str, int]], int | None, int | None]:
    stats = {
        int(minutes): {"rows": 0, "buy": 0, "sell": 0, "alert": 0, "net": 0}
        for minutes in windows_minutes
    }
    parsed_ages: list[int] = []

    for row in rows:
        ts_dt = parse_ts(row.timestamp)
        if ts_dt == datetime.min:
            continue
        age_s = max(0, int((now_dt - ts_dt).total_seconds()))
        parsed_ages.append(age_s)

        direction = (row.direction or "").upper()
        strength = _safe_int(row.strength, 0)

        for minutes in windows_minutes:
            if age_s > int(minutes) * 60:
                continue
            bucket = stats[int(minutes)]
            bucket["rows"] += 1
            if direction == "BUY":
                bucket["buy"] += 1
                bucket["net"] += strength
            elif direction == "SELL":
                bucket["sell"] += 1
                bucket["net"] -= strength
            elif direction in {"ALERT", "ALER"}:
                bucket["alert"] += 1

    if not parsed_ages:
        return stats, None, None
    return stats, min(parsed_ages), max(parsed_ages)

def _signal_row_age_seconds(row: SignalRow, now_dt: datetime) -> int | None:
    ts_dt = parse_ts(row.timestamp)
    if ts_dt == datetime.min:
        return None
    return max(0, int((now_dt - ts_dt).total_seconds()))

def _count_recent_signal_rows(rows: list[SignalRow], now_dt: datetime, *, max_age_s: int) -> int:
    limit_s = max(0, int(max_age_s))
    count = 0
    for row in rows:
        age_s = _signal_row_age_seconds(row, now_dt)
        if age_s is not None and age_s <= limit_s:
            count += 1
    return count

def _split_signal_rows_by_age(
    rows: list[SignalRow],
    now_dt: datetime,
) -> tuple[list[tuple[SignalRow, int]], list[tuple[SignalRow, int]], list[tuple[SignalRow, int]]]:
    realtime_rows: list[tuple[SignalRow, int]] = []
    h1_rows: list[tuple[SignalRow, int]] = []
    h12_rows: list[tuple[SignalRow, int]] = []

    for row in rows:
        age_s = _signal_row_age_seconds(row, now_dt)
        if age_s is None:
            continue
        if age_s <= 5 * 60:
            realtime_rows.append((row, age_s))
        elif age_s <= 60 * 60:
            h1_rows.append((row, age_s))
        elif age_s <= 12 * 60 * 60:
            h12_rows.append((row, age_s))

    return realtime_rows, h1_rows, h12_rows

def _latest_signal_row(rows: list[SignalRow], now_dt: datetime) -> tuple[SignalRow, int] | None:
    latest: tuple[SignalRow, int] | None = None
    for row in rows:
        age_s = _signal_row_age_seconds(row, now_dt)
        if age_s is None:
            continue
        if latest is None or age_s < latest[1]:
            latest = (row, age_s)
    return latest

def _build_recent_signal_panel_title(rows: list[SignalRow], now_dt: datetime) -> str:
    base = "规则信号列表（5min/1h/12h）"
    latest = _latest_signal_row(rows, now_dt)
    if latest is None:
        return f"{base} | 暂无历史信号"

    latest_row, latest_age_s = latest
    if latest_age_s <= 12 * 60 * 60:
        return base

    return (
        f"{base} | 近12h无信号 | 最新={_fmt_date(latest_row.timestamp)} "
        f"{_fmt_time(latest_row.timestamp)} ({_fmt_duration_compact(latest_age_s)}前)"
    )

def _line_chars() -> tuple[str, str, str, str, str, str]:
    # Avoid ncurses ACS fallback glyphs (q/x/l/m/...) on some terminals.
    encoding = (locale.getpreferredencoding(False) or "").lower()
    if "utf" in encoding:
        return ("│", "─", "┌", "┐", "└", "┘")
    return ("|", "-", "+", "+", "+", "+")

def _safe_vline(win, y: int, x: int, height: int, attr: int = 0) -> None:
    if height <= 0:
        return
    vline, _, _, _, _, _ = _line_chars()
    for i in range(height):
        _safe_addstr(win, y + i, x, vline, attr)

def _safe_hline(win, y: int, x: int, width: int, attr: int = 0) -> None:
    if width <= 0:
        return
    _, hline, _, _, _, _ = _line_chars()
    _safe_addstr(win, y, x, hline * width, attr)

def _draw_box(win, x: int, y: int, width: int, height: int, attr: int = 0) -> None:
    if width < 2 or height < 2:
        return
    left = x
    top = y
    right = x + width - 1
    bottom = y + height - 1

    _safe_hline(win, top, left + 1, max(0, width - 2), attr)
    _safe_hline(win, bottom, left + 1, max(0, width - 2), attr)
    _safe_vline(win, top + 1, left, max(0, height - 2), attr)
    _safe_vline(win, top + 1, right, max(0, height - 2), attr)

    _, _, tl, tr, bl, br = _line_chars()
    _safe_addstr(win, top, left, tl, attr)
    _safe_addstr(win, top, right, tr, attr)
    _safe_addstr(win, bottom, left, bl, attr)
    _safe_addstr(win, bottom, right, br, attr)

def _safe_addstr(win, y: int, x: int, s: str, attr: int = 0) -> None:
    try:
        win.addstr(y, x, s, attr)
    except Exception:
        # Avoid crashing on edge cases (small terminal, wide chars, etc.)
        pass

def _signal_rows_signature(rows: list[SignalRow]) -> tuple[int, int, int, str, str]:
    if not rows:
        return (0, 0, 0, "", "")
    newest = rows[0]
    oldest = rows[-1]
    return (len(rows), int(newest.id), int(oldest.id), str(newest.timestamp), str(oldest.timestamp))

def _quote_book_signature(state: QuoteBookState) -> tuple:
    out: list[tuple] = []
    for sym, entry in sorted(state.entries.items()):
        q = entry.quote
        if q is None:
            out.append((sym, 0.0, "", "", round(float(entry.last_fetch_at), 3), (entry.last_error or "").strip()))
            continue
        out.append(
            (
                sym,
                round(float(q.price), 6),
                round(float(q.volume), 3),
                round(float(q.amount), 3),
                (q.ts or "").strip(),
                (q.source or "").strip(),
                round(float(entry.last_fetch_at), 3),
                (entry.last_error or "").strip(),
            )
        )
    return tuple(out)

def _curve_map_signature(curve_map: dict[str, list[Candle]]) -> tuple:
    out: list[tuple] = []
    for sym in sorted(curve_map):
        curve = curve_map[sym]
        if not curve:
            out.append((sym, 0, 0, 0.0, 0.0))
            continue
        last = curve[-1]
        out.append(
            (
                sym,
                len(curve),
                int(last.ts_open),
                round(float(last.close), 6),
                round(float(last.volume_est), 3),
            )
        )
    return tuple(out)

def _micro_snapshot_signature(snapshot: MicroSnapshot) -> tuple:
    candles = snapshot.candles
    last_candle = candles[-1] if candles else None
    flow = snapshot.flow
    last_flow = flow[-1] if flow else None
    return (
        (snapshot.symbol or "").strip().upper(),
        int(snapshot.interval_s),
        round(float(snapshot.last_price), 6),
        (snapshot.last_source or "").strip(),
        (snapshot.last_quote_ts or "").strip(),
        (snapshot.error or "").strip(),
        len(candles),
        0 if last_candle is None else int(last_candle.ts_open),
        0.0 if last_candle is None else round(float(last_candle.close), 6),
        len(flow),
        0.0 if last_flow is None else round(float(last_flow.ts), 3),
        "" if last_flow is None else (last_flow.side or "").strip(),
        round(float(snapshot.signals.score), 4),
        (snapshot.signals.bias or "").strip(),
    )

def _service_status_signature(status: ServiceStatus) -> tuple[int, int, bool, bool, bool, bool]:
    return (
        int(status.data_running),
        int(status.data_total),
        bool(status.signal_up),
        bool(status.trading_up),
        bool(status.signal_data_fresh),
        bool(status.trading_data_fresh),
    )

def _char_display_width(ch: str) -> int:
    if not ch:
        return 0
    if unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in {"F", "W"}:
        return 2
    return 1

def _text_display_width(text: str) -> int:
    return sum(_char_display_width(ch) for ch in (text or ""))

def _truncate(s: str, width: int) -> str:
    if width <= 0:
        return ""

    text = str(s or "")
    if _text_display_width(text) <= width:
        return text

    if width == 1:
        return ">"

    budget = width - 1
    used = 0
    out: list[str] = []
    for ch in text:
        w = _char_display_width(ch)
        if used + w > budget:
            break
        out.append(ch)
        used += w

    # Keep ASCII-only suffix to avoid locale-specific truncation glyph issues.
    return "".join(out) + ">"

def _fit_cell(text: str, width: int, *, align: str = "left") -> str:
    """
    Fit text into a fixed display-width cell (handles CJK full-width chars).
    """
    if width <= 0:
        return ""
    clipped = _truncate(text, width)
    pad = max(0, width - _text_display_width(clipped))
    if align == "right":
        return (" " * pad) + clipped
    return clipped + (" " * pad)

def _tail_truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""

    raw = str(text or "")
    if _text_display_width(raw) <= width:
        return raw
    if width == 1:
        return "<"

    budget = width - 1
    used = 0
    out: deque[str] = deque()
    for ch in reversed(raw):
        ch_w = _char_display_width(ch)
        if used + ch_w > budget:
            break
        out.appendleft(ch)
        used += ch_w
    return "<" + "".join(out)

def _wrap_display_text(text: str, width: int) -> list[str]:
    if width <= 0:
        return []

    paragraphs = str(text or "").splitlines() or [""]
    lines: list[str] = []
    for paragraph in paragraphs:
        if not paragraph:
            lines.append("")
            continue

        buf: list[str] = []
        used = 0
        for ch in paragraph:
            ch_w = _char_display_width(ch)
            if used + ch_w > width and buf:
                lines.append("".join(buf))
                buf = [ch]
                used = ch_w
                continue
            if used + ch_w > width:
                lines.append(ch)
                buf = []
                used = 0
                continue
            buf.append(ch)
            used += ch_w
        if buf:
            lines.append("".join(buf))
    return lines or [""]

def _coerce_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        return float(text)
    except (TypeError, ValueError):
        return None

def _coerce_int(value: object) -> int | None:
    fv = _coerce_float(value)
    if fv is None:
        return None
    return int(round(fv))

def _coerce_pct(value: object) -> float | None:
    fv = _coerce_float(value)
    if fv is None:
        return None
    if abs(fv) <= 1.0:
        return fv * 100.0
    return fv

def _extract_metric(payload: dict, keys: tuple[str, ...]) -> object | None:
    if not isinstance(payload, dict):
        return None

    for key in keys:
        if key in payload:
            return payload.get(key)

    for container_key in ("summary", "metrics", "result", "stats", "performance"):
        nested = payload.get(container_key)
        if not isinstance(nested, dict):
            continue
        for key in keys:
            if key in nested:
                return nested.get(key)

    return None

def _resample_series(values: list[float], max_points: int) -> list[float]:
    if max_points <= 0 or not values:
        return []
    if len(values) <= max_points:
        return list(values)
    if max_points == 1:
        return [values[-1]]

    out: list[float] = []
    step = (len(values) - 1) / float(max_points - 1)
    for i in range(max_points):
        idx = int(round(i * step))
        idx = max(0, min(len(values) - 1, idx))
        out.append(float(values[idx]))
    return out

def run(
    db_path: str,
    refresh_s: float = 1.0,
    limit: int = 500,
    quotes: QuoteConfigs | None = None,
    micro_cfg: MicroConfig | None = None,
    start_view: str = "market_micro",
    watchlists_path: str = "",
    hot_reload: bool = False,
    hot_reload_poll_s: float = 1.0,
) -> None:
    sv = (start_view or "market_micro").strip().lower()
    # Back-compat: "quotes" means US quotes.
    if sv == "quotes":
        sv = "market_us"
    if sv in {"quotes_us"}:
        sv = "market_us"
    if sv in {"quotes_cn"}:
        sv = "market_cn"
    if sv in {"quotes_hk"}:
        sv = "market_hk"
    if sv in {"market_fund", "market_fund_cn", "quotes_fund_cn", "quotes_fund"}:
        sv = "market_fund_cn"
    if sv in {"quotes_metals", "market_crypto", "quotes_crypto"}:
        # Back-compat: old quote pages are folded into market_micro.
        sv = "market_micro"
    if sv in {"news", "market_news"}:
        sv = "market_news"
    if sv in {"backtest", "market_bt"}:
        sv = "market_backtest"
    if sv not in {
        "signals",
        "quotes_us",
        "quotes_hk",
        "quotes_cn",
        "quotes_metals",
        "market_us",
        "market_cn",
        "market_hk",
        "market_fund_cn",
        "market_micro",
        "market_news",
        "market_backtest",
    }:
        sv = "market_micro"
    micro = micro_cfg or MicroConfig()
    watcher = _build_hot_reload_watcher(bool(hot_reload), poll_s=hot_reload_poll_s)
    # 从 start_view 推导初始 top_page / market_tab
    _init_tp = 1
    _init_mt = 0
    if sv == _PAGE_NEWS_VIEW:
        _init_tp = 3
    elif sv in _MARKET_TABS:
        _init_tp = 1
        _init_mt = _MARKET_TABS.index(sv)
    top_page = _init_tp
    market_tab = _init_mt

    while True:
        try:
            curses.wrapper(_main, db_path, refresh_s, limit, quotes or QuoteConfigs(), micro, sv, watchlists_path, watcher)
            return
        except _HotReloadRequested:
            if watcher is None:
                return
            # Full process restart is required for Python source updates to take effect.
            # Re-entering curses.wrapper alone would keep old modules/functions in memory.
            restart_argv = [sys.executable, "-m", "src", *sys.argv[1:]]
            try:
                os.execv(sys.executable, restart_argv)
            except Exception:
                continue

def _main(
    stdscr,
    db_path: str,
    refresh_s: float,
    limit: int,
    quote_cfgs: QuoteConfigs,
    micro_cfg: MicroConfig,
    start_view: str,
    watchlists_path: str,
    hot_reload_watcher: _HotReloadWatcher | None = None,
) -> None:
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)

    colors = _init_colors()
    filt = Filters()

    poll_us = QuotePoller(quote_cfgs.us)
    poll_hk = QuotePoller(quote_cfgs.hk)
    poll_cn = QuotePoller(quote_cfgs.cn)
    poll_fund_cn = QuotePoller(quote_cfgs.fund_cn)
    poll_crypto = QuotePoller(quote_cfgs.crypto)
    poll_metals = QuotePoller(quote_cfgs.metals)
    pollers_by_name: dict[str, QuotePoller] = {
        "us": poll_us,
        "hk": poll_hk,
        "cn": poll_cn,
        "fund_cn": poll_fund_cn,
        "crypto": poll_crypto,
        "metals": poll_metals,
    }
    poll_us.start()
    poll_hk.start()
    poll_cn.start()
    poll_fund_cn.start()
    poll_crypto.start()
    poll_metals.start()

    fund_bridge = DirectFundBridge(
        provider=quote_cfgs.fund_cn.provider,
        market=quote_cfgs.fund_cn.market,
        timeout_s=6.0,
    )

    news_poller: RssNewsPoller | None = None
    raw_news_feeds = (os.getenv("TUI_NEWS_RSS_FEEDS", "") or os.getenv("NEWS_RSS_FEEDS", "") or "").strip()
    if not raw_news_feeds:
        raw_news_feeds = _default_tui_news_rss_feeds_value()
    news_feeds = _parse_rss_feeds_value(raw_news_feeds)
    news_database_url = resolve_news_database_url(_REPO_ROOT)
    news_database_schema = resolve_news_database_schema(_REPO_ROOT)
    if news_feeds or news_database_url:
        try:
            news_refresh_s = float(os.getenv("TUI_NEWS_RSS_REFRESH_S", "2").strip() or "2")
        except Exception:
            news_refresh_s = 2.0
        try:
            news_timeout_s = float(os.getenv("TUI_NEWS_RSS_TIMEOUT_S", "5").strip() or "5")
        except Exception:
            news_timeout_s = 5.0
        try:
            news_max_items = int(os.getenv("TUI_NEWS_MAX_ITEMS", "300").strip() or "300")
        except Exception:
            news_max_items = 300
        try:
            news_db_window_h = int(os.getenv("TUI_NEWS_DB_WINDOW_HOURS", "72").strip() or "72")
        except Exception:
            news_db_window_h = 72
        try:
            news_db_timeout_s = float(os.getenv("TUI_NEWS_DB_TIMEOUT_S", "5").strip() or "5")
        except Exception:
            news_db_timeout_s = 5.0
        news_poller = RssNewsPoller(
            news_feeds,
            refresh_s=news_refresh_s,
            timeout_s=news_timeout_s,
            max_items=news_max_items,
            database_url=news_database_url,
            database_schema=news_database_schema,
            database_window_h=news_db_window_h,
            database_timeout_s=news_db_timeout_s,
        )
        news_poller.start()

    last_id = 0
    rows: list[SignalRow] = []
    rows_all: list[SignalRow] = []
    scroll = 0
    last_refresh = 0.0
    view = start_view  # "signals" or "quotes"
    # --- 三页收敛：top_page 控制大页面，market_tab 控制 P1 内子标签 ---
    # top_page: 1=行情, 2=模拟盘, 3=资讯
    # market_tab: 0=加密, 1=美股, 2=A股, 3=港股, 4=基金

    def _resolve_top_page_from_view(v: str) -> int:
        cv = _canonical_view(v) if '_canonical_view' in dir() else v
        if cv in _MARKET_TABS or v in _MARKET_TABS:
            return 1
        if cv == _PAGE_NEWS_VIEW:
            return 3
        return 1  # default to market page

    def _resolve_market_tab_from_view(v: str) -> int:
        cv = _canonical_view(v) if '_canonical_view' in dir() else v
        try:
            return _MARKET_TABS.index(cv)
        except ValueError:
            return 0

    top_page = 1
    market_tab = 0
    qscroll: dict[str, int] = {
        "quotes_us": 0,
        "quotes_hk": 0,
        "quotes_cn": 0,
        "quotes_crypto": 0,
        "quotes_metals": 0,
    }
    master_panes: dict[str, MasterPaneState] = {
        "market_us": MasterPaneState(),
        "market_cn": MasterPaneState(),
        "market_hk": MasterPaneState(),
        "market_fund_cn": MasterPaneState(),
    }
    news_state = NewsPageState()
    seed = normalize_crypto_symbols(micro_cfg.symbol or "")
    micro_symbol_current = seed[0] if seed else "BTC_USDT"
    micro_engines: dict[str, MicroEngine] = {}
    micro_last_refresh: dict[str, float] = {}
    micro_errors: dict[str, str] = {}
    us_quote_curves: dict[str, deque[Candle]] = {}
    hk_quote_curves: dict[str, deque[Candle]] = {}
    cn_quote_curves: dict[str, deque[Candle]] = {}
    fund_cn_quote_curves: dict[str, deque[Candle]] = {}
    fund_cn_daily_curves: dict[str, deque[Candle]] = {}
    crypto_quote_curves: dict[str, deque[Candle]] = {}
    us_curve_seed_attempts: dict[str, float] = {}
    hk_curve_seed_attempts: dict[str, float] = {}
    cn_curve_seed_attempts: dict[str, float] = {}
    fund_cn_curve_seed_attempts: dict[str, float] = {}
    us_micro_engines: dict[str, MicroEngine] = {}
    hk_micro_engines: dict[str, MicroEngine] = {}
    cn_micro_engines: dict[str, MicroEngine] = {}
    fund_cn_micro_engines: dict[str, MicroEngine] = {}
    us_micro_errors: dict[str, str] = {}
    hk_micro_errors: dict[str, str] = {}
    cn_micro_errors: dict[str, str] = {}
    fund_cn_micro_errors: dict[str, str] = {}
    us_last_ingested_fetch: dict[str, float] = {}
    hk_last_ingested_fetch: dict[str, float] = {}
    cn_last_ingested_fetch: dict[str, float] = {}
    fund_cn_last_ingested_fetch: dict[str, float] = {}
    crypto_last_ingested_fetch: dict[str, float] = {}
    service_status = _collect_service_status()
    service_status_refresh_s = _SERVICE_STATUS_REFRESH_S
    render_state = RenderState()
    runtime_state = RuntimeState()
    next_frame_at = time.time()
    pending_force_redraw = True

    micro_switch = DebounceSwitch()
    micro_switch_applied = 0
    master_switches: dict[str, DebounceSwitch] = {
        "market_us": DebounceSwitch(),
        "market_cn": DebounceSwitch(),
        "market_hk": DebounceSwitch(),
        "market_fund_cn": DebounceSwitch(),
    }
    master_switch_applied: dict[str, int] = {"market_us": 0, "market_cn": 0, "market_hk": 0, "market_fund_cn": 0}
    view_aliases = {
        "quotes_us": "market_us",
        "quotes_cn": "market_cn",
        "quotes_hk": "market_hk",
        "quotes_fund_cn": "market_fund_cn",
        "quotes_metals": "market_micro",
        "quotes_crypto": "market_micro",
        "market_crypto": "market_micro",
        "news": "market_news",
        "backtest": _BACKTEST_VIEW,
        "market_bt": _BACKTEST_VIEW,
    }

    def _canonical_view(v: str) -> str:
        return view_aliases.get(v, v)

    def _desired_quote_poller_names(v: str) -> set[str]:
        cur = _canonical_view(v)
        if v in {"quotes_metals"}:
            return {"metals"}
        if cur == "market_us":
            return {"us"}
        if cur == "market_cn":
            return {"cn"}
        if cur == "market_hk":
            return {"hk"}
        if cur == "market_fund_cn":
            return {"fund_cn"}
        if cur == "market_micro":
            return {"crypto"}
        return set()

    def _should_poll_news(v: str) -> bool:
        return _canonical_view(v) == "market_news"

    poller_sync_sig: tuple[tuple[str, ...], bool, bool] | None = None

    def _sync_background_activity(force: bool = False) -> None:
        nonlocal poller_sync_sig

        active_quote_names = tuple(sorted(_desired_quote_poller_names(view)))
        news_active = _should_poll_news(view)
        sync_sig = (active_quote_names, bool(filt.paused), bool(news_active))
        if not force and sync_sig == poller_sync_sig:
            return

        active_quote_set = set(active_quote_names)
        for name, poller in pollers_by_name.items():
            poller.set_paused(bool(filt.paused) or name not in active_quote_set)
        if news_poller is not None:
            news_poller.set_paused(bool(filt.paused) or not news_active)
        poller_sync_sig = sync_sig

    last_primary_view = _canonical_view(view)
    if last_primary_view not in _PRIMARY_MARKET_VIEWS:
        last_primary_view = "market_micro"
    backtest_parent_view = last_primary_view
    _sync_background_activity(force=True)

    def _remember_primary_view(v: str) -> None:
        nonlocal last_primary_view
        canonical = _canonical_view(v)
        if canonical in _PRIMARY_MARKET_VIEWS:
            last_primary_view = canonical

    def _is_master_view(v: str) -> bool:
        return v in master_panes

    def _master_has_signal_panel(v: str) -> bool:
        # Market pages are unified as quad layout; tab keeps cycling pages.
        return False

    def _next_view(v: str) -> str:
        cur = _canonical_view(v)
        if cur not in _PRIMARY_MARKET_VIEWS:
            cur = backtest_parent_view if backtest_parent_view in _PRIMARY_MARKET_VIEWS else last_primary_view
        try:
            idx = _PRIMARY_MARKET_VIEWS.index(cur)
        except ValueError:
            return "market_micro"
        return _PRIMARY_MARKET_VIEWS[(idx + 1) % len(_PRIMARY_MARKET_VIEWS)]

    def _master_symbol_count(v: str) -> int:
        if v == "market_us":
            return len(quote_cfgs.us.symbols)
        if v == "market_cn":
            return len(quote_cfgs.cn.symbols)
        if v == "market_hk":
            return len(quote_cfgs.hk.symbols)
        if v == "market_fund_cn":
            return len(quote_cfgs.fund_cn.symbols)
        return 0

    def _cycle_master_symbol(v: str, delta: int) -> bool:
        pane = master_panes.get(v)
        count = _master_symbol_count(v)
        if pane is None or count <= 0:
            return False
        old_selected = pane.selected
        pane.selected = (pane.selected + int(delta)) % count
        pane.right_scroll = 0
        changed = pane.selected != old_selected
        if changed and v in master_switches:
            master_switches[v].bump(time.time(), _SWITCH_DEBOUNCE_S)
        return changed

    def _ensure_micro_engine(symbol: str) -> MicroEngine:
        sym = (symbol or "").strip().upper() or "BTC_USDT"
        engine = micro_engines.get(sym)
        if engine is None:
            engine = MicroEngine(
                MicroConfig(
                    symbol=sym,
                    interval_s=micro_cfg.interval_s,
                    window=micro_cfg.window,
                    flow_rows=micro_cfg.flow_rows,
                    refresh_s=micro_cfg.refresh_s,
                )
            )
            micro_engines[sym] = engine
        return engine

    def _ensure_us_micro_engine(symbol: str) -> MicroEngine:
        sym = (symbol or "").strip().upper()
        if not sym:
            sym = "NVDA"
        engine = us_micro_engines.get(sym)
        if engine is None:
            engine = MicroEngine(
                MicroConfig(
                    symbol=sym,
                    interval_s=5,
                    window=micro_cfg.window,
                    flow_rows=micro_cfg.flow_rows,
                    refresh_s=quote_cfgs.us.refresh_s,
                )
            )
            us_micro_engines[sym] = engine
        return engine

    def _ensure_cn_micro_engine(symbol: str) -> MicroEngine:
        sym = _normalize_cn_symbol(symbol)
        if not sym:
            sym = "SH600519"
        engine = cn_micro_engines.get(sym)
        if engine is None:
            engine = MicroEngine(
                MicroConfig(
                    symbol=sym,
                    interval_s=5,
                    window=micro_cfg.window,
                    flow_rows=micro_cfg.flow_rows,
                    refresh_s=quote_cfgs.cn.refresh_s,
                )
            )
            cn_micro_engines[sym] = engine
        return engine

    def _ensure_hk_micro_engine(symbol: str) -> MicroEngine:
        sym = _normalize_hk_symbol(symbol)
        if not sym:
            sym = "00700"
        engine = hk_micro_engines.get(sym)
        if engine is None:
            engine = MicroEngine(
                MicroConfig(
                    symbol=sym,
                    interval_s=5,
                    window=micro_cfg.window,
                    flow_rows=micro_cfg.flow_rows,
                    refresh_s=quote_cfgs.hk.refresh_s,
                )
            )
            hk_micro_engines[sym] = engine
        return engine

    def _ensure_fund_cn_micro_engine(symbol: str) -> MicroEngine:
        sym = _normalize_cn_fund_symbol(symbol)
        if not sym:
            sym = "SH510300"
        engine = fund_cn_micro_engines.get(sym)
        if engine is None:
            engine = MicroEngine(
                MicroConfig(
                    symbol=sym,
                    interval_s=5,
                    window=micro_cfg.window,
                    flow_rows=micro_cfg.flow_rows,
                    refresh_s=quote_cfgs.fund_cn.refresh_s,
                )
            )
            fund_cn_micro_engines[sym] = engine
        return engine

    def _micro_watch_symbols() -> list[str]:
        syms = [s.strip().upper() for s in (quote_cfgs.crypto.symbols or []) if (s or "").strip()]
        cur = (micro_symbol_current or "").strip().upper()
        if cur and cur not in syms:
            syms.insert(0, cur)
        return syms

    def _switch_micro_symbol(delta: int) -> bool:
        nonlocal micro_symbol_current
        syms = _micro_watch_symbols()
        if not syms:
            return False

        cur = (micro_symbol_current or "").strip().upper()
        try:
            idx = syms.index(cur)
        except ValueError:
            idx = 0

        target_idx = max(0, min(len(syms) - 1, idx + int(delta)))
        target = syms[target_idx]
        if not target:
            return False

        changed = target != cur
        micro_symbol_current = target
        _ensure_micro_engine(micro_symbol_current)
        if changed:
            micro_switch.bump(time.time(), _SWITCH_DEBOUNCE_S)
        return changed

    _ensure_micro_engine(micro_symbol_current)

    def _persist_watchlists() -> None:
        if not watchlists_path:
            return
        wl = Watchlists(
            us=normalize_us_symbols(",".join(quote_cfgs.us.symbols)),
            hk=normalize_hk_symbols(",".join(quote_cfgs.hk.symbols)),
            cn=normalize_cn_symbols(",".join(quote_cfgs.cn.symbols)),
            fund_cn=normalize_cn_fund_symbols(",".join(quote_cfgs.fund_cn.symbols)),
            crypto=normalize_crypto_symbols(",".join(quote_cfgs.crypto.symbols)),
            metals=normalize_metals_symbols(",".join(quote_cfgs.metals.symbols)),
        )
        try:
            save_watchlists(watchlists_path, wl)
        except Exception:
            # Persistence should never crash the UI.
            pass

    def _reload_dynamic_fund_universe(top_n: int = 35) -> bool:
        dynamic = load_dynamic_auto_driving_symbols(_REPO_ROOT, top_n=top_n)
        if not dynamic:
            return False
        normalized = normalize_cn_fund_symbols(",".join(dynamic))
        if not normalized:
            return False
        if normalized == [s.strip().upper() for s in (quote_cfgs.fund_cn.symbols or []) if (s or "").strip()]:
            return False

        quote_cfgs.fund_cn.symbols = list(normalized)
        poll_fund_cn.set_symbols(quote_cfgs.fund_cn.symbols)
        pane = master_panes.get("market_fund_cn")
        if pane is not None:
            pane.selected = min(max(0, pane.selected), max(0, len(quote_cfgs.fund_cn.symbols) - 1))
            pane.left_scroll = min(max(0, pane.left_scroll), max(0, len(quote_cfgs.fund_cn.symbols) - 1))
            pane.right_scroll = 0
        master_switches["market_fund_cn"].bump(time.time(), _SWITCH_DEBOUNCE_S)
        return True

    def _refresh_all_data() -> None:
        nonlocal last_refresh
        last_refresh = 0.0
        for name, poller in pollers_by_name.items():
            if name in _desired_quote_poller_names(view):
                poller.request_refresh()
        if news_poller is not None and _should_poll_news(view):
            news_poller.request_refresh()
        us_curve_seed_attempts.clear()
        hk_curve_seed_attempts.clear()
        cn_curve_seed_attempts.clear()
        fund_cn_curve_seed_attempts.clear()

    def _prompt(prompt: str, max_len: int = 64) -> str:
        """
        Prompt on the last line.

        Keys:
        - Enter: confirm
        - ESC: cancel (returns empty string)
        - Backspace: edit
        """
        h, w = stdscr.getmaxyx()
        y = h - 1
        x0 = 0
        # Keep the hint short; it will be truncated if terminal is narrow.
        hint = f"{prompt} (Enter=OK, Esc=Cancel) "
        buf: list[str] = []

        stdscr.nodelay(False)
        try:
            while True:
                stdscr.move(y, x0)
                stdscr.clrtoeol()
                _safe_addstr(stdscr, y, x0, _truncate(hint + "".join(buf), max(0, w - 1)))
                stdscr.refresh()

                try:
                    ch = stdscr.getch()
                except KeyboardInterrupt:
                    return ""

                if ch in (27,):  # ESC
                    return ""
                if ch in (10, 13):  # Enter
                    return "".join(buf).strip()
                if ch in (curses.KEY_BACKSPACE, 127, 8):
                    if buf:
                        buf.pop()
                    continue
                if ch == -1:
                    continue

                # Only accept a conservative ASCII subset to avoid weird control chars in watchlists.
                if 32 <= ch <= 126:
                    c = chr(ch)
                    if len(buf) < max_len:
                        buf.append(c)
        finally:
            stdscr.nodelay(True)

    def _pane_signature(pane: MasterPaneState) -> tuple[int, int, int, str]:
        return (
            int(pane.selected),
            int(pane.left_scroll),
            int(pane.right_scroll),
            (pane.focus or "left").strip(),
        )

    def _ui_signature() -> tuple:
        return (
            view,
            int(scroll),
            int(qscroll.get(view, 0)),
            bool(filt.paused),
            tuple(sorted(filt.sources)),
            tuple(sorted(filt.directions)),
            tuple((name, _pane_signature(pane)) for name, pane in sorted(master_panes.items())),
            tuple(s.strip().upper() for s in (quote_cfgs.us.symbols or [])),
            tuple(s.strip().upper() for s in (quote_cfgs.hk.symbols or [])),
            tuple(s.strip().upper() for s in (quote_cfgs.cn.symbols or [])),
            tuple(s.strip().upper() for s in (quote_cfgs.fund_cn.symbols or [])),
            tuple(s.strip().upper() for s in (quote_cfgs.crypto.symbols or [])),
            tuple(s.strip().upper() for s in (quote_cfgs.metals.symbols or [])),
            (micro_symbol_current or "").strip().upper(),
            runtime_state.fund_domain.selected_key,
            int(runtime_state.fund_domain.selected_idx),
            (news_state.focus or "middle").strip(),
            int(news_state.watch_selected),
            int(news_state.news_selected),
            int(news_state.news_scroll),
            int(news_state.category_idx),
            int(news_state.source_idx),
            int(news_state.window_idx),
            (news_state.search_query or "").strip().lower(),
            bool(news_state.watch_filter_locked),
        )

    def _maybe_apply_switch_debounce(now_ts: float) -> bool:
        nonlocal micro_switch_applied, pending_force_redraw

        changed = False

        if micro_switch.version != micro_switch_applied and now_ts >= micro_switch.ready_at:
            micro_switch_applied = micro_switch.version
            current = (micro_symbol_current or "").strip().upper()
            if current:
                micro_last_refresh[current] = 0.0
            changed = True

        for mv in ("market_us", "market_cn", "market_hk", "market_fund_cn"):
            sw = master_switches[mv]
            if sw.version == master_switch_applied[mv] or now_ts < sw.ready_at:
                continue

            master_switch_applied[mv] = sw.version
            pane = master_panes.get(mv)
            if pane is None:
                continue

            if mv == "market_us":
                syms = [s.strip().upper() for s in (quote_cfgs.us.symbols or []) if (s or "").strip()]
                if not syms:
                    continue
                pane.selected = min(max(0, pane.selected), len(syms) - 1)
                us_curve_seed_attempts.pop(syms[pane.selected], None)
                changed = True
                continue

            if mv == "market_hk":
                syms_hk = [_normalize_hk_symbol(s) for s in (quote_cfgs.hk.symbols or []) if (s or "").strip()]
                syms_hk = [s for s in syms_hk if s]
                if not syms_hk:
                    continue
                pane.selected = min(max(0, pane.selected), len(syms_hk) - 1)
                hk_curve_seed_attempts.pop(syms_hk[pane.selected], None)
                changed = True
                continue

            source_symbols = quote_cfgs.cn.symbols if mv == "market_cn" else quote_cfgs.fund_cn.symbols
            norm_fn = _normalize_cn_symbol if mv == "market_cn" else _normalize_cn_fund_symbol
            syms_cn = [norm_fn(s) for s in (source_symbols or []) if (s or "").strip()]
            syms_cn = [s for s in syms_cn if s]
            if not syms_cn:
                continue
            pane.selected = min(max(0, pane.selected), len(syms_cn) - 1)
            if mv == "market_cn":
                cn_curve_seed_attempts.pop(syms_cn[pane.selected], None)
            else:
                fund_cn_curve_seed_attempts.pop(syms_cn[pane.selected], None)
            changed = True

        if changed:
            pending_force_redraw = True
        return changed

    try:
        while True:
            now = time.time()
            _sync_background_activity()
            dirty = DirtyFlags(forced=pending_force_redraw)
            pending_force_redraw = False
            if hot_reload_watcher is not None and hot_reload_watcher.should_reload(now):
                raise _HotReloadRequested()
            if (now - service_status.checked_at) >= service_status_refresh_s:
                new_service_status = _collect_service_status(now)
                if _service_status_signature(new_service_status) != _service_status_signature(service_status):
                    dirty.services = True
                service_status = new_service_status

            if _maybe_apply_switch_debounce(now):
                dirty.ui = True

            if not filt.paused and (now - last_refresh) >= refresh_s:
                ok, _ = probe(db_path)
                if ok:
                    new_rows = fetch_recent(
                        db_path,
                        limit=limit,
                        min_id=None,
                        sources=sorted(filt.sources),
                        directions=sorted(filt.directions),
                    )
                    # Also keep an unfiltered view for cross-page correlation (quotes <-> signals),
                    # so the quotes pages can still show "latest signal" even if the user hides a direction/source.
                    rows_all = fetch_recent(
                        db_path,
                        limit=max(200, int(limit)),
                        min_id=None,
                        sources=["pg", "sqlite"],
                        directions=["BUY", "SELL", "ALERT"],
                    )
                    # fetch_recent returns DESC order (newest first)
                    rows = new_rows
                    if rows:
                        last_id = max(last_id, rows[0].id)
                else:
                    rows = []
                    rows_all = []
                last_refresh = now

            quote_state_us = poll_us.snapshot()
            quote_state_hk = poll_hk.snapshot()
            quote_state_cn = poll_cn.snapshot()
            quote_state_fund_cn = poll_fund_cn.snapshot()
            quote_state_crypto = poll_crypto.snapshot()
            quote_state_metals = poll_metals.snapshot()

            active_us_symbols = {s.strip().upper() for s in (quote_cfgs.us.symbols or []) if (s or "").strip()}
            for stale_symbol in list(us_quote_curves.keys()):
                if stale_symbol not in active_us_symbols:
                    us_quote_curves.pop(stale_symbol, None)
                    us_curve_seed_attempts.pop(stale_symbol, None)
            for stale_symbol in list(us_micro_engines.keys()):
                if stale_symbol not in active_us_symbols:
                    us_micro_engines.pop(stale_symbol, None)
                    us_micro_errors.pop(stale_symbol, None)
                    us_last_ingested_fetch.pop(stale_symbol, None)

            for sym in active_us_symbols:
                st = quote_state_us.entries.get(sym)
                if st and st.quote is not None:
                    curve_ts = _curve_update_ts(st.quote, st.last_fetch_at, now)
                    _update_quote_curve(us_quote_curves, sym, st.quote, curve_ts, interval_s=5, max_points=240)
                    us_engine = _ensure_us_micro_engine(sym)
                    last_seen = us_last_ingested_fetch.get(sym, 0.0)
                    if st.last_fetch_at > last_seen:
                        us_engine.ingest_quote(st.quote, fetched_at=st.last_fetch_at)
                        us_last_ingested_fetch[sym] = st.last_fetch_at
                    us_micro_errors[sym] = (st.last_error or "").strip()
                else:
                    us_micro_errors[sym] = "no data"

            active_hk_symbols = {_normalize_hk_symbol(s) for s in (quote_cfgs.hk.symbols or []) if (s or "").strip()}
            active_hk_symbols.discard("")
            for stale_symbol in list(hk_quote_curves.keys()):
                if stale_symbol not in active_hk_symbols:
                    hk_quote_curves.pop(stale_symbol, None)
                    hk_curve_seed_attempts.pop(stale_symbol, None)
            for stale_symbol in list(hk_micro_engines.keys()):
                if stale_symbol not in active_hk_symbols:
                    hk_micro_engines.pop(stale_symbol, None)
                    hk_micro_errors.pop(stale_symbol, None)
                    hk_last_ingested_fetch.pop(stale_symbol, None)

            for sym in active_hk_symbols:
                st = quote_state_hk.entries.get(sym)
                if st and st.quote is not None:
                    curve_ts = _curve_update_ts(st.quote, st.last_fetch_at, now)
                    _update_quote_curve(hk_quote_curves, sym, st.quote, curve_ts, interval_s=5, max_points=240)
                    hk_engine = _ensure_hk_micro_engine(sym)
                    last_seen = hk_last_ingested_fetch.get(sym, 0.0)
                    if st.last_fetch_at > last_seen:
                        hk_engine.ingest_quote(st.quote, fetched_at=st.last_fetch_at)
                        hk_last_ingested_fetch[sym] = st.last_fetch_at
                    hk_micro_errors[sym] = (st.last_error or "").strip()
                else:
                    hk_micro_errors[sym] = "no data"

            active_cn_symbols = {_normalize_cn_symbol(s) for s in (quote_cfgs.cn.symbols or []) if (s or "").strip()}
            active_cn_symbols.discard("")
            for stale_symbol in list(cn_quote_curves.keys()):
                if stale_symbol not in active_cn_symbols:
                    cn_quote_curves.pop(stale_symbol, None)
                    cn_curve_seed_attempts.pop(stale_symbol, None)
            for stale_symbol in list(cn_micro_engines.keys()):
                if stale_symbol not in active_cn_symbols:
                    cn_micro_engines.pop(stale_symbol, None)
                    cn_micro_errors.pop(stale_symbol, None)
                    cn_last_ingested_fetch.pop(stale_symbol, None)

            for sym in active_cn_symbols:
                st = quote_state_cn.entries.get(sym)
                if st and st.quote is not None:
                    curve_ts = _curve_update_ts(st.quote, st.last_fetch_at, now)
                    _update_quote_curve(cn_quote_curves, sym, st.quote, curve_ts, interval_s=5, max_points=240)
                    cn_engine = _ensure_cn_micro_engine(sym)
                    last_seen = cn_last_ingested_fetch.get(sym, 0.0)
                    if st.last_fetch_at > last_seen:
                        cn_engine.ingest_quote(st.quote, fetched_at=st.last_fetch_at)
                        cn_last_ingested_fetch[sym] = st.last_fetch_at
                    cn_micro_errors[sym] = (st.last_error or "").strip()
                else:
                    cn_micro_errors[sym] = "no data"

            active_fund_cn_symbols = {
                _normalize_cn_fund_symbol(s) for s in (quote_cfgs.fund_cn.symbols or []) if (s or "").strip()
            }
            active_fund_cn_symbols.discard("")
            for stale_symbol in list(fund_cn_quote_curves.keys()):
                if stale_symbol not in active_fund_cn_symbols:
                    fund_cn_quote_curves.pop(stale_symbol, None)
            for stale_symbol in list(fund_cn_daily_curves.keys()):
                if stale_symbol not in active_fund_cn_symbols:
                    fund_cn_daily_curves.pop(stale_symbol, None)
                    fund_cn_curve_seed_attempts.pop(stale_symbol, None)
            for stale_symbol in list(fund_cn_curve_seed_attempts.keys()):
                if stale_symbol not in active_fund_cn_symbols:
                    fund_cn_curve_seed_attempts.pop(stale_symbol, None)
            for stale_symbol in list(fund_cn_micro_engines.keys()):
                if stale_symbol not in active_fund_cn_symbols:
                    fund_cn_micro_engines.pop(stale_symbol, None)
                    fund_cn_micro_errors.pop(stale_symbol, None)
                    fund_cn_last_ingested_fetch.pop(stale_symbol, None)

            for sym in active_fund_cn_symbols:
                st = quote_state_fund_cn.entries.get(sym)
                if st and st.quote is not None:
                    curve_ts = _curve_update_ts(st.quote, st.last_fetch_at, now)
                    _update_quote_curve(fund_cn_quote_curves, sym, st.quote, curve_ts, interval_s=5, max_points=240)
                    cn_engine = _ensure_fund_cn_micro_engine(sym)
                    last_seen = fund_cn_last_ingested_fetch.get(sym, 0.0)
                    if st.last_fetch_at > last_seen:
                        quote_for_engine = st.quote
                        if (quote_for_engine.symbol or "").strip().upper() != sym:
                            # Keep engine key stable for mixed fund symbols (exchange/off-market).
                            quote_for_engine = Quote(
                                symbol=sym,
                                name=quote_for_engine.name,
                                price=quote_for_engine.price,
                                prev_close=quote_for_engine.prev_close,
                                open=quote_for_engine.open,
                                high=quote_for_engine.high,
                                low=quote_for_engine.low,
                                currency=quote_for_engine.currency,
                                volume=quote_for_engine.volume,
                                amount=quote_for_engine.amount,
                                ts=quote_for_engine.ts,
                                source=quote_for_engine.source,
                            )
                        cn_engine.ingest_quote(quote_for_engine, fetched_at=st.last_fetch_at)
                        fund_cn_last_ingested_fetch[sym] = st.last_fetch_at
                    fund_cn_micro_errors[sym] = (st.last_error or "").strip()
                else:
                    fund_cn_micro_errors[sym] = "no data"

            _maybe_seed_closed_curve_from_history(
                curves=us_quote_curves,
                quote_state=quote_state_us,
                symbols=active_us_symbols,
                market=quote_cfgs.us.market,
                provider=quote_cfgs.us.provider,
                attempts=us_curve_seed_attempts,
                now_ts=now,
                max_points=240,
            )
            _maybe_seed_closed_curve_from_history(
                curves=cn_quote_curves,
                quote_state=quote_state_cn,
                symbols=active_cn_symbols,
                market=quote_cfgs.cn.market,
                provider=quote_cfgs.cn.provider,
                attempts=cn_curve_seed_attempts,
                now_ts=now,
                max_points=240,
            )
            _maybe_seed_closed_curve_from_history(
                curves=hk_quote_curves,
                quote_state=quote_state_hk,
                symbols=active_hk_symbols,
                market=quote_cfgs.hk.market,
                provider=quote_cfgs.hk.provider,
                attempts=hk_curve_seed_attempts,
                now_ts=now,
                max_points=240,
            )
            fund_symbols_order = [_normalize_cn_fund_symbol(s) for s in (quote_cfgs.fund_cn.symbols or []) if (s or "").strip()]
            fund_symbols_order = [s for s in fund_symbols_order if s]
            fund_pane = master_panes.get("market_fund_cn")
            selected_fund_symbol = ""
            if fund_symbols_order and fund_pane is not None:
                fund_pane.selected = min(max(0, fund_pane.selected), len(fund_symbols_order) - 1)
                selected_fund_symbol = fund_symbols_order[fund_pane.selected]
            if selected_fund_symbol and selected_fund_symbol.startswith(("SH", "SZ")):
                _maybe_seed_fund_curve_from_daily_history(
                    curves=fund_cn_daily_curves,
                    symbols={selected_fund_symbol},
                    bridge=fund_bridge,
                    attempts=fund_cn_curve_seed_attempts,
                    now_ts=now,
                    lookback_days=_FUND_CN_CURVE_DAYS,
                )

            micro_symbols = _micro_watch_symbols()
            active_crypto_symbols = set(micro_symbols)
            for stale_symbol in list(crypto_quote_curves.keys()):
                if stale_symbol not in active_crypto_symbols:
                    crypto_quote_curves.pop(stale_symbol, None)
            for stale_symbol in list(micro_engines.keys()):
                if stale_symbol not in active_crypto_symbols:
                    micro_engines.pop(stale_symbol, None)
                    micro_errors.pop(stale_symbol, None)
                    micro_last_refresh.pop(stale_symbol, None)
                    crypto_last_ingested_fetch.pop(stale_symbol, None)

            if not filt.paused:
                for sym in sorted(active_crypto_symbols):
                    entry = quote_state_crypto.entries.get(sym)
                    if entry and entry.quote is not None:
                        _update_quote_curve(crypto_quote_curves, sym, entry.quote, entry.last_fetch_at, interval_s=5, max_points=240)
                        micro_engine = _ensure_micro_engine(sym)
                        last_seen = crypto_last_ingested_fetch.get(sym, 0.0)
                        if entry.last_fetch_at > last_seen:
                            micro_engine.ingest_quote(entry.quote, fetched_at=entry.last_fetch_at)
                            crypto_last_ingested_fetch[sym] = entry.last_fetch_at
                        micro_errors[sym] = (entry.last_error or "").strip()
                        micro_last_refresh[sym] = now
                        continue

                    current_micro_symbol = (micro_symbol_current or "").strip().upper()
                    if sym != current_micro_symbol:
                        if entry is None:
                            micro_errors[sym] = "no data"
                        else:
                            micro_errors[sym] = (entry.last_error or "").strip() or "no data"
                        continue

                    if micro_switch.version != micro_switch_applied and now < micro_switch.ready_at:
                        continue

                    last_micro_refresh = micro_last_refresh.get(sym, 0.0)
                    if (now - last_micro_refresh) < micro_cfg.refresh_s:
                        continue

                    switch_version = micro_switch.version
                    quote = fetch_quote(
                        quote_cfgs.crypto.provider,
                        quote_cfgs.crypto.market,
                        sym,
                        timeout_s=quote_cfgs.crypto.timeout_s,
                    )
                    if switch_version != micro_switch.version or sym != (micro_symbol_current or "").strip().upper():
                        continue
                    if quote is None:
                        micro_errors[sym] = "no quote"
                    else:
                        ts_now = time.time()
                        _update_quote_curve(crypto_quote_curves, sym, quote, ts_now, interval_s=5, max_points=240)
                        micro_engine = _ensure_micro_engine(sym)
                        micro_engine.ingest_quote(quote, fetched_at=ts_now)
                        crypto_last_ingested_fetch[sym] = ts_now
                        micro_errors[sym] = ""
                        # Sync back to quote_state so left panel & stats line show data
                        if sym not in quote_state_crypto.entries:
                            quote_state_crypto.entries[sym] = QuoteEntryState()
                        quote_state_crypto.entries[sym].quote = quote
                        quote_state_crypto.entries[sym].last_fetch_at = ts_now
                        quote_state_crypto.entries[sym].last_error = ""
                    micro_last_refresh[sym] = now

            cur_micro_symbol = micro_symbol_current
            cur_micro_engine = _ensure_micro_engine(cur_micro_symbol)

            latest_sig_map_crypto = _build_latest_signal_map(rows_all)
            us_curve_map = _snapshot_quote_curves(us_quote_curves)
            hk_curve_map = _snapshot_quote_curves(hk_quote_curves)
            cn_curve_map = _snapshot_quote_curves(cn_quote_curves)
            fund_cn_curve_map = _snapshot_quote_curves(fund_cn_quote_curves)
            fund_cn_daily_curve_map = _snapshot_quote_curves(fund_cn_daily_curves)
            crypto_curve_map = _snapshot_quote_curves(crypto_quote_curves)
            us_micro_snapshots = {
                sym: engine.snapshot(error=us_micro_errors.get(sym, "")) for sym, engine in us_micro_engines.items()
            }
            hk_micro_snapshots = {
                sym: engine.snapshot(error=hk_micro_errors.get(sym, "")) for sym, engine in hk_micro_engines.items()
            }
            cn_micro_snapshots = {
                sym: engine.snapshot(error=cn_micro_errors.get(sym, "")) for sym, engine in cn_micro_engines.items()
            }
            fund_cn_micro_snapshots = {
                sym: engine.snapshot(error=fund_cn_micro_errors.get(sym, ""))
                for sym, engine in fund_cn_micro_engines.items()
            }
            micro_snapshot = cur_micro_engine.snapshot(error=micro_errors.get(cur_micro_symbol, ""))

            db_sig = (
                _signal_rows_signature(rows),
                _signal_rows_signature(rows_all),
                int(last_id),
            )
            if db_sig != render_state.db_sig:
                dirty.db = True
                render_state.db_sig = db_sig

            quote_sig = (
                _quote_book_signature(quote_state_us),
                _quote_book_signature(quote_state_hk),
                _quote_book_signature(quote_state_cn),
                _quote_book_signature(quote_state_fund_cn),
                _quote_book_signature(quote_state_crypto),
                _quote_book_signature(quote_state_metals),
            )
            if quote_sig != render_state.quote_sig:
                dirty.quotes = True
                render_state.quote_sig = quote_sig

            micro_sig = (
                _curve_map_signature(us_curve_map),
                _curve_map_signature(hk_curve_map),
                _curve_map_signature(cn_curve_map),
                _curve_map_signature(fund_cn_curve_map),
                _curve_map_signature(fund_cn_daily_curve_map),
                _curve_map_signature(crypto_curve_map),
                tuple((sym, _micro_snapshot_signature(ss)) for sym, ss in sorted(us_micro_snapshots.items())),
                tuple((sym, _micro_snapshot_signature(ss)) for sym, ss in sorted(hk_micro_snapshots.items())),
                tuple((sym, _micro_snapshot_signature(ss)) for sym, ss in sorted(cn_micro_snapshots.items())),
                tuple((sym, _micro_snapshot_signature(ss)) for sym, ss in sorted(fund_cn_micro_snapshots.items())),
                _micro_snapshot_signature(micro_snapshot),
                tuple(micro_symbols),
            )
            if micro_sig != render_state.micro_sig:
                dirty.micro = True
                render_state.micro_sig = micro_sig

            ui_sig = _ui_signature()
            if ui_sig != render_state.ui_sig:
                dirty.ui = True
                render_state.ui_sig = ui_sig

            service_sig = _service_status_signature(service_status)
            if service_sig != render_state.service_sig:
                dirty.services = True
                render_state.service_sig = service_sig

            h, w = stdscr.getmaxyx()
            layout_sig = (int(h), int(w))
            if layout_sig != render_state.layout_sig:
                dirty.layout = True
                render_state.layout_sig = layout_sig

            idle_due = render_state.last_draw_at <= 0.0 or (now - render_state.last_draw_at) >= _RENDER_IDLE_REDRAW_S
            frame_due = now >= next_frame_at
            header_only_due = (
                dirty.services
                and not (dirty.db or dirty.quotes or dirty.micro or dirty.ui or dirty.layout or dirty.forced)
            )

            if frame_due and (dirty.any() or idle_due):
                if header_only_due and not idle_due:
                    _, w = stdscr.getmaxyx()
                    _draw_header(stdscr, colors, filt, refresh_s, view, service_status, w, top_page, market_tab)
                    stdscr.noutrefresh()
                    curses.doupdate()
                else:
                    news_snapshot: NewsFeedSnapshot | None = None
                    if view == "market_news":
                        if news_poller is not None:
                            news_snapshot = news_poller.snapshot()
                        else:
                            news_snapshot = NewsFeedSnapshot(
                                mode="RSS",
                                items=(),
                                feeds=(),
                                last_ok_at=0.0,
                                latest_item_at=0.0,
                                refresh_s=0.0,
                                last_error="news feeds not configured",
                            )
                    _draw(
                        stdscr,
                        db_path,
                        rows,
                        rows_all,
                        filt,
                        scroll,
                        colors,
                        refresh_s,
                        last_id,
                        quote_cfgs,
                        quote_state_us,
                        quote_state_hk,
                        quote_state_cn,
                        quote_state_fund_cn,
                        quote_state_crypto,
                        quote_state_metals,
                        latest_sig_map_crypto,
                        us_curve_map,
                        hk_curve_map,
                        cn_curve_map,
                        fund_cn_curve_map,
                        fund_cn_daily_curve_map,
                        crypto_curve_map,
                        us_micro_snapshots,
                        hk_micro_snapshots,
                        cn_micro_snapshots,
                        fund_cn_micro_snapshots,
                        micro_snapshot,
                        micro_symbols,
                        service_status,
                        view,
                        qscroll.get(view, 0),
                        master_panes.get(view),
                        runtime_state,
                        news_state,
                        news_snapshot,
                        top_page,
                        market_tab,
                    )
                render_state.last_draw_at = now
                next_frame_at = now + _RENDER_FRAME_INTERVAL_S
            key = stdscr.getch()
            if key == -1:
                sleep_for = min(_IDLE_POLL_SLEEP_S, max(0.0, next_frame_at - time.time()))
                if sleep_for > 0:
                    wait_seconds(sleep_for)
                continue

            pending_force_redraw = True
            if key in (ord("q"), 27):  # q or ESC
                return
            if key in (ord(" "),):
                filt.paused = not filt.paused
                _sync_background_activity(force=True)
            elif key == ord("\t"):
                if view == "market_news":
                    focus_order = ("middle", "right")
                    try:
                        idx = focus_order.index(news_state.focus)
                    except ValueError:
                        idx = 0
                    news_state.focus = focus_order[(idx + 1) % len(focus_order)]
                elif _is_master_view(view) and _master_has_signal_panel(view):
                    pane = master_panes[view]
                    pane.focus = "right" if pane.focus == "left" else "left"
                else:
                    view = _next_view(view)
                    _remember_primary_view(view)
            elif key == ord("t"):
                view = _next_view(view)
                _remember_primary_view(view)
            elif key == ord("1"):
                top_page = 1
                market_tab = 0  # default to 加密
                view = _MARKET_TABS[market_tab]
                _remember_primary_view(view)
            elif key == ord("2"):
                top_page = 2
                view = "market_micro"  # placeholder, P2 渲染时走分支
            elif key == ord("3"):
                top_page = 3
                view = _PAGE_NEWS_VIEW
                _remember_primary_view(view)
            elif key == ord("4"):
                if view == _BACKTEST_VIEW:
                    view = backtest_parent_view if backtest_parent_view in _PRIMARY_MARKET_VIEWS else last_primary_view
                    if view not in _PRIMARY_MARKET_VIEWS:
                        view = "market_micro"
                    _remember_primary_view(view)
                elif view == "market_micro":
                    canonical = _canonical_view(view)
                    if canonical in _PRIMARY_MARKET_VIEWS:
                        backtest_parent_view = canonical
                    else:
                        backtest_parent_view = last_primary_view
                    view = _BACKTEST_VIEW
            elif key == ord("5"):
                view = "market_fund_cn"
                _remember_primary_view(view)
            elif key == ord("6"):
                view = "market_hk"
                _remember_primary_view(view)
            elif key == ord("7"):
                view = "market_news"
                _remember_primary_view(view)
            elif key == ord("["):
                if top_page == 1:
                    market_tab = (market_tab - 1) % len(_MARKET_TABS)
                    view = _MARKET_TABS[market_tab]
                    _remember_primary_view(view)
                elif view == "market_micro":
                    _switch_micro_symbol(-1)
                elif view in {"market_us", "market_cn", "market_hk", "market_fund_cn"}:
                    _cycle_master_symbol(view, -1)
            elif key == ord("]"):
                if top_page == 1:
                    market_tab = (market_tab + 1) % len(_MARKET_TABS)
                    view = _MARKET_TABS[market_tab]
                    _remember_primary_view(view)
                elif view == "market_micro":
                    _switch_micro_symbol(1)
                elif view in {"market_us", "market_cn", "market_hk", "market_fund_cn"}:
                    _cycle_master_symbol(view, 1)
            elif key == ord(","):  # 切换领域（上一个）
                if view == "market_fund_cn":
                    selected_key = runtime_state.fund_domain.cycle(-1)
                    if selected_key:
                        # 更新候选池 symbols
                        domain_profile = get_etf_domain_profile(selected_key)
                        new_symbols = [s.upper() for s in domain_profile.symbols]
                        quote_cfgs.fund_cn.symbols = new_symbols
                        poll_fund_cn.set_symbols(new_symbols)
                        # 重置候选池选中状态
                        pane = master_panes.get(view)
                        if pane:
                            pane.selected = 0
                            pane.left_scroll = 0
                        master_switches["market_fund_cn"].bump(now, _SWITCH_DEBOUNCE_S)
            elif key == ord("."):  # 切换领域（下一个）
                if view == "market_fund_cn":
                    selected_key = runtime_state.fund_domain.cycle(1)
                    if selected_key:
                        # 更新候选池 symbols
                        domain_profile = get_etf_domain_profile(selected_key)
                        new_symbols = [s.upper() for s in domain_profile.symbols]
                        quote_cfgs.fund_cn.symbols = new_symbols
                        poll_fund_cn.set_symbols(new_symbols)
                        # 重置候选池选中状态
                        pane = master_panes.get(view)
                        if pane:
                            pane.selected = 0
                            pane.left_scroll = 0
                        master_switches["market_fund_cn"].bump(now, _SWITCH_DEBOUNCE_S)
            elif key == ord("0"):
                # Keep a stable home key, now pointing to micro page by default.
                view = "market_micro"
                _remember_primary_view(view)
            elif key == curses.KEY_UP:
                if view == "market_news":
                    _, item_count = _news_counts(news_state=news_state, news_poller=news_poller, now_ts=now)
                    news_state.news_selected = max(0, news_state.news_selected - 1)
                    news_state.news_selected = min(news_state.news_selected, max(0, item_count - 1))
                elif _is_master_view(view):
                    pane = master_panes[view]
                    if _master_has_signal_panel(view) and pane.focus == "right":
                        pane.right_scroll = max(0, pane.right_scroll - 1)
                    else:
                        old_selected = pane.selected
                        pane.selected = max(0, pane.selected - 1)
                        pane.right_scroll = 0
                        if pane.selected != old_selected and view in master_switches:
                            master_switches[view].bump(now, _SWITCH_DEBOUNCE_S)
                elif view.startswith("quotes_"):
                    qscroll[view] = max(0, qscroll.get(view, 0) - 1)
                elif view == "market_micro":
                    # Avoid wheel/arrow accidental symbol switches on micro page.
                    pass
                else:
                    scroll = max(0, scroll - 1)
            elif key == curses.KEY_DOWN:
                if view == "market_news":
                    _, item_count = _news_counts(news_state=news_state, news_poller=news_poller, now_ts=now)
                    news_state.news_selected = min(max(0, item_count - 1), news_state.news_selected + 1)
                elif _is_master_view(view):
                    pane = master_panes[view]
                    if _master_has_signal_panel(view) and pane.focus == "right":
                        pane.right_scroll = max(0, pane.right_scroll + 1)
                    else:
                        old_selected = pane.selected
                        pane.selected = min(max(0, _master_symbol_count(view) - 1), pane.selected + 1)
                        pane.right_scroll = 0
                        if pane.selected != old_selected and view in master_switches:
                            master_switches[view].bump(now, _SWITCH_DEBOUNCE_S)
                elif view.startswith("quotes_"):
                    qscroll[view] = max(0, qscroll.get(view, 0) + 1)
                elif view == "market_micro":
                    # Avoid wheel/arrow accidental symbol switches on micro page.
                    pass
                else:
                    scroll = min(max(0, len(rows) - 1), scroll + 1)
            elif key == curses.KEY_PPAGE:  # PageUp
                if view == "market_news":
                    _, item_count = _news_counts(news_state=news_state, news_poller=news_poller, now_ts=now)
                    news_state.news_selected = max(0, news_state.news_selected - 10)
                    news_state.news_selected = min(news_state.news_selected, max(0, item_count - 1))
                elif _is_master_view(view):
                    pane = master_panes[view]
                    if _master_has_signal_panel(view) and pane.focus == "right":
                        pane.right_scroll = max(0, pane.right_scroll - 10)
                    else:
                        old_selected = pane.selected
                        pane.selected = max(0, pane.selected - 10)
                        pane.right_scroll = 0
                        if pane.selected != old_selected and view in master_switches:
                            master_switches[view].bump(now, _SWITCH_DEBOUNCE_S)
                elif view.startswith("quotes_"):
                    qscroll[view] = max(0, qscroll.get(view, 0) - 10)
                else:
                    scroll = max(0, scroll - 10)
            elif key == curses.KEY_NPAGE:  # PageDown
                if view == "market_news":
                    _, item_count = _news_counts(news_state=news_state, news_poller=news_poller, now_ts=now)
                    news_state.news_selected = min(max(0, item_count - 1), news_state.news_selected + 10)
                elif _is_master_view(view):
                    pane = master_panes[view]
                    if _master_has_signal_panel(view) and pane.focus == "right":
                        pane.right_scroll = max(0, pane.right_scroll + 10)
                    else:
                        old_selected = pane.selected
                        pane.selected = min(max(0, _master_symbol_count(view) - 1), pane.selected + 10)
                        pane.right_scroll = 0
                        if pane.selected != old_selected and view in master_switches:
                            master_switches[view].bump(now, _SWITCH_DEBOUNCE_S)
                elif view.startswith("quotes_"):
                    qscroll[view] = max(0, qscroll.get(view, 0) + 10)
                else:
                    scroll = min(max(0, len(rows) - 1), scroll + 10)
            elif key == ord("g"):
                if view == "market_news":
                    news_state.news_selected = 0
                    news_state.news_scroll = 0
                elif _is_master_view(view):
                    pane = master_panes[view]
                    if _master_has_signal_panel(view) and pane.focus == "right":
                        pane.right_scroll = 0
                    else:
                        old_selected = pane.selected
                        pane.selected = 0
                        pane.left_scroll = 0
                        pane.right_scroll = 0
                        if pane.selected != old_selected and view in master_switches:
                            master_switches[view].bump(now, _SWITCH_DEBOUNCE_S)
                elif view.startswith("quotes_"):
                    qscroll[view] = 0
                else:
                    scroll = 0
            elif key == ord("G"):
                if view == "market_news":
                    _, item_count = _news_counts(news_state=news_state, news_poller=news_poller, now_ts=now)
                    news_state.news_selected = max(0, item_count - 1)
                elif _is_master_view(view):
                    pane = master_panes[view]
                    if _master_has_signal_panel(view) and pane.focus == "right":
                        pane.right_scroll = 10**9
                    else:
                        old_selected = pane.selected
                        pane.selected = max(0, _master_symbol_count(view) - 1)
                        pane.right_scroll = 0
                        if pane.selected != old_selected and view in master_switches:
                            master_switches[view].bump(now, _SWITCH_DEBOUNCE_S)
                elif view.startswith("quotes_"):
                    qscroll[view] = 10**9
                else:
                    scroll = max(0, len(rows) - 1)
            elif key in (10, 13, curses.KEY_ENTER):
                pass
            elif key == ord("/"):
                if view == "market_news":
                    raw = _prompt("News search keyword: ", max_len=80)
                    news_state.search_query = (raw or "").strip()
                    news_state.news_selected = 0
                    news_state.news_scroll = 0
            elif key in (ord("f"), ord("F")):
                if view == "market_news":
                    news_state.category_idx = (news_state.category_idx + 1) % len(_NEWS_CATEGORIES)
                    news_state.news_selected = 0
                    news_state.news_scroll = 0
            elif key in (ord("w"), ord("W")):
                if view == "market_news":
                    news_state.window_idx = (news_state.window_idx + 1) % len(_NEWS_WINDOWS_H)
                    news_state.news_selected = 0
                    news_state.news_scroll = 0
            elif key in (ord("c"), ord("C")):
                if view == "market_news":
                    news_state.search_query = ""
                    news_state.source_idx = 0
                    news_state.news_selected = 0
                    news_state.news_scroll = 0
            elif key == ord("p"):
                filt.toggle_source("pg")
                scroll = 0
                last_refresh = 0.0
            elif key in (ord("s"), ord("S")):
                if view == "market_news":
                    source_options = _news_source_options(news_poller=news_poller)
                    if source_options:
                        news_state.source_idx = (news_state.source_idx + 1) % len(source_options)
                        news_state.news_selected = 0
                        news_state.news_scroll = 0
                else:
                    filt.toggle_source("sqlite")
                    scroll = 0
                    last_refresh = 0.0
            elif key == ord("b"):
                filt.toggle_direction("BUY")
                scroll = 0
                last_refresh = 0.0
            elif key == ord("e"):
                filt.toggle_direction("SELL")
                scroll = 0
                last_refresh = 0.0
            elif key == ord("a"):
                filt.toggle_direction("ALERT")
                scroll = 0
                last_refresh = 0.0
            elif key in (ord("r"), ord("R")):
                _refresh_all_data()
                if view == "market_fund_cn":
                    _reload_dynamic_fund_universe(top_n=35)
            elif key in (ord("u"), ord("U")) and view == "market_fund_cn":
                if _reload_dynamic_fund_universe(top_n=35):
                    _refresh_all_data()
            elif key in (ord("+"), ord("=")) and (view.startswith("quotes_") or _is_master_view(view) or view == "market_micro"):
                raw = _prompt("Add symbols (comma-separated): ")
                if raw:
                    if view in {"quotes_us", "market_us"}:
                        added = normalize_us_symbols(raw)
                        quote_cfgs.us.symbols = normalize_us_symbols(",".join(quote_cfgs.us.symbols + added))
                        poll_us.set_symbols(quote_cfgs.us.symbols)
                        pane = master_panes.get("market_us")
                        if pane is not None:
                            pane.selected = min(max(0, pane.selected), max(0, len(quote_cfgs.us.symbols) - 1))
                        master_switches["market_us"].bump(now, _SWITCH_DEBOUNCE_S)
                    elif view in {"quotes_hk", "market_hk"}:
                        added = normalize_hk_symbols(raw)
                        quote_cfgs.hk.symbols = normalize_hk_symbols(",".join(quote_cfgs.hk.symbols + added))
                        poll_hk.set_symbols(quote_cfgs.hk.symbols)
                        pane = master_panes.get("market_hk")
                        if pane is not None:
                            pane.selected = min(max(0, pane.selected), max(0, len(quote_cfgs.hk.symbols) - 1))
                        master_switches["market_hk"].bump(now, _SWITCH_DEBOUNCE_S)
                    elif view in {"quotes_cn", "market_cn"}:
                        added = normalize_cn_symbols(raw)
                        quote_cfgs.cn.symbols = normalize_cn_symbols(",".join(quote_cfgs.cn.symbols + added))
                        poll_cn.set_symbols(quote_cfgs.cn.symbols)
                        pane = master_panes.get("market_cn")
                        if pane is not None:
                            pane.selected = min(max(0, pane.selected), max(0, len(quote_cfgs.cn.symbols) - 1))
                        master_switches["market_cn"].bump(now, _SWITCH_DEBOUNCE_S)
                    elif view == "market_fund_cn":
                        added = normalize_cn_fund_symbols(raw)
                        quote_cfgs.fund_cn.symbols = normalize_cn_fund_symbols(",".join(quote_cfgs.fund_cn.symbols + added))
                        poll_fund_cn.set_symbols(quote_cfgs.fund_cn.symbols)
                        pane = master_panes.get("market_fund_cn")
                        if pane is not None:
                            pane.selected = min(max(0, pane.selected), max(0, len(quote_cfgs.fund_cn.symbols) - 1))
                        master_switches["market_fund_cn"].bump(now, _SWITCH_DEBOUNCE_S)
                    elif view in {"quotes_crypto", "market_crypto", "market_micro"}:
                        added = normalize_crypto_symbols(raw)
                        quote_cfgs.crypto.symbols = normalize_crypto_symbols(",".join(quote_cfgs.crypto.symbols + added))
                        poll_crypto.set_symbols(quote_cfgs.crypto.symbols)
                        micro_switch.bump(now, _SWITCH_DEBOUNCE_S)
                    elif view == "quotes_metals":
                        added = normalize_metals_symbols(raw)
                        quote_cfgs.metals.symbols = normalize_metals_symbols(",".join(quote_cfgs.metals.symbols + added))
                        poll_metals.set_symbols(quote_cfgs.metals.symbols)
                    _persist_watchlists()
            elif key in (ord("-"), ord("_")) and (view.startswith("quotes_") or _is_master_view(view) or view == "market_micro"):
                raw = _prompt("Remove symbols (comma-separated): ")
                if raw:
                    if view in {"quotes_us", "market_us"}:
                        rm = set(normalize_us_symbols(raw))
                        quote_cfgs.us.symbols = [s for s in quote_cfgs.us.symbols if s.upper() not in rm]
                        poll_us.set_symbols(quote_cfgs.us.symbols)
                        pane = master_panes.get("market_us")
                        if pane is not None:
                            pane.selected = min(max(0, pane.selected), max(0, len(quote_cfgs.us.symbols) - 1))
                        master_switches["market_us"].bump(now, _SWITCH_DEBOUNCE_S)
                    elif view in {"quotes_hk", "market_hk"}:
                        rm = set(normalize_hk_symbols(raw))
                        quote_cfgs.hk.symbols = [s for s in quote_cfgs.hk.symbols if s.zfill(5) not in rm]
                        poll_hk.set_symbols(quote_cfgs.hk.symbols)
                        pane = master_panes.get("market_hk")
                        if pane is not None:
                            pane.selected = min(max(0, pane.selected), max(0, len(quote_cfgs.hk.symbols) - 1))
                        master_switches["market_hk"].bump(now, _SWITCH_DEBOUNCE_S)
                    elif view in {"quotes_cn", "market_cn"}:
                        rm = set(normalize_cn_symbols(raw))
                        quote_cfgs.cn.symbols = [s for s in quote_cfgs.cn.symbols if s.upper() not in rm]
                        poll_cn.set_symbols(quote_cfgs.cn.symbols)
                        pane = master_panes.get("market_cn")
                        if pane is not None:
                            pane.selected = min(max(0, pane.selected), max(0, len(quote_cfgs.cn.symbols) - 1))
                        master_switches["market_cn"].bump(now, _SWITCH_DEBOUNCE_S)
                    elif view == "market_fund_cn":
                        rm = set(normalize_cn_fund_symbols(raw))
                        quote_cfgs.fund_cn.symbols = [s for s in quote_cfgs.fund_cn.symbols if s.upper() not in rm]
                        poll_fund_cn.set_symbols(quote_cfgs.fund_cn.symbols)
                        pane = master_panes.get("market_fund_cn")
                        if pane is not None:
                            pane.selected = min(max(0, pane.selected), max(0, len(quote_cfgs.fund_cn.symbols) - 1))
                        master_switches["market_fund_cn"].bump(now, _SWITCH_DEBOUNCE_S)
                    elif view in {"quotes_crypto", "market_crypto", "market_micro"}:
                        rm = set(normalize_crypto_symbols(raw))
                        quote_cfgs.crypto.symbols = [s for s in quote_cfgs.crypto.symbols if s.upper() not in rm]
                        poll_crypto.set_symbols(quote_cfgs.crypto.symbols)
                        _switch_micro_symbol(0)
                        micro_switch.bump(now, _SWITCH_DEBOUNCE_S)
                    elif view == "quotes_metals":
                        rm = set(normalize_metals_symbols(raw))
                        quote_cfgs.metals.symbols = [s for s in quote_cfgs.metals.symbols if s.upper() not in rm]
                        poll_metals.set_symbols(quote_cfgs.metals.symbols)
                    _persist_watchlists()
    finally:
        poll_us.stop()
        poll_hk.stop()
        poll_cn.stop()
        poll_fund_cn.stop()
        poll_crypto.stop()
        poll_metals.stop()
        if news_poller is not None:
            news_poller.stop()

