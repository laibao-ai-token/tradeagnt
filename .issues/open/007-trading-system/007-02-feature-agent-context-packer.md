---
title: "007-02-feature-agent-context-packer"
status: open
created: 2026-03-18
updated: 2026-03-20
owner: lixh6
priority: medium
type: feature
---

# 007-02：Agent 上下文打包器（Context Packer）

## 背景

当前 Agent 研究流程需要多次调用 quotes/signals/news/backtest，模型上下文碎片化，重复 token 成本高，且容易遗漏风险提示。

## 目标

新增可复用的上下文打包入口，把“研究所需核心信息”一次性输出为结构化快照：

1. 价格状态
2. 多周期信号摘要
3. 新闻摘要
4. 回测健康度摘要
5. 风险提示

## 本期范围

1. 提供 `context pack` 只读命令
2. 支持 `symbol + timeframe + window` 参数
3. 输出统一 JSON，适配上层编排或外部运行时调用
4. 增加 freshness 检查和缺失字段标注

## 非目标

- 不做自动交易建议执行
- 不把模型总结写回数据库
- 不修改生产 `config/.env`

## 预期落点

- `scripts/tradecat_get_context_pack.py`
- `README.md` / `README_EN.md` / `AGENTS.md`（新增调用说明）

## 实现清单

### Phase 1：数据模型

- [ ] 定义 `context_pack` 数据结构与版本号
- [ ] 约定每个子块的 freshness 字段与 warning 语义

### Phase 2：命令与组装

- [ ] 聚合 quotes/signals/news/backtest health
- [ ] 支持 `--symbol --timeframe --news-limit --signal-limit`
- [ ] 缺数据时保持结构完整并标注风险

### Phase 3：验证与集成

- [ ] 补充脚本级 smoke 测试
- [ ] 在 skill runbook 增加标准调用示例

## 验收标准

- [ ] 单命令可生成结构化 context pack
- [ ] 输出包含 freshness / warnings / 风险摘要
- [ ] 上层编排或外部运行时可直接消费该对象
- [ ] 无数据场景不崩溃、可解释

## 相关 Issue

- Parent: `#007`
- Depends on: `#007-01`
- Related: `#003-06`

## 进展记录

### 2026-03-18

- [x] 从 `#007` 拆出 `#007-02`
- [ ] 待进入实现
