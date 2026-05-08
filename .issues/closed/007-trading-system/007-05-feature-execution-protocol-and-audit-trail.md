---
title: "007-05-feature-execution-protocol-and-audit-trail"
status: closed
created: 2026-03-18
updated: 2026-04-11
closed: 2026-04-11
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

- [x] 固定状态机与事件类型
- [x] 约定 `trace_id / intent_id / order_id` 关联键

### Phase 2：日志与回放

- [x] 事件写入 append-only JSONL
- [x] 提供按 `trace_id` 回放与汇总
- [x] 失败场景记录完整错误上下文

### Phase 3：集成与验证

- [x] 与 paper workflow 联调
- [x] 与 guard pipeline 联调
- [x] 补最小 E2E 验证脚本

## 验收标准

- [x] 六段执行协议可稳定串联
- [x] 每次执行都有完整审计轨迹
- [x] 可按 trace 回放单笔决策全过程
- [x] 异常场景可定位到具体阶段与规则

## 相关 Issue

- Parent: `#007`
- Depends on: `#007-03`
- Depends on: `#007-04`

## 进展记录

### 2026-04-06

- [x] 从 `#007` 拆出 `#007-05`
- [x] 已创建 Execution Protocol (services/signal-service/src/execution_protocol/)
- [x] 已创建 CLI 入口 (scripts/tradecat_execution_audit.py)
- [x] 已实现 6 段协议：propose → validate → stage → confirm → execute → sync
- [x] 已实现 append-only JSONL 审计日志
- [x] 已实现 replay 功能

### 2026-04-08

- [x] ExecutionProtocol 新增 `fail()`，失败分支落盘并标注 phase/reason
- [x] paper orchestrator 失败阶段接入 `ExecutionPhase` 级别失败事件
- [x] 新增 `test_execution_protocol.py`，覆盖 happy-path 与 failed-path replay
- [x] 新增 `docs/analysis/execution_protocol.md`，沉淀协议与回放说明

### 2026-04-11

- [x] `tradecat_execution_audit.py` 支持 `TRADECAT_EXECUTION_AUDIT_DIR`，便于隔离 CLI 回归与 smoke
- [x] 新增 `tests/test_execution_audit_cli.py`，以 subprocess 覆盖 `start/validate/stage/confirm/execute/sync/replay/list`
- [x] 新增 `scripts/smoke_trade_agent_007.sh`，串联 007 只读模型与 paper trade 最小链路
