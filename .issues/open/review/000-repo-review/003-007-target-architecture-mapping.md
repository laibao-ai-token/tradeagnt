# `#007` 目标架构与主仓模块映射

> 最后更新: 2026-03-24
> 映射范围: `#007` runbook / `#007-01` ~ `#007-05` / 当前主仓可复用模块
> 核实状态: 已通过 `#007` 文档、桥接脚本、`signal-service` / `tui-service` / `scripts` 目录核实
> 总体结论: 不应新建第六个服务；应以 `scripts` 形成薄桥接层，以 `signal-service` 承担有状态交易领域层

---

## 结论先行

`#007` 要补的不是一个新的运行时，也不是一个新的 UI，而是 TradeCat 主仓内部的一层交易领域层。

当前最合理的落位方式是：

1. `TradeCat` 主仓继续负责数据、指标、信号、回测、TUI
2. 新增的 `Bridge / Domain Layer` 先以“薄桥接 + 明确领域归属”方式落地：
   - 只读桥接入口放在 `scripts/`
   - 桥接组装逻辑优先放在 `scripts/lib/` 或极薄的共享 helper
   - 任何有状态的交易编排、风控、执行协议都落在 `services/signal-service/`
3. 外部编排层只消费稳定命令与领域对象，不再反向定义主仓边界

结论上不建议：

- 新建第六个微服务
- 把交易领域逻辑塞进 `tui-service`
- 把核心交易状态机塞进 `repository/*` 外挂仓
- 把模拟交易和执行协议做成单纯脚本拼接

## 映射原则

### 原则 1：只读桥接和有状态交易必须分层

当前 `tradecat_get_quotes/signals/news/backtest_summary` 已经证明，只读查询入口适合留在 `scripts/`。  
但 paper trading、risk guard、execution audit 都属于有状态领域能力，必须放入服务内模块，而不是长期停留在脚本层。

### 原则 2：UI 和外部编排层都不拥有交易领域状态

- `services-preview/tui-service` 是展示层
- 外部编排层是消费层

它们都可以消费领域对象，但不应拥有交易领域的 Source of Truth。

### 原则 3：优先复用现有链路，不做“第二套系统”

`#007` 的核心不是“重写”，而是“把缺的中间层长出来”。

## 当前主仓可复用资产

### 1. 现有只读桥接入口

| 能力 | 当前入口 | 当前作用 | 结论 |
|:---|:---|:---|:---|
| Quote | `scripts/tradecat_get_quotes.py` | 最新行情快照 | 可直接作为 `#007-01/#007-02` 底座 |
| Signals | `scripts/tradecat_get_signals.py` | 最近规则信号 | 可直接作为 `#007-01/#007-02` 底座 |
| News | `scripts/tradecat_get_news.py` | 最近新闻查询 | 可直接作为 `#007-01/#007-02` 底座 |
| Backtest | `scripts/tradecat_get_backtest_summary.py` | 读取已有回测摘要 | 可直接作为 `#007-01/#007-02` 底座 |

### 2. 现有服务内可复用模块

| 模块 | 路径 | 可复用点 | 结论 |
|:---|:---|:---|:---|
| 信号只读模型 | `services/signal-service/src/storage/read_only.py` | 只读查询、稳定 DTO | 是 `signal context` 的直接底座 |
| 冷却持久化 | `services/signal-service/src/storage/cooldown.py` | 冷却键持久化 | 是 `#007-04` 的现成输入之一 |
| 回测质量 gate | `services/signal-service/src/backtest/precheck.py` | 新鲜度/覆盖率/输入质量 guard 思路 | 可复用到 `#007-04`，但不能代替交易 guard |
| 回测状态 | `services/signal-service/src/backtest/state.py` | 回测运行状态聚合 | 可为 `backtest health` 提供参考 |
| Quote 适配 | `services-preview/tui-service/src/quote.py` | 统一行情读取 | 是 `symbol snapshot` 的底座之一 |
| 新闻读层 | `scripts/lib/tradecat_news.py`、`services-preview/tui-service/src/news_db.py`、`services-preview/tui-service/src/news_health.py` | 新闻查询和健康检查 | 可为 `market state` / `service health` 提供输入 |
| Agent 事件 DTO | `services-preview/tui-service/src/agent_events.py` | 标准化事件结构 | 可作为 `#007-05` 审计事件风格参考，不建议直接复用为执行协议 |

## `#007` 子 Issue 映射

### `#007-01` Domain 只读模型与 Bridge 契约统一

