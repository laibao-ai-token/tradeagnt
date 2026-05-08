---
title: "007-04-feature-unified-risk-guard-pipeline"
status: closed
created: 2026-03-18
updated: 2026-04-11
closed: 2026-04-11
owner: lixh6
priority: high
type: feature
---

# 007-04：统一风险闸门（Guard Pipeline）

## 背景

交易风险限制目前分散在不同脚本/服务中，缺少统一入口，不利于模拟交易与后续小仓位实盘的稳定收敛。

## 目标

建立统一 guard pipeline，在执行前统一完成风控检查并输出可审计结论：

1. 最大仓位
2. 单标的暴露上限
3. 冷却时间
4. 黑白名单
5. 最大回撤暂停
6. 数据新鲜度校验

## 本期范围

1. 风控规则配置模型（默认保守）
2. 统一校验入口（给 paper workflow 复用）
3. guard 检查结果结构化输出（pass/fail/reasons）
4. 最小单测与样例配置

## 非目标

- 不直接接交易所账户风控接口
- 不做复杂组合优化
- 不修改生产 `config/.env`

## 预期落点

- `services/signal-service/src/risk/guard_pipeline.py`
- `services/signal-service/src/risk/models.py`
- `config/.env.example`（如需新增 guard 配置项）
- `services/signal-service/tests/test_guard_pipeline.py`

## 实现清单

### Phase 1：规则建模

- [x] 定义 guard 配置与默认值
- [x] 定义规则评估顺序与短路策略

### Phase 2：校验实现

- [x] 实现统一 `validate_trade_intent` 入口
- [x] 输出 `risk_level / reasons / failed_rules`
- [x] 接入数据新鲜度与冷却校验

### Phase 3：验证与集成

- [x] 补单测覆盖 pass/fail 关键分支
- [x] 接入 `#007-03` paper workflow
- [x] 更新 runbook 风控说明

## 验收标准

- [x] 执行前必须经过统一 guard
- [x] guard 结果可解释、可审计
- [x] 参数缺省时采用保守默认值
- [x] 对现有只读查询链路无破坏

## 相关 Issue

- Parent: `#007`
- Related: `#006`
- Blocks: `#007-03`

## 进展记录

### 2026-04-06

- [x] 从 `#007` 拆出 `#007-04`
- [x] 已创建 Guard Pipeline (services/signal-service/src/risk/guard_pipeline.py)
- [x] 5 项规则已实现：max_position, max_single_symbol, cooldown, whitelist, blacklist

### 2026-04-08

- [x] 新增 `risk/models.py`，统一 GuardConfig/GuardResult 与风险等级语义
- [x] guard pipeline 扩展为 7 规则链（含 max_drawdown、data_freshness）并支持短路策略
- [x] 新增 `test_guard_pipeline.py`，覆盖 pass/fail 关键分支
