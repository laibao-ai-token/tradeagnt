# tradeagnt V2 产品需求文档（PRD）

| 字段 | 值 |
|:---|:---|
| 文档 ID | `tradeagnt-prd-v2` |
| 状态 | **Draft — 文本驱动研发** |
| 版本 | 2.0.0-target |
| 基线分支 | `tradeagnt`（v1.0 封板，只修 hotfix） |
| **V2 开发分支** | **`v2/agent-harness`**（本 PRD 及后续实现均在此分支推进） |
| 文档目录 | `docs/20260527-V2/` |
| 上一版基线 | [FREEZE_SCOPE.md](../FREEZE_SCOPE.md)（v1.0 封板） |
| 参考架构 | 官方 TradeCat Public Agent Contract（本地 `../tradecat-upstream`，只读对照） |
| 最后更新 | 2026-05-27 |

---

## 1. 一句话

**V2 以 Agent 为唯一主用户**：通过 **Agent Harness**（manifest + 只读研究工具 + schema 闸门 + 纸面执行 + 审计）驱动 trade 研究闭环；人类仅作监督、配置与例外处理，**不再**以 TUI 点击作为主路径。

---

## 2. 背景与问题

### 2.1 V1 已解决

- 独立仓库、单体运行、加密/美股双市场演示。
- Agent **只读** JSON 工具：`tradecat_get_*`、`context_pack`、`skills/tradeagnt/agents/manifest.json`。

### 2.2 V1 未解决（V2 要解）

| 痛点 | 影响 |
|:---|:---|
| Agent 不能提交结构化交易假设 | 无法闭环「研究 → 纸面」 |
| 无统一 schema / fail-closed | Agent 输出不可机器验收 |
| 无 audit journal | 无法复盘「为何拒单/为何成交」 |
| TUI/daemon 与 Agent 职责重叠 | 优先级不清，难自动化 |
| manifest 仅 readonly | Cursor/Hermes 无法从契约发现写路径 |

### 2.3 产品立场（相对官方 Public）

- **借鉴**：Harness 分层（软 Agent / 硬 TradeCat）、`agent_trade_thesis`、风险分级、JSON 信封。
- **不照搬**：Google 公开表为唯一信号、Binance-only、废弃 TUI、整仓 merge。
- **保留**：本地策略信号、`signal_history`、多市场 Provider、现有 `PaperTradingEngine`。

---

## 3. 目标与非目标

### 3.1 目标（Must）

1. **G1**：Agent 可在无人工点击下完成一轮「读上下文 → 产出 thesis → 过闸门 → 纸面结果/拒绝」。
2. **G2**：所有 Harness 命令输出稳定 JSON（含 `schema` / `ok` / 结构化 `error`）。
3. **G3**：`manifest.json` 为唯一机器契约；风险类与命令一一对应。
4. **G4**：fail-closed：缺 sizing/leverage/exit 等必填项 → 拒绝，**禁止**运行时默认猜仓。
5. **G5**：每笔 accept/reject 写入 audit journal，可供 `paper-report` 类命令查询。
6. **G6**：与 v1.0 只读工具 **向后兼容**（不破坏现有 `tradecat_get_*`）。

### 3.2 非目标（Won’t in V2.0）

- 实盘下单、API 签名、读交易所密钥。
- 7×24 TimescaleDB 全量采集管线。
- 用公开 Google Sheet 替代本地策略（可作 V2.x 可选适配）。
- 完整 Hermes 技能市场发布（仅文档 + manifest 对齐）。
- TUI 大改或删除（降为监控面）。
- 全量历史 pytest 全绿（以 V2 验收子集为准）。

---

## 4. 用户与场景

### 4.1 主用户：编排型 Agent

| 属性 | 说明 |
|:---|:---|
| 示例 | Cursor Agent、Hermes、自建 LLM 编排 |
| 入口 | 读 `skills/tradeagnt/agents/manifest.json` → 调脚本/CLI |
| 目标 | 基于本地信号与行情做研究，提交 thesis，获得确定性纸面反馈 |
| 约束 | 默认只读；写纸面必须显式任务与 `paper_runtime_write` 类命令 |

### 4.2 次用户：人类操作员

| 属性 | 说明 |
|:---|:---|
| 角色 | 配置策略、看 TUI/报告、处理 reject、启停 daemon |
| 原则 | 不阻塞 Agent 主路径；人工 CLI 优先级可配置（见 FR-08） |

### 4.3 核心场景（Happy Path）

```text
Agent 启动
  → manifest.json（发现 readonly + write 命令）
  → tradecat_get_context_pack --symbol BTC_USDT
  → （可选）tradecat_get_signals / news / market_state
  → Agent 生成 agent_trade_thesis.v1 JSON（本地文件或 stdin）
  → tradecat agent submit-thesis --input thesis.json
       ├─ schema 校验通过 + risk gate 通过 → paper 引擎落单/调仓
       └─ 否则 → structured reject + audit 记录
  → tradecat agent paper-report --json
  → Agent 根据 report 决定下一轮或 WATCH_ONLY
```

