# tradeagnt Agent Skill

tradeagnt **V2 以 Agent 为主用户**：Harness = manifest + 只读研究 + thesis 闸门 + 纸面 + 审计。人类可用 `tradecat tui` 监控。

- 产品需求：[pi/docs/trade-agent/20260527-V2/PRD.md](../../../pi/docs/trade-agent/20260527-V2/PRD.md)
- 机器契约：`agents/manifest.json`（v2 起含写路径）
- 验收：[pi/docs/trade-agent/20260527-V2/ACCEPTANCE.md](../../../pi/docs/trade-agent/20260527-V2/ACCEPTANCE.md)

## V2 推荐流程（E2 观察层）

在 **Pi + tradeagnt Extension** 下，**禁止**用 `bash` 手敲 `python scripts/...`；改用工具：

1. 读 `agents/manifest.json`（风险类 + 命令表）
2. **`trade_get_quotes`** — 行情（P1）：`symbol` 如 `BTC_USDT`
3. **`trade_get_indicators`** — 技术指标（RSI/EMA/MACD 等，K 线计算）：`symbol`，`timeframe` 默认 `5m`。**A 股收盘后/周末也用 `5m`**（腾讯分钟重放）；`1d` 依赖东财，不通时会自动回退 `5m`。问指标时必须调此工具，不能只用 `trade_get_quotes` 推断。
4. **`trade_get_news`** — 资讯（P3）：`symbol`，`limit` 默认 5

**不要**使用 `trade_get_signals`（策略 BUY/SELL 在 E3+ 或后台 poller，E2 不暴露给 Agent）。
5. 生成 `agent_trade_thesis.v1` JSON（见 `pi/docs/trade-agent/20260527-V2/examples/agent_trade_thesis.example.json`）
6. **`trade_submit_thesis`** / **`trade_paper_report`**（E3 写路径；或 CLI `tradecat agent submit-thesis` / `paper-report --json`，详见 §5）

> E2 **不接**模拟盘、回测、**策略信号**；只给 **报价 + 技术指标数值 + 资讯**。

## 环境

```bash
source .venv/bin/activate
export TRADECAT_PIPELINE_PROFILE=tui_dual
```

封板范围：`docs/FREEZE_SCOPE.md`。

## §5 E3: Agent 模拟盘

V2 写路径硬层。Agent 在「V2 推荐流程」第 5 步生成 `agent_trade_thesis.v1` JSON 后，通过本节命令提交到**本地纸面**（**不**连实盘、**不**读 `.env` 密钥）。底层走 `PaperTradingEngine.long/short/close`，落 SQLite + 写 `data/agent_audit.jsonl`。

### 5.1 何时用 submit-thesis

- Agent 已生成合规 thesis（见 `pi/docs/trade-agent/20260527-V2/examples/agent_trade_thesis.example.json`）
- 想立刻落本地纸面研究；**不**想跑时先看 §6 backtest 验
- 想在 Pi/Extension 之外**手工**调试闸门（`--input <path>` 比 `--stdin` 方便）

### 5.2 5 道闸门速查

| 闸门 | 失败 `error.code` | 默认 | strict 拒 |
|:---|:---|:---:|:---:|
| **G1 schema+safety**（schema 内 `safety.*` 7 项 const 强约束） | `agent_thesis_schema_invalid` | ✅ fail-closed | – |
| **G2 risk**（缺 margin/leverage/exit 或 `leverage ∉ (0,100]`） | `agent_sizing_required` | ✅ fail-closed | – |
| **G3 symbol/market**（`core.symbols` 归一化失败 / Provider 不支持） | `agent_symbol_unsupported` | ✅ fail-closed | – |
| **G4 conflict**（同 account 同 symbol 反向持仓） | `agent_position_conflict` | ⚠ warn | `TRADEAGNT_AGENT_CONFLICT=strict` |
| **G5 freshness**（submit 拉 `quote_ts` 距 now > 60s） | `agent_data_stale` | ⚠ warn | `TRADEAGNT_FRESHNESS_SEC` 配 reject |

- **AC-31** 锁：同 symbol 同方向 → 直接拒（防重复加仓）；反方向默认 `ok=true, warnings=["position_conflict"]`
- **NFR-05**：`TRADEAGNT_HARNESS_V1=1` 入口短路 → `ok=false, code=agent_harness_v1_disabled`，**不**读 thesis body、**不**写 audit
- **NFR-01**：submit 路径不触发 `BINANCE_API_KEY` / `LINEAR_API_KEY` 任何读取
- **幂等**：`thesis_id` 重复 submit → 返回首次 accept 信封，不重复开仓
- **Notional**：`notional_usdt = requested_margin_usdt × paper_leverage`（E3 内部算）

