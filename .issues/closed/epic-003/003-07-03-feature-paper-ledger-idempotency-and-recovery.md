---
title: "003-07-03-feature-paper-ledger-idempotency-and-recovery"
status: open
created: 2026-03-21
updated: 2026-03-21
owner: lixh6
priority: high
type: feature
---

# 003-07-03：Paper 账本、幂等去重与重启恢复

## 背景

没有可靠账本与恢复机制，Agent 即使能决策也无法验证稳定性，更无法做 48h/7d 连续运行。

## 目标

实现 append-only 的 paper ledger，并确保重试/重启场景下不重复记账、不中断链路。

## 本期范围

1. 账本产物（V1）：
   - `artifacts/paper_trading/ledger/YYYYMMDD.csv`
2. 决策产物（V1）：
   - `artifacts/paper_trading/decisions/YYYYMMDD.jsonl`
3. 幂等去重：
   - 以 `cycle_id` 为唯一键避免重复写入
4. 恢复策略：
   - 进程重启后回放最近快照，1 个周期内恢复
5. 失败场景处理：
   - 超时、重复触发、缺数据场景保持可继续运行

## 非目标

- 不接入真实交易所下单
- 不做跨日归档系统重构
- 不引入新数据库 schema

## 预期落点

- `scripts/`（ledger 写入与恢复）
- `artifacts/paper_trading/`（标准目录）
- 必要时补充 `services/*/src/` 的状态读取接口

## 验收标准

- [ ] 每个周期最多落 1 条同 `cycle_id` 的账本记录
- [ ] 重试/重启后不会重复写入同一周期
- [ ] 进程重启后 1 个周期内恢复运行
- [ ] 决策与账本可按 `cycle_id` 关联追踪

## 依赖关系

- Parent: `#003-07`
- Depends on: `#003-07-01`
- Parallel with: `#003-07-02`
- Next: `#003-07-04`, `#003-07-05`

## Sym 派单建议

- 优先级：P0
- 并行性：可与风控单并行，但需共享 `cycle_id` 契约
