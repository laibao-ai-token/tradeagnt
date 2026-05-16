"""Backtest page module — snapshot loading, charting, and TUI rendering."""

from __future__ import annotations

import curses
import json
import math
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from tradecat.common.utils.scheduler import wait_seconds

# Constants (duplicated from tui.py for independence)
_REPO_ROOT = Path(__file__).resolve().parents[4]
_BACKTEST_LATEST_DIR = _REPO_ROOT / "artifacts" / "backtest" / "latest"
_BACKTEST_RUN_STATE_PATH = _REPO_ROOT / "artifacts" / "backtest" / "run_state.json"
_BACKTEST_MAX_EQUITY_POINTS = 600
_BACKTEST_RECENT_TRADES = 8
_BACKTEST_SHOW_COMPARE = str(os.environ.get("TUI_BACKTEST_SHOW_COMPARE", "")).strip().lower() in {
    "1", "true", "yes", "y", "on"
}

# Utility helpers
def _safe_addstr(win, y: int, x: int, s: str, attr: int = 0) -> None:
    try:
        max_y, max_x = win.getmaxyx()
        if y < 0 or y >= max_y or x < 0: return
        available = max_x - x
        if available <= 0: return
        win.addnstr(y, x, s, available, attr)
    except curses.error: pass

def _truncate(s: str, width: int) -> str:
    if width <= 0: return ""
    result = []
    current_width = 0
    for ch in s:
        ch_width = 2 if ord(ch) > 0x7F else 1
        if current_width + ch_width > width: break
        result.append(ch)
        current_width += ch_width
    return "".join(result)

def _coerce_float(value: object) -> float | None:
    if value is None: return None
    try: return float(value)
    except (TypeError, ValueError): return None

def _coerce_int(value: object) -> int | None:
    if value is None: return None
    try: return int(value)
    except (TypeError, ValueError): return None

def _coerce_pct(value: object) -> float | None:
    if value is None: return None
    try:
        v = float(value)
        return v * 100 if abs(v) < 1 else v
    except (TypeError, ValueError): return None

def _extract_metric(payload: dict, keys: tuple[str, ...]) -> object | None:
    for k in keys:
        if k in payload: return payload[k]
    return None

def _resample_series(values: list[float], max_points: int) -> list[float]:
    if len(values) <= max_points: return values
    step = len(values) / max_points
    return [values[int(i * step)] for i in range(max_points)]

# === BacktestSymbolContribution ===

class BacktestSymbolContribution:
    symbol: str
    pnl_net: float | None = None
    trade_count: int | None = None
    win_rate_pct: float | None = None
    avg_holding_minutes: float | None = None



# === BacktestCompareDelta ===

class BacktestCompareDelta:
    key: str
    history_count: int
    rule_count: int
    delta: int



# === BacktestCompareSnapshot ===

class BacktestCompareSnapshot:
    available: bool = False
    run_id: str = "--"
    history_run_id: str = "--"
    rule_run_id: str = "--"
    delta_return_pct: float | None = None
    delta_max_drawdown_pct: float | None = None
    delta_trade_count: int | None = None
    delta_excess_return_pct: float | None = None
    delta_signal_count: int | None = None
    history_buy_ratio_pct: float | None = None
    rule_buy_ratio_pct: float | None = None
    delta_buy_ratio_pct: float | None = None
    rule_history_types: int | None = None
    rule_rule_types: int | None = None
    rule_shared_types: int | None = None
    rule_jaccard_pct: float | None = None
    alignment_score: float | None = None
    alignment_status: str = "--"
    alignment_risk_level: str = "--"
    alignment_risk_summary: str = ""
    alignment_warning_count: int = 0
    alignment_warning_summary: str = ""
    signal_type_delta_top: list[BacktestCompareDelta] = field(default_factory=list)
    missing_rule_reason: str = ""



# === BacktestSnapshot ===

class BacktestSnapshot:
    available: bool = False
    status: str = "no backtest artifacts"
    mode: str = "--"
    run_id: str = "--"
    date_range: str = "--"
    total_return_pct: float | None = None
    max_drawdown_pct: float | None = None
    sharpe: float | None = None
    win_rate_pct: float | None = None
    trade_count: int | None = None
    avg_holding_minutes: float | None = None
    buy_hold_return_pct: float | None = None
    excess_return_pct: float | None = None
    quality_score: float | None = None
    quality_status: str = "--"
    quality_summary: str = ""
    stability_status: str = "--"
    stability_summary: str = ""
    stability_comparable_run_count: int = 0
    strategy_label: str = "--"
    strategy_summary: str = ""
    equity_points: list[float] = field(default_factory=list)
    symbol_contributions: list[BacktestSymbolContribution] = field(default_factory=list)
    recent_trades: list[str] = field(default_factory=list)
    is_walk_forward: bool = False
    wf_fold_count: int | None = None
    wf_positive_fold_rate_pct: float | None = None
    wf_history_fold_count: int | None = None
    wf_replay_fold_count: int | None = None
    wf_fallback_fold_count: int | None = None



# === BacktestRunStateSnapshot ===

class BacktestRunStateSnapshot:
    status: str = "idle"
    stage: str = "idle"
    run_id: str = "--"
    mode: str = "--"
    started_at: str = ""
    updated_at: str = ""
    finished_at: str = ""
    latest_run_id: str = "--"
    message: str = ""
    error: str = ""



# === _backtest_mode_text ===

def _backtest_mode_text(mode: str) -> str:
    """Human-friendly backtest mode label for the TUI."""

    key = str(mode or "").strip().lower()
    mapping = {
        "offline_rule_replay": "RULE(129规则离线重放)",
        "history_signal": "HISTORY(signal_history回放)",
        "offline_replay": "OFFLINE(PG K线伪信号)",
        "compare_history_rule": "COMPARE(history vs rule)",
    }
    return mapping.get(key, str(mode or "--").strip() or "--")



# === backtest_loaders ===

def _load_equity_curve(path: Path, max_points: int = _BACKTEST_MAX_EQUITY_POINTS) -> list[float]:
    if not path.exists():
        return []

    values: list[float] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            has_header = True
            try:
                has_header = csv.Sniffer().has_header(sample)
            except Exception:
                has_header = True

            if has_header:
                reader = csv.DictReader(fh)
                for row in reader:
                    if not row:
                        continue
                    val: float | None = None
                    for key in (
                        "equity",
                        "equity_value",
                        "balance",
                        "net_value",
                        "value",
                        "asset",
                        "capital",
                        "close",
                    ):
                        val = _coerce_float(row.get(key))
                        if val is not None:
                            break
                    if val is None:
                        for raw in row.values():
                            val = _coerce_float(raw)
                            if val is not None:
                                break
                    if val is not None:
                        values.append(float(val))
            else:
                reader2 = csv.reader(fh)
                for row in reader2:
                    if not row:
                        continue
                    val: float | None = None
                    for raw in reversed(row):
                        val = _coerce_float(raw)
                        if val is not None:
                            break
                    if val is not None:
                        values.append(float(val))
    except Exception:
        return []

    return _resample_series(values, max_points=max_points)