### 4.4 异常场景（必须覆盖）

| 场景 | 期望行为 |
|:---|:---|
| thesis 缺 `paper_intent` 尺寸 | `error.code=agent_sizing_required`，`ok=false`，无成交 |
| 信号数据陈旧 | `warnings` + 可配置拒绝（freshness gate） |
| symbol 不在支持市场 | `error.code=symbol_unsupported` |
| 与 daemon 自动跟单冲突 | 默认 **显式 thesis 优先**（FR-08） |
| 重复提交同一 thesis id | 幂等：同 `thesis_id` 不重复开仓 |

---

## 5. 功能需求（FR）

优先级：**P0** = V2.0 MVP；**P1** = V2.1；**P2** = V2.2+。

### 5.1 契约与 manifest

| ID | 优先级 | 需求 |
|:---|:---|:---|
| FR-01 | P0 | `manifest.json` 升级 `schema: tradeagnt.agent_manifest.v2`，含 `command_risk_classes` 与完整命令表 |
| FR-02 | P0 | 引入 `contracts/agent_trade_thesis.schema.json`（对齐 `tradecat_auto.agent_trade_thesis.v1` 语义，允许 tradeagnt 扩展字段） |
| FR-03 | P0 | 所有 Harness 命令 stdout 为 JSON，字段含 `schema`、`schema_version`、`ok`、可选 `data`/`error`/`warnings` |
| FR-04 | P1 | 可选 `agent_market_context.v1` 校验与 `context-audit` 子命令 |
| FR-05 | P2 | `agent_research_cycle.v1` 一次打包多 symbol |

### 5.2 Agent 写路径（Harness 硬层）

| ID | 优先级 | 需求 |
|:---|:---|:---|
| FR-10 | P0 | CLI：`tradecat agent submit-thesis --input <path>`（`--stdin` 可选） |
| FR-11 | P0 | 校验 thesis → 映射到现有 `PaperTradingEngine` 意图（LONG/SHORT/WATCH_ONLY） |
| FR-12 | P0 | fail-closed：缺 leverage/notional/exit 之一则拒绝（错误码稳定） |
| FR-13 | P0 | CLI：`tradecat agent paper-report --json`（账户、持仓、最近 reject） |
| FR-14 | P0 | audit journal：每次 submit 写一条（accept/reject、原因、thesis 摘要 hash） |
| FR-15 | P1 | CLI：`tradecat agent context-audit --input <ctx.json>` |
| FR-16 | P1 | CLI：`tradecat agent thesis-validate --input`（只校验不落单） |

### 5.3 只读研究层（延续 V1）

| ID | 优先级 | 需求 |
|:---|:---|:---|
| FR-20 | P0 | 保持 `scripts/tradecat_get_*.py` 行为兼容；响应逐步对齐 FR-03 信封 |
| FR-21 | P0 | `tradecat_get_context_pack` 增加 `harness_version` / `freshness` 元数据 |
| FR-22 | P1 | manifest 登记 freshness SLA（秒）供 Agent 自检 |

### 5.4 信号与行情

| ID | 优先级 | 需求 |
|:---|:---|:---|
| FR-30 | P0 | thesis 的 `symbol` 支持 crypto（BTCUSDT 等）与 us_stock（NVDA 等），经现有 symbols 归一化 |
| FR-31 | P0 | 纸面成交价格来源：与 v1 一致（Provider 报价），写入 audit |
| FR-32 | P1 | freshness gate：信号 DB / 报价超过阈值可拒绝 thesis |
| FR-33 | P2 | 可选适配公开表 `signal_flow`（network_readonly） |

### 5.5 与现有运行时关系

| ID | 优先级 | 需求 |
|:---|:---|:---|
| FR-40 | P0 | `tradecat daemon` + `auto_consumer` 默认 **不**与 Agent thesis 同时抢同一 symbol（env 控制） |
| FR-41 | P0 | 环境变量 `TRADEAGNT_AGENT_MODE=1` 时：推荐仅 Agent 写 paper |
| FR-42 | P1 | TUI 只读展示最近 audit / paper 状态（小改，非 P0） |
| FR-43 | P0 | 文档声明：V2 主路径为 Agent；TUI 为 optional 监控 |

### 5.6 文档与 Agent 可发现性

| ID | 优先级 | 需求 |
|:---|:---|
| FR-50 | P0 | `skills/tradeagnt/SKILL.md` 更新为 V2 流程（读 PRD 摘要 + manifest） |
| FR-51 | P0 | `AGENTS.md` 增加 V2 命令表与禁止项 |
| FR-52 | P0 | [ACCEPTANCE.md](./ACCEPTANCE.md) 验收用例（与 PRD 一一对应） |
| FR-53 | P1 | 示例 thesis：[examples/agent_trade_thesis.example.json](./examples/agent_trade_thesis.example.json) |

