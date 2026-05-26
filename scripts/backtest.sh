#!/usr/bin/env bash
# tradeagnt 回测入口（单体 tradecat backtest）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MONOLITH_LIB="$ROOT/scripts/lib/monolith_runtime.sh"
if [[ -f "$MONOLITH_LIB" ]]; then
    # shellcheck disable=SC1091
    source "$MONOLITH_LIB"
fi

if [[ $# -eq 0 ]] || [[ "${1:-}" == "-h" ]] || [[ "${1:-}" == "--help" ]]; then
    cat <<'EOF'
用法: ./scripts/backtest.sh [tradecat backtest 选项]

示例:
  ./scripts/backtest.sh --strategy current/fast_1m.yaml --symbol BTC_USDT --days 3
  ./scripts/backtest.sh --strategy current/us_fast_5m.yaml --symbol NVDA --days 5 --mode scan

说明: 转发到 `tradecat backtest`（见 src/tradecat/cli/backtest.py）。
EOF
    exit 0
fi

py=""
if ! py="$(monolith_python "$ROOT" 2>/dev/null)"; then
    echo "✗ 未找到 Python：请先 ./scripts/init.sh" >&2
    exit 1
fi

exec "$py" -m tradecat.cli.main backtest "$@"