### 5.3 thesis JSON 关键字段速查

| 字段 | 必填 | 备注 |
|:---|:---:|:---|
| `schema` / `schema_version` | ✅ | const `tradecat_auto.agent_trade_thesis.v1` / `"1.0.0"`（沿用上游） |
| `symbol` | ✅ | 经 `core.symbols.normalize_symbol` |
| `direction` | ✅ | `LONG` / `SHORT` / `WATCH_ONLY` |
| `paper_intent.{requested_margin_usdt, paper_leverage}` | ✅* | LONG/SHORT 必填；leverage 上界 100 |
| `invalidation_price` / `take_profit_price` | ✅* | LONG/SHORT 必填 |
| `paper_intent.real_order` | ✅ | const `false` |
| `safety.{real_orders, signed_requests, reads_api_keys, binance_account_state}` | ✅ | 全 const `false`（G2 守门） |
| `safety.{public_readonly_market_data, public_readonly, paper_or_watch_only}` | ✅ | 全 const `true` |
| `limitations` | ✅ | 必含 `paper` / `no real` / `no Binance` 之一 |
| `paper_intent.account_id` / `client_order_id` | – | tradeagnt 扩展（默认 `default` / `thesis_id`） |
| `meta.research_session` | – | tradeagnt 扩展（debug） |

`*` = G2 fail-closed 触发条件。完整 schema：`tradeagnt/contracts/agent_trade_thesis.schema.json`。

### 5.4 信封返回速查（`tradeagnt.agent_envelope.v1`）

- 进程退出码：**0**（仅参数解析错才非 0）
- `ok: bool` — true ≠ 成交，**必须看 `data.action`**
- `data.action`：
  - `filled` → `data.fill = {price, notional_usdt, margin_usdt, leverage, order_id, account_id}`
  - `watch_only` → 不开仓；`data.reason` 由 Agent 自填（不调 engine）
  - `dry_run` → `data.gates` 快照（仅 `thesis-validate` 路径）
- `error: {code, message, gate}` — 闸门失败时填
- `warnings: list[str]` — G4/G5 warn 等软提示（不阻成交）
- `audit_ref: thesis_id` — 与 `data/agent_audit.jsonl` 行对应（不用行号避 race）

### 5.5 audit（`data/agent_audit.jsonl`）

- 位置：`tradeagnt/data/agent_audit.jsonl`（gitignore；与 `data/signal_history.db` 同目录）
- 一行 = 一次 submit 尝试（accept / reject / watch_only 都写；**NFR-05 短路不写**）
- 关键字段：
  - `quote_ts_delta_ms` — submit 时 Provider 拉的 `quote_ts` 距 now 的差（G5 用）
  - `engine_tx_note: "partial"` — accept 时填，标记 `OrderManager.rollback` 只能部分恢复（E3-06 文档化此限制；E3-P1 可加 `BEGIN IMMEDIATE`）
  - `thesis_hash` — thesis AS RECEIVED FROM AGENT 的 canonical JSON SHA-256 前 16 hex
  - `gates.{schema, risk, symbol, conflict, freshness}` — 5 步快照
  - `warnings: ["freshness_warn" | "position_conflict" | ...]`
- 下游消费：`tradecat agent paper-report --include-rejects 50` 取最近 reject 摘要

### 5.6 命令速查

```bash
# 提交 thesis（Pi 默认走 --stdin；手测可用 --input）
tradecat agent submit-thesis --input <thesis.json>
tradecat agent submit-thesis --stdin < <thesis.json>

# 只校验不落单、不写 audit（E3-P1）
tradecat agent thesis-validate --input <thesis.json>

# 读 paper 状态 + 最近 reject 摘要
tradecat agent paper-report --json
tradecat agent paper-report --symbol BTCUSDT
tradecat agent paper-report --include-rejects 50
```

### 5.7 不进 E3（P1+）

- `tradecat agent context-audit` → P1
- `tradecat agent feedback-pack` → E4
- `tradecat agent run-cycle` → E5（24h 自动循环 / R3 评估）

## §6 E3-BACKTEST

回测是 submit-thesis 前的**假设验证**手段，**不**替代 G2～G5 闸门。

- 工具：`trade_run_backtest`（Pi 暴露）→ 底层走 `tradecat backtest`
- 何时用：Agent 在产 thesis 前，先用历史回测验策略 / 估 leverage / 看风险；详见 `AGENTS.md §2.2 / §3.0` 的 `tradecat backtest --strategy <yaml> --symbol X --days N` 用法
