# P9 — 验收与协作

| 字段 | 值 |
|:---|:---|
| 状态 | ✅ 已锁定（2026-05-28） |
| 总表 | [PLANNING.md](../PLANNING.md) § P9 |

## 决策（已锁定）

### 协作（对你）

- 仍用 [CONTROL_PLANE.md](../../CONTROL_PLANE.md)：**CEO 摘要** + [EXEC_SUMMARY.md](../EXEC_SUMMARY.md)。
- 每个 **小版本** 结束：更新 EXEC_SUMMARY + 该版本 **3～5 条 AC**（不一次灌完全部 AC）。

### 验收方式 — 跟发版迭代走

| 原则 | 说明 |
|:---|:---|
| **分段验收** | 每个迭代 tag 有 **自己的 AC 子集**，绿了才算该段完成 |
| **首段** | **v2-base** 验收（见下），**不要求** R3/R4/日级自动循环 |
| **后续段** | v2.0.1 验 R3；v2.0.2 验 R4；依 [P8](./P8-scope-v20.md) |
| **文档** | [ACCEPTANCE.md](../ACCEPTANCE.md) 作总表；每段在 MILESTONES 打勾 |

### v2-base 最小验收（建议 AC 子集）

| AC | 内容 |
|:---|:---|
| B-01 | Pi（或等价）能调 `tradecat_get_context_pack` |
| B-02 | `tradecat agent submit-thesis` R2 路径：采纳后 paper 或明确 reject |
| B-03 | `data/agent_audit.jsonl` 有记录 |
| B-04 | 右 TUI 与 v1 同套代码可跑；`TRADEAGNT_AGENT_MODE=1` 时 auto_consumer 不抢写 |
| B-05 | `freeze_verify` / v2-base 子集 pytest 绿 |

> **不** 在 v2-base 要求：24h R3 循环、R4、完整双栏 Pi 嵌入（可部分占位）。

### 封 tag 节奏

- **不** 等「完整 V2」才打第一个 tag → **v2-base 绿了就打 v2-base tag**。
- 完整 `v2.0.0` 可在 R3/R4 都迭代完后再说，或改名为「产品线 GA」。

## 主 Agent 记录

- 2026-05-28：用户 — 按发版迭代验收；先 V2 Base，再叠功能。
