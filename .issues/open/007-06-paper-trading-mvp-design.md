---
title: "007-06-paper-trading-mvp-design"
status: draft
created: 2026-04-05
updated: 2026-04-05
owner: lixh6
priority: high
type: design
---

# 007-06：Paper Trading MVP 设计讨论

## 背景与痛点

### 当前困境

- **回测是"后视镜"**：只能评估历史表现，无法追踪实时策略状态
- **研究无法落地**：一直在优化信号和回测，但没有验证"跟着信号做会怎样"
- **缺乏过程指标**：不知道本周胜率、当前持仓、连续亏损次数等关键运营数据
- **策略迭代无反馈**：无法区分"策略本身不行"还是"参数需要调整"

### 为什么需要 Paper Trading

| 能力 | 回测 | Paper Trading |
|:---|:---|:---|
| 数据源 | 历史 K 线 | 实时信号流 |
| 执行时机 | 批量回放 | 信号触发即时响应 |
| 滑点/成交 | 模拟假设 | 可对接真实盘口深度 |
| 心理验证 | 无 | 有（看到实时盈亏波动） |
| 运营指标 | 无 | 本周胜率、最大回撤、持仓时长 |
| 策略调优 | 离线 | 在线 A/B 对比 |

## 定位与边界

### Paper Trading 不是什么

- 不是实盘交易系统
- 不是交易所对接层
- 不是复杂组合优化器
- 不是高频执行引擎

### Paper Trading 是什么

- 信号→执行的**最小验证闭环**
- 策略运营的**实时仪表盘**
- 实盘前的**最后一道验证**
- 策略迭代的**在线反馈源**

## MVP 方案设计

### 整体架构

```
signal-service (实时信号)
        │
        │ 写入 signal_history.db
        ▼
┌───────────────────┐
│  Paper Trading    │  ← 新增模块
│  Orchestrator     │
│  (轮询信号流)      │
└────────┬──────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌───────┐ ┌──────────┐
│ Guard │ │ Executor │  ← 复用 backtest/execution_engine.py 逻辑
│ 风控  │ │ 模拟成交  │
└───┬───┘ └─────┬────┘
    │           │
    ▼           ▼
┌──────────────────────┐
│  Paper Ledger (SQLite)│
│  orders / positions   │
│  fills / equity       │
└──────────────────────┘
         │
         ▼
┌──────────────────────┐
│  TUI / CLI 查询接口   │
│  当前持仓 / 盈亏曲线   │
│  本周胜率 / 归因       │
└──────────────────────┘
```

### 核心数据模型设计

> 设计原则：**尽量复用 backtest/models.py 已有的 dataclass**，避免重复定义。

#### 1. PaperOrder（模拟订单）

```python
@dataclass
class PaperOrder:
    order_id: str              # UUID / snowflake
    symbol: str                # BTCUSDT
    side: str                  # LONG / SHORT / NEUTRAL
    qty: float                 # 请求数量
    entry_price: float         # 成交价（含滑点）
    entry_ts: datetime         # 开仓时间
    entry_score: int           # 触发信号强度
    entry_reason: str          # 触发原因（规则 ID 列表）
    status: str                # PENDING / FILLED / CANCELLED / REJECTED
    slippage_bps: float        # 实际滑点
    fee: float                 # 手续费
    strategy_label: str        # 策略标签（支持多策略对比）
```

#### 2. PaperPosition（模拟持仓）

```python
@dataclass
class PaperPosition:
    symbol: str
    side: str                  # LONG / SHORT
    qty: float                 # 当前持仓量
    entry_price: float         # 均价
    entry_ts: datetime
    unrealized_pnl: float      # 未实现盈亏（实时计算）
    realized_pnl: float        # 已实现盈亏（平仓后）
    max_drawdown: float        # 持仓期间最大回撤
    holding_minutes: float     # 持仓时长
    mark_price: float          # 当前标记价格
    liquidation_price: float   # 强平价
    initial_margin: float      # 初始保证金
```

#### 3. PaperEquity（权益曲线）

```python
@dataclass
class PaperEquityPoint:
    timestamp: datetime
    total_equity: float        # 总权益
    available: float           # 可用资金
    margin_used: float         # 占用保证金
    unrealized_pnl: float      # 浮动盈亏
    position_count: int        # 当前持仓数
```

### 存储方案

**新建独立 SQLite 文件**：`libs/database/services/signal-service/paper_trading.db`

理由：
- 与 `signal_history.db`（信号源）、`cooldown.db`（冷却状态）职责分离
- 不触碰 TimescaleDB，保持只读
- 文件级备份/删除方便

#### 表结构

