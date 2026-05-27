#!/usr/bin/env bash
# v1.0 封板门禁：演示闭环 + Agent 只读桥接冒烟
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

PY="${PYTHON:-python3}"

FREEZE_TESTS=(
  tests/test_tradecat_get_signals.py
  tests/test_tradecat_get_quotes.py
  tests/test_pipeline_profile.py
  tests/test_strategy_loader_paths.py
  tests/test_strategy_release.py
  tests/test_us_equity.py
  tests/test_collector_on_demand.py
  tests/test_start_script.py
  tests/test_script_alignment.py
  tests/test_data_paths.py
)

echo "=== tradeagnt freeze gate (v1.0) ==="

echo ""
echo "1) pytest freeze subset..."
"$PY" -m pytest "${FREEZE_TESTS[@]}" -q --tb=short

echo ""
echo "2) bridge: tradecat_get_signals..."
out="$("$PY" scripts/tradecat_get_signals.py --limit 1)"
echo "$out" | "$PY" -c "import json,sys; p=json.load(sys.stdin); assert p.get('ok') is True, p"

echo ""
echo "3) bridge: tradecat_get_quotes (NVDA)..."
out="$("$PY" scripts/tradecat_get_quotes.py NVDA)"
echo "$out" | "$PY" -c "import json,sys; p=json.load(sys.stdin); assert p.get('ok') is True, p"

echo ""
echo "4) strategy release current bundle..."
"$PY" scripts/strategy_release.py show | grep -q us_fast_5m.yaml

echo ""
echo "5) pipeline profile tui_dual..."
TRADECAT_PIPELINE_PROFILE=tui_dual "$PY" -c "
import os
from pathlib import Path
from tradecat.core.pipeline.profile import bootstrap_pipeline_profile
bootstrap_pipeline_profile(repo_root=Path('.'), only_if_unset=False)
assert 'us_fast_5m.yaml' in os.environ.get('TUI_SIGNAL_STRATEGY_EXTRA', '')
assert os.environ.get('PAPER_AUTO_MARKET') == 'all'
"

echo ""
echo "6) collector on-demand status..."
out="$(bash scripts/start.sh status-collector)"
echo "$out" | "$PY" -c "import json,sys; p=json.load(sys.stdin); assert p.get('data_mode')=='on_demand', p"

echo -e "${GREEN}freeze gate: PASS${NC}"
