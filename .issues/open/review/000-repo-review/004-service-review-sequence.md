# 服务级 Review 顺序与执行范围

> 最后更新: 2026-03-24
> 适用范围: 主仓整仓 review 的服务级拆分顺序
> 核实状态: 已结合 `001-003` 审计文档、当前目录结构、现有桥接脚本与服务入口核实
> 总体结论: 先 review 桥接层，再 review `signal-service`，再 review 展示层，最后处理其余采集与指标服务

---

## 结论先行

如果继续推进“整仓 review”，不建议按目录字母顺序看，也不建议五个服务平均用力。

当前最合理的顺序是：

1. `scripts/` + `scripts/lib/`
2. `services/signal-service/`
3. `services-preview/tui-service/`
4. `services/trading-service/`
5. `services/data-service/`
6. `services-preview/markets-service/`

原因：

- `#007` 的桥接层先落在 `scripts/`
- 有状态交易领域能力主落位应在 `signal-service`
- `tui-service` 是消费桥接层和信号层的展示壳，必须确认不越界
- `trading-service`、`data-service`、`markets-service` 更偏上游基础设施，应在主链清楚后审

## 总体原则

### 原则 1：先定边界，再看实现细节

每一阶段先回答：

1. 这个区域该负责什么
2. 不该负责什么
3. 当前是否已经越界

### 原则 2：先看入口，再钻核心

每个区域的 review 都应先从：

- `__main__.py`
- `scripts/start.sh`
- CLI 入口脚本
- 关键测试文件

开始，而不是直接跳进大文件深处。

### 原则 3：优先审查会影响 `#007` 落位的区域

整仓 review 不是纯代码体操，目标是给 `#007` 后续实现铺路。  
因此顺序必须服务于：

- 桥接层清晰
- 交易领域层清晰
- 展示层不越界

## Review 顺序总表

| 顺序 | 区域 | 主要目标 | 风险等级 | 为什么先看 |
|:---|:---|:---|:---|:---|
| 1 | `scripts/` + `scripts/lib/` | 确认桥接层边界与契约 | High | `#007-01/#007-02` 直接落这里 |
| 2 | `services/signal-service/` | 确认交易领域内核归属 | High | `#007-03/#007-04/#007-05` 主落位 |
| 3 | `services-preview/tui-service/` | 确认展示层不承载交易状态 | High | 当前最容易和桥接/占位 Agent Shell 混杂 |
| 4 | `services/trading-service/` | 确认指标层边界、输入输出稳定性 | Medium | 是信号上游，但不直接承载交易编排 |
| 5 | `services/data-service/` | 确认采集层边界、回填与容错 | Medium | 偏数据采集，优先级低于交易链 |
| 6 | `services-preview/markets-service/` | 确认预览采集链与正式链边界 | Medium | 对 `#007` 重要，但更偏补充信息层 |

## Phase 1: `scripts/` + `scripts/lib/`

### Review 目标

- 确认只读桥接层是否边界清晰
- 确认桥接命令输出契约是否稳定
- 确认是否存在重复组装逻辑、散乱 helper、职责漂移

### 优先入口

- `scripts/tradecat_get_quotes.py`
- `scripts/tradecat_get_signals.py`
- `scripts/tradecat_get_news.py`
- `scripts/tradecat_get_backtest_summary.py`
- `scripts/lib/tradecat_news.py`

### 高风险核心

- 脚本直接 import 服务内模块导致的耦合
- 同类查询逻辑在 `scripts/lib/` 与 TUI 模块内重复实现
- 桥接脚本悄悄承载业务状态或副作用

### 建议命令

```bash
pytest -q tests/test_tradecat_get_backtest_summary.py
python3 -m py_compile scripts/tradecat_get_quotes.py scripts/tradecat_get_signals.py scripts/tradecat_get_news.py scripts/tradecat_get_backtest_summary.py
```

## Phase 2: `services/signal-service/`

### Review 目标

- 确认它是否适合作为 `#007` 的有状态交易领域层
- 确认冷却、只读查询、回测、事件、规则引擎之间的边界
- 找出未来 `risk/`、`paper_trading/`、`execution_protocol/` 的自然落点

### 优先入口

- `services/signal-service/src/__main__.py`
- `services/signal-service/src/storage/read_only.py`
- `services/signal-service/src/storage/cooldown.py`
- `services/signal-service/src/backtest/precheck.py`
- `services/signal-service/src/backtest/state.py`
- `services/signal-service/src/engines/sqlite_engine.py`
- `services/signal-service/src/engines/pg_engine.py`

### 建议命令

```bash
cd services/signal-service && make test
pytest -q services/signal-service/tests/test_read_only_signals.py services/signal-service/tests/test_backtest_state.py
python3 -m py_compile services/signal-service/src/storage/read_only.py services/signal-service/src/storage/cooldown.py services/signal-service/src/backtest/precheck.py
```

## Phase 3: `services-preview/tui-service/`

### Review 目标

- 确认它仍是展示层和读适配层
- 确认 Agent Shell 只是壳，不是交易领域实现层
- 确认 quote / news / db 读层是否可安全被桥接层复用

### 优先入口

- `services-preview/tui-service/src/__main__.py`
- `services-preview/tui-service/src/tui.py`
- `services-preview/tui-service/src/quote.py`
- `services-preview/tui-service/src/db.py`
- `services-preview/tui-service/src/news_db.py`
- `services-preview/tui-service/src/news_health.py`
- `services-preview/tui-service/src/agent_events.py`

### 建议命令

```bash
cd services-preview/tui-service && make test
pytest -q services-preview/tui-service/tests/test_db.py services-preview/tui-service/tests/test_news_db.py services-preview/tui-service/tests/test_news_health.py
python3 -m py_compile services-preview/tui-service/src/db.py services-preview/tui-service/src/news_health.py services-preview/tui-service/src/agent_events.py
```

## Phase 4-6: 上游服务

剩余顺序：

1. `services/trading-service/`
2. `services/data-service/`
3. `services-preview/markets-service/`

判断标准：

- 是否仍遵守采集 / 指标 / 信号分层
- 是否对 `#007` 所需的读模型和风险判断提供稳定输入
- 是否把与交易状态机无关的复杂度隔离在上游
