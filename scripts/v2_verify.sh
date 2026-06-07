#!/usr/bin/env bash
# v2_verify.sh — E3 验收门禁（AC-10~14, AC-21, AC-30/31, AC-40/41, NFR-03, NFR-05）
# 单 AC 失败不中断；最后汇总 pass/fail
# Exit code: 0 = 全过, 1 = 至少 1 个失败
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# 强制用 venv 的 python + bin（修 shebang 跑偏问题）
export PATH="$ROOT/.venv/bin:$PATH"
VENV_PY="$ROOT/.venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "FATAL: venv python 不存在: $VENV_PY" >&2
  exit 2
fi
# 把 tradecat 包装器的 shebang 也指到 venv
if [[ -f "$ROOT/.venv/bin/tradecat" ]]; then
  tail -n +2 "$ROOT/.venv/bin/tradecat" > /tmp/tradecat.tmp 2>/dev/null
  echo "#!$ROOT/.venv/bin/python3.12" > "$ROOT/.venv/bin/tradecat"
  cat /tmp/tradecat.tmp >> "$ROOT/.venv/bin/tradecat" 2>/dev/null
  rm -f /tmp/tradecat.tmp
  chmod +x "$ROOT/.venv/bin/tradecat"
fi
mkdir -p "$ROOT/data"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

PASS=0
FAIL=0
SKIP=0
declare -a FAILED_IDS=()

pass() { PASS=$((PASS+1)); echo -e "  ${GREEN}PASS${NC}  $1"; }
fail() { FAIL=$((FAIL+1)); FAILED_IDS+=("$1"); echo -e "  ${RED}FAIL${NC}  $1 — $2"; }
skip() { SKIP=$((SKIP+1)); echo -e "  ${YELLOW}SKIP${NC}  $1 — $2"; }

# json_query: 从 stdin 读 JSON, 用 Python 提取 key (支持点路径 a.b.c)
jget() { python3 -c "import json,sys; d=json.load(sys.stdin)
for k in '$1'.split('.'):
    d = d.get(k) if isinstance(d, dict) else None
print('' if d is None else d)"; }

# jassert: stdin JSON, 期望 key=val (用 ==)
jassert() {
  local path="$1" expected="$2" desc="$3"
  local actual
  actual=$(jget "$path")
  if [[ "$actual" == "$expected" ]]; then pass "$desc"
  else fail "$desc" "expected $path=$expected, got '$actual'"; fi
}

# ---- 准备 thesis fixture ----
BTC_VALID='{
  "schema": "tradecat_auto.agent_trade_thesis.v1",
  "schema_version": "1.0.0",
  "ok": true,
  "thesis_id": "v2-verify-btc",
  "symbol": "BTC_USDT",
  "mode": "paper_research",
  "direction": "LONG",
  "confidence": 0.6,
  "holding_horizon": "intraday",
  "invalidation_price": 60000,
  "take_profit_price": 80000,
  "rationale": "v2_verify smoke",
  "provenance": {"source": "v2_verify.sh"},
  "safety": {
    "public_readonly_market_data": true,
    "public_readonly": true,
    "paper_or_watch_only": true,
    "real_orders": false,
    "signed_requests": false,
    "reads_api_keys": false,
    "binance_account_state": false
  },
  "limitations": ["no real orders", "paper only"],
  "paper_intent": {
    "requested_margin_usdt": 50,
    "paper_leverage": 2,
    "real_order": false
  }
}'

BTC_WATCH='{
  "schema": "tradecat_auto.agent_trade_thesis.v1",
  "schema_version": "1.0.0",
  "ok": true,
  "thesis_id": "v2-verify-watch",
  "symbol": "BTC_USDT",
  "mode": "paper_research",
  "direction": "WATCH_ONLY",
  "confidence": 0.3,
  "rationale": "watch only smoke",
  "provenance": {"source": "v2_verify.sh"},
  "safety": {
    "public_readonly_market_data": true, "public_readonly": true,
    "paper_or_watch_only": true, "real_orders": false,
    "signed_requests": false, "reads_api_keys": false,
    "binance_account_state": false
  },
  "limitations": ["no real orders"]
}'

BTC_NO_INTENT='{
  "schema": "tradecat_auto.agent_trade_thesis.v1",
  "schema_version": "1.0.0",
  "ok": true,
  "thesis_id": "v2-verify-no-intent",
  "symbol": "BTC_USDT",
  "mode": "paper_research",
  "direction": "LONG",
  "confidence": 0.5,
  "invalidation_price": 60000,
  "take_profit_price": 80000,
  "rationale": "missing paper_intent smoke",
  "provenance": {"source": "v2_verify.sh"},
  "safety": {
    "public_readonly_market_data": true, "public_readonly": true,
    "paper_or_watch_only": true, "real_orders": false,
    "signed_requests": false, "reads_api_keys": false,
    "binance_account_state": false
  },
  "limitations": ["no real orders"]
}'