```sql
-- 订单表
CREATE TABLE orders (
    order_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    entry_price REAL NOT NULL,
    entry_ts TEXT NOT NULL,
    entry_score INTEGER,
    entry_reason TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    slippage_bps REAL DEFAULT 0,
    fee REAL DEFAULT 0,
    strategy_label TEXT DEFAULT 'default',
    created_at TEXT NOT NULL
);

-- 持仓表（单币种单方向最多一条）
CREATE TABLE positions (
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    entry_price REAL NOT NULL,
    entry_ts TEXT NOT NULL,
    entry_score INTEGER,
    initial_margin REAL,
    liquidation_price REAL DEFAULT 0,
    strategy_label TEXT DEFAULT 'default',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (symbol, side, strategy_label)
);

-- 成交记录（用于归因）
CREATE TABLE fills (
    fill_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    qty REAL NOT NULL,
    fee REAL DEFAULT 0,
    slippage_bps REAL DEFAULT 0,
    pnl REAL DEFAULT 0,
    reason TEXT,
    fill_ts TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

-- 权益快照（定时写入，用于绘制曲线）
CREATE TABLE equity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    total_equity REAL NOT NULL,
    available REAL NOT NULL,
    margin_used REAL NOT NULL,
    unrealized_pnl REAL DEFAULT 0,
    position_count INTEGER DEFAULT 0,
    strategy_label TEXT DEFAULT 'default'
);

CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_symbol ON orders(symbol);
CREATE INDEX idx_equity_ts ON equity_snapshots(timestamp);
CREATE INDEX idx_fills_order ON fills(order_id);
```

### 编排流程（Orchestrator）

#### 核心循环

```
每 N 秒（默认 60s）:
  1. 从 signal_history.db 读取最新未处理信号
  2. 对每条信号执行 Guard Pipeline 检查
  3. 通过检查 → 生成 PaperOrder
  4. 执行模拟成交（复用 execution_engine 滑点/手续费逻辑）
  5. 更新 positions 表
  6. 更新现有持仓的 mark_price（从 TimescaleDB 读最新价）
  7. 计算 unrealized_pnl
  8. 写入 equity_snapshot
  9. 标记信号为"已处理"
```

#### 信号→订单映射规则

| 信号方向 | 当前持仓 | 动作 |
|:---|:---|:---|
| BUY (score ≥ threshold) | 无 | 开多仓 |
| BUY (score ≥ threshold) | 持有空仓 | 平空 + 开多（反手） |
| BUY (score ≥ threshold) | 持有多仓 | 忽略（加仓逻辑后续再议） |
| SELL (score ≥ threshold) | 无 | 开空仓 |
| SELL (score ≥ threshold) | 持有多仓 | 平多 + 开空（反手） |
| SELL (score ≥ threshold) | 持有空仓 | 忽略 |
| NEUTRAL (score ≤ close_threshold) | 有持仓 | 平仓 |
| NEUTRAL (score ≤ close_threshold) | 无持仓 | 忽略 |

### Guard Pipeline（风控闸门）设计

> 复用 #007-04 的设计，MVP 先实现最小集。

#### MVP 必须有的检查

| 检查项 | 规则 | 默认值 |
|:---|:---|:---|
| 最大持仓数 | 同时持仓 ≤ N | 3 |
| 单标的风控 | 同一币种不重复开仓 | 是 |
| 冷却时间 | 同一币种平仓后 N 分钟内不开新仓 | 5 分钟 |
| 最大回撤暂停 | 总权益从高点回撤 ≥ X% 时暂停开仓 | 10% |
| 数据新鲜度 | 最新价格数据超过 N 分钟则停止交易 | 5 分钟 |

#### MVP 暂不做的检查

- 黑白名单管理（后续通过配置文件加）
- 复杂组合风险（VaR、相关性等）
- 账户级联风控

### 与现有代码的复用关系

| 现有模块 | 复用方式 | 说明 |
|:---|:---|:---|
| `backtest/models.py` | 直接引用 | `Position`, `ExecutionConfig`, `RiskConfig` 可直接复用 |
| `backtest/execution_engine.py` | 提取函数 | `_apply_slippage()`, 手续费计算逻辑提取为公共函数 |
| `storage/history.py` | 读取源 | 从 `signal_history.db` 读取未处理信号 |
| `storage/cooldown.py` | 参考模式 | Paper Trading 的冷却逻辑可参考 cooldown 实现 |
| `backtest/config_loader.py` | 参考模式 | YAML 配置加载可直接复用 `_deep_merge` 和 `_parse_text` |

### CLI 接口设计

```bash
# 启动模拟交易编排器
python scripts/tradecat_paper_trade.py start --strategy default.crypto.yaml

# 查看当前持仓
python scripts/tradecat_paper_trade.py positions

# 查看最近订单
python scripts/tradecat_paper_trade.py orders --limit 20

# 查看权益曲线摘要
python scripts/tradecat_paper_trade.py equity --days 7

# 查看运营指标（本周胜率、最大回撤等）
python scripts/tradecat_paper_trade.py stats --days 7

# 暂停/恢复
python scripts/tradecat_paper_trade.py pause
python scripts/tradecat_paper_trade.py resume

# 重置（清空所有模拟数据）
python scripts/tradecat_paper_trade.py reset --confirm
```

### 输出示例

