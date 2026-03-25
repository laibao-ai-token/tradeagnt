---
title: "003-07-office-hours-agent-quant-decision-loop"
status: open
created: 2026-03-21
updated: 2026-03-21
owner: lixh6
priority: high
type: feature
---

# 003-07 Office Hours 结论：Agent 量化决策闭环（中文稿）

## 背景与结论

- `006-backtest` 已完成并验收，可作为稳定底座复用。
- `003` 当前是“部分完成”：双 TUI 工作台与能力桥已具备，但 Agent 交易决策闭环未打通。
- 当前核心不是继续做研究展示，而是补齐 `003-B`：让 Agent 基于现有数据形成可执行、可解释、可复盘的决策链路。

> 本文档由 2026-03-21 的 office-hours 产出转换为仓库内中文版本，作为 `003-B` 主线执行依据，并用于驱动 `007` 的 paper 验证。

## 问题定义

TradeCat 已具备行情/信号/新闻/回测能力，但还缺少从“数据输入”到“交易动作”的自动化闭环。  
目标是先在模拟盘环境跑通稳定链路，而不是先追求实盘收益。

## 目标用户（首个楔子）

- 用户画像：非全职交易者、碎片化时间、稳健偏好、当前以观望为主。
- 第一阶段范围：
  - 市场：Crypto
  - 执行上下文：Perp（现货后置到 v1.1）
  - 标的：`BTCUSDT`、`ETHUSDT`
  - 执行模式：Paper Only

## 推荐方案（已选 A）

### A. 单市场完整闭环（推荐）

最小但完整的链路：

`数据读取 -> 决策生成 -> 风控校验 -> 模拟执行 -> 账本与日报`

为什么选它：

1. 范围最小但不是残缺版，能最快证明 Agent 的交易能力。
2. 完全复用现有桥接命令与 006 产物。
3. 可以在 7-14 天内产出硬证据（行为数据 + 稳定性数据）。

## V1 术语与固定默认值

### 核心术语

- 可执行决策：包含 `ts/cycle_id/symbol/side/size_pct/confidence/reason_codes/risk_checks/action_id` 的 JSON 记录。
- 风险断路器（Risk Breaker）：触发后当日禁止开新仓，仅允许 `exits-only`（持仓管理/平仓）。
- 硬证据：连续 7 天 paper 运行 + 每天至少 2 次回看标注（回看标注不阻塞执行）。

### 固定默认值（V1）

| 项目 | 默认值 |
| --- | --- |
| 市场范围 | Crypto |
| 执行上下文 | Perp（Spot 延后） |
| 标的 | BTCUSDT, ETHUSDT |
| 决策频率 | 固定每 15 分钟 |
| 每标的最大仓位 | 20% |
| 总风险敞口上限 | 40% |
| 单日风险上限 | 日回撤到 `-2.0%` 停止新开仓 |
| 连续亏损断路 | 连亏 3 笔停止新开仓 |
| 日边界 | UTC 00:00-23:59 |
| 日重置语义 | UTC 00:00 重置日回撤/连亏计数，并开启新日报窗口 |
| 成本假设 | fee 6bps/side，slippage 4bps/side，funding v1 忽略 |
| 去重键 | `cycle_id = symbol + timeframe + cycle_start_ts`（持久化唯一约束） |

## 交付里程碑（防发散）

### M1（必须）

- 决策 + 风控 + 账本
- 输入仅用 `quotes + signals`
- 输出 `decision jsonl + ledger csv`
- Gate：连续 48h 无人值守运行通过

### M2（必须）

- 日报自动化
- 输出：`PnL / Drawdown / HitRate / mistake taxonomy`
- Gate：连续 7 天日报完整生成

### M3（可选，证据充分后再做）

- 加入 `news/backtest-summary` 作为决策理由增强
- 不改变执行链路契约

## 失败状态矩阵（V1）

| 状态 | 检测 | 回退动作 | 恢复策略 |
| --- | --- | --- | --- |
| 行情过期 | quote age > 120s | 本轮 `hold` 并标记 `data_stale` | 数据恢复后自动继续 |
| 信号缺失 | signal payload 为空 | 本轮 `hold` | 下一周期自动重试 |
| 上游超时 | tool > 10s | 退避 5s 重试 1 次，失败则 `hold` | 下周期继续 |
| 重复触发 | 同 `cycle_id` 再次触发 | 丢弃重复 | 无需人工介入 |
| 进程重启 | pid 变化且上轮未完成 | 回放最近账本快照后继续 | 一个周期内恢复 |
| 日报失败 | report 任务非 0 退出 | 保留原始产物并重试 1 次 | 下一窗口继续 |

## 验收标准（14 天内）

1. 固定频率产生 BTC/ETH 机器可读决策记录。
2. 每条决策都有显式风控检查结果（pass/fail reason）。
3. Paper 账本完整记录开平仓、仓位、理由、止损条件。
4. 每日自动输出 PnL/回撤/命中率/错误分类报告。
5. 连续 7 天运行，漏周期不超过 1 个间隔。
6. 48h 干跑通过：重启恢复 + 幂等去重均可验证。
7. Risk Breaker 触发后 1 个周期内进入 `exits-only` 并可追踪原因。

## 依赖与复用

- 现有桥接命令：
  - `scripts/tradecat_get_quotes.py`
  - `scripts/tradecat_get_signals.py`
  - `scripts/tradecat_get_news.py`
  - `scripts/tradecat_get_backtest_summary.py`
- 现有回测底座：`006-backtest` 产物与指标口径。
- 运行保障：调度器 + watchdog + append-only 产物目录。

## 两周执行建议（可直接派单）

1. 第 1-3 天：落地 M1（决策记录、风控闸门、paper ledger、cycle_id 唯一约束）。
2. 第 4-5 天：落地 M2（日报、错误分类、恢复/重试可观测字段）。
3. 第 6-7 天：48h 干跑，修复稳定性问题。
4. 第 8-14 天：正式 7 天 paper 验证，形成是否进入 limited-live 的结论。

## 子 Issue 拆分（2026-03-21，可派 Sym）

1. `#003-07-01`：`003-07-01-feature-agent-decision-loop-contract-and-cycle.md`
2. `#003-07-02`：`003-07-02-feature-agent-risk-guard-and-breaker-policy.md`
3. `#003-07-03`：`003-07-03-feature-paper-ledger-idempotency-and-recovery.md`
4. `#003-07-04`：`003-07-04-feature-paper-daily-report-and-mistake-taxonomy.md`
5. `#003-07-05`：`003-07-05-feature-48h-dryrun-and-7d-paper-validation-gate.md`

## 并行建议（Sym）

- 第一批先做：`#003-07-01`
- 第二批并行：`#003-07-02` + `#003-07-03`
- 第三批串行收口：`#003-07-04` -> `#003-07-05`

## 待后置问题（v1.1）

- funding-rate 是否纳入 PnL 分解。
- 是否做波动率自适应 cadence。
- spot 执行上下文接入。