def _load_recent_trades(path: Path, max_rows: int = _BACKTEST_RECENT_TRADES) -> list[str]:
    if not path.exists():
        return []

    lines: list[str] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames:
                parsed: list[str] = []
                for row in reader:
                    ts = (
                        (row.get("exit_ts") or row.get("timestamp") or row.get("time") or row.get("entry_ts") or "--")
                        .strip()
                        .replace("T", " ")
                    )
                    ts = ts[:19] if ts else "--"
                    sym = (row.get("symbol") or row.get("asset") or "--").strip().upper()[:10]
                    side_raw = (row.get("side") or row.get("direction") or "--").strip()
                    side = _display_side_cn(side_raw)[:5]

                    pnl: float | None = None
                    for key in ("realized_pnl", "pnl", "profit", "net_pnl"):
                        pnl = _coerce_float(row.get(key))
                        if pnl is not None:
                            break
                    pnl_txt = f"pnl={pnl:+.2f}" if pnl is not None else "pnl=--"
                    parsed.append(f"{ts:<19} {sym:<10} {side:<5} {pnl_txt}")
                lines = parsed[-max_rows:]
            else:
                fh.seek(0)
                reader2 = csv.reader(fh)
                raw_lines = [" ".join(col.strip() for col in row if col.strip()) for row in reader2 if row]
                lines = [_truncate(line, 96) for line in raw_lines[-max_rows:]]
    except Exception:
        return []

    return lines


def _display_side_cn(side: str) -> str:
    """Human display name for trade sides (keep internal CSV as LONG/SHORT)."""
    s = (side or "").strip().upper()
    if s == "LONG":
        return "做多"
    if s == "SHORT":
        return "做空"
    return (side or "--").strip()


def _load_symbol_contributions(payload: dict, max_rows: int = 4) -> list[BacktestSymbolContribution]:
    raw = payload.get("symbol_contributions")
    if not isinstance(raw, list):
        return []

    rows: list[BacktestSymbolContribution] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "--").strip().upper()[:10]
        rows.append(
            BacktestSymbolContribution(
                symbol=symbol,
                pnl_net=_coerce_float(item.get("pnl_net")),
                trade_count=_coerce_int(item.get("trade_count")),
                win_rate_pct=_coerce_pct(item.get("win_rate_pct")),
                avg_holding_minutes=_coerce_float(item.get("avg_holding_minutes")),
            )
        )

    return rows[: max(0, max_rows)]


def _normalize_compare_base_run_id(run_id: str) -> str:
    rid = str(run_id or "").strip()
    if not rid:
        return ""
    for suffix in ("-history", "-rules", "-compare"):
        if rid.endswith(suffix):
            return rid[: -len(suffix)]
    return rid


def _parse_compare_delta_rows(raw: object, max_rows: int = 3) -> list[BacktestCompareDelta]:
    if not isinstance(raw, list):
        return []

    rows: list[BacktestCompareDelta] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "--").strip()
        if not key:
            key = "--"
        rows.append(
            BacktestCompareDelta(
                key=key,
                history_count=_coerce_int(item.get("history_count")) or 0,
                rule_count=_coerce_int(item.get("rule_count")) or 0,
                delta=_coerce_int(item.get("delta")) or 0,
            )
        )

    return rows[: max(0, max_rows)]


def _resolve_backtest_root(base_dir: Path) -> Path:
    base = Path(base_dir)
    if (base / "latest").exists():
        return base
    if base.name == "latest":
        return base.parent
    if base.parent.name == "backtest":
        return base.parent
    return base


def _find_compare_json(root: Path, base_run: str) -> Path | None:
    direct = root / f"{base_run}-compare" / "comparison.json"
    if direct.exists():
        return direct

    # New layout: artifacts/backtest/<timestamp>/<base_run>-compare/comparison.json
    try:
        nested = [
            p
            for p in root.glob(f"*/{base_run}-compare/comparison.json")
            if p.is_file()
        ]
    except Exception:
        nested = []

    if not nested:
        return None
    nested.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return nested[0]


def _load_backtest_compare_snapshot(
    base_dir: Path = _BACKTEST_LATEST_DIR,
    *,
    run_state: BacktestRunStateSnapshot | None = None,
    current_run_id: str = "",
) -> BacktestCompareSnapshot:
    root = _resolve_backtest_root(Path(base_dir))
    candidate_ids: list[str] = []

    if run_state and run_state.mode == "compare_history_rule" and run_state.run_id != "--":
        candidate_ids.append(run_state.run_id)
    if current_run_id and current_run_id != "--":
        candidate_ids.append(current_run_id)
    if run_state and run_state.latest_run_id != "--":
        candidate_ids.append(run_state.latest_run_id)

    compare_json: Path | None = None
    for rid in candidate_ids:
        base_run = _normalize_compare_base_run_id(rid)
        if not base_run:
            continue
        candidate = _find_compare_json(root, base_run)
        if candidate is None:
            continue
        if candidate.exists():
            compare_json = candidate
            break

    if compare_json is None:
        return BacktestCompareSnapshot()

    try:
        payload = json.loads(compare_json.read_text(encoding="utf-8"))
    except Exception:
        return BacktestCompareSnapshot()

    if not isinstance(payload, dict):
        return BacktestCompareSnapshot()

    history_mix = payload.get("history_direction_mix") if isinstance(payload.get("history_direction_mix"), dict) else {}
    rule_mix = payload.get("rule_direction_mix") if isinstance(payload.get("rule_direction_mix"), dict) else {}
    rule_overlap = payload.get("rule_overlap") if isinstance(payload.get("rule_overlap"), dict) else {}

    missing_rule_reason = ""
    missing_diag = payload.get("missing_history_rules_diagnostics")
    if isinstance(missing_diag, list) and missing_diag:
        top = missing_diag[0]
        if isinstance(top, dict):
            key = str(top.get("key") or "--").strip() or "--"
            reason = str(top.get("primary_block_reason") or "unknown").strip() or "unknown"
            missing_rule_reason = f"{key}: {reason}"

    alignment_status = str(payload.get("alignment_status") or "--").strip().lower() or "--"
    alignment_risk_level = str(payload.get("alignment_risk_level") or "--").strip().lower() or "--"
    alignment_risk_summary = str(payload.get("alignment_risk_summary") or "").strip()
    alignment_warning_summary = ""
    alignment_warnings = payload.get("alignment_warnings") if isinstance(payload.get("alignment_warnings"), list) else []
    if alignment_warnings:
        top_warning = alignment_warnings[0]
        if isinstance(top_warning, dict):
            kind = str(top_warning.get("kind") or "warn").strip() or "warn"
            subject = str(top_warning.get("subject") or "--").strip() or "--"
            alignment_warning_summary = f"{kind}: {subject}"

    return BacktestCompareSnapshot(
        available=True,
        run_id=str(payload.get("run_id") or "--").strip() or "--",
        history_run_id=str(payload.get("history_run_id") or "--").strip() or "--",
        rule_run_id=str(payload.get("rule_run_id") or "--").strip() or "--",
        delta_return_pct=_coerce_float(payload.get("delta_return_pct")),
        delta_max_drawdown_pct=_coerce_float(payload.get("delta_max_drawdown_pct")),
        delta_trade_count=_coerce_int(payload.get("delta_trade_count")),
        delta_excess_return_pct=_coerce_float(payload.get("delta_excess_return_pct")),
        delta_signal_count=_coerce_int(payload.get("delta_signal_count")),
        history_buy_ratio_pct=_coerce_float(history_mix.get("buy_ratio_pct")),
        rule_buy_ratio_pct=_coerce_float(rule_mix.get("buy_ratio_pct")),
        delta_buy_ratio_pct=_coerce_float(payload.get("delta_buy_ratio_pct")),
        rule_history_types=_coerce_int(rule_overlap.get("history_rule_types")),
        rule_rule_types=_coerce_int(rule_overlap.get("rule_rule_types")),
        rule_shared_types=_coerce_int(rule_overlap.get("shared_rule_types")),
        rule_jaccard_pct=_coerce_float(rule_overlap.get("jaccard_pct")),
        alignment_score=_coerce_float(payload.get("alignment_score")),
        alignment_status=alignment_status,
        alignment_risk_level=alignment_risk_level,
        alignment_risk_summary=alignment_risk_summary,
        alignment_warning_count=len(alignment_warnings),
        alignment_warning_summary=alignment_warning_summary,
        signal_type_delta_top=_parse_compare_delta_rows(payload.get("signal_type_delta_top"), max_rows=3),
        missing_rule_reason=missing_rule_reason,
    )