---

## 6. 非功能需求（NFR）

| ID | 类别 | 要求 |
|:---|:---|:---|
| NFR-01 | 安全 | 命令默认不读 `config/.env` 密钥；manifest 禁止 signed 请求 |
| NFR-02 | 可测 | P0 用例纳入 `scripts/freeze_verify.sh` 或 `scripts/v2_verify.sh` |
| NFR-03 | 性能 | `submit-thesis` 冷启动 &lt; 3s（无网络除外） |
| NFR-04 | 可观测 | audit 行含 `ts`、`thesis_id`、`symbol`、`outcome`、`error_code` |
| NFR-05 | 兼容 | v1.0 tag 行为可通过 `TRADEAGNT_HARNESS_V1=1` 关闭写路径（可选） |

---

## 7. 命令与风险分级（目标态）

| 风险类 | 含义 | V2.0 命令（拟） |
|:---|:---|:---|
| `local_readonly` | 本地 DB/文件 | `tradecat_get_*`、`agent paper-report`、`agent thesis-validate` |
| `network_readonly` | 公网行情 | `tradecat_get_quotes`（Provider） |
| `paper_runtime_write` | 仅本地纸面 | `tradecat agent submit-thesis` |

**禁止**出现在 manifest 的类：实盘、签名、账户余额查询。

---

## 8. 数据与存储

| 路径 | 用途 |
|:---|:---|
| `data/signal_history.db` | 信号（优先） |
| `data/.paper_trading.db` | 纸面账户 |
| `data/agent_audit.jsonl` | **新增** Harness 审计（P0） |
| `.runtime/agent/` | 可选：单次 thesis 暂存（gitignore） |

---

## 9. 里程碑（文本驱动排期）

| 里程碑 | 交付物 | 退出标准 |
|:---|:---|:---|
| **M0 — PRD 冻结** | 本文档 + [ACCEPTANCE.md](./ACCEPTANCE.md) | 你确认 Open Questions |
| **M1 — 契约** | `contracts/`、`manifest v2`、JSON 信封 helper | AC-01～AC-03 绿 |
| **M2 — 写路径** | `submit-thesis`、`audit.jsonl` | AC-10～AC-14 绿 |
| **M3 — 报告与文档** | `paper-report`、SKILL/AGENTS 更新 | AC-13、AC-20 绿 |
| **M4 — V2.0 tag** | `freeze_verify` 扩展、README | 全 P0 AC 绿 |

实现任务拆解见 [MILESTONES.md](./MILESTONES.md)（工程 checklist，随 PRD 更新）。

---

## 10. 开放问题（需产品确认）

| # | 问题 | 建议默认 |
|:---|:---|:---|
| Q1 | V2.0 是否必须 `context-audit` 才能 `submit-thesis`？ | **否**；thesis-only MVP，audit 放 V2.1 |
| Q2 | 多 symbol 并行 thesis？ | V2.0 单次 CLI 单 symbol；批处理 V2.1 |
| Q3 | thesis 与本地 `signal_history` 方向不一致时？ | **warn + 可配置 reject** |
| Q4 | 美股非 RTH 是否允许 paper？ | **允许**（纸面），标注 `limitations` |
| Q5 | 版本号：发 `v2.0.0` 还是继续 `1.x`？ | 对外 **v2.0.0**（产品代际清晰） |

---

## 11. PRD 驱动研发约定

1. **唯一需求源**：功能以本文档 FR/NFR 编号为准；实现 PR 标题注明 `FR-xx`。
2. **先改验收再写码**：[ACCEPTANCE.md](./ACCEPTANCE.md) 与 FR 同步更新。
3. **Agent 可自检**：每个里程碑更新 `manifest.json` 与示例 JSON。
4. **不扩 scope**：P1/P2 不得 sneak into P0；若必须，先改 PRD 版本号。
5. **周节奏**：M0 确认 → M1 契约 → M2 写路径 → M3 封 tag。

---

## 12. 追溯

| PRD 章节 | 实现落点（计划） |
|:---|:---|
| FR-10～14 | `src/tradecat/agent/`、`src/tradecat/cli/agent.py` |
| FR-03 | `src/tradecat/agent/envelope.py` |
| FR-14 | `src/tradecat/agent/audit.py` |
| FR-01 | `skills/tradeagnt/agents/manifest.json` |
| 验收 | `tests/test_agent_harness_*.py`、`scripts/v2_verify.sh` |

历史路线图：[V1_AGENT_HARNESS.md](../V1_AGENT_HARNESS.md)（已由本文档 supersede 实现优先级）。
