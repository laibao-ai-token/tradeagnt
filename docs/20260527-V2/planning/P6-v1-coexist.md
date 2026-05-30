# P6 — 与 V1 共存

| 字段 | 值 |
|:---|:---|
| 状态 | ✅ 已锁定（2026-05-28，架构层） |
| 总表 | [PLANNING.md](../PLANNING.md) § P6 |
| **工程重心** | → [CLOSED_LOOP.md](./CLOSED_LOOP.md)（交易闭环与正反馈，**优先于布局细节**） |

## 决策（已锁定 — 架构）

| # | 决策 |
|:---|:---|
| **6a** | `tradeagnt` = v1 hotfix；`v2/agent-harness` = V2 开发 |
| **6b** | **一套 TUI**；`tradecat tui` = V1 全屏；`tradecat harness`（或 `--harness`）= 左 Pi + 右 TUI |
| **6c** | V2 双栏 **默认关** `auto_consumer`；R3/R4 仅走评估链写 paper |
| **6d** | `TRADEAGNT_AGENT_MODE=1` 禁 auto_consumer 写 paper；`TRADEAGNT_EXEC_MODE=R2\|R3\|R4` |
| **6e** | **保留** v1 路径（无 Pi 仍可跑） |

> 布局/分支为实现细节；**可持续性闭环**见 [CLOSED_LOOP.md](./CLOSED_LOOP.md)。