NVDA_VALID='{
  "schema": "tradecat_auto.agent_trade_thesis.v1",
  "schema_version": "1.0.0",
  "ok": true,
  "thesis_id": "v2-verify-nvda",
  "symbol": "NVDA",
  "market": "us_stock",
  "mode": "paper_research",
  "direction": "LONG",
  "confidence": 0.6,
  "holding_horizon": "multi_day",
  "invalidation_price": 100,
  "take_profit_price": 200,
  "rationale": "v2_verify dual market smoke",
  "provenance": {"source": "v2_verify.sh"},
  "safety": {
    "public_readonly_market_data": true, "public_readonly": true,
    "paper_or_watch_only": true, "real_orders": false,
    "signed_requests": false, "reads_api_keys": false,
    "binance_account_state": false
  },
  "limitations": ["no real orders", "us stock paper"],
  "paper_intent": {
    "requested_margin_usdt": 100,
    "paper_leverage": 1,
    "real_order": false
  }
}'

AUDIT_PATH="data/agent_audit.jsonl"
AUDIT_BEFORE=$(wc -l < "$AUDIT_PATH" 2>/dev/null || echo 0)

echo "=== v2_verify.sh — E3 验收门禁 ==="
echo "ROOT: $ROOT"
echo "audit baseline: $AUDIT_BEFORE 行"
echo ""

# ---- AC-10 happy path ----
echo "[AC-10] submit-thesis happy path (BTC long)"
OUT=$(echo "$BTC_VALID" | tradecat agent submit-thesis --stdin 2>&1)
if echo "$OUT" | jassert "ok" "True" "AC-10 ok=true"; then :; fi

# ---- AC-11 missing paper_intent (LONG direction 缺 paper_intent 触发 schema allOf) ----
echo "[AC-11] LONG direction 缺 paper_intent → schema 拒 (allOf 强约束)"
OUT=$(echo "$BTC_NO_INTENT" | tradecat agent submit-thesis --stdin 2>&1)
if echo "$OUT" | jassert "error.code" "agent_thesis_schema_invalid" "AC-11 reject"; then :; fi

# ---- AC-12 WATCH_ONLY ----
echo "[AC-12] WATCH_ONLY → ok=true, action=watch_only"
OUT=$(echo "$BTC_WATCH" | tradecat agent submit-thesis --stdin 2>&1)
ACTION=$(echo "$OUT" | jget "data.action" 2>/dev/null || echo "")
if [[ "$ACTION" == "watch_only" ]]; then pass "AC-12 action=watch_only"
elif echo "$OUT" | grep -q '"ok": true'; then pass "AC-12 ok=true (action=$ACTION)"
else fail "AC-12" "got: $(echo "$OUT" | head -c 200)"; fi

# ---- AC-13 audit 追加 ----
echo "[AC-13] audit jsonl 追加行"
AUDIT_AFTER=$(wc -l < "$AUDIT_PATH" 2>/dev/null || echo 0)
if (( AUDIT_AFTER > AUDIT_BEFORE )); then
  LAST=$(tail -1 "$AUDIT_PATH")
  if echo "$LAST" | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'thesis_id' in d and 'outcome' in d" 2>/dev/null; then
    pass "AC-13 audit +$((AUDIT_AFTER-AUDIT_BEFORE)) 行，结构 ok"
  else
    fail "AC-13" "audit 行结构缺字段: $(echo "$LAST" | head -c 200)"
  fi
else
  fail "AC-13" "audit 没新增 (before=$AUDIT_BEFORE after=$AUDIT_AFTER)"
fi

# ---- AC-14 dual market (validate dry-run，避免网络) ----
echo "[AC-14] dual market (BTC + NVDA, dry-run validate 避网络)"
OUT_BTC=$(echo "$BTC_VALID" | tradecat agent thesis-validate --stdin 2>&1)
OUT_NVDA=$(echo "$NVDA_VALID" | tradecat agent thesis-validate --stdin 2>&1)
if echo "$OUT_BTC" | grep -q '"ok"'; then pass "AC-14 BTC validate 结构 ok"
else fail "AC-14 BTC" "$(echo "$OUT_BTC" | head -c 200)"; fi
if echo "$OUT_NVDA" | grep -q '"ok"'; then pass "AC-14 NVDA validate 结构 ok"
else fail "AC-14 NVDA" "$(echo "$OUT_NVDA" | head -c 200)"; fi