def _extract_walk_forward_payload(base: Path, metrics_payload: dict) -> dict:
    summary_path = base / "walk_forward_summary.json"
    if summary_path.exists():
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            return {}

    nested = metrics_payload.get("walk_forward_summary")
    if isinstance(nested, dict):
        return nested
    return {}


def _apply_walk_forward_snapshot(
    snap: BacktestSnapshot,
    wf_payload: dict,
    *,
    initial_equity: float | None = None,
) -> None:
    if not isinstance(wf_payload, dict):
        return

    fold_count = _coerce_int(wf_payload.get("fold_count"))
    if fold_count is None or fold_count <= 0:
        return

    snap.is_walk_forward = True
    snap.wf_fold_count = fold_count
    snap.wf_positive_fold_rate_pct = _coerce_float(wf_payload.get("positive_fold_rate_pct"))
    snap.wf_history_fold_count = _coerce_int(wf_payload.get("history_fold_count"))
    snap.wf_replay_fold_count = _coerce_int(wf_payload.get("replay_fold_count"))
    snap.wf_fallback_fold_count = _coerce_int(wf_payload.get("fallback_fold_count"))

    avg_ret = _coerce_float(wf_payload.get("avg_return_pct"))
    avg_dd = _coerce_float(wf_payload.get("avg_max_drawdown_pct"))
    avg_excess = _coerce_float(wf_payload.get("avg_excess_return_pct"))
    if avg_ret is not None:
        snap.total_return_pct = avg_ret
    if avg_dd is not None:
        snap.max_drawdown_pct = avg_dd
    if avg_excess is not None:
        snap.excess_return_pct = avg_excess
    if snap.total_return_pct is not None and snap.excess_return_pct is not None:
        snap.buy_hold_return_pct = snap.total_return_pct - snap.excess_return_pct

    folds_raw = wf_payload.get("folds")
    folds = [item for item in folds_raw if isinstance(item, dict)] if isinstance(folds_raw, list) else []

    if folds:
        first_start = folds[0].get("test_start")
        last_end = folds[-1].get("test_end")
        if (snap.date_range == "--") and (first_start or last_end):
            snap.date_range = f"{_compact_backtest_date(first_start)} -> {_compact_backtest_date(last_end)}"

        if not snap.recent_trades:
            lines: list[str] = []
            for item in folds[-_BACKTEST_RECENT_TRADES:]:
                fold_idx = _coerce_int(item.get("fold"))
                fold_txt = "--" if fold_idx is None else f"F{fold_idx:02d}"
                mode_txt = str(item.get("mode") or "--").strip()[:7]
                ret_val = _coerce_float(item.get("total_return_pct"))
                dd_val = _coerce_float(item.get("max_drawdown_pct"))
                trade_val = _coerce_int(item.get("trade_count"))
                ret_txt = "--" if ret_val is None else f"{ret_val:+.2f}%"
                dd_txt = "--" if dd_val is None else f"{dd_val:.2f}%"
                trade_txt = "--" if trade_val is None else str(trade_val)
                ts_txt = _compact_backtest_date(item.get("test_end") or item.get("test_start"))
                lines.append(f"{ts_txt} {fold_txt:<4} {mode_txt:<7} ret={ret_txt} dd={dd_txt} n={trade_txt}")
            snap.recent_trades = lines

        if not snap.equity_points:
            initial = _coerce_float(initial_equity)
            if initial is None or initial <= 0:
                initial = 10_000.0

            curve: list[float] = [float(initial)]
            equity = float(initial)
            for item in folds:
                ret_val = _coerce_float(item.get("total_return_pct"))
                if ret_val is None:
                    continue
                equity *= 1.0 + ret_val / 100.0
                curve.append(float(equity))

            if len(curve) >= 2:
                snap.equity_points = _resample_series(curve, max_points=_BACKTEST_MAX_EQUITY_POINTS)


