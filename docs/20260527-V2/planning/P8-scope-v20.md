# P8 — 发版范围与迭代策略

| 字段 | 值 |
|:---|:---|
| 状态 | ✅ 已锁定（2026-05-28） |
| 总表 | [PLANNING.md](../PLANNING.md) § P8 |

## 决策（已锁定）

- **不做一次性大 bang 发 `v2.0.0` 才开工**；采用 **持续迭代**，做到哪、验收到哪、**小版本 tag**。
- **当前目标**：先交付 **V2 Base**（可 tag `v2.0.0-base` 或 `v2-base`，名实现时定），再在其上叠加 R3/R4、闭环调度等。

### 版本梯队（产品层）

| 版本 | 目标 | 包含（建议） |
|:---|:---|:---|
| **v2-base** | 能「跟 Pi 聊 + 用 tradeagnt 能力 + 手动闭环」 | Pi Extension；`tradecat_get_*`；右 TUI；**R0/R1/R2**；submit + audit + paper-report；**CLOSED_LOOP 手动 tick** |
| **v2.0.1+** | 半自动可持续 | **R3** 评估服务 + 调度；Feedback pack |
| **v2.0.2+** | 高自动 | **R4** 放宽；跨轮降档规则 |
| **v2.1+** | 增强 | context-audit、新数据源、Pi 嵌入优化等 |

> **P5 的 R3/R4「必做」** = 产品路线图必做，**不强制全挤进 v2-base**。

### 技术选型（已选型，实现随迭代）

- **Agent**：Pi + Extension 调 Python（见 [PI_RUNTIME.md](./PI_RUNTIME.md)）。
- **嵌入**：v2-base 可用 **子进程调脚本**；pi-tui 同屏可 v2.0.1。

### 分支

- 开发仍在 **`v2/agent-harness`**；小版本 tag 打在 harness 线；**合并 `tradeagnt` 主分支** 按你方便时进行。

## 主 Agent 记录

- 2026-05-28：用户 — 持续迭代，先 V2 Base，不现在定完整 v2.0.0 范围。