```
$ python scripts/tradecat_paper_trade.py stats --days 7

=== Paper Trading Report (7 days) ===

Account:
  Initial Equity:    $10,000.00
  Current Equity:    $10,342.50
  Total Return:      +3.43%
  Max Drawdown:      -2.18%

Trading Activity:
  Total Trades:      47
  Win Rate:          58.3%
  Profit Factor:     1.42
  Avg Holding Time:  2h 15m
  Best Trade:        +$284.30 (BTCUSDT LONG)
  Worst Trade:       -$156.20 (ETHUSDT SHORT)

Current Positions:
  BTCUSDT LONG  0.025 @ $84,320  |  PnL: +$127.50 (+1.21%)
  SOLUSDT SHORT 5.0   @ $142.80  |  PnL:  -$34.00 (-0.48%)

This Week (Mon-Sun):
  Trades: 12 | Wins: 8 | Losses: 4 | Win Rate: 66.7%
  PnL: +$342.50
```

## 实施计划

### Phase 1：数据模型与存储（1-2 天）

- [ ] 创建 `paper_trading.db` schema
- [ ] 实现 `PaperLedger` 类（增删改查）
- [ ] 实现 `equity_snapshot` 定时写入
- [ ] 最小单测覆盖

### Phase 2：编排器核心逻辑（2-3 天）

- [ ] 实现 `Orchestrator` 主循环
- [ ] 信号→订单映射逻辑
- [ ] 复用 execution_engine 的滑点/手续费计算
- [ ] 持仓更新与 unrealized_pnl 计算

### Phase 3：Guard Pipeline MVP（1-2 天）

- [ ] 实现 5 项基本风控检查
- [ ] 配置模型（YAML / env）
- [ ] 阻断执行并记录原因

### Phase 4：CLI 接口（1 天）

- [ ] `tradecat_paper_trade.py` 入口脚本
- [ ] positions / orders / equity / stats 子命令
- [ ] JSON 输出模式（供 TUI 消费）

### Phase 5：TUI 集成（2-3 天）

- [ ] TUI 新增 "Paper Trading" 页面
- [ ] 实时持仓表格 + 权益曲线
- [ ] 本周/本月运营指标卡片

### Phase 6：回放与归因（1-2 天）

- [ ] 基于历史信号回放 paper trading
- [ ] 输出归因报告（哪些规则赚钱、哪些亏钱）
- [ ] 与回测结果对比分析

## 关键决策点（待讨论）

### Q1: Orchestrator 放在哪个服务？

**方案 A：放在 signal-service 内**
- 优点：直接读取 signal_history.db，无跨服务依赖
- 缺点：signal-service 职责变重

**方案 B：独立 paper-trading-service**
- 优点：职责清晰，独立部署
- 缺点：多一个服务，运维成本增加

**建议：MVP 选 A**，放在 `signal-service/src/paper_trading/` 下，作为 signal-service 的一个可选子模块启动。后续如果功能膨胀再拆分。

### Q2: 价格数据从哪里来？

**方案 A：从 TimescaleDB 读最新价**
- 优点：数据准确，与回测一致
- 缺点：需要连接 PG

**方案 B：从 collector-service 直接订阅**
- 优点：延迟更低
- 缺点：增加架构复杂度

**建议：MVP 选 A**，每分钟从 TimescaleDB 读一次最新价更新持仓盈亏即可。

### Q3: 多策略对比怎么做？

MVP 阶段先支持**单策略运行**，但数据模型中预留 `strategy_label` 字段。后续可以：
- 同时运行多个策略实例（不同 strategy_label）
- 在 TUI 中切换/对比不同策略表现
- 输出策略对比报告

### Q4: 与回测结果如何对比？

设计一个 `compare` 命令：
```bash
python scripts/tradecat_paper_trade.py compare --backtest-run-id 20260401-120000
```
输出同一策略在**相同时间段**的回测 vs 模拟交易对比：
- 收益率差异
- 交易次数差异
- 胜率差异
- 差异原因分析（滑点假设 vs 实际、信号延迟等）

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|:---|:---|:---|
| 信号延迟导致成交偏差 | 模拟结果过于乐观 | 记录信号产生时间 vs 处理时间的延迟 |
| 价格数据不连续 | 盈亏计算不准确 | 检查数据新鲜度，不连续时暂停 |
| 与回测结果差异过大 | 用户困惑 | 提供 compare 命令解释差异 |
| 状态机 bug 导致持仓异常 | 数据损坏 | 每次状态变更写入审计日志 |

## 验收标准

- [ ] 可基于实时信号自动生成模拟订单
- [ ] 风控未通过时阻断执行并给出原因
- [ ] 成功执行可生成持仓与审计产物
- [ ] CLI 可查询持仓、订单、权益、统计
- [ ] 整个链路可重放、可追溯
- [ ] TUI 可展示模拟盘实时状态
- [ ] 与回测结果可对比分析

## 相关 Issue

- Parent: `#007`
- Depends on: `#007-04` (Guard Pipeline)
- Related: `#006` (Backtest)
- Supersedes: `#007-03` (本设计整合了 007-03 的编排流程 + 007-04 的风控)

## 进展记录

### 2026-04-05

- [x] 创建设计讨论文档
- [ ] 待评审与讨论
- [ ] 待进入实现
