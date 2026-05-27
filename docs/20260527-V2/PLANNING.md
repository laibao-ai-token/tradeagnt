# tradeagnt V2 逐点规划表

> **用法**：一次只填一行。你拍板 → 主 Agent 写入「决策」列 → 再进下一行。  
> 分支：`v2/agent-harness` · 协作：[CONTROL_PLANE.md](../CONTROL_PLANE.md) · 现状：[EXEC_SUMMARY.md](./EXEC_SUMMARY.md)

**状态图例**：`⬜ 未讨论` · `🟡 讨论中` · `✅ 已锁定` · `❌ 不做/推迟`

---

## 总进度

| 已锁定 | 讨论中 | 未讨论 |
|:---:|:---:|:---:|
| 0 / 9 | 1 / 9（P1） | 8 / 9 |

分点讨论页：`planning/` 目录（[索引](./planning/README.md)）。

---

## 规划议程（逐行填充）

| 序号 | 主题 | 要拍板什么 | 状态 | 决策（拍板后填写） | 备注 |
|:---|:---|:---|:---:|:---|:---|
| **P1** | [产品定位与边界](./planning/P1-positioning.md) | V2 是什么 / 明确不做啥 | 🟡 | **Agent 原生交易研究 Harness**（彭博交易员式工具链 + Codex 式 Agent 调用；纸面非实盘） | 待你回「P1 锁定」 |
| **P2** | [主用户与主路径](./planning/P2-users-path.md) | Agent 主、人辅到什么程度 | ⬜ | | |
| **P3** | [最小闭环](./planning/P3-min-loop.md) | 从读数据到 paper 最少几步 | ⬜ | | |
| **P4** | [信号与行情](./planning/P4-signals-quotes.md) | 本地策略 vs 公开表 vs Agent 自备 | ⬜ | | |
| **P5** | [写入与闸门](./planning/P5-gates.md) | 仅 thesis？要不要 context-audit？ | ⬜ | | |
| **P6** | [与 V1 共存](./planning/P6-v1-coexist.md) | TUI、daemon、双分支怎么并存 | ⬜ | | |
| **P7** | [安全与 fail-closed](./planning/P7-safety.md) | 缺字段、非 RTH、反向信号 | ⬜ | | |
| **P8** | [V2.0 范围](./planning/P8-scope-v20.md) | 首版 tag vs V2.1 | ⬜ | | |
| **P9** | [验收与协作](./planning/P9-acceptance.md) | AC 汇报、何时封 v2.0.0 | ⬜ | | |

---

## 与 PRD 的关系

| 文档 | 角色 |
|:---|:---|
| **本文件 PLANNING.md** | 你与主 Agent **逐点拍板**（短、一行一行填） |
| [PRD.md](./PRD.md) | 拍板完成后，主 Agent **汇总写入**正式需求 |
| [EXEC_SUMMARY.md](./EXEC_SUMMARY.md) | 给你的 **一页现状**（含「规划进度」摘要） |

**规则**：PLANNING 未 ✅ 的行，不当作已批准需求写进代码。

---

## 变更记录

| 日期 | 变更 |
|:---|:---|
| 2026-05-27 | 初建规划表（9 行议程） |
