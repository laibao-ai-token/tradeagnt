---
title: "007-feature-trade-agent-trading-system-runbook"
status: open
created: 2026-03-13
updated: 2026-03-24
owner: lixh6
priority: high
type: feature
---

# Trade Agent 交易系统运行方案（TradeCat 主仓）

## 背景

当前仓库已经具备：

- `TradeCat` 主链：行情采集、指标计算、规则信号、回测、TUI
- 一组稳定的只读桥接命令：quotes / signals / news / backtest summary
- `OpenAlice` 等外部仓可作为编排、guard、工作流设计参考

但当前还没有一份统一文档，说明：

1. 我们最终要做的交易系统长什么样
2. 这个系统应该如何在 TradeCat 主仓内落位
3. 当前仓库哪些能力可直接复用，哪些能力要继续补

本 issue 负责沉淀这份运行方案。

## Source of Truth

- 本 issue：`#007`
- 子 issue 目录：`.issues/open/007-trading-system/`
- 当前交易 Agent 主线参考：`.issues/open/003-trade-agent/closed-003-feature-trade-agent-development.md`
- 当前回测主线参考：`.issues/open/006-backtest/006-feature-backtest-prod-readiness.md`
- 当前只读能力桥：
  - `scripts/tradecat_get_quotes.py`
  - `scripts/tradecat_get_signals.py`
  - `scripts/tradecat_get_news.py`
  - `scripts/tradecat_get_backtest_summary.py`

## 子 Issue 拆分（2026-03-18）

1. `#007-01`：`007-01-feature-domain-read-models-and-bridge-contracts.md`
2. `#007-02`：`007-02-feature-agent-context-packer.md`
3. `#007-03`：`007-03-feature-paper-trading-workflow.md`
4. `#007-04`：`007-04-feature-unified-risk-guard-pipeline.md`
5. `#007-05`：`007-05-feature-execution-protocol-and-audit-trail.md`

## 关联 Issue（跨主线）

- `#003-07`：`.issues/open/003-trade-agent/003-07-office-hours-agent-quant-decision-loop.md`

## 结论先行

### ADR-1：不再在主仓绑定特定外部 runtime 路线

TradeCat 主仓不再内置旧 workbench / skill 路线。  
主仓只保留稳定的本地只读桥接命令与交易领域实现。

### ADR-2：TradeCat 继续做量化底座

`TradeCat` 继续负责：

- 实时行情
- 多市场数据
- 指标计算
- 规则信号
- 回测与校准
- TUI 展示

### ADR-3：中间新增一层 Trade Agent Bridge / Domain Layer

真正需要建设的是一个更厚一点的交易领域层，位于：

```text
上层编排 / 外部消费方
   ↓
Trade Agent Bridge / Domain Layer
   ↓
TradeCat
```

这层负责：

- 统一只读 tool 契约
- 高层领域快照
- 上下文打包
- 信号解释
- 模拟交易编排
- 风控闸门
- 执行审计

## 目标系统长什么样

### 目标架构

```text
                    ┌────────────────────────────────────┐
                    │   上层编排 / 外部 Agent Runtime    │
                    │   只消费稳定命令与领域对象          │
                    └────────────────┬───────────────────┘
                                     │
                        local bridge commands / contracts
                                     │
              ┌──────────────────────┴──────────────────────┐
              │      Trade Agent Bridge / Domain Layer      │
              │ symbol snapshot / signal context /          │
              │ risk guard / paper workflow / audit         │
              └──────────────────────┬──────────────────────┘
                                     │
     ┌───────────────────────────────┼───────────────────────────────┐
     │                               │                               │
┌────▼────┐                    ┌─────▼─────┐                  ┌──────▼─────┐
│ data    │                    │ signal    │                  │ backtest    │
│ markets │                    │ trading   │                  │ artifacts   │
│ services│                    │ services  │                  │ + reports   │
└────┬────┘                    └─────┬─────┘                  └──────┬─────┘
     │                               │                               │
     └──────────────────────┬────────┴────────┬──────────────────────┘
                            │                 │
                            ▼                 ▼
                      TimescaleDB        SQLite / PG
```

### 职责划分