def _format_symbol_contrib_lines(
    rows: list[BacktestSymbolContribution],
    width: int,
) -> list[tuple[str, int]]:
    if not rows:
        return [("--", 0)]

    max_abs_pnl = max((abs(row.pnl_net) for row in rows if row.pnl_net is not None), default=0.0)
    bar_limit = max(1, min(10, max(1, width // 6)))
    utf = "utf" in (locale.getpreferredencoding(False) or "").lower()
    pos_char = "█" if utf else "+"
    neg_char = "█" if utf else "-"

    compact = width < 36
    medium = 36 <= width < 50

    out: list[tuple[str, int]] = []
    for row in rows:
        pnl_txt = "--" if row.pnl_net is None else f"{row.pnl_net:+.2f}"
        pnl_short = "--" if row.pnl_net is None else f"{row.pnl_net:+.0f}"
        trade_txt = "--" if row.trade_count is None else str(row.trade_count)
        win_txt = "--" if row.win_rate_pct is None else f"{row.win_rate_pct:.1f}%"
        hold_txt = "--" if row.avg_holding_minutes is None else f"{row.avg_holding_minutes:.1f}m"

        sign = 0
        bar = ""
        if row.pnl_net is not None and max_abs_pnl > 1e-9:
            sign = 1 if row.pnl_net >= 0 else -1
            bar_len = max(1, int(round(abs(row.pnl_net) / max_abs_pnl * bar_limit)))
            bar = (pos_char if sign > 0 else neg_char) * bar_len

        if compact:
            base = f"{row.symbol[:8]:<8} {pnl_short:>7}"
        elif medium:
            base = f"{row.symbol[:8]:<8} {pnl_txt:>9} n={trade_txt:>4}"
        else:
            base = f"{row.symbol:<8} {pnl_txt:>9} n={trade_txt:>4} w={win_txt:>6} h={hold_txt:>6}"

        if bar:
            space_left = max(0, width - len(base) - 1)
            if space_left > 0:
                bar = bar[:space_left]
                base = f"{base} {bar}"

        out.append((base, sign))

    return out


def _format_backtest_curve_summary(values: list[float]) -> str:
    if not values:
        return "净值: -- | 最高: -- | 最低: -- | 变化: -- | 均值: --"

    first = float(values[0])
    last = float(values[-1])
    highest = max(values)
    lowest = min(values)
    avg = sum(values) / max(1, len(values))

    if abs(first) <= 1e-9:
        delta_pct = 0.0
    else:
        delta_pct = (last - first) / abs(first) * 100.0

    arrow = "↗" if delta_pct >= 0 else "↘"
    return (
        f"净值: {last:.2f} | 最高: {highest:.2f} | 最低: {lowest:.2f} | "
        f"变化: {arrow} {delta_pct:+.2f}% | 均值: {avg:.2f}"
    )


def _format_backtest_trade_line(raw: str, width: int) -> str:
    line = (raw or "").strip()
    if not line or line == "--":
        return "--"

    parts = line.split()
    if len(parts) >= 4 and len(parts[0]) >= 10:
        day = parts[0][5:10]
        hhmm = parts[1][:5] if len(parts) >= 2 else "--:--"
        symbol = parts[2][:10] if len(parts) >= 3 else "--"
        side_raw = parts[3] if len(parts) >= 4 else "--"
        side = _display_side_cn(side_raw)[:5]

        pnl = "--"
        for item in parts[4:]:
            if item.startswith("pnl="):
                pnl = item.split("=", 1)[1]
                break

        compact = f"{day} {hhmm} {symbol:<10} {side:<5} pnl {pnl}"
        return _truncate(compact, max(0, width))

    return _truncate(line, max(0, width))


def _compute_drawdown_series(values: list[float]) -> list[float]:
    if not values:
        return []

    series: list[float] = []
    peak = float(values[0]) if abs(float(values[0])) > 1e-9 else 1.0
    for value in values:
        fv = float(value)
        if fv > peak:
            peak = fv
        if abs(peak) <= 1e-9:
            series.append(0.0)
        else:
            series.append((fv - peak) / abs(peak) * 100.0)
    return series


def _format_backtest_drawdown_summary(values: list[float]) -> str:
    series = _compute_drawdown_series(values)
    if not series:
        return "回撤: --"

    cur_dd = series[-1]
    max_dd = min(series)
    return f"回撤: 当前 {cur_dd:+.2f}% | 最大 {max_dd:+.2f}%"


def _draw_backtest_drawdown_strip(
    stdscr,
    values: list[float],
    colors: dict[str, int],
    x0: int,
    y: int,
    width: int,
) -> None:
    if width <= 14:
        return

    label = "回撤带"
    label_w = len(label) + 2
    spark_w = max(6, width - label_w - 12)
    if spark_w <= 4:
        return

    dd_series = _compute_drawdown_series(values)
    if not dd_series:
        _safe_addstr(stdscr, y, x0, _truncate(f"{label}: --", width), curses.color_pair(colors.get("SRC", 0)))
        return

    samples = _resample_series(dd_series, max_points=spark_w)
    max_abs = max((abs(v) for v in samples), default=0.0)
    max_abs = max(max_abs, 1e-9)

    utf = "utf" in (locale.getpreferredencoding(False) or "").lower()
    levels = "▁▂▃▄▅▆▇█" if utf else ".-:=+*#@"

    src_attr = curses.color_pair(colors.get("SRC", 0))
    dd_attr = curses.color_pair(colors.get("SELL", 0)) | curses.A_BOLD

    _safe_addstr(stdscr, y, x0, f"{label}:", src_attr)

    for idx, value in enumerate(samples):
        if value >= -1e-9:
            char = levels[0]
            attr = src_attr
        else:
            ratio = min(1.0, abs(value) / max_abs)
            level_idx = max(1, int(round(ratio * (len(levels) - 1))))
            char = levels[level_idx]
            attr = dd_attr
        _safe_addstr(stdscr, y, x0 + label_w + idx, char, attr)

    tail = f" {samples[-1]:+.2f}%"
    _safe_addstr(stdscr, y, x0 + label_w + spark_w, _truncate(tail, max(0, width - label_w - spark_w)), src_attr)


def _compact_backtest_date(raw: object) -> str:
    text = str(raw or "").strip().replace("T", " ").replace("Z", "")
    if not text:
        return "--"
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return text[:19]


def _parse_backtest_date(raw: object) -> datetime | None:
    text = str(raw or "").strip().replace("T", " ").replace("Z", "")
    if not text:
        return None
    candidates = [text]
    if len(text) >= 19:
        candidates.append(text[:19])
    if len(text) >= 10:
        candidates.append(text[:10])
    for item in dict.fromkeys(candidates):
        try:
            return datetime.fromisoformat(item)
        except Exception:
            continue
    return None


def _short_backtest_date(raw: object) -> str:
    compact = _compact_backtest_date(raw)
    if len(compact) >= 10 and compact[4] == "-" and compact[7] == "-":
        return compact[2:10]
    return compact


def _format_backtest_time_axis(date_range: str, width: int) -> str:
    w = max(0, int(width))
    if w <= 0:
        return ""

    start_raw = "--"
    end_raw = "--"
    if "->" in (date_range or ""):
        left, right = date_range.split("->", 1)
        start_raw = left.strip() or "--"
        end_raw = right.strip() or "--"
    elif date_range:
        start_raw = str(date_range).strip()
        end_raw = str(date_range).strip()

    start_label = _short_backtest_date(start_raw)
    end_label = _short_backtest_date(end_raw)

    mid_label = "--"
    start_dt = _parse_backtest_date(start_raw)
    end_dt = _parse_backtest_date(end_raw)
    if start_dt and end_dt and end_dt >= start_dt:
        mid_label = _short_backtest_date(start_dt + (end_dt - start_dt) / 2)

    if w < 24:
        base = f"{start_label} -> {end_label}"
        return _truncate(base, w)

    utf = "utf" in (locale.getpreferredencoding(False) or "").lower()
    tick = "┬" if utf else "|"

    chars = [" "] * w

    def _put(center_x: int, label: str) -> None:
        if not label:
            return
        x = max(0, min(w - len(label), int(center_x)))
        for i, ch in enumerate(label):
            idx = x + i
            if 0 <= idx < w:
                chars[idx] = ch

    tick_pos = [0, w // 2, w - 1]
    for pos in tick_pos:
        if 0 <= pos < w:
            chars[pos] = tick

    _put(0, start_label)
    _put(max(0, w // 2 - len(mid_label) // 2), mid_label)
    _put(max(0, w - len(end_label)), end_label)
    return "".join(chars)


def _backtest_state_status_text(status: str) -> str:
    mapping = {
        "idle": "空闲",
        "running": "运行中",
        "done": "已完成",
        "error": "异常",
        "unknown": "未知",
    }
    return mapping.get((status or "").strip().lower(), "未知")


def _backtest_state_stage_text(stage: str) -> str:
    mapping = {
        "idle": "空闲",
        "loading_signals": "读取信号",
        "loading_candles": "读取K线",
        "loading_indicator_tables": "读取规则表",
        "replaying_signals": "离线回放",
        "executing": "回测执行",
        "walk_forward": "滚动验证",
        "compare_modes": "模式对比",
        "writing": "写入产物",
        "retention": "更新latest",
        "done": "完成",
        "error": "异常",
    }
    return mapping.get((stage or "").strip().lower(), "未知")


def _load_backtest_run_state(path: Path = _BACKTEST_RUN_STATE_PATH) -> BacktestRunStateSnapshot:
    state_path = Path(path)
    if not state_path.exists():
        return BacktestRunStateSnapshot()

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return BacktestRunStateSnapshot(status="unknown", stage="unknown", message="run_state parse failed")

    if not isinstance(payload, dict):
        return BacktestRunStateSnapshot(status="unknown", stage="unknown", message="run_state invalid payload")

    status = str(payload.get("status") or "idle").strip().lower()
    if status not in {"idle", "running", "done", "error"}:
        status = "unknown"

    stage = str(payload.get("stage") or "idle").strip().lower() or "unknown"

    run_id = str(payload.get("run_id") or "--").strip() or "--"
    mode = str(payload.get("mode") or "--").strip() or "--"
    started_at = str(payload.get("started_at") or "").strip()
    updated_at = str(payload.get("updated_at") or "").strip()
    finished_at = str(payload.get("finished_at") or "").strip()
    latest_run_id = str(payload.get("latest_run_id") or "--").strip() or "--"
    message = str(payload.get("message") or "").strip()
    error = str(payload.get("error") or "").strip()

    return BacktestRunStateSnapshot(
        status=status,
        stage=stage,
        run_id=run_id,
        mode=mode,
        started_at=started_at,
        updated_at=updated_at,
        finished_at=finished_at,
        latest_run_id=latest_run_id,
        message=message,
        error=error,
    )


def _format_backtest_state_line(state: BacktestRunStateSnapshot, width: int) -> str:
    status_txt = _backtest_state_status_text(state.status)
    stage_txt = _backtest_state_stage_text(state.stage)

    run_txt = state.run_id if state.run_id != "--" else state.latest_run_id
    if not run_txt:
        run_txt = "--"

    updated_txt = _fmt_quote_ts(state.updated_at) if state.updated_at else "--"
    line = f"状态: {status_txt} | 阶段: {stage_txt} | run={run_txt} | 更新: {updated_txt}"

    if state.status == "error" and state.error:
        line = f"{line} | err={state.error}"
    elif state.message:
        # Keep the backtest page focused on RULE by default; compare-mode message
        # contains both history + rule returns and can confuse users.
        if (not _BACKTEST_SHOW_COMPARE) and state.mode == "compare_history_rule":
            line = f"{line} | compare done"
        else:
            line = f"{line} | {state.message}"

    return _truncate(line, width)



def _load_backtest_snapshot(base_dir: Path = _BACKTEST_LATEST_DIR) -> BacktestSnapshot:
    base = Path(base_dir)
    metrics_path = base / "metrics.json"
    equity_path = base / "equity_curve.csv"
    trades_path = base / "trades.csv"
    input_quality_path = base / "input_quality.json"
    stability_path = base / "stability_report.json"
    wf_summary_path = base / "walk_forward_summary.json"

    snap = BacktestSnapshot()
    snap.equity_points = _load_equity_curve(equity_path, max_points=_BACKTEST_MAX_EQUITY_POINTS)
    snap.recent_trades = _load_recent_trades(trades_path, max_rows=_BACKTEST_RECENT_TRADES)

    if not metrics_path.exists() and not snap.equity_points and not snap.recent_trades and not wf_summary_path.exists():
        snap.status = "no backtest artifacts yet"
        return snap

    payload: dict = {}
    if metrics_path.exists():
        try:
            payload = json.loads(metrics_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}
            snap.status = "metrics.json parse failed"

    run_id = _extract_metric(payload, ("run_id", "runId", "id"))
    if run_id is not None and str(run_id).strip():
        snap.run_id = str(run_id).strip()

    mode = _extract_metric(payload, ("mode", "run_mode"))
    if mode is not None and str(mode).strip():
        snap.mode = str(mode).strip()

    start = _extract_metric(payload, ("start", "date_start", "start_ts", "from"))
    end = _extract_metric(payload, ("end", "date_end", "end_ts", "to"))
    if start or end:
        snap.date_range = f"{_compact_backtest_date(start)} -> {_compact_backtest_date(end)}"

    # New artifacts use *_pct fields directly. Legacy fields such as "total_return"
    # and "max_drawdown" may be fractional ratios (0.123 -> 12.3%).
    snap.total_return_pct = _coerce_float(_extract_metric(payload, ("total_return_pct", "return_pct")))
    if snap.total_return_pct is None:
        snap.total_return_pct = _coerce_pct(_extract_metric(payload, ("total_return", "pnl_pct", "roi")))

    snap.max_drawdown_pct = _coerce_float(_extract_metric(payload, ("max_drawdown_pct", "mdd_pct")))
    if snap.max_drawdown_pct is None:
        snap.max_drawdown_pct = _coerce_pct(_extract_metric(payload, ("max_drawdown", "mdd")))

    snap.sharpe = _coerce_float(_extract_metric(payload, ("sharpe", "sharpe_ratio")))
    snap.win_rate_pct = _coerce_float(_extract_metric(payload, ("win_rate_pct",)))
    if snap.win_rate_pct is None:
        snap.win_rate_pct = _coerce_pct(_extract_metric(payload, ("win_rate", "hit_rate")))
    snap.trade_count = _coerce_int(_extract_metric(payload, ("trade_count", "total_trades", "trades", "n_trades")))
    snap.avg_holding_minutes = _coerce_float(
        _extract_metric(payload, ("avg_holding_minutes", "avg_hold_minutes", "avg_holding_mins"))
    )
    snap.buy_hold_return_pct = _coerce_float(
        _extract_metric(payload, ("buy_hold_return_pct", "buyhold_return_pct", "benchmark_return_pct"))
    )
    snap.excess_return_pct = _coerce_float(
        _extract_metric(payload, ("excess_return_pct", "alpha_return_pct", "strategy_minus_buy_hold_pct"))
    )
    strategy_label = _extract_metric(payload, ("strategy_label", "strategy", "profile"))
    if strategy_label is not None and str(strategy_label).strip():
        snap.strategy_label = str(strategy_label).strip()
    strategy_summary = _extract_metric(payload, ("strategy_summary",))
    if strategy_summary is not None and str(strategy_summary).strip():
        snap.strategy_summary = str(strategy_summary).strip()
    snap.symbol_contributions = _load_symbol_contributions(payload)

    if input_quality_path.exists():
        try:
            quality_payload = json.loads(input_quality_path.read_text(encoding="utf-8"))
        except Exception:
            quality_payload = {}
        if isinstance(quality_payload, dict):
            snap.quality_score = _coerce_float(quality_payload.get("quality_score"))
            snap.quality_status = str(quality_payload.get("quality_status") or "--").strip().lower() or "--"
            coverage = _coerce_float(quality_payload.get("candle_coverage_pct"))
            gaps = _coerce_int(quality_payload.get("gap_count"))
            no_next_open = _coerce_int(quality_payload.get("no_next_open_bucket_count"))
            dropped = _coerce_int(quality_payload.get("dropped_signal_count"))
            parts = []
            if coverage is not None:
                parts.append(f"coverage={coverage:.1f}%")
            if gaps is not None:
                parts.append(f"gaps={gaps}")
            if no_next_open is not None:
                parts.append(f"no_next_open={no_next_open}")
            if dropped is not None:
                parts.append(f"dropped={dropped}")
            snap.quality_summary = " | ".join(parts)

    if stability_path.exists():
        try:
            stability_payload = json.loads(stability_path.read_text(encoding="utf-8"))
        except Exception:
            stability_payload = {}
        if isinstance(stability_payload, dict):
            snap.stability_status = str(stability_payload.get("stability_status") or "--").strip().lower() or "--"
            snap.stability_summary = str(stability_payload.get("stability_summary") or "").strip()
            snap.stability_comparable_run_count = int(stability_payload.get("comparable_run_count") or 0)

    wf_payload = _extract_walk_forward_payload(base, payload)
    _apply_walk_forward_snapshot(
        snap,
        wf_payload,
        initial_equity=_extract_metric(payload, ("initial_equity",)),
    )

    if snap.trade_count is None and snap.recent_trades:
        snap.trade_count = len(snap.recent_trades)

    snap.available = bool(metrics_path.exists() or snap.equity_points or snap.recent_trades or bool(wf_payload))
    if snap.available and snap.status == "no backtest artifacts":
        snap.status = "ok"
    elif snap.available and snap.status == "no backtest artifacts yet":
        snap.status = "partial"

    return snap



# === _draw_backtest_curve ===

def _draw_backtest_curve(
    stdscr,
    values: list[float],
    colors: dict[str, int],
    x0: int,
    y0: int,
    width: int,
    height: int,
) -> None:
    if width <= 14 or height <= 6 or len(values) < 2:
        return

    label_w = 10
    if width <= label_w + 6:
        label_w = max(7, width - 6)
    if width <= label_w + 3:
        return

    chart_x0 = x0 + label_w
    chart_w = max(3, width - label_w)

    samples = _resample_series(values, max_points=chart_w)
    if len(samples) < 2:
        return

    low = min(samples)
    high = max(samples)
    span0 = high - low

    # Avoid over-amplifying tiny returns: keep the y-range at least +/-1% around the initial equity.
    # Otherwise a -0.5% move can look like a "crash" because we stretch min/max to the full chart height.
    baseline = float(values[0]) if values else float(samples[0])
    min_span = max(1e-9, abs(baseline) * 0.02)  # >=2% span around baseline
    if span0 < min_span:
        low = min(low, baseline - min_span / 2.0)
        high = max(high, baseline + min_span / 2.0)
        span0 = high - low

    pad = max(1e-9, abs(high) * 0.001, span0 * 0.04)
    low -= pad
    high += pad
    span = max(1e-9, high - low)

    def _to_y(value: float) -> int:
        ratio = (high - value) / span
        y = y0 + int(round(ratio * max(1, height - 1)))
        return max(y0, min(y0 + height - 1, y))

    utf = "utf" in (locale.getpreferredencoding(False) or "").lower()
    guide_char = "┈" if utf else "."
    up_char = "╱" if utf else "/"
    down_char = "╲" if utf else "\\"
    flat_char = "─" if utf else "-"
    point_char = "●" if utf else "*"
    join_char = "│" if utf else "|"

    buy_attr = curses.color_pair(colors.get("BUY", 0)) | curses.A_BOLD
    sell_attr = curses.color_pair(colors.get("SELL", 0)) | curses.A_BOLD
    neutral_attr = curses.color_pair(colors.get("SRC", 0))

    tick_rows = sorted({y0, y0 + (height - 1) // 3, y0 + ((height - 1) * 2) // 3, y0 + height - 1})
    for gy in tick_rows:
        rel = (gy - y0) / max(1, height - 1)
        val = high - span * rel
        _safe_addstr(stdscr, gy, x0, _truncate(f"{val:>9.2f}", label_w), neutral_attr)
        _safe_addstr(stdscr, gy, chart_x0, guide_char * chart_w, neutral_attr)

    prev_y: int | None = None
    for i, value in enumerate(samples):
        x = chart_x0 + i
        y = _to_y(value)
        if prev_y is not None:
            prev_value = samples[i - 1]
            attr = buy_attr if value >= prev_value else sell_attr
            if y == prev_y:
                _safe_addstr(stdscr, y, x - 1, flat_char, attr)
            else:
                _safe_addstr(stdscr, prev_y, x - 1, up_char if y < prev_y else down_char, attr)
                step = 1 if y > prev_y else -1
                for yy in range(prev_y + step, y, step):
                    _safe_addstr(stdscr, yy, x - 1, join_char, attr)
            _safe_addstr(stdscr, y, x, point_char, attr)
        else:
            _safe_addstr(stdscr, y, x, point_char, neutral_attr)
        prev_y = y



# === _draw_market_backtest ===

def _draw_market_backtest(stdscr, colors: dict[str, int], w: int, h: int) -> None:
    snap = _load_backtest_snapshot()
    run_state = _load_backtest_run_state()
    compare_snap = BacktestCompareSnapshot()
    if _BACKTEST_SHOW_COMPARE:
        compare_snap = _load_backtest_compare_snapshot(
            _BACKTEST_LATEST_DIR,
            run_state=run_state,
            current_run_id=snap.run_id,
        )

    _safe_addstr(stdscr, 1, 0, _truncate("回测看板[只读]: latest目录产物展示", w))
    resolved_latest = _BACKTEST_LATEST_DIR
    try:
        resolved_latest = _BACKTEST_LATEST_DIR.resolve()
    except Exception:
        resolved_latest = _BACKTEST_LATEST_DIR
    if resolved_latest != _BACKTEST_LATEST_DIR:
        path_line = f"路径: {_BACKTEST_LATEST_DIR} -> {resolved_latest}"
    else:
        path_line = f"路径: {_BACKTEST_LATEST_DIR}"
    _safe_addstr(stdscr, 2, 0, _truncate(path_line, w), curses.color_pair(colors.get("SRC", 0)))

    state_attr = curses.color_pair(colors.get("SRC", 0))
    if run_state.status == "done":
        state_attr = curses.color_pair(colors.get("BUY", 0)) | curses.A_BOLD
    elif run_state.status == "error":
        state_attr = curses.color_pair(colors.get("SELL", 0)) | curses.A_BOLD
    _safe_addstr(stdscr, 3, 0, _format_backtest_state_line(run_state, w), state_attr)

    panel_top = 4
    panel_h = max(0, h - panel_top - 1)
    if panel_h < 12:
        _safe_addstr(stdscr, h - 1, 0, _truncate("回测页: 终端高度不足（建议>=26行）", w))
        return

    # Readability-first split: keep right metrics area larger than before.
    split_x = max(40, int(w * 0.55))
    if split_x >= w - 34:
        split_x = max(24, w - 34)

    left_w = max(24, split_x)
    right_x = min(w - 1, split_x + 1)
    right_w = max(16, w - right_x)

    box_attr = curses.color_pair(colors.get("SRC", 0))
    _draw_box(stdscr, 0, panel_top, left_w, panel_h, box_attr)
    _draw_box(stdscr, right_x, panel_top, right_w, panel_h, box_attr)

    left_inner_w = max(0, left_w - 2)
    right_inner_w = max(0, right_w - 2)

    run_title = f"权益曲线 | run={snap.run_id}"
    if snap.is_walk_forward:
        run_title = f"Walk-Forward | run={snap.run_id}"
    _safe_addstr(stdscr, panel_top, 2, _truncate(run_title, max(0, left_w - 4)), curses.A_UNDERLINE)

    left_body_top = panel_top + 1
    left_bottom = panel_top + panel_h - 2

    _safe_addstr(
        stdscr,
        left_body_top,
        1,
        _truncate(f"区间: {snap.date_range}", left_inner_w),
        curses.color_pair(colors.get("SRC", 0)),
    )
    chart_desc = "主图: 权益折线（下方回撤带用于判断风险阶段）"
    if snap.is_walk_forward:
        chart_desc = "主图: Walk-Forward 累计折线（每点代表一折）"
    _safe_addstr(
        stdscr,
        left_body_top + 1,
        1,
        _truncate(chart_desc, left_inner_w),
        curses.color_pair(colors.get("SRC", 0)),
    )

    summary_y = left_bottom
    drawdown_y: int | None = left_bottom - 1
    divider_y = left_bottom - 2
    chart_y = left_body_top + 2
    chart_h = divider_y - chart_y + 1

    if chart_h < 6:
        drawdown_y = None
        divider_y = left_bottom - 1
        chart_h = divider_y - chart_y + 1

    if chart_h < 3:
        chart_y = left_body_top + 1
        divider_y = None
        drawdown_y = None
        chart_h = max(1, left_bottom - chart_y)

    if not snap.available:
        if run_state.status == "running":
            missing_lines = [
                "回测正在运行，等待产物输出...",
                f"阶段: {_backtest_state_stage_text(run_state.stage)}",
                f"run: {run_state.run_id}",
                "可稍后按 r 刷新",
            ]
        elif run_state.status == "error":
            missing_lines = [
                "回测失败，暂无可读产物",
                f"阶段: {_backtest_state_stage_text(run_state.stage)}",
                f"错误: {run_state.error or '--'}",
                "修复后重试: ./scripts/backtest.sh",
            ]
        else:
            missing_lines = [
                "暂无回测结果",
                "先运行 signal-service 回测脚本",
                "需要文件: metrics.json/equity_curve.csv/trades.csv",
                "执行: ./scripts/backtest.sh",
            ]

        max_rows = max(1, chart_h)
        for i, line in enumerate(missing_lines[:max_rows]):
            _safe_addstr(
                stdscr,
                chart_y + i,
                1,
                _truncate(line, left_inner_w),
                curses.color_pair(colors.get("SRC", 0)),
            )
    else:
        _draw_backtest_curve(stdscr, snap.equity_points, colors, 1, chart_y, left_inner_w, chart_h)

    if divider_y is not None and divider_y >= chart_y:
        axis = _format_backtest_time_axis(snap.date_range, left_inner_w)
        _safe_addstr(stdscr, divider_y, 1, _truncate(axis, left_inner_w), curses.color_pair(colors.get("SRC", 0)))
    if drawdown_y is not None and drawdown_y < summary_y:
        _draw_backtest_drawdown_strip(stdscr, snap.equity_points, colors, 1, drawdown_y, left_inner_w)

    summary_line = _format_backtest_curve_summary(snap.equity_points)
    _safe_addstr(stdscr, summary_y, 1, _truncate(summary_line, left_inner_w), curses.color_pair(colors.get("SRC", 0)))

    def _fmt_pct(value: float | None, *, signed: bool = False) -> str:
        if value is None:
            return "--"
        return f"{value:+.2f}%" if signed else f"{value:.2f}%"

    def _fmt_num(value: float | None) -> str:
        return "--" if value is None else f"{value:.2f}"

    def _fmt_int(value: int | None) -> str:
        return "--" if value is None else str(value)

    def _fmt_delta_int(value: int | None) -> str:
        return "--" if value is None else f"{value:+d}"

    def _interpret_text() -> str:
        if snap.is_walk_forward:
            if (snap.wf_fold_count or 0) <= 0:
                return "解读: Walk-Forward 折数不足，先检查窗口配置"
            if snap.total_return_pct is None or snap.max_drawdown_pct is None:
                return "解读: 折均指标不足，先补齐完整窗口"
            if (snap.excess_return_pct or 0.0) >= 0 and snap.max_drawdown_pct <= 5:
                return "解读: 折均超额为正且回撤可控，可进入参数稳健性验证"
            if snap.total_return_pct < 0 and snap.max_drawdown_pct >= 15:
                return "解读: 折均收益偏弱且回撤偏大，建议提高阈值并降频"
            return "解读: 当前是折均结果，建议结合下方各折明细再决策"

        if snap.total_return_pct is None or snap.max_drawdown_pct is None:
            return "解读: 数据不足，先补齐一轮完整回测"
        if snap.total_return_pct < 0 and snap.max_drawdown_pct >= 20:
            return "解读: 当前处于亏损+深回撤阶段，建议先降频再调参"
        if snap.total_return_pct >= 0 and snap.max_drawdown_pct <= 15:
            return "解读: 收益/回撤均可接受，可继续做稳健性验证"
        return "解读: 收益与风险不匹配，重点看币种贡献与交易明细"

    status_map = {
        "ok": "正常",
        "partial": "部分可用",
        "metrics.json parse failed": "metrics.json 解析失败",
        "no backtest artifacts": "暂无回测产物",
        "no backtest artifacts yet": "暂无回测产物",
    }
    status_text = status_map.get(snap.status, snap.status)

    run_status_txt = _backtest_state_status_text(run_state.status)
    run_stage_txt = _backtest_state_stage_text(run_state.stage)
    run_status_attr = curses.color_pair(colors.get("SRC", 0))
    if run_state.status == "done":
        run_status_attr = curses.color_pair(colors.get("BUY", 0)) | curses.A_BOLD
    elif run_state.status == "error":
        run_status_attr = curses.color_pair(colors.get("SELL", 0)) | curses.A_BOLD

    row = panel_top
    max_row = panel_top + panel_h - 1

    def _section(title: str) -> bool:
        nonlocal row
        if row >= max_row:
            return False
        _safe_addstr(stdscr, row, right_x + 2, _truncate(title, max(0, right_w - 4)), curses.A_UNDERLINE)
        row += 1
        return row < max_row

    def _line(text: str, attr: int = 0) -> bool:
        nonlocal row
        if row >= max_row:
            return False
        _safe_addstr(stdscr, row, right_x + 1, _truncate(text, right_inner_w), attr)
        row += 1
        return row < max_row

    _section("核心指标")
    _line(f"运行状态: {run_status_txt} | 阶段: {run_stage_txt}", run_status_attr)
    if run_state.run_id != "--":
        _line(f"当前run: {run_state.run_id}")
    if snap.mode != "--":
        _line(f"产物模式: {_backtest_mode_text(snap.mode)}")
    if snap.strategy_label != "--":
        _line(f"策略: {snap.strategy_label}")
    if snap.strategy_summary:
        _line(f"策略参数: {snap.strategy_summary}")
    if _BACKTEST_SHOW_COMPARE and run_state.mode != "--" and run_state.mode != snap.mode:
        _line(f"命令模式: {_backtest_mode_text(run_state.mode)}")
    _line(f"产物状态: {status_text}")
    _line(f"收益率: {_fmt_pct(snap.total_return_pct, signed=True)} | 最大回撤: {_fmt_pct(snap.max_drawdown_pct)}")
    _line(f"夏普: {_fmt_num(snap.sharpe)} | 胜率: {_fmt_pct(snap.win_rate_pct)}")
    trade_count_txt = "--" if snap.trade_count is None else str(snap.trade_count)
    avg_hold_txt = "--" if snap.avg_holding_minutes is None else f"{snap.avg_holding_minutes:.2f}m"
    _line(f"交易数: {trade_count_txt} | 平均持仓: {avg_hold_txt}")
    _line(
        f"基准(BH): {_fmt_pct(snap.buy_hold_return_pct, signed=True)} | 超额: {_fmt_pct(snap.excess_return_pct, signed=True)}"
    )
    if snap.quality_score is not None or snap.quality_status != "--":
        _line(
            f"质量分: {_fmt_num(snap.quality_score)} | 质量状态: {(snap.quality_status or '--').upper()}"
        )
        if snap.quality_summary:
            _line(f"质量摘要: {snap.quality_summary}")
    if snap.stability_status != "--":
        _line(
            f"稳定性: {(snap.stability_status or '--').upper()} | 可比run: {snap.stability_comparable_run_count}"
        )
        if snap.stability_summary:
            _line(f"稳定性摘要: {snap.stability_summary}")
    if snap.is_walk_forward:
        fold_txt = "--" if snap.wf_fold_count is None else str(snap.wf_fold_count)
        pos_txt = _fmt_pct(snap.wf_positive_fold_rate_pct)
        hist_txt = "--" if snap.wf_history_fold_count is None else str(snap.wf_history_fold_count)
        replay_txt = "--" if snap.wf_replay_fold_count is None else str(snap.wf_replay_fold_count)
        fallback_txt = "--" if snap.wf_fallback_fold_count is None else str(snap.wf_fallback_fold_count)
        _line(f"WF折数: {fold_txt} | 正收益折比: {pos_txt}")
        _line(f"WF来源: history={hist_txt} replay={replay_txt} fallback={fallback_txt}")

    if run_state.status == "error" and run_state.error and row < max_row:
        _line(f"错误: {run_state.error}", curses.color_pair(colors.get("SELL", 0)) | curses.A_BOLD)
    elif run_state.message and row < max_row:
        msg = run_state.message
        if (not _BACKTEST_SHOW_COMPARE) and run_state.mode == "compare_history_rule":
            msg = "compare done"
        _line(f"消息: {msg}", curses.color_pair(colors.get("SRC", 0)))

    if row < max_row:
        _safe_hline(stdscr, row, right_x + 1, right_inner_w, box_attr)
        row += 1

    _section("风险解读")
    _line(_format_backtest_drawdown_summary(snap.equity_points))
    _line(_interpret_text(), curses.color_pair(colors.get("SRC", 0)))
    if snap.quality_status in {"warn", "fail"} and row < max_row:
        _line(
            "检查建议: ./scripts/backtest.sh --check-only",
            curses.color_pair(colors.get("ALERT", 0)),
        )
    if snap.stability_status in {"warn", "critical"} and row < max_row:
        _line(
            "稳定性建议: ./scripts/backtest.sh --walk-forward --walk-forward-max-folds 6",
            curses.color_pair(colors.get("ALERT", 0)),
        )
    if compare_snap.available and compare_snap.alignment_risk_level in {"high", "critical"} and row < max_row:
        _line(
            "对齐建议: ./scripts/backtest.sh --mode compare_history_rule --alignment-min-score 70 --alignment-max-risk-level medium",
            curses.color_pair(colors.get("ALERT", 0)),
        )

    if row < max_row:
        _safe_hline(stdscr, row, right_x + 1, right_inner_w, box_attr)
        row += 1

    if compare_snap.available and (not snap.is_walk_forward):
        _section("模式对比（history vs rule）")
        _line(f"对比run: {compare_snap.run_id}")
        status_text = (compare_snap.alignment_status or "--").upper()
        status_attr = curses.color_pair(colors.get("SRC", 0))
        if status_text == "PASS":
            status_attr = curses.color_pair(colors.get("BUY", 0))
        elif status_text == "FAIL":
            status_attr = curses.color_pair(colors.get("SELL", 0)) | curses.A_BOLD
        elif status_text == "WARN":
            status_attr = curses.color_pair(colors.get("ALERT", 0))
        risk_text = (compare_snap.alignment_risk_level or "--").upper()
        _line(
            f"对齐分: {_fmt_num(compare_snap.alignment_score)} / 100 | 状态: {status_text} | "
            f"风险: {risk_text} | 告警: {compare_snap.alignment_warning_count}",
            status_attr,
        )
        if compare_snap.alignment_risk_summary:
            _line(f"风险说明: {compare_snap.alignment_risk_summary}")
        _line(
            f"规则重合: {_fmt_int(compare_snap.rule_shared_types)}/"
            f"{_fmt_int(compare_snap.rule_history_types)}/"
            f"{_fmt_int(compare_snap.rule_rule_types)} | "
            f"Jaccard: {_fmt_pct(compare_snap.rule_jaccard_pct)}"
        )
        _line(
            f"收益差: {_fmt_pct(compare_snap.delta_return_pct, signed=True)} | "
            f"信号差: {_fmt_delta_int(compare_snap.delta_signal_count)}"
        )
        _line(
            f"交易差: {_fmt_delta_int(compare_snap.delta_trade_count)} | "
            f"超额差: {_fmt_pct(compare_snap.delta_excess_return_pct, signed=True)}"
        )
        _line(f"买入占比差: {_fmt_pct(compare_snap.delta_buy_ratio_pct, signed=True)}")
        if compare_snap.alignment_warning_summary and row < max_row:
            _line(f"主告警: {compare_snap.alignment_warning_summary}")
        if compare_snap.missing_rule_reason and row < max_row:
            _line(f"缺失主因: {compare_snap.missing_rule_reason}")
        if compare_snap.signal_type_delta_top and row < max_row:
            _line("命中差异前列:")
            for item in compare_snap.signal_type_delta_top:
                if row >= max_row:
                    break
                _line(
                    f"- {item.key} {item.history_count}->{item.rule_count} "
                    f"({item.delta:+d})"
                )

        if row < max_row:
            _safe_hline(stdscr, row, right_x + 1, right_inner_w, box_attr)
            row += 1

    contrib_title = "币种贡献（红盈绿亏）" if not snap.is_walk_forward else "Walk-Forward统计"
    _section(contrib_title)
    if snap.is_walk_forward:
        hist_txt = "--" if snap.wf_history_fold_count is None else str(snap.wf_history_fold_count)
        replay_txt = "--" if snap.wf_replay_fold_count is None else str(snap.wf_replay_fold_count)
        fallback_txt = "--" if snap.wf_fallback_fold_count is None else str(snap.wf_fallback_fold_count)
        _line(f"history折: {hist_txt} | replay折: {replay_txt}")
        _line(f"fallback折: {fallback_txt}")
    else:
        contrib_lines = _format_symbol_contrib_lines(snap.symbol_contributions, right_inner_w)
        for line, sign in contrib_lines:
            if row >= max_row:
                break
            attr = 0
            if sign > 0:
                attr = curses.color_pair(colors.get("BUY", 0)) | curses.A_BOLD
            elif sign < 0:
                attr = curses.color_pair(colors.get("SELL", 0)) | curses.A_BOLD
            _line(line, attr)

    if row < max_row:
        _safe_hline(stdscr, row, right_x + 1, right_inner_w, box_attr)
        row += 1

    trade_section_title = "最近平仓" if not snap.is_walk_forward else "最近折结果"
    _section(trade_section_title)
    trade_lines = snap.recent_trades or ["--"]
    for raw in trade_lines:
        if row >= max_row:
            break
        if snap.is_walk_forward:
            _line(_truncate(raw, right_inner_w))
        else:
            _line(_format_backtest_trade_line(raw, right_inner_w))

    if row < max_row:
        hint = "提示: 读图顺序=收益/回撤 -> 币种贡献 -> 最近交易"
        if compare_snap.available and (not snap.is_walk_forward):
            hint = "提示: 读图顺序=收益/回撤 -> 模式对比 -> 币种贡献"
        if snap.is_walk_forward:
            hint = "提示: 读图顺序=折均指标 -> 折来源 -> 最近折结果"
        _line(hint, curses.color_pair(colors.get("SRC", 0)))

    footer = "回测页: q退出 | t主页面切换 | 1美股 | 2A股 | 3加密 | 4返回主页面 | 5基金 | 6港股 | 7资讯 | r刷新"
    _safe_addstr(stdscr, h - 1, 0, _truncate(footer, w))


