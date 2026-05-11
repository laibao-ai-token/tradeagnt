# 008-08 虚拟盘引擎（加密货币）

**Issue ID**: #008-08 | **Priority**: High | **Dependencies**: #008-03 + #008-05

## 目标
合并 `Orchestrator` + `BtcPaperTrader` 两套实现，构建**统一的加密货币虚拟盘引擎**。状态从 JSON 迁移到 PG，全量使用 Decimal 精度。

> ⚠️ **Phase 1 币种约束**：只支持**加密货币**（BTCUSDT、ETHUSDT），价格从 Binance/Gate Provider 获取。

## 当前问题

| 问题 | 说明 |
|------|------|
| 两套重复代码 | Orchestrator（891行）+ BtcPaperTrader（785行）各有一套仓位/P&L |
| JSON 非并发安全 | `state.json` 多进程写入会损坏 |
| 精度不一致 | 289 处 float，btc_paper 3 个自定义 round，orchestrator 0 处精度控制 |
| 价格源硬编码 | Binance/Gate URL 写死在代码里 |

## 统一架构

```
signal.history (PG) / 内存 Queue
          ↓
┌──────────────────────────────────────────┐
│      PaperTradingEngine（统一引擎）        │
│  ┌──────────────┐  ┌─────────────────┐  │
│  │ OrderManager   │  │ PositionManager │  │
│  │  订单状态机     │  │  仓位/合并/翻转   │  │
│  └──────┬───────┘  └────────┬────────┘  │
│         └─────────┬──────────┘            │
│                   ↓                        │
│         ┌─────────────────┐            │
│         │   RiskGuard       │            │
│         │  风控 drawdown    │            │
│         └────────┬────────┘             │
│                    ↓                       │
│         ┌─────────────────┐            │
│         │ ExecutionAuditor│            │
│         │  执行审计 + 归因   │           │
│         └────────┬────────┘             │
└────────────────────┼───────────────────────┘
                     ↓
              ┌────────────────┐
              │  TimescaleDB   │
              │ • paper_orders │
              │ • paper_positions│
              │ • paper_fills  │
              │ • portfolio_snapshots |
              │ • execution_attributions |
              └────────────────┘
```

## 数据模型（Decimal 全仓）

```python
class PaperOrder:
    order_id: str
    symbol: str            # BTCUSDT / ETHUSDT
    side: Side              # LONG / SHORT / NEUTRAL
    qty: Decimal            # 统一 Decimal
    entry_price: Decimal
    status: OrderStatus     # PENDING→STAGED→CONFIRMED→FILLED
    leverage: float = 1.0

class PaperPosition:
    symbol: str
    side: str
    qty: Decimal
    entry_price: Decimal
    margin: Decimal
    leverage: float
    unrealized_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
```

## PG Schema（6 张表）

```sql
CREATE TABLE paper_accounts (
    account_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    balance NUMERIC(24,8) DEFAULT 10000.0,
    leverage NUMERIC(5,2) DEFAULT 1.0,
    max_drawdown_pct NUMERIC(5,2) DEFAULT 10.0
);

CREATE TABLE paper_orders (
    order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID REFERENCES paper_accounts(account_id),
    idempotency_key TEXT UNIQUE,
    symbol TEXT NOT NULL,
    side TEXT CHECK (side IN ('LONG','SHORT','NEUTRAL')),
    qty NUMERIC(24,8),
    entry_price NUMERIC(24,8),
    status TEXT CHECK (status IN ('PENDING','STAGED','CONFIRMED','FILLED','CANCELLED','REJECTED')),
    leverage NUMERIC(5,2) DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_orders_symbol ON paper_orders(symbol, status);

CREATE TABLE paper_positions (
    account_id UUID REFERENCES paper_accounts(account_id),
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty NUMERIC(24,8) DEFAULT 0,
    entry_price NUMERIC(24,8),
    margin NUMERIC(24,8) DEFAULT 0,
    leverage NUMERIC(5,2) DEFAULT 1.0,
    unrealized_pnl NUMERIC(24,8) DEFAULT 0,
    realized_pnl NUMERIC(24,8) DEFAULT 0,
    PRIMARY KEY (account_id, symbol)
);

CREATE TABLE paper_fills (
    ts TIMESTAMPTZ NOT NULL,
    fill_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID REFERENCES paper_orders(order_id),
    symbol TEXT, side TEXT, qty NUMERIC(24,8),
    price NUMERIC(24,8), fee NUMERIC(24,8)
);
SELECT create_hypertable('paper_fills', 'ts', chunk_time_interval => INTERVAL '7 days');

CREATE TABLE portfolio_snapshots (
    ts TIMESTAMPTZ NOT NULL,
    account_id UUID,
    cash_balance NUMERIC(24,8),
    total_equity NUMERIC(24,8),
    peak_equity NUMERIC(24,8),
    drawdown_pct NUMERIC(5,2)
);
SELECT create_hypertable('portfolio_snapshots', 'ts', chunk_time_interval => INTERVAL '1 day');

CREATE TABLE execution_attributions (
    ts TIMESTAMPTZ NOT NULL, trace_id UUID, order_id UUID,
    symbol TEXT, side TEXT, qty NUMERIC(24,8),
    requested_price NUMERIC(24,8), fill_price NUMERIC(24,8),
    fee NUMERIC(24,8), outcome TEXT,
    guard_passed BOOLEAN, guard_risk_level TEXT,
    guard_failed_rules TEXT[]
);
SELECT create_hypertable('execution_attributions', 'ts', chunk_time_interval => INTERVAL '7 days');
```

