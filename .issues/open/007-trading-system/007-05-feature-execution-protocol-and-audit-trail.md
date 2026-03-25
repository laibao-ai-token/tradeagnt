---
title: "007-05-feature-execution-protocol-and-audit-trail"
status: open
created: 2026-03-18
updated: 2026-03-18
owner: lixh6
priority: high
type: feature
---

# 007-05：统一执行协议与审计回放

## 背景

交易系统进入执行阶段前，需要固定协议与审计口径，否则无法稳定复盘“为什么下单/为什么没下单”。

## 目标

定义并落地统一执行协议：

`propose -> validate -> stage -> confirm -> execute -> sync`

同时保证每一步都有可回放审计事件。

## 本期范围

1. 定义执行协议状态机与事件 schema
2. 输出 append-only 审计日志（JSONL）
3. 提供最小回放/查询入口
4. 与 `#007-03`、`#007-04` 对接

## 非目标

- 不做实盘资金调度与清算
- 不做多交易所路由
- 不修改生产 `config/.env`

## 预期落点

- `services/signal-service/src/execution_protocol/`
- `scripts/tradecat_execution_audit.py`
- `artifacts/execution_audit/`（协议事件与回放产物）
- `docs/analysis/`（协议与审计说明）

## 实现清单

### Phase 1：协议与事件

- [ ] 固定状态机与事件类型
- [ ] 约定 `trace_id / intent_id / order_id` 关联键

### Phase 2：日志与回放

- [ ] 事件写入 append-only JSONL
- [ ] 提供按 `trace_id` 回放与汇总
- [ ] 失败场景记录完整错误上下文

### Phase 3：集成与验证

- [ ] 与 paper workflow 联调
- [ ] 与 guard pipeline 联调
- [ ] 补最小 E2E 验证脚本

## 验收标准

- [ ] 六段执行协议可稳定串联
- [ ] 每次执行都有完整审计轨迹
- [ ] 可按 trace 回放单笔决策全过程
- [ ] 异常场景可定位到具体阶段与规则

## 相关 Issue

- Parent: `#007`
- Depends on: `#007-03`
- Depends on: `#007-04`

## 进展记录

### 2026-03-18

- [x] 从 `#007` 拆出 `#007-05`
- [ ] 待进入实现

