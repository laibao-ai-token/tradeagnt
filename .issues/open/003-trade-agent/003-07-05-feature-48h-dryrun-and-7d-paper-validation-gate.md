---
title: "003-07-05-feature-48h-dryrun-and-7d-paper-validation-gate"
status: open
created: 2026-03-21
updated: 2026-03-21
owner: lixh6
priority: high
type: feature
---

# 003-07-05：48h 干跑与 7 天 Paper 验证 Gate

## 背景

`003-B` 是否闭环必须由连续运行验证给出结论，而不是单次本地成功。

## 目标

建立统一验证 gate：先 48h 干跑，再 7 天 paper 验证，并给出是否可进入 limited-live 的明确结论。

## 本期范围

1. 48h 干跑 gate：
   - 验证重启恢复、幂等去重、周期稳定性
2. 7 天 paper gate：
   - 验证运行连续性、风险约束、日报完整性
3. 验收阈值（V1）：
   - 漏周期 <= 1/day
   - Max drawdown <= 3.0%
   - Profit factor >= 1.10
   - 所有亏损记录可归类到 mistake taxonomy
4. 输出结论：
   - `GO`（可进入 limited-live 小流量试验）
   - `NO-GO`（需返工项清单）

## 非目标

- 不直接切实盘
- 不做收益承诺
- 不替代策略研发流程

## 预期落点

- `scripts/`（dry-run / 7d gate 脚本）
- `artifacts/paper_trading/validation/`（验证报告）
- `.issues/open/003-trade-agent/`（结果回填）

## 验收标准

- [ ] 完成一次 48h 干跑并输出报告
- [ ] 完成一次连续 7 天 paper 验证并输出报告
- [ ] 明确给出 GO/NO-GO 结论与原因
- [ ] 验证报告可追溯到决策/账本/日报产物

## 依赖关系

- Parent: `#003-07`
- Depends on: `#003-07-01`, `#003-07-02`, `#003-07-03`, `#003-07-04`
- Related: `#007`（模拟盘系统主线）

## Sym 派单建议

- 优先级：P0（收口单）
- 并行性：建议最后串行执行，作为本阶段闭环判定
