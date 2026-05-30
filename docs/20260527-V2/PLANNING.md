# tradeagnt V2 逐点规划表

> **用法**：一次只填一行。你拍板 → 主 Agent 写入「决策」列 → 再进下一行。  
> 分支：`v2/agent-harness` · 协作：[CONTROL_PLANE.md](../CONTROL_PLANE.md) · 现状：[EXEC_SUMMARY.md](./EXEC_SUMMARY.md)

**状态图例**：`⬜ 未讨论` · `🟡 讨论中` · `✅ 已锁定` · `❌ 不做/推迟`

---

## 总进度

| 已锁定 | 讨论中 | 未讨论 |
|:---:|:---:|:---:|
| 9 / 9 议程 | 1 / 9（闭环 L1～L4） | 0 / 9 |

分点讨论页：`planning/` 目录（[索引](./planning/README.md)）。

---

## 规划议程（逐行填充）

| 序号 | 主题 | 要拍板什么 | 状态 | 决策（拍板后填写） | 备注 |
|:---|:---|:---|:---:|:---|:---|
| **P1** | [产品定位与边界](./planning/P1-positioning.md) | V2 是什么 / 明确不做啥 | ✅ | **Trade-layer Claude Code / Codex**（交易垂直 Agent 工具链 + 上下文；纸面非实盘） | 2026-05-27 锁定 |
| **P2** | [主用户与主路径](./planning/P2-users-path.md) | Agent 主、人辅到什么程度 | ✅ | **左 Agent / 右 TUI**；人 40/AI 60；KPI+步骤摘要；R 档位搁置 | 2026-05-27 锁定 |
| **P3** | [最小闭环](./planning/P3-min-loop.md) | 双栏交互 + Pi/TUI 分工 | ✅ | **左 Pi / 右 TUI**；TUI→Pi 最小字段；V2 先不模拟下单 | 2026-05-28 锁定 |
| **P4** | [信号与行情](./planning/P4-signals-quotes.md) | 数据从哪来 | ✅ | **沿用现有基建**（Provider/signal_history/news/回测）；新源有需求再加 | 2026-05-28 |
| **P5** | [写入与闸门](./planning/P5-gates.md) | R 模式 / 闸门 / submit | ✅ | R0–R4；**R2+R3+R4 必做可切换**；评估后自动；fail-closed | 2026-05-28 |
| **P6** | [与 V1 共存](./planning/P6-v1-coexist.md) | 分支/TUI/env | ✅ | 一套 TUI 双壳；V2 关 auto_consumer | 2026-05-28 |
| **—** | [**交易闭环**](./planning/CLOSED_LOOP.md) | 硬工程/正反馈 | 🟡 | Observe→Act→Measure→Learn | **当前重心** |
| **P7** | [安全与 fail-closed](./planning/P7-safety.md) | 安全默认 | ✅ | **全部采用默认**，不扩特别配置 | 2026-05-28 |
| **P8** | [发版与迭代](./planning/P8-scope-v20.md) | 迭代策略 / v2-base | ✅ | **持续迭代**；先 **v2-base**，R3/R4 后续小版本 | 2026-05-28 |
| **P9** | [验收与协作](./planning/P9-acceptance.md) | 分段验收 | ✅ | **按每段 tag 验收**；CEO 摘要；先 v2-base AC | 2026-05-28 |

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