## 核心性能优化

| 场景 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| 价格获取 | 同步 HTTP | Async + 5s TTL cache | 5-20x |
| 下单写入 | JSON 覆盖写 | PG 行锁事务 | 100x+ |
| Fill 批量 | 逐条 INSERT | `copy_records_to_table` | 50-100x |
| 资金曲线 | JSON 全量加载 | 连续聚合视图 | 秒查 |
| 精度 | float | Decimal | 零误差 |

## CLI 命令

```bash
tradecat paper account create --name "主账户" --balance 10000 --leverage 3
tradecat paper long BTCUSDT --notional 1000
tradecat paper short BTCUSDT --notional 500
tradecat paper close BTCUSDT
tradecat paper flip BTCUSDT --notional 1000
tradecat paper status
tradecat paper history --limit 20
tradecat paper from-signal BTCUSDT --timeframe 1h
tradecat paper positions / portfolio / stats / report
```

## 配置 YAML

```yaml
paper_trading:
  default_account: { balance: 10000.0, leverage: 1.0 }
  execution: { fee_rate: 0.0004, default_slippage_bps: 2.0 }
  precision: { price: 2, qty: 6, usdt: 2 }
  risk: { max_drawdown_pct: 10.0, max_positions: 5, max_single_trade_pct: 0.95 }
  price_fetchers: [{ name: binance, priority: 1 }, { name: gate, priority: 2 }]
```

## 补充说明（边界与接口）

### 1. 失败回滚

订单生命周期 `PENDING → STAGED → CONFIRMED → FILLED` 中，若 **STAGED → CONFIRMED** 阶段检测到价格异常（滑点超过 `default_slippage_bps`），自动回滚到 `PENDING` 状态并记录 `execution_attributions.guard_failed_rules`。

### 2. 与 008-05 信号引擎的接口

`tradecat paper from-signal BTCUSDT --timeframe 1h` 时，SignalEngine 传入的 payload 格式：

```python
{
    "symbol": "BTCUSDT",
    "side": "LONG" | "SHORT",      # 由 SignalEvent.direction 映射
    "qty_notional": Decimal,       # 按 account.max_single_trade_pct * balance 计算
    "strength": int,               # SignalEvent.strength
    "rule_name": str,              # SignalEvent.rule_name
    "idempotency_key": str,         # signal_id + symbol + side
}
```

PaperTradingEngine 收到 payload 后：
1. 校验 `idempotency_key` 是否已存在
2. 通过 RiskGuard
3. 调用 OrderManager.create_order()

## 验收标准

- [ ] `tradecat paper long BTCUSDT --notional 1000` 成功开仓
- [ ] `tradecat paper flip BTCUSDT --notional 1000` 多空翻转正确
- [ ] 同一 idempotency_key 重复下单只执行一次
- [ ] 风控超限（max_drawdown）时订单 REJECTED
- [ ] 价格获取 < 1.5s，批量写入 1000 fills < 2s
- [ ] Decimal 精度零误差：`Decimal("0.1") + Decimal("0.2") == Decimal("0.3")`
- [ ] 并发 100 订单写入后 balance + positions 一致
- [ ] 滑点超限回滚：STAGED→PENDING 正确恢复
- [ ] `from-signal` 接收 SignalEngine payload 正确映射为订单
