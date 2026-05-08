#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

TMP_ROOT="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

PRINT() {
  printf '[smoke] %s\n' "$*"
}

ENV_VARS=(
  "TRADECAT_PAPER_ARTIFACTS_DIR=$TMP_ROOT/paper"
  "TRADECAT_EXECUTION_AUDIT_DIR=$TMP_ROOT/audit"
)

run() {
  PRINT "running: $*"
  env "${ENV_VARS[@]}" "$@"
}

PRINT "starting 007 smoke run"
run python scripts/tradecat_get_symbol_snapshot.py --symbol BTCUSDT --timeframe 1h
run python scripts/tradecat_get_signal_context.py --symbol BTCUSDT --timeframe 1h --limit 5
run python scripts/tradecat_get_market_state.py
run python scripts/tradecat_get_backtest_health.py
run python scripts/tradecat_get_service_health.py
run python scripts/tradecat_get_context_pack.py --symbol BTCUSDT --timeframe 1h --news-limit 3 --signal-limit 5

SIGNAL_TS="$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())')"
ORDER_ID="$(env "${ENV_VARS[@]}" python3 scripts/tradecat_paper_trade.py candidate BTCUSDT LONG 0.05 | python3 -c 'import json,sys;print(json.load(sys.stdin)["data"]["order"]["order_id"])')"
run python scripts/tradecat_paper_trade.py execute "$ORDER_ID" 80000 --signal-ts "$SIGNAL_TS"
run python scripts/tradecat_paper_trade.py report 5

PRINT "007 smoke completed"
