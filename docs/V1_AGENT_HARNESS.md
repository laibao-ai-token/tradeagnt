# tradeagnt v1 — Agent Harness 路线图（摘要）

> **V2 实现以 [pi/docs/trade-agent/20260527-V2/PRD.md](../../pi/docs/trade-agent/20260527-V2/PRD.md) 为唯一需求源**；本文档保留 v1.0 基线与官方对照索引。

v1.0 **已封板**的是：独立仓库 + 单体运行 + **Agent 只读工具层**（`tradecat_get_*` + `manifest.json`）。

v2.0 起按 [pi V2 PRD](../../pi/docs/trade-agent/20260527-V2/PRD.md) 文本驱动研发；可参考官方 TradeCat Public（外部仓库，**非本仓子模块/远程**）**逐特性引入**，不整仓 merge。

## 已对齐官方（v1.0）

| 官方能力 | tradeagnt v1.0 |
|:---|:---|
| 只读 JSON 入口 | `scripts/tradecat_get_*.py` |
| 一次拉齐上下文 | `tradecat_get_context_pack.py` |
| 机器命令表 | `skills/tradeagnt/agents/manifest.json` |
| 编码 Agent 说明 | `AGENTS.md` |

## 计划引入（优先级）

**P0 — Harness 闭环（v1.1）**

- `agent_trade_thesis` JSON 入参 + schema 校验（参考官方 `contracts/`）
- `tradecat agent submit-thesis` → 现有 paper 引擎，fail-closed
- 扩充 manifest：`command_risk_classes`、freshness、统一 `{ok,data,error,warnings}`

**P1 — 对齐官方硬层（v1.2）**

- context audit / strategy_intent 命名与报告结构
- paper ledger 审计 journal（SQLite JSONL）
- `run-tradecat.sh` 风格子命令或等价 CLI 组

**P2 — 可选**

- Hermes skill 挂载文档（`skills/tradeagnt/SKILL.md`）
- 公开表格信号源适配（仅当产品需要；默认仍用本地策略信号）
- 官方 soft-layer prompt 资源（改为我们多市场语境）

## 明确不照搬

- 放弃 TUI / 129 规则引擎作为官方主路径
- 不强绑 Binance-only、公开 Google 表为唯一信号源
- 不实盘 executor

## 参考克隆路径（本地对照）

| 路径 | 说明 |
|:---|:---|
| 本仓 | `tradeagnt` 分支 |
| 官方新版 | `../tradecat-upstream` |
| 自家旧 main | `../tradeagnt-main-snapshot` |