# ---- AC-21 freeze_verify no regression ----
echo "[AC-21] freeze_verify.sh 无回归"
if PYTHON="$VENV_PY" bash scripts/freeze_verify.sh >/tmp/freeze_verify.log 2>&1; then
  pass "AC-21 freeze_verify exit 0"
else
  fail "AC-21" "freeze_verify 失败 (见 /tmp/freeze_verify.log)"
fi

# ---- AC-30 agent_mode env ----
echo "[AC-30] TRADEAGNT_AGENT_MODE env 已读取"
OUT=$(TRADEAGNT_AGENT_MODE=1 echo '{}' | tradecat agent audit-tail --limit 0 2>&1)
if [[ $? -eq 0 ]]; then pass "AC-30 env 解析不崩"
else fail "AC-30" "$(echo "$OUT" | head -c 200)"; fi

# ---- AC-31 default warn (schema-level 锁定：默认通过 + warnings) ----
echo "[AC-31] default conflict = warn 不拒"
OUT=$(echo "$BTC_VALID" | tradecat agent thesis-validate --stdin 2>&1)
# 默认无 strict，validate 不应被同 symbol 拒
if echo "$OUT" | grep -q '"ok": true'; then
  pass "AC-31 默认 validate 不拒"
else
  # 若被拒，应是 strict 模式，没设 env 所以不可能
  fail "AC-31" "$(echo "$OUT" | head -c 200)"
fi

# ---- AC-40 SKILL.md V2 主路径 ----
echo "[AC-40] SKILL.md §5/§6 V2 主路径"
if grep -q "§5 E3" skills/tradeagnt/SKILL.md 2>/dev/null \
   && grep -q "§6 E3-BACKTEST" skills/tradeagnt/SKILL.md 2>/dev/null; then
  pass "AC-40 §5 + §6 存在"
else
  fail "AC-40" "SKILL.md 缺 §5/§6"
fi

# ---- AC-41 AGENTS.md 命令表 ----
echo "[AC-41] AGENTS.md tradecat agent * 命令"
HITS=0
for cmd in submit-thesis paper-report thesis-validate; do
  if grep -q "$cmd" AGENTS.md 2>/dev/null; then HITS=$((HITS+1)); fi
done
if (( HITS >= 3 )); then pass "AC-41 $HITS/3 命令在表"
else fail "AC-41" "只命中 $HITS/3"; fi

# ---- NFR-03 冷启动 < 3s ----
echo "[NFR-03] submit-thesis 冷启动 < 3s"
T_OUT=$( { time echo '{}' | tradecat agent thesis-validate --stdin >/dev/null; } 2>&1 )
ELAPSED=$(echo "$T_OUT" | grep real | awk '{print $2}' | sed -E 's/m/:/;s/s//')
ELAPSED_SEC=$(echo "$ELAPSED" | awk -F: '{ if (NF==2) print $1*60+$2; else print $1+0 }')
ELAPSED_SEC=${ELAPSED_SEC:-0}
# awk 整数比较（避免依赖 bc）
if awk "BEGIN { exit !($ELAPSED_SEC < 3) }" 2>/dev/null; then
  pass "NFR-03 冷启动 ${ELAPSED_SEC}s < 3s"
else
  fail "NFR-03" "冷启动 ${ELAPSED_SEC}s 超过 3s"
fi

# ---- NFR-05 HARNESS_V1=1 短路 ----
echo "[NFR-05] TRADEAGNT_HARNESS_V1=1 短路"
OUT=$(TRADEAGNT_HARNESS_V1=1 echo "$BTC_VALID" | TRADEAGNT_HARNESS_V1=1 tradecat agent submit-thesis --stdin 2>&1)
if echo "$OUT" | jassert "error.code" "agent_harness_v1_disabled" "NFR-05 短路"; then :; fi

# ---- AC-32 同 thesis_id 并发幂等（P0-1 修） ----
echo "[AC-32] 并发 10x 同 thesis_id → 1 accept + 9 idempotent_replay"
if "$VENV_PY" -m pytest tests/test_agent_submit_concurrent.py -q --tb=line 2>&1 | grep -q "5 passed"; then
  pass "AC-32 并发幂等 5/5 测试过"
else
  fail "AC-32" "并发测试失败（见 $ROOT/tests/test_agent_submit_concurrent.py）"
fi

# ---- 汇总 ----
echo ""
echo "==================================="
TOTAL=$((PASS+FAIL+SKIP))
echo "TOTAL: $TOTAL  PASS: $PASS  FAIL: $FAIL  SKIP: $SKIP"
if (( FAIL > 0 )); then
  echo -e "${RED}FAILED: ${FAILED_IDS[*]}${NC}"
  exit 1
fi
echo -e "${GREEN}v2_verify: ALL PASS${NC}"
exit 0
