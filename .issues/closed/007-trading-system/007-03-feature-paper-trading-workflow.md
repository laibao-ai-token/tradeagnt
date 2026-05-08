---
title: "007-03-feature-paper-trading-workflow"
status: closed
created: 2026-03-18
updated: 2026-04-11
closed: 2026-04-11
owner: lixh6
priority: high
type: feature
---

# 007-03：Paper Trading 模拟交易编排

## 背景

`#007` 已确定当前阶段不直接实盘，需要先把“信号 -> 风控 -> 候选单 -> 模拟持仓 -> 结果归因”链路跑通。

## 目标

落地最小可用 paper workflow：

1. `candidate generation`
2. `risk validate`
3. `paper stage`
4. `confirm`
5. `execute(simulated)`
6. `sync`
7. `audit`

## 本期范围

1. 设计 paper order / position / fill 的本地存储模型
2. 落地最小编排命令（不连接实盘交易所）
3. 输出可回放执行日志与结果归因
4. 提供 dry-run/confirm 两种模式

## 非目标

- 不接真实交易所下单
- 不处理多账户实盘路由
- 不改生产配置与数据库 schema

## 预期落点

- `services/signal-service/src/paper_trading/`（编排与状态）
- `scripts/tradecat_paper_trade.py`（CLI 入口）
- `artifacts/paper_trading/`（执行与审计产物）

## 实现清单

### Phase 1：数据模型与状态机

- [x] 定义 order/position/fill 状态机
- [x] 定义状态迁移与幂等键

### Phase 2：编排与执行

- [x] 实现 candidate -> validate -> stage
- [x] 实现 confirm -> execute(simulated) -> sync
- [x] 统一错误处理与重试语义

### Phase 3：验证与回放

- [x] 输出交易结果与归因摘要
- [x] 增加最小回放脚本或测试
- [x] 补 runbook 示例

## 验收标准

- [x] 可基于历史/实时信号生成模拟候选单
- [x] 风控未通过时阻断执行并给出原因
- [x] 成功执行可生成持仓与审计产物
- [x] 整个链路可重放、可追溯

## 相关 Issue

- Parent: `#007`
- Depends on: `#007-01`
- Depends on: `#007-04`

## 进展记录

### 2026-04-06

- [x] 从 `#007` 拆出 `#007-03`
- [x] 已创建 Paper Trading 核心模块 (services/signal-service/src/paper_trading/)
- [x] 已创建 CLI 入口 (scripts/tradecat_paper_trade.py)
- [x] 已实现 candidate → validate → execute → positions → stats 完整链路

### 2026-04-08

- [x] 订单状态机补充 `STAGED/CONFIRMED`，并增加状态迁移校验
- [x] 订单模型新增 `idempotency_key`，执行流程接入统一 Guard Pipeline
- [x] `confirm_and_execute` 接入 Execution Protocol 审计轨迹与失败阶段标记
- [x] 新增 `test_paper_trading_workflow.py`，覆盖成功与 guard 拒单场景
- [x] 新增 `from-signal` 路径：可从 `signal_history.db` 最新记录生成候选单
- [x] 新增 `confirm_and_execute_with_retry` 重试入口，统一返回 `error_code/retriable/attempt`

### 2026-04-09

- [x] `confirm_and_execute` 增加结构化 `attribution` 输出（含 fee/slippage/net cash impact）
- [x] 归因记录落盘到 `artifacts/paper_trading/execution_reports.jsonl`
- [x] 新增 `tradecat_paper_trade.py report [limit]` 查询归因摘要
- [x] 新增测试覆盖：成功执行/guard 拒单均会写入归因报告并可汇总查询
- [x] `artifacts/paper_trading/state.json` 扩展为订单/仓位/成交/cooldown 全量持久化
- [x] 修复跨进程 `candidate -> execute` 丢单问题（重启 orchestrator 可继续执行）
- [x] CLI 兼容 `dry-run` 与 `dry_run` 两种调用写法
- [x] `candidate` 幂等去重策略细化：未终态复用同 key，终态后可重新生成；`from-signal` 保持同 signal key 复用
- [x] `candidate` 支持 flags 参数模式（`--score/--reason/--idempotency-key/--reuse-finalized`），保留位置参数兼容
- [x] 新增 `tests/test_paper_trade_cli.py`，以 subprocess 覆盖 `candidate -> execute -> report` 与非法参数错误码
- [x] 修复 `last_signal_ts=None` 被错误当成“当前时间”的 freshness 绕过；手工 `validate/dry-run/execute` 支持 `--signal-ts`
