---
title: "007-01-feature-domain-read-models-and-bridge-contracts"
status: open
created: 2026-03-18
updated: 2026-03-20
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
3. `get_market_state(market)`
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

- [ ] 统一返回骨架：`ok/tool/ts/source/request/data/error/warnings/schema_version`
- [ ] 定义 5 个领域对象的必填/可选字段

### Phase 2：命令落地

- [ ] 脚本实现与参数解析
- [ ] 旧库/缺字段降级策略
- [ ] 失败场景结构化错误码

### Phase 3：验证与文档

- [ ] 增加单测或脚本级 smoke
- [ ] runbook 增加示例调用与预期输出

## 验收标准

- [ ] 5 个命令均可在本地只读执行
- [ ] 输出结构统一且稳定
- [ ] 缺字段/无数据时返回可解释错误或 warning
- [ ] 不破坏现有 `tradecat_get_quotes/signals/news/backtest_summary` 使用方式

## 相关 Issue

- Parent: `#007`
- Related: `#003`
- Related: `#006`

## 进展记录

### 2026-03-18

- [x] 从 `#007` 拆出 `#007-01`
- [ ] 待进入实现
