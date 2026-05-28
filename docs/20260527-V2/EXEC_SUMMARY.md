# V2 执行摘要（决策者只看这一页）

> 最后更新：2026-05-27 · 维护者：主 Agent · 分支：`v2/agent-harness`  
> 协作规则：[../CONTROL_PLANE.md](../CONTROL_PLANE.md)

---

## 一句话

**V2 = Trade-layer Claude Code / Codex**（在 trade 域复刻「上下文 + 工具 + 多步 Agent」；行情/信号/资讯/回测 → 分析 → 纸面闸门；人监督，非实盘）。  
V1 已封板在 `tradeagnt`；V2 在独立分支上按 PRD 文本推进。

---

## 你现在需要知道的（≤10 条）

| # | 事实 |
|:---|:---|
| 1 | v1.0 已 tag，人类主路径仍是 TUI + 只读 `tradecat_get_*` |
| 2 | V2 文档在 **`docs/20260527-V2/`**（时间戳目录，本轮需求包） |
| 3 | **你不必读** `PRD.md` 全文，除非要改范围；细节问我或看本页 |
| 4 | 开发分支：**`v2/agent-harness`**（已从 v1.0 拉出并推送） |
| 5 | 文档包内三件套：`PRD`（要什么）、`ACCEPTANCE`（怎么算做完）、`MILESTONES`（工程 checklist） |
| 6 | 示例 thesis JSON 在 `examples/agent_trade_thesis.example.json`（给以后 submit 用） |
| 7 | **代码还没做**：`tradecat agent submit-thesis` 等是 PRD 目标，当前是 **M0 文档阶段** |
| 8 | 等你拍板 PRD 里 5 个开放问题（见下「等你」）后，才能标 M0 Approved、开 M1 写码 |
| 9 | **你我每一轮对话**都走 [CONTROL_PLANE](../CONTROL_PLANE.md) CEO 摘要，不只子任务结束后 |
| 10 | 子 Agent 只干活；**你永远只和主 Agent 一个人对齐** |

---

## V2 规划进度（逐点填充）

→ 总表：[PLANNING.md](./PLANNING.md) · 分点页：[planning/](./planning/)（**P1✅ P2✅ P3✅ · 下一步 P4**，3/9 已锁定）

**P3 已锁定**：左 **Pi**（非自研）+ 右 **TUI 看板**；Pi 可读 TUI（symbol/价/盈亏/信号等）；V2 先只研究工具、不模拟下单、不自动下一轮。

---

## 里程碑状态

| 阶段 | 状态 | 对你意味着什么 |
|:---|:---|:---|
| M0 PRD/AC/分支 | ✅ 文档与分支已就绪 | 可开始「V2 研发」，但范围需你点头 |
| M1 契约（schema、manifest v2） | ⬜ 未开始 | 做完后 Agent 工具表会变，仍不影响 v1 分支 |
| M2 submit-thesis + 审计 | ⬜ 未开始 | **V2 核心能力**，Agent 才能「驱动 trade」 |
| M3 封 v2.0.0 | ⬜ 未开始 | 全 P0 验收绿 |

---

## 等你拍板（回复一句即可）

PRD 建议默认——你可回「全部默认」或逐条改：

| 问题 | 建议 |
|:---|:---|
| Q1 是否必须先 context-audit？ | **否**，先 thesis |
| Q2 一次是否多 symbol？ | **否**，V2.1 再做 |
| Q3 thesis 与本地信号反向？ | warn，可配置 reject |
| Q4 美股非交易时段 paper？ | **允许** |
| Q5 版本号 | **v2.0.0** |

---

## 文件地图（防迷路）

```text
docs/CONTROL_PLANE.md          ← 你与主 Agent 怎么协作（读一次即可）
docs/20260527-V2/
  EXEC_SUMMARY.md              ← 本文件（每次会话先看）
  PRD.md                       ← 完整需求（主 Agent / 子 Agent 用）
  ACCEPTANCE.md                ← 验收编号 AC-xx（你只听摘要）
  MILESTONES.md                ← 工程勾选（你只听摘要）
  examples/*.json              ← 示例数据
```

---

## 最近交付（changelog 极简）

- 建立 `docs/20260527-V2/` 文档包
- 创建并推送分支 `v2/agent-harness`
- v1 线 `tradeagnt` 保持 v1.0 封板点不动

---

## 下一步（主 Agent 建议）

1. 你确认 Q1～Q5 → 我把 PRD 标为 Approved。  
2. 在 `v2/agent-harness` 开 **M1**（只契约，不改交易逻辑）。  
3. 用子 Agent 做实现时，我只向你更新本页 + 短汇报。
