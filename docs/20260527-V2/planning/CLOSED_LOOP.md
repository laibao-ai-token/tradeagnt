# V2 核心 — 交易闭环与正反馈（Harness 硬工程）

> **优先级**：高于 TUI 布局细化。  
> **目标**：可持续的 **模拟交易闭环**（非一次性的「看一下分析」）。  
> 依赖：P4 数据基建 · P5 R2/R3/R4 · P6 不与 daemon 抢写。

---

## 1. 什么叫「闭环」（不是 TOI 好不好看）

```text
        ┌──────────────────────────────────────────┐
        │           正反馈（下一轮输入）              │
        │  audit 摘要 / PnL 变化 / 拒绝原因 / 模式建议 │
        └──────────────────▲───────────────────────┘
                           │
  ① Observe 观察          │          ⑤ Learn 调参/改模式
  行情/信号/资讯/TUI 快照   │          人切 R2 或收紧 R3 规则
           │               │
           ▼               │
  ② Orient  评估          │          ④ Measure 度量
  新鲜度/风控/与信号一致     │          纸面 PnL、持仓、滑点模拟
           │               │          audit + paper-report
           ▼               │
  ③ Decide  决策          │
  thesis（Pi 起草）        │
           │               │
           ▼               │
  ③b Gate   硬闸门         │
  schema + fail-closed     │
  R2:人采纳 R3/R4:评估服务  │
           │               │
           ▼               │
  ④ Act     执行           │
  submit → PaperEngine     │
  （仅模拟盘）              │
           └───────────────┘
```

**可持续性** = 每一圈都有 **可观测结果** → **可解释**（audit）→ **可调整**（模式/规则/人），而不是 Agent 自说自话。

---

## 2. 自动化在 V2 里「长什么样」（对应 P5）

| 档位 | 自动化体现 | 正反馈入口 |
|:---|:---|:---|
| **R2** | 人采纳后才 Act；循环由 **人触发** 下一轮 | 人看 KPI + audit 拒绝原因 |
| **R3** | **评估服务**自动跑 ②→③b→④；周期可配置（非对话连播） | `evaluation_report` 写入 audit；不达标则 **拒绝** 并记因 |
| **R4** | 放宽 R3 触发条件/标的池；仍 **必须先评估** | 同上 + 聚合 metrics（如连续拒绝次数→建议降档 R2） |

**禁止**：无评估的裸循环下单（「while True 买」）。

---

## 3. 硬工程组件（要实现什么，不只是 Pi 聊天）

| 组件 | 职责 | 产物 |
|:---|:---|:---|
| **A. Trade tools** | 现有 `tradecat_get_*` + TUI 快照 | JSON 观察层 |
| **B. Thesis + schema** | `agent_trade_thesis.v1` 校验 | 可审计决策输入 |
| **C. Evaluation** | R3/R4：**信号新鲜度、风控、与本地信号方向、最小盈亏比占位** | `evaluation_pass/fail` + 原因码 |
| **D. Gate + submit** | fail-closed → `PaperTradingEngine` | accept/reject |
| **E. Audit journal** | 每圈一条：`observe→evaluate→act→measure` 摘要 | `data/agent_audit.jsonl` |
| **F. Measure API** | `tradecat agent paper-report`、右 TUI KPI | PnL、持仓、最近 N 笔 |
| **G. Loop scheduler** | R3/R4：**定时或事件** 触发一轮（如每 5m、或信号 DB 新行） | 可配置；默认 **关** |
| **H. Feedback pack** | 把 E+F 压成 **Pi 下一轮的 system 附加块**（≤N 行） | 正反馈，非全文灌上下文 |

**Pi** = 左栏 **编排与对话**；**B～H 为 Python 硬层**（可持续性的主体）。

---

## 4. 正反馈循环（最小可行）

### 单轮（tick）

1. 读 **Feedback pack**（上轮 PnL、上次 reject code、当前模式 R?）。
2. Observe：`context_pack` + TUI 快照。
3. Decide：Pi 产 thesis（或 R3 由评估服务直接产）。
4. Gate + Act。
5. Measure：paper-report + 写 audit。
6. 生成 **下轮 Feedback pack**（给步骤 1）。

### 跨轮（可持续）

| 信号 | 动作 |
|:---|:---|
| 连续 N 次 `evaluation_fail` | 建议/UI 提示 **降回 R2** |
| 纸面回撤 > 阈值 X | R3/R4 **暂停** Act，只 Observe |
| 人切 R2 | 清空自动 scheduler，只保留手动 tick |

---

## 5. 与「只看 TUI 做得怎么样」的区别

| 界面层（次要） | 闭环层（**关键**） |
|:---|:---|
| 左 Pi 右 TUI 布局 | Evaluation + Gate + Audit + Scheduler |
| 模式切换按钮 | R2/3/4 **行为差异** 是否真接 Engine |
| 步骤摘要 UI | **Feedback pack** 是否驱动下一轮 |

**验收**应优先：**跑满 24h 模拟、audit 可追溯、R3 拒绝率可解释**，而非截图双栏。

---

## 6. 建议实现分期（写进 P8）

| 阶段 | 交付 | 闭环能力 |
|:---|:---|:---|
| **M2a** | B + D + E + F；仅 **R2** | 人驱动闭环 |
| **M2b** | C + G + H；**R3** | 自动评估闭环 |
| **M2c** | R4 参数 + 跨轮降档规则 | 渐进自动 |
| **M3** | paper-report、freeze 验收 | 可演示可持续 run |

---

## 7. 待你拍板（闭环专用，可另开 P6b 或并入 P7）

| # | 问题 |
|:---|:---|
| L1 | R3 **触发器**：定时（如 5m）还是 **signal_history 新信号**？ |
| L2 | **可持续性** 第一指标：**最大回撤** / **连续亏损笔数** / **夏普占位**？ |
| L3 | Feedback pack 给 Pi：**固定 5 行** 是否够？ |
| L4 | V2.0 是否要求 **至少跑通 1 次 R3 日循环** 才算封板？ |

---

## 变更记录

| 日期 | 说明 |
|:---|:---|
| 2026-05-28 | 用户强调：重心为 Harness 硬工程与正反馈闭环，非布局 |
