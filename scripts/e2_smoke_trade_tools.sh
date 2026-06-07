#!/usr/bin/env bash
# E2 smoke: Python bridges (run before Pi Extension test)
# Updated 2026-06-02: signals → indicators (per E2 review)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[[ -f .venv/bin/activate ]] && source .venv/bin/activate
export TRADEAGNT_ROOT="$ROOT"

echo "== quotes =="
python scripts/tradecat_get_quotes.py BTC_USDT | python -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok'), d; print('ok', d['data'][0].get('price'))"

echo "== indicators =="
python scripts/tradecat_get_indicators.py --symbol BTC_USDT --timeframe 5m | python -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok'), d; ks=list(d.get('data',{}).keys()); print('ok indicators:', ','.join(ks[:5]))"

echo "== news (may fail if PG down) =="
python scripts/tradecat_get_news.py --symbol BTC_USDT --limit 1 2>&1 | head -c 400 || true
echo ""
echo "E2 python smoke done (news optional)."
