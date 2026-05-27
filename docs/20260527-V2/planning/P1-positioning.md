# P1 — 产品定位与边界

| 字段 | 值 |
|:---|:---|
| 状态 | 🟡 待你确认锁定 |
| 总表 | [PLANNING.md](../PLANNING.md) § P1 |

---

## 要拍板什么

1. **V2 一句话定义**是什么？
2. **V2.0 明确不做**哪些事（防止跑偏）？

---

## 选项（请择一或改写）

### V2 是什么

| 选项 | 描述 |
|:---|:---|
| **A（建议）** | **Agent Harness**：Agent 只读研究 → 提交 thesis → 系统闸门 → **仅纸面**；人监督。 |
| B | A + 与现有 signal daemon 同等优先级（谁写 paper 另议，放 P6） |
| C | 对齐官方 Public 为主（公开表信号 + 整包 tradecat_auto），弱化本地 TUI/129 |

### V2.0 明确不做（建议写死）

- 实盘、签名下单、读 API 密钥
- 7×24 TimescaleDB 全量管线纳入 V2.0
- 删除 TUI（可保留监控，见 P6）
- 整仓 merge 官方 Public 仓库

### 建议一句边界

> V2 **不替换** V1 已封板的 demo；在 V1 只读工具之上，补上 **Agent 可提交、可审计的纸面闭环**。

---

## 决策（拍板后填写）

- **选定选项**：**Trade-layer Claude Code / Codex**（用户 2026-05-27 明确）。
- **补充说明（用户原意摘要）**：
  - **要什么**：不是「多几个 JSON 脚本」，而是 **交易垂直领域的 Claude Code / Codex**——同一套 Agent 范式（仓库上下文 + 工具调用 + 多步规划 + 可审计产出），落在 **trade** 层。
  - **彭博隐喻**：交易员 = 在数据环境里连续调研再决策；我们用 **工具链** 替代人点终端 Tab。
  - **我们提供**：trade 专用上下文（symbol、市场、策略剖面）+ 工具（行情、信号、资讯、回测等）+ 可选纸面闸门；Agent 像写代码一样 **串行调工具、改假设、再验证**。
  - **执行边界**：纸面 / simulation，非实盘；具体命令与 schema 在 P3/P5 拆。

### 建议写入 PRD 的一句话定位

> **tradeagnt V2 = Trade-layer Claude Code**：在 tradeagnt 仓库内为 Agent 提供与 Claude Code/Codex 同构的「上下文 + 工具 + 多步研究」体验，工具面覆盖行情/信号/资讯/回测，产出可审计的交易假设与纸面结果；人类不主路径操作。

### V2.0 明确不做（与上述一致）

- 实盘、签名、读密钥
- 以人类 TUI 点击为主路径
- V2.0 内建完整彭博终端级 UI（只做 Agent 工具 + 可选监控）
- 整仓替换为官方 Public / 公开表唯一信号源

---

## 主 Agent 记录

- 2026-05-27：用户给出 P1 方向（Agent 中心 + 彭博交易员隐喻 + Codex 式工具链）。
- 2026-05-27：用户强调 **要做 trade 层级的 Claude Code / Codex**，非泛 API 集合。
- 待用户回复 `P1 锁定` 后标 ✅，并进入 P2。

### 与 Claude Code / Codex 的对照（P1 锚点）

| Claude Code / Codex | tradeagnt V2（trade 层） |
|:---|:---|
| 仓库 + 代码上下文 | 仓库 + **市场/策略/账户** 上下文（context_pack 等） |
| 读文件、跑终端、改代码 | **tradecat_get_***、回测摘要、（后续）submit-thesis、paper-report |
| 多步 plan → act → observe | 调研 → 分析 → 假设 → 纸面验证 |
| 人监督、Agent 执行 | 同上；TUI 降为可选监控 |
