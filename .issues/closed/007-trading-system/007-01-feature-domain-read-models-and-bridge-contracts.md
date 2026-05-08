---
title: "007-01-feature-domain-read-models-and-bridge-contracts"
status: closed
created: 2026-03-18
updated: 2026-04-11
closed: 2026-04-11
owner: lixh6
priority: medium
type: feature
---

# 007-01：Domain 只读模型与 Bridge 契约统一

## 背景

当前 TradeCat 已有原子命令：

- `tradecat_get_quotes`
- `tradecat_get_signals`
- `tradecat_get_news`
- `tradecat_get_backtest_summary`

但上层消费方仍需拼接多个原子输出，成本高且容易出现语义不一致。

## 目标

新增一层只读领域对象，让上层消费方直接消费高层结果，而不是每次拼原子脚本：

1. `get_symbol_snapshot(symbol)`
2. `get_signal_context(symbol, timeframe)`
3. `get_market_state()`
4. `get_backtest_health(run_id/strategy)`
5. `get_service_health()`

## 本期范围

1. 统一领域对象 JSON 契约（含版本字段）
2. 落地对应只读桥接命令入口
3. 兼容旧数据缺字段场景（降级字段、warning）
4. 补最小单测/烟测与 runbook 示例

## 非目标

- 不做任何写操作或下单动作
- 不改生产 `config/.env`
- 不修改数据库 schema

## 预期落点

- `scripts/tradecat_get_symbol_snapshot.py`
- `scripts/tradecat_get_signal_context.py`
- `scripts/tradecat_get_market_state.py`
- `scripts/tradecat_get_backtest_health.py`
- `scripts/tradecat_get_service_health.py`
- `README.md` / `README_EN.md` / `AGENTS.md`（示例补充）

## 实现清单

### Phase 1：契约定义

- [x] 统一返回骨架：`ok/tool/ts/source/request/data/error/warnings/schema_version`
- [x] 定义 5 个领域对象的必填/可选字段

### Phase 2：命令落地

- [x] 脚本实现与参数解析
- [x] 旧库/缺字段降级策略
- [x] 失败场景结构化错误码

### Phase 3：验证与文档

- [x] 增加单测或脚本级 smoke
- [x] runbook 增加示例调用与预期输出

## 验收标准

- [x] 5 个命令均可在本地只读执行
- [x] 输出结构统一且稳定
- [x] 缺字段/无数据时返回可解释错误或 warning
- [x] 不破坏现有 `tradecat_get_quotes/signals/news/backtest_summary` 使用方式

## 相关 Issue

- Parent: `#007`
- Related: `#003`
- Related: `#006`

## 进展记录

### 2026-04-06

- [x] 从 `#007` 拆出 `#007-01`
- [x] 5 个命令已完成（quotes/signals/news/backtest_summary 已存在，service_health 已创建）
- [x] 统一 JSON 输出格式已确认

### 2026-04-09

- [x] `symbol_snapshot/signal_context/market_state` 增加 `source_status` 子块，输出结构化错误码
- [x] domain read model 单测补充 source_status 覆盖（`tests/test_domain_read_models.py`）
- [x] 本地 smoke 验证 5 个命令可执行，缺数据场景维持结构并返回 warning
- [x] `get_market_state` 目标文案收敛为全局服务/数据库快照，与实际脚本契约保持一致