| 项目 | 建议 |
|:---|:---|
| 目标能力 | `symbol snapshot` / `signal context` / `market state` / `backtest health` / `service health` |
| 主落位 | `scripts/` |
| 推荐辅助落位 | `scripts/lib/` 中新增桥接组装 helper；信号只读部分复用 `services/signal-service/src/storage/read_only.py` |
| 可复用输入 | `tradecat_get_quotes.py` / `tradecat_get_signals.py` / `tradecat_get_news.py` / `tradecat_get_backtest_summary.py` |
| 不建议落位 | `services-preview/tui-service`、`repository/*` |

### `#007-02` Agent Context Packer

| 项目 | 建议 |
|:---|:---|
| 目标能力 | 把 quote / signal / news / backtest health 聚合成单个 context pack |
| 主落位 | `scripts/tradecat_get_context_pack.py` |
| 推荐辅助落位 | `scripts/lib/` 中新增 context assembler；必要时引用 `scripts/lib/tradecat_news.py` 等现有 helper |
| 可复用输入 | `#007-01` 产出的领域对象；当前四个桥接命令 |
| 不建议落位 | `services/signal-service` 核心引擎内部、`tui-service` UI 层 |

### `#007-04` 统一风险闸门（Guard Pipeline）

| 项目 | 建议 |
|:---|:---|
| 目标能力 | 执行前统一校验最大仓位、暴露、冷却、黑白名单、回撤暂停、数据新鲜度 |
| 主落位 | `services/signal-service/src/risk/` |
| 推荐辅助落位 | `services/signal-service/tests/`；如需配置新增，仅改 `config/.env.example` |
| 可复用输入 | `storage/cooldown.py`、`backtest/precheck.py` 的 gate 口径、信号历史读层 |
| 不建议落位 | `scripts/`、`tui-service`、`repository/*` |

### `#007-03` Paper Trading 模拟交易编排

| 项目 | 建议 |
|:---|:---|
| 目标能力 | `candidate -> validate -> stage -> confirm -> execute(simulated) -> sync -> audit` |
| 主落位 | `services/signal-service/src/paper_trading/` |
| 推荐辅助落位 | `scripts/tradecat_paper_trade.py` 作为 CLI 入口；`artifacts/paper_trading/` 存放产物 |
| 依赖 | 依赖 `#007-01` 统一读模型和 `#007-04` 统一 guard |
| 不建议落位 | `tui-service`、`trading-service`、`repository/*` |

### `#007-05` 统一执行协议与审计回放

| 项目 | 建议 |
|:---|:---|
| 目标能力 | `propose -> validate -> stage -> confirm -> execute -> sync` 状态机与 append-only 审计 |
| 主落位 | `services/signal-service/src/execution_protocol/` |
| 推荐辅助落位 | `scripts/tradecat_execution_audit.py`；`artifacts/execution_audit/`；必要时文档落在 `docs/analysis/` |
| 可复用参考 | `services-preview/tui-service/src/agent_events.py` 的 DTO 风格、现有 artifacts 产物目录习惯 |
| 不建议落位 | `repository/*`、`services-preview/tui-service` |

## 建议的总体落位

### A. `scripts/` 负责桥接入口

适合放：

- 只读领域对象 CLI
- context pack CLI
- 审计查询 / 回放 CLI
- paper workflow 的控制台入口

不适合放：

- 交易状态机本体
- 风控规则核心
- 持仓状态和执行协议持久化逻辑

### B. `scripts/lib/` 负责薄组装层

适合放：

- 只读聚合 helper
- 多桥接脚本共享的 JSON 契约 / 组装函数
- 与外部消费方强相关但仍只读的适配逻辑

不适合放：

- 长期有状态的交易领域对象仓储
- 风控状态、执行协议状态、持仓账本

### C. `services/signal-service/` 负责交易领域内核

适合放：

- guard pipeline
- paper trading 状态机
- execution protocol
- 审计事件的领域定义和写入逻辑

### D. `services-preview/tui-service/` 继续做展示和读适配

适合放：

- 只读数据库适配
- 新闻健康度、展示 DTO
- 工作台可视化消费层

不适合放：

- 下单候选生成
- 风控判定
- 执行协议状态机

## 推荐实现顺序

建议顺序不是 `01 -> 02 -> 03 -> 04 -> 05`，而是：

1. 先统一只读领域对象和契约
2. 再补 context pack
3. 然后把 guard pipeline 长进 `signal-service`
4. 再做 paper trading
5. 最后做统一执行协议与审计
