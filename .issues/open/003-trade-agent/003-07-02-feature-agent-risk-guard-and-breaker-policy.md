---
title: "003-07-02-feature-agent-risk-guard-and-breaker-policy"
status: open
created: 2026-03-21
updated: 2026-03-21
owner: lixh6
priority: high
type: feature
---

# 003-07-02：Agent 风控闸门与断路器策略

## 背景

`003-B` 的核心要求不是“有决策”，而是“有约束的决策”。必须有统一风控闸门和可审计断路器。

## 目标

在决策链路上实现 V1 风控规则，保证超限时自动进入 `exits-only`，并保留可审计原因。

## 本期范围

1. 风控阈值（V1）：
   - 每标的最大仓位 20%
   - 总敞口上限 40%
   - 单日回撤到 `-2.0%` 停止新开仓
   - 连续亏损 3 笔停止新开仓
2. 断路器策略：
   - 触发后进入 `exits-only`
   - 1 个周期内生效
3. 风控检查字段标准化：
   - `max_position_ok, max_exposure_ok, daily_loss_ok, breaker_ok`
4. UTC 日边界重置：
   - `00:00` 重置日回撤计数与连亏计数

## 非目标

- 不扩展多市场参数模板
- 不做实盘风控联动
- 不做策略 alpha 优化

## 预期落点

- `services/signal-service/src/`（风控规则实现或复用）
- `scripts/`（风控检查与决策落地桥接）
- `docs/learn/`（风险策略说明）

## 验收标准

- [ ] 每条决策都有完整风控检查结果与 pass/fail 原因
- [ ] 风控触发后 1 个周期内进入 `exits-only`
- [ ] UTC 00:00 重置语义生效且可验证
- [ ] 风控失败场景不崩溃，自动降级 `HOLD` 或 `exits-only`

## 依赖关系

- Parent: `#003-07`
- Depends on: `#003-07-01`
- Next: `#003-07-05` 验证风险门槛效果

## Sym 派单建议

- 优先级：P0
- 并行性：可与 `#003-07-03` 并行
