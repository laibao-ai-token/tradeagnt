---
title: "003-07-01-feature-agent-decision-loop-contract-and-cycle"
status: open
created: 2026-03-21
updated: 2026-03-21
owner: lixh6
priority: high
type: feature
---

# 003-07-01：Agent 决策契约与周期循环骨架

## 背景

`003-B` 需要先固定一个稳定决策契约，否则后续风控、账本、日报都无法解耦并行推进。

## 目标

落地 V1 决策记录契约与固定周期（15m）循环骨架，作为 `003-07` 的统一输入输出接口。

## 本期范围

1. 固定决策记录字段（最小必填）：
   - `ts, cycle_id, symbol, side, size_pct, confidence, reason_codes, risk_checks, action_id`
2. 固定执行范围：
   - 市场 `crypto`
   - 上下文 `perp`
   - 标的 `BTCUSDT, ETHUSDT`
3. 固定调度策略：
   - 每 15 分钟触发一次决策循环
4. 固定周期幂等键：
   - `cycle_id = symbol + timeframe + cycle_start_ts`

## 非目标

- 不做实际下单（仅 paper）
- 不把具体外部 runtime / UI 绑定进本单
- 不修改数据库 schema

## 预期落点

- `services-preview/tui-service/src/`（如需读状态展示）
- `scripts/` 下新增或扩展 decision loop 入口脚本
- `docs/learn/` 下补最小契约说明（如有）

## 验收标准

- [ ] 每 15 分钟能为 BTC/ETH 生成机器可读决策记录
- [ ] 决策 JSON 字段完整、枚举稳定（`BUY|SELL|HOLD`）
- [ ] 每条记录包含 `cycle_id` 且可被下游复用
- [ ] 缺数据场景下可降级为 `HOLD` 并打标原因

## 依赖关系

- Parent: `#003-07`
- 下游依赖本单：`#003-07-02`, `#003-07-03`, `#003-07-04`, `#003-07-05`

## Sym 派单建议

- 优先级：P0（必须先完成）
- 并行性：独占先做，完成后再放开后续并行