| 层 | 职责 | 当前状态 |
| --- | --- | --- |
| `TradeCat` 核心层 | 数据、指标、信号、回测、TUI | 已有 |
| `Bridge / Domain Layer` | 统一 tool、快照、解释、编排、风控 | 部分已有，需继续建设 |
| 外部消费层 | 调用桥接命令、展示、编排 | 不在主仓内实现 |
| `Execution Layer` | 模拟盘 / 实盘执行 | 只适合先做模拟盘，实盘待后续 |

## 为什么这样设计

### 1. 先把主仓边界定清楚

当前主仓已经明确：

- `data-service / markets-service` 负责采集
- `trading-service` 负责指标
- `signal-service` 负责规则信号
- `services-preview/tui-service` 负责只读展示
- 根目录 `scripts/` 负责只读桥接命令

因此，新的交易系统不应该推翻现有链路，而应该站在这些链路上继续长出来。

### 2. 研究层和执行层必须解耦

回测、context pack、研究快照都属于读侧。  
paper trading、guard、execution protocol 都属于状态侧。

这两类能力必须分层，否则很快会把脚本、TUI、服务内核混在一起。

### 3. 外部编排层不反向拥有主仓状态

无论后续接什么上层 runtime，TradeCat 主仓都只暴露稳定契约。  
持仓、风险、执行协议、审计事实源都必须留在主仓内。

## 系统该怎么跑

## 运行模式分层

### 模式 A：研究模式（当前可用）

目标：

- 用 `TradeCat TUI` 看行情、信号、资讯、回测切片
- 用只读桥接命令拿结构化 JSON
- 完成“行情 -> 信号 -> 新闻 -> 回测摘要”的研究闭环

### 模式 B：回测模式（当前可用）

目标：

- 用现有 `signal-service` 回测链跑历史评估
- 输出 `metrics.json / report.md / input_quality.json / stability_report.json`
- 作为 Agent 研究结论的历史验证底座

### 模式 C：模拟交易模式（下一阶段）

目标：

- 不直接实盘
- 在领域层引入 `paper workflow`
- 先验证“信号 -> 风控 -> 候选单 -> 持仓跟踪 -> 结果归因”

### 模式 D：小仓位实盘模式（后续阶段）

目标：

- 在统一 guard 与审计到位后，才允许实盘
- 默认从单账户、小资金、手工确认开始

## 当前建议运行路径

### 1. 初始化环境

```bash
cd /public/home/lixh6/laibao/proj/tx_test_0106/tradecat-origin
./scripts/init.sh --all
```

### 2. 配置环境

按现有主仓规范准备：

- `config/.env`
- 数据库连接
- 代理 / API 配置

注意：不在本 issue 中修改生产 `config/.env`。

### 3. 启动核心服务

```bash
./scripts/start.sh start
./scripts/start.sh status
```

### 4. 启动 TradeCat TUI

```bash
./scripts/start.sh run
```

### 5. 使用当前只读桥接命令

```bash
python scripts/tradecat_get_quotes.py NVDA
python scripts/tradecat_get_signals.py --symbol BTCUSDT --timeframe 1m --limit 5
python scripts/tradecat_get_news.py --symbol BTCUSDT --limit 5 --since-minutes 120
python3 scripts/tradecat_get_backtest_summary.py --run-id <run_id>
```

约束：

- 这些命令只读，不写库
- 这些命令是当前主仓对上层最稳定的契约
- 后续 `#007-01/#007-02` 只是在这之上做更高层的统一对象与 context pack

## 当前主仓哪些能力可直接复用

### 已有

- 行情采集、指标计算、规则信号
- 回测、对齐 gate、walk-forward、稳定性摘要
- TUI 展示与新闻 / 数据库读适配
- 四个稳定的只读桥接命令

### 待补

- 高层领域对象统一 JSON 契约
- `context pack` 单入口
- 统一的交易 guard pipeline
- paper trading 状态机与账本
- append-only 执行协议与按 `trace_id` 回放

## 推荐推进顺序

1. 先做 `#007-01`：统一只读领域对象与桥接契约
2. 再做 `#007-02`：context pack
3. 然后做 `#007-04`：统一风险闸门
4. 再做 `#007-03`：paper trading
5. 最后做 `#007-05`：执行协议与审计

## 本期不做什么

- 不在 TradeCat 主仓内重建新的 Agent runtime
- 不把交易状态机塞进 TUI
- 不把交易状态长期留在脚本层
- 不修改生产 `config/.env`
- 不触碰数据库 schema
