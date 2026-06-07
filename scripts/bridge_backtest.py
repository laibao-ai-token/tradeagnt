#!/usr/bin/env python3
"""Bridge: run a `tradecat backtest` and return a JSON summary.

Spawns the tradecat backtest subcommand, parses its stdout for signal/PnL
metrics, and returns a structured payload in the standard
``tradecat_get_*`` bridge envelope:

    {"ok", "tool", "ts", "request", "data", "error"}

The CLI itself (``tradecat backtest``) is the existing single-source
implementation; this bridge only orchestrates it and normalises output.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence


TOOL_NAME = "bridge_backtest"
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[1]

# `tradecat` console_script is the canonical entry; resolve to venv first.
_TRADECAT_CANDIDATES = (
    REPO_ROOT / ".venv" / "bin" / "tradecat",
    REPO_ROOT / ".venv" / "bin" / "python",
)


DEFAULT_TIMEOUT_S = 90.0
MAX_OUTPUT_BYTES = 8 * 1024 * 1024  # 8 MB

MARKET_ALIASES = {
    "us": "us_stock",
    "us_stock": "us_stock",
    "hk": "hk_stock",
    "hk_stock": "hk_stock",
    "cn": "cn_stock",
    "cn_stock": "cn_stock",
    "crypto": "crypto_spot",
    "crypto_spot": "crypto_spot",
    "metals": "metals",
}


class CliError(RuntimeError):
    """Structured command error."""

    def __init__(self, code: str, message: str, *, details: Optional[dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ParserExit(RuntimeError):
    """Raised when argparse wants to terminate."""

    def __init__(self, status: int, message: Optional[str] = None) -> None:
        super().__init__(message or "")
        self.status = int(status)
        self.message = message or ""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # noqa: D401
        raise CliError("invalid_arguments", message)

    def exit(self, status: int = 0, message: Optional[str] = None) -> None:
        if status == 0:
            raise ParserExit(status=status, message=message)
        raise CliError(
            "invalid_arguments",
            (message or "").strip() or f"argument parsing failed (status={status})",
        )


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _error_payload(code: str, message: str, *, details: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return {
        "code": str(code),
        "message": str(message),
        "details": details or None,
    }


def _base_response() -> dict[str, Any]:
    return {
        "ok": False,
        "tool": TOOL_NAME,
        "ts": _utc_now_iso(),
        "source": {
            "kind": "tradecat_cli_subprocess",
            "script": "scripts/bridge_backtest.py",
            "driver": "tradecat backtest",
            "writes": False,
        },
        "request": {},
        "summary": {
            "signals_total": None,
            "signals_buy": None,
            "signals_sell": None,
            "signals_strong": None,
            "paper_trade_count": None,
        },
        "data": None,
        "error": None,
    }


def _resolve_tradecat_bin() -> str:
    for candidate in _TRADECAT_CANDIDATES:
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return "tradecat"


def _resolve_market(raw_market: str) -> Optional[str]:
    if not raw_market:
        return None
    market = MARKET_ALIASES.get(str(raw_market).strip().lower(), "")
    return market or None


def _build_parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(
        description="Bridge: run `tradecat backtest` and return a JSON summary.",
    )
    parser.add_argument("--strategy", required=True, help="Strategy YAML path (relative to repo root or absolute).")
    parser.add_argument("--symbol", required=True, help="Symbol, e.g. BTC_USDT or NVDA.")
    parser.add_argument(
        "--market",
        default="",
        help="Optional market hint (crypto/us_stock/...). Forwarded to provider selection when useful.",
    )
    parser.add_argument("--timeframe", default="", help="Optional timeframe override (e.g. 5m, 1h).")
    parser.add_argument("--provider", default="", help="Optional provider override.")
    parser.add_argument("--days", type=int, default=3, help="Backtest lookback days (default 3).")
    parser.add_argument("--min-strength", type=int, default=50, help="Min signal strength (default 50).")
    parser.add_argument(
        "--initial-equity",
        type=float,
        default=None,
        help="Optional initial cash; forwarded to `--initial-cash`.",
    )
    parser.add_argument("--notional", type=float, default=None, help="Optional per-trade notional.")
    parser.add_argument("--mode", default="scan", help="Backtest mode: runner/scan/dry (default scan).")
    parser.add_argument(
        "--no-paper",
        action="store_true",
        help="Skip paper PnL simulation (default: paper enabled).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help=f"Subprocess timeout in seconds (default {DEFAULT_TIMEOUT_S}).",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    return parser


# ----------------------------- stdout parsing ------------------------------ #


_NUM = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
_INT = r"-?\d+"

# Backtest header line:  "Backtest [crypto]: BTC_USDT @ 5m"
_RE_HEADER = re.compile(r"^Backtest\s+\[([^\]]+)\]:\s*(\S+)\s+@\s*(\S+)\s*$")

# "Provider: gate | Fetching up to 234 bars (~3d)..."
_RE_PROVIDER = re.compile(
    r"^Provider:\s*(\S+)\s*\|\s*Fetching\s+up\s+to\s+(\d+)\s+bars.*?~\s*(\d+)\s*d\b",
    re.IGNORECASE,
)
_RE_LOADED = re.compile(r"^Loaded\s+(\d+)\s+rows\s*$", re.IGNORECASE)

# "  Total signals:       8"
_RE_TOTAL = re.compile(rf"^Total\s+signals:\s+({_INT})\s*$", re.IGNORECASE)
_RE_BUY_SELL = re.compile(
    rf"^BUY:\s+({_INT})\s*\|\s*SELL:\s+({_INT})\s*$",
    re.IGNORECASE,
)
_RE_STRONG = re.compile(
    rf"^Strength\s*>=\s*({_INT}):\s*({_INT})\s*$",
    re.IGNORECASE,
)
# "  [BUY] RSI超卖反弹买入 (str=62) | RSI超卖反弹: 39.0"
_RE_SIGNAL_LINE = re.compile(
    r"^\s*\[(BUY|SELL)\]\s+(.+?)\s+\(str\s*=\s*(\d+)\)\s*\|\s*(.+?)\s*$"
)

# "  Trades:        1"
_RE_PAPER_TRADES = re.compile(rf"^Trades:\s+({_INT})\s*$", re.IGNORECASE)
_RE_PAPER_PNL = re.compile(rf"^Realized\s+PnL:\s+({_NUM})\s*$", re.IGNORECASE)
_RE_PAPER_NAV = re.compile(rf"^NAV:\s+({_NUM})\s*$", re.IGNORECASE)
_RE_PAPER_RETURN = re.compile(rf"^Return:\s+({_NUM})\s*%\s*$", re.IGNORECASE)
_RE_PAPER_NOTIONAL = re.compile(
    rf"\(notional\s*=\s*({_NUM})\s+(\S+)\s+per\s+trade\)",
    re.IGNORECASE,
)


def _safe_float(text: str) -> Optional[float]:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _safe_int(text: str) -> Optional[int]:
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _parse_backtest_stdout(stdout: str) -> dict[str, Any]:
    """Parse the human-readable `tradecat backtest` stdout into structured fields.

    Best-effort: missing sections simply leave ``None``/empty. Does not raise
    on regex miss — caller decides ok/error.
    """
    parsed: dict[str, Any] = {
        "header": {
            "market": None,
            "symbol": None,
            "timeframe": None,
        },
        "provider": None,
        "bars_requested": None,
        "days_requested": None,
        "bars_loaded": None,
        "signals": {
            "total": None,
            "buy": None,
            "sell": None,
            "strong": None,
            "strong_threshold": None,
            "samples": [],
        },
        "paper": {
            "enabled": False,
            "trades": None,
            "realized_pnl": None,
            "nav": None,
            "return_pct": None,
            "notional": None,
            "currency": None,
        },
        "warnings": [],
    }

    in_signals_section = False
    in_paper_section = False
    in_samples = False

    for raw_line in stdout.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            in_samples = False
            continue

        m = _RE_HEADER.match(stripped)
        if m:
            parsed["header"]["market"] = m.group(1)
            parsed["header"]["symbol"] = m.group(2)
            parsed["header"]["timeframe"] = m.group(3)
            continue

        m = _RE_PROVIDER.match(stripped)
        if m:
            parsed["provider"] = m.group(1)
            parsed["bars_requested"] = _safe_int(m.group(2))
            parsed["days_requested"] = _safe_int(m.group(3))
            continue

        m = _RE_LOADED.match(stripped)
        if m:
            parsed["bars_loaded"] = _safe_int(m.group(1))
            continue

        if stripped.lower().startswith("signal results"):
            in_signals_section = True
            in_paper_section = False
            in_samples = False
            continue

        if stripped.lower().startswith("paper simulation"):
            in_paper_section = True
            in_signals_section = False
            in_samples = False
            parsed["paper"]["enabled"] = True
            continue

        if stripped.startswith("---"):
            in_samples = False
            continue

        if in_signals_section:
            m = _RE_TOTAL.match(stripped)
            if m:
                parsed["signals"]["total"] = _safe_int(m.group(1))
                continue
            m = _RE_BUY_SELL.match(stripped)
            if m:
                parsed["signals"]["buy"] = _safe_int(m.group(1))
                parsed["signals"]["sell"] = _safe_int(m.group(2))
                continue
            m = _RE_STRONG.match(stripped)
            if m:
                parsed["signals"]["strong_threshold"] = _safe_int(m.group(1))
                parsed["signals"]["strong"] = _safe_int(m.group(2))
                continue
            if stripped.lower().startswith("last ") and stripped.lower().endswith("signals:"):
                in_samples = True
                continue
            if in_samples:
                m = _RE_SIGNAL_LINE.match(line)
                if m:
                    parsed["signals"]["samples"].append(
                        {
                            "direction": m.group(1).upper(),
                            "rule_name": m.group(2).strip(),
                            "strength": _safe_int(m.group(3)),
                            "message": m.group(4).strip(),
                        }
                    )
                continue
            continue

        if in_paper_section:
            m = _RE_PAPER_TRADES.match(stripped)
            if m:
                parsed["paper"]["trades"] = _safe_int(m.group(1))
                continue
            m = _RE_PAPER_PNL.match(stripped)
            if m:
                parsed["paper"]["realized_pnl"] = _safe_float(m.group(1))
                continue
            m = _RE_PAPER_NAV.match(stripped)
            if m:
                parsed["paper"]["nav"] = _safe_float(m.group(1))
                continue
            m = _RE_PAPER_RETURN.match(stripped)
            if m:
                parsed["paper"]["return_pct"] = _safe_float(m.group(1))
                continue
            m = _RE_PAPER_NOTIONAL.search(stripped)
            if m:
                parsed["paper"]["notional"] = _safe_float(m.group(1))
                parsed["paper"]["currency"] = m.group(2)
                continue
            continue

    return parsed


def _summarize(parsed: dict[str, Any]) -> dict[str, Any]:
    signals = parsed.get("signals", {}) or {}
    paper = parsed.get("paper", {}) or {}
    return {
        "signals_total": signals.get("total"),
        "signals_buy": signals.get("buy"),
        "signals_sell": signals.get("sell"),
        "signals_strong": signals.get("strong"),
        "paper_trade_count": paper.get("trades"),
    }


# ----------------------------- subprocess ---------------------------------- #


def _run_tradecat_backtest(
    *,
    tradecat_bin: str,
    argv: list[str],
    timeout_s: float,
) -> tuple[int, str, str, Optional[str]]:
    """Spawn tradecat backtest. Returns (exit_code, stdout, stderr, spawn_error)."""
    try:
        proc = subprocess.run(
            [tradecat_bin, "backtest", *argv],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
        return 124, stdout, stderr, f"timeout after {timeout_s}s"
    except FileNotFoundError as exc:
        return 127, "", "", f"spawn failed: {exc}"
    except Exception as exc:  # noqa: BLE001
        return 1, "", "", f"spawn failed: {exc}"

    if len(proc.stdout.encode("utf-8")) > MAX_OUTPUT_BYTES:
        return proc.returncode, proc.stdout[: MAX_OUTPUT_BYTES // 2], proc.stderr, "stdout truncated at 8MB"
    return proc.returncode, proc.stdout, proc.stderr, None


# ----------------------------- main ---------------------------------------- #


def execute(argv: Optional[Sequence[str]] = None) -> tuple[int, dict[str, Any]]:
    response = _base_response()
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.days <= 0:
        raise CliError("invalid_arguments", "--days must be > 0")
    if args.min_strength < 0:
        raise CliError("invalid_arguments", "--min-strength must be >= 0")
    if args.timeout <= 0:
        raise CliError("invalid_arguments", "--timeout must be > 0")

    market = _resolve_market(args.market) if args.market else None

    child_argv: list[str] = [
        "--mode",
        args.mode,
        "--strategy",
        args.strategy,
        "--symbol",
        args.symbol,
        "--days",
        str(int(args.days)),
        "--min-strength",
        str(int(args.min_strength)),
    ]
    if args.provider:
        child_argv += ["--provider", args.provider]
    if args.timeframe:
        child_argv += ["--timeframe", args.timeframe]
    if args.initial_equity is not None and args.initial_equity > 0:
        child_argv += ["--initial-cash", str(float(args.initial_equity))]
    if args.notional is not None and args.notional > 0:
        child_argv += ["--notional", str(float(args.notional))]
    if args.no_paper:
        child_argv += ["--no-paper"]

    tradecat_bin = _resolve_tradecat_bin()
    request_payload: dict[str, Any] = {
        "strategy": args.strategy,
        "symbol": args.symbol,
        "market": market,
        "timeframe": args.timeframe or None,
        "provider": args.provider or None,
        "days": int(args.days),
        "min_strength": int(args.min_strength),
        "initial_equity": float(args.initial_equity) if args.initial_equity is not None else None,
        "notional": float(args.notional) if args.notional is not None else None,
        "mode": args.mode,
        "paper": not args.no_paper,
        "timeout_s": float(args.timeout),
    }
    response["request"] = request_payload
    response["source"]["tradecat_bin"] = tradecat_bin
    response["source"]["child_argv"] = child_argv

    exit_code, stdout, stderr, spawn_error = _run_tradecat_backtest(
        tradecat_bin=tradecat_bin,
        argv=child_argv,
        timeout_s=float(args.timeout),
    )

    if spawn_error is not None and exit_code == 124:
        response["error"] = _error_payload(
            "timeout",
            spawn_error,
            details={"exit_code": exit_code, "stderr_tail": stderr[-2000:] if stderr else ""},
        )
        return 1, response

    if spawn_error is not None and exit_code != 0:
        response["error"] = _error_payload(
            "spawn",
            spawn_error,
            details={"exit_code": exit_code, "stderr_tail": stderr[-2000:] if stderr else ""},
        )
        return 1, response

    parsed = _parse_backtest_stdout(stdout)
    summary = _summarize(parsed)
    response["summary"] = summary

    # Header missing → either tradecat binary broken, or arg rejection.
    if parsed["header"]["market"] is None:
        # Click / argparse errors are printed by tradecat to stderr/stdout.
        tail = (stderr or stdout or "").strip().splitlines()[-10:]
        response["error"] = _error_payload(
            "backtest_failed",
            "could not parse `tradecat backtest` header line; check args / CLI output",
            details={
                "exit_code": exit_code,
                "stderr_tail": tail,
                "stdout_tail": (stdout or "").splitlines()[-10:],
            },
        )
        return 1, response

    response["data"] = {
        "header": parsed["header"],
        "provider": parsed["provider"],
        "bars": {
            "requested": parsed["bars_requested"],
            "loaded": parsed["bars_loaded"],
            "days": parsed["days_requested"],
        },
        "signals": parsed["signals"],
        "paper": parsed["paper"],
        "exit_code": exit_code,
        "stderr_tail": (stderr or "").splitlines()[-10:] if stderr else [],
    }

    if exit_code != 0 and not parsed["signals"]["samples"]:
        response["ok"] = False
        response["error"] = _error_payload(
            "backtest_failed",
            f"tradecat backtest exited with code {exit_code}",
            details={"stderr_tail": (stderr or "").splitlines()[-10:]},
        )
        return exit_code or 1, response

    response["ok"] = True
    response["error"] = None
    return 0, response


def main(argv: Optional[Sequence[str]] = None) -> int:
    pretty = "--pretty" in set(argv if argv is not None else sys.argv[1:])
    try:
        exit_code, payload = execute(argv)
    except ParserExit as exc:
        if exc.message:
            sys.stdout.write(exc.message)
        return exc.status
    except CliError as exc:
        payload = _base_response()
        payload["request"] = {"argv": list(argv) if argv is not None else sys.argv[1:]}
        payload["error"] = _error_payload(exc.code, str(exc), details=exc.details)
        exit_code = 1
    except Exception as exc:  # noqa: BLE001
        payload = _base_response()
        payload["request"] = {"argv": list(argv) if argv is not None else sys.argv[1:]}
        payload["error"] = _error_payload(
            "unexpected_error",
            f"unexpected error: {exc}",
            details={"type": exc.__class__.__name__},
        )
        exit_code = 1

    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2 if pretty else None, sort_keys=False)
    sys.stdout.write("\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
