---
title: "003-07-04-feature-paper-daily-report-and-mistake-taxonomy"
status: open
created: 2026-03-21
updated: 2026-03-21
owner: lixh6
priority: medium
type: feature
---

# 003-07-04：Paper 日报与错误分类体系

## 背景

没有日报就无法判断“是否值得继续信任 Agent”。需要把运行结果变成每天可读、可比较的证据。

## 目标

自动生成日报，并输出稳定的错误分类（mistake taxonomy），支持 7 天验证期复盘。

## 本期范围

1. 日报产物：
   - `artifacts/paper_trading/reports/YYYYMMDD.md`
2. 必要指标：
   - `PnL`, `Drawdown`, `HitRate`, `Trade Count`
3. 错误分类（V1）：
   - `late_entry`, `false_breakout`, `over_position`, `ignored_news_risk`, `exit_too_late`
4. 回看标注：
   - 每日支持用户记录“是否继续信任 + 原因”

## 非目标

- 不做可视化 dashboard 重构
- 不做复杂因子归因框架
- 不做跨策略对比平台

## 预期落点

- `scripts/`（日报生成器）
- `docs/learn/`（日报字段说明）
- `artifacts/paper_trading/reports/`（落地目录）

## 验收标准

- [ ] 每日自动生成一份结构稳定的 markdown 报告
- [ ] 报告包含 PnL/回撤/命中率/错误分类统计
- [ ] 日报能关联到当日决策与账本产物
- [ ] 连续 7 天生成不中断（允许单次失败重试）

## 依赖关系

- Parent: `#003-07`
- Depends on: `#003-07-03`
- Optional enrich from: `tradecat_get_news`, `tradecat_get_backtest_summary`

## Sym 派单建议

- 优先级：P1
- 并行性：建议在 `#003-07-03` 基础上串行推进
