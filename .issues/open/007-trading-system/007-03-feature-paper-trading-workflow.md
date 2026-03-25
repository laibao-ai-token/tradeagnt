---
title: "007-03-feature-paper-trading-workflow"
status: open
created: 2026-03-18
updated: 2026-03-18
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

- [ ] 定义 order/position/fill 状态机
- [ ] 定义状态迁移与幂等键

### Phase 2：编排与执行

- [ ] 实现 candidate -> validate -> stage
- [ ] 实现 confirm -> execute(simulated) -> sync
- [ ] 统一错误处理与重试语义

### Phase 3：验证与回放

- [ ] 输出交易结果与归因摘要
- [ ] 增加最小回放脚本或测试
- [ ] 补 runbook 示例

## 验收标准

- [ ] 可基于历史/实时信号生成模拟候选单
- [ ] 风控未通过时阻断执行并给出原因
- [ ] 成功执行可生成持仓与审计产物
- [ ] 整个链路可重放、可追溯

## 相关 Issue

- Parent: `#007`
- Depends on: `#007-01`
- Depends on: `#007-04`

## 进展记录

### 2026-03-18

- [x] 从 `#007` 拆出 `#007-03`
- [ ] 待进入实现

