# TradeCat 系统架构图

> 最后更新: 2026-03-21
> 核实状态: 已通过源码核实

---

## 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                            TradeCat 系统架构 (最终版)                                  │
└─────────────────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                            🌐 外部数据源                                      │
  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
  │  │ Binance API │  │  Gate.io    │  │  yfinance   │  │ RSS 新闻源  │         │
  │  │ WS + REST   │  │  备用源     │  │ 美股/A股    │  │ 市场资讯    │         │
  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
  └─────────┼────────────────┼────────────────┼────────────────┼─────────────────┘
            │                │                │                │
            ▼                ▼                ▼                ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                            📥 采集层                                          │
  │  ┌─────────────────────────────────┐  ┌─────────────────────────────────┐   │
  │  │        data-service             │  │      markets-service (预览)     │   │
  │  │  • WebSocket K线实时采集         │  │  • 美股/港股/A股分钟线          │   │
  │  │  • REST 期货指标采集             │  │  • RSS/Atom 新闻聚合            │   │
  │  │  • 历史数据回填                  │  │  • 宏观经济数据                 │   │
  │  │  • ccxt + cryptofeed            │  │  • yfinance + akshare           │   │
  │  └────────────────┬────────────────┘  └────────────────┬────────────────┘   │
  └───────────────────┼─────────────────────────────────────┼─────────────────────┘
                      │                                     │
                      ▼                                     ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                            💾 存储层                                          │
  │  ┌───────────────────────────────────────────────────────────────────────┐  │
  │  │                    TimescaleDB (PostgreSQL 16)                         │  │
  │  │              默认端口: 5434 | 导出脚本默认: 5433                         │  │
  │  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐   │  │
  │  │  │ market_data     │  │     raw         │  │   alternative       │   │  │
  │  │  │ • candles_1m    │  │ • crypto_kline  │  │ • news_articles     │   │  │
  │  │  │ • futures_*     │  │ • equity_1m_*   │  │                     │   │  │
  │  │  └─────────────────┘  └─────────────────┘  └─────────────────────┘   │  │
  │  └───────────────────────────────────────────────────────────────────────┘  │
  │                                                                              │
  │  ┌────────────────────────────── SQLite (本地) ───────────────────────────┐  │
  │  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐    │  │
  │  │  │ market_data.db  │  │  cooldown.db    │  │ signal_history.db   │    │  │
  │  │  │ 指标计算结果     │  │ 信号冷却持久化   │  │ 信号触发历史         │    │  │
  │  │  │ (33 张表)       │  │                 │  │ (append-only)       │    │  │
  │  │  └─────────────────┘  └─────────────────┘  └─────────────────────┘    │  │
  │  └───────────────────────────────────────────────────────────────────────┘  │
  └─────────────────────────────────────────────────────────────────────────────┘
                      │
                      ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                            ⚙️ 计算层                                          │
  │  ┌───────────────────────────────────────────────────────────────────────┐  │
  │  │                        trading-service                                 │  │
  │  │                                                                         │  │
  │  │   核心分层:                                                              │  │
  │  │   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐                  │  │
  │  │   │  core/io    │ → │core/compute │ → │core/storage │                  │  │
  │  │   │ 数据读取(只读)│   │ 指标计算(纯算)│   │ 结果落盘(只写)│                │  │
  │  │   └─────────────┘   └─────────────┘   └─────────────┘                  │  │
  │  │                                                                         │  │
  │  │   指标模块 (33个):                                                       │  │
  │  │   ┌────────────────────────────────────────────────────────────────┐   │  │
  │  │   │ incremental (9): macd, kdj, atr, ema_gc, obv, cvd,            │   │  │
  │  │   │                   base_data, buy_sell_ratio, futures_sentiment │   │  │
  │  │   ├────────────────────────────────────────────────────────────────┤   │  │
  │  │   │ batch (24): k_pattern, trend_line, support_resistance, vpvr,  │   │  │
  │  │   │              super_trend, bollinger, vwap, volume_ratio, mfi, │   │  │
  │  │   │              liquidity, tv_rsi, tv_trend_cloud, tv_big_money, │   │  │
  │  │   │              tv_fib_sniper, tv_zero_lag, tv_volume_signal,    │   │  │
  │  │   │              tv_long_short, scalping, harmonic,               │   │  │
  │  │   │              futures_aggregate, lean_indicators, data_monitor,│   │  │
  │  │   │              futures_gap_monitor                              │   │  │
  │  │   └────────────────────────────────────────────────────────────────┘   │  │
  │  │                                                                         │  │
  │  │   技术栈: pandas + numpy + TA-Lib + m-patternpy                         │  │
  │  └───────────────────────────────────────────────────────────────────────┘  │
  └─────────────────────────────────────────────────────────────────────────────┘
                      │
                      ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                            📊 信号层                                          │
  │  ┌───────────────────────────────────────────────────────────────────────┐  │
  │  │                        signal-service                                  │  │
  │  │                                                                         │  │
  │  │   双引擎: SQLite引擎 (读指标库) + PG引擎 (读原始K线)                      │  │
  │  │                                                                         │  │
  │  │   规则分类 (129条, 8类):                                                 │  │
  │  │   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │  │
  │  │   │  core    │ │ momentum │ │  trend   │ │ pattern  │ │ volume   │    │  │
  │  │   │  (27条)  │ │  (32条)  │ │  (20条)  │ │  (16条)  │ │  (15条)  │    │  │
  │  │   └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘    │  │
  │  │   ┌──────────┐ ┌──────────┐ ┌──────────┐                              │  │
  │  │   │volatility│ │ futures  │ │   misc   │                              │  │
  │  │   │  (18条)  │ │  (12条)  │ │  (9条)   │                              │  │
  │  │   └──────────┘ └──────────┘ └──────────┘                              │  │
  │  └───────────────────────────────────────────────────────────────────────┘  │
  └─────────────────────────────────────────────────────────────────────────────┘
                      │
        ┌─────────────┴─────────────┐
        ▼                           ▼
  ┌───────────────────────────┐  ┌─────────────────────────────────────────────┐
  │        🖥️ 展示层          │  │              🧪 回测引擎                     │
  │  ┌─────────────────────┐  │  │  ┌───────────────────────────────────────┐  │
  │  │  tui-service (预览) │  │  │  │         backtest / backtest.sh        │  │
  │  │                     │  │  │  │                                       │  │
  │  │ • 终端 TUI 信号看板 │  │  │  │  回测模式 (4种):                       │  │
  │  │ • 多市场行情展示    │  │  │  │  ┌─────────────────────────────────┐   │  │
  │  │ • 回测结果可视化    │  │  │  │  │ • history_signal (历史信号)     │   │  │
  │  │ • 新闻资讯聚合      │  │  │  │  │ • offline_replay (离线回放)     │   │  │
  │  │ • 只读数据库        │  │  │  │  │ • offline_rule_replay (规则重放)│   │  │
  │  │                     │  │  │  │  │ • compare_history_rule (对比)   │   │  │
  │  └─────────────────────┘  │  │  │  └─────────────────────────────────┘   │  │
  │                           │  │  │                                       │  │
  │  双TUI工作台:              │  │  │  功能特性:                             │  │
  │  TradeCat + 外部编排层     │  │  │  • 覆盖率检查                          │  │
  │  (tmux 并排)              │  │  │  • 分层滑点模型                        │  │
  │                           │  │  │  • 执行约束 (max_participation)        │  │
  └───────────────────────────┘  │  │  • 多基准对比 (buy_hold等)             │  │
                                 │  │  • Walk-Forward 滚动窗口               │  │
                                 │  │  • 真实窗口校准验证                    │  │
                                 │  │  • 自动选参 (每折)                     │  │
                                 │  └───────────────────────────────────────┘  │
                                 └─────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                            ⚙️ 配置与共享库                                    │
  │  ┌─────────────────────────────┐  ┌─────────────────────────────────────┐   │
  │  │       config/.env           │  │         libs/common/ (7模块)        │   │
  │  │  • 统一配置 (权限 600)       │  │  • config_loader 配置加载           │   │
  │  │  • 所有服务共用              │  │  • db_url 数据库URL解析            │   │
  │  │  • 含密钥/数据库连接         │  │  • i18n 国际化                      │   │
  │  │  • 默认端口 5434             │  │  • proxy_manager 代理管理           │   │
  │  │                             │  │  • scheduler 调度器                 │   │
  │  │                             │  │  • symbols 币种分组管理             │   │
  │  │                             │  │  • utils/gemini_client             │   │
  │  └─────────────────────────────┘  └─────────────────────────────────────┘   │
  └─────────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                            📁 产物输出                                        │
  │  ┌───────────────────────────────────────────────────────────────────────┐  │
  │  │                      artifacts/backtest/                               │  │
  │  │                                                                         │  │
  │  │  ├── YYYYMMDD-HHMMSS/           # 时间戳目录 (每次运行)                 │  │
  │  │  │   ├── metrics.json           # 回测指标 (收益/夏普/回撤)             │  │
  │  │  │   ├── trades.csv             # 交易记录                              │  │
  │  │  │   ├── equity_curve.csv       # 权益曲线                              │  │
  │  │  │   ├── input_quality.json     # 输入质量评分                          │  │
  │  │  │   ├── stability_report.json  # 稳定性分析                            │  │
  │  │  │   ├── comparison.json/.md    # 历史对比                              │  │
  │  │  │   └── walk_forward_summary.json  # Walk-Forward 汇总                 │  │
  │  │  │                                                                     │  │
  │  │  └── latest/                    # 软链接指向最新结果                     │  │
  │  └───────────────────────────────────────────────────────────────────────┘  │
  └─────────────────────────────────────────────────────────────────────────────┘
```

---

## 数据流向

```
  外部API        采集层           存储层           计算层           信号层         展示/回测
  ────────      ──────           ──────           ──────           ──────         ────────
  Binance  ──→  data-service ──→ TimescaleDB ──→ trading-svc ──→ signal-svc ──→ tui-service
  yfinance  ──→ markets-svc  ──↗      │              │               │               │
  RSS       ──────────────────────↗   │              │               │               │
                                    │              ▼               │               │
                                    │        SQLite ◄─────────────┘               │
                                    │        (指标)                               │
                                    │              │                               │
                                    │              ▼                               │
                                    │        SQLite (信号历史)                     │
                                    │              │                               │
                                    └──────────────┼───────────────────────────────┘
                                                   │
                                    ┌──────────────┴──────────────┐
                                    ▼                             ▼
                              回测引擎                      artifacts/backtest/
                              ────────                      ──────────────────
                              • history_signal              • metrics.json
                              • offline_replay              • trades.csv
                              • offline_rule_replay         • equity_curve.csv
                              • compare_history_rule        • stability_report
```

---

## 服务清单

| 层级 | 服务 | 位置 | 职责 | 技术栈 |
|:---|:---|:---|:---|:---|
| **采集层** | data-service | `services/` | 加密货币 K线/期货采集 | ccxt, cryptofeed, asyncio |
| **采集层** | markets-service | `services-preview/` | 全市场数据采集 (美股/A股/新闻) | yfinance, akshare, fredapi |
| **计算层** | trading-service | `services/` | 33 个技术指标计算 | pandas, numpy, TA-Lib |
| **信号层** | signal-service | `services/` | 129 条信号规则检测 (8 分类) | SQLite + PostgreSQL 双引擎 |
| **展示层** | tui-service | `services-preview/` | 终端 TUI 信号看板 (只读) | Python stdlib |

---

## 数据库架构

### TimescaleDB (PostgreSQL 16)

| Schema | 表 | 用途 |
|:---|:---|:---|
| `market_data` | `candles_1m` | 1 分钟 K 线数据 (hypertable) |
| `market_data` | `binance_futures_metrics_5m` | 期货情绪指标 |
| `raw` | `crypto_kline_1m` | 加密货币原始 K 线 |
| `raw` | `equity_1m_*` | 美股/港股/A股分钟线 |
| `alternative` | `news_articles` | 新闻文章表 |

**端口**: 默认 5434 (新库)，导出脚本默认 5433 (旧库)

### SQLite (本地)

| 数据库 | 路径 | 用途 |
|:---|:---|:---|
| `market_data.db` | `libs/database/services/telegram-service/` | 指标计算结果 (33 张表) |
| `signal_history.db` | `libs/database/services/signal-service/` | 信号触发历史 (append-only) |
| `cooldown.db` | `libs/database/services/signal-service/` | 信号冷却持久化 |

---

## 指标模块 (33 个)

### 增量指标 (incremental, 9 个)

| 指标 | 说明 |
|:---|:---|
| macd | MACD 柱状扫描器 |
| kdj | KDJ 随机指标扫描器 |
| atr | ATR 波幅扫描器 |
| ema_gc | EMA 金叉扫描器 |
| obv | OBV 能量潮扫描器 |
| cvd | CVD 信号排行榜 |
| base_data | 基础数据同步器 |
| buy_sell_ratio | 主动买卖比扫描器 |
| futures_sentiment | 期货情绪元数据 |

### 批量指标 (batch, 24 个)

| 指标 | 说明 |
|:---|:---|
| k_pattern | K 线形态扫描器 |
| trend_line | 趋势线榜单 |
| support_resistance | 全量支撑阻力扫描器 |
| vpvr | VPVR 排行生成器 |
| super_trend | SuperTrend |
| bollinger | 布林带扫描器 |
| vwap | VWAP 离线信号扫描 |
| volume_ratio | 成交量比率扫描器 |
| mfi | MFI 资金流量扫描器 |
| liquidity | 流动性扫描器 |
| tv_rsi | 智能 RSI 扫描器 |
| tv_trend_cloud | 趋势云反转扫描器 |
| tv_big_money | 大资金操盘扫描器 |
| tv_fib_sniper | 量能斐波狙击扫描器 |
| tv_zero_lag | 零延迟趋势扫描器 |
| tv_volume_signal | 量能信号扫描器 |
| tv_long_short | G，C 点扫描器 |
| scalping | 剥头皮信号扫描器 |
| harmonic | 谐波信号扫描器 |
| futures_aggregate | 期货情绪聚合表 |
| lean_indicators | 精简指标 |
| data_monitor | 数据监控器 |
| futures_gap_monitor | 期货情绪缺口监控 |

---

## 信号规则 (129 条, 8 分类)

| 分类 | 规则数 | 说明 |
|:---:|:---|:---|
| **core** | 27 | 核心高价值信号 (confluence, futures_extreme, volume_anomaly, smc, macd, sr) |
| **momentum** | 32 | 动量指标 (rsi, kdj, cci, williams, mfi, adx, harmonic) |
| **trend** | 20 | 趋势指标 (supertrend, precise, ichimoku, zerolag, cloud, trendline, ha, volume_trend, gc) |
| **volatility** | 18 | 波动率指标 (bollinger, atr, donchian, keltner, sr, vwap) |
| **volume** | 15 | 成交量指标 (macd, obv, cvd, ratio, taker) |
| **futures** | 12 | 期货情绪 (sentiment) |
| **pattern** | 16 | K 线形态 (candlestick, smc, fibonacci, vpvr) |
| **misc** | 9 | 其他信号 (liquidity, scalping, basic) |

---

## 回测模块

### 回测模式 (4 种)

| 模式 | 说明 |
|:---|:---|
| `history_signal` | 历史信号回测 |
| `offline_replay` | 基于 K 线生成信号的离线回放 |
| `offline_rule_replay` | SQLite 129 规则离线重放 |
| `compare_history_rule` | 历史信号 vs 规则重放对比 |

### 功能特性

- **覆盖率检查**: `--check-only` 预检门槛
- **分层滑点模型**: volatility + volume + session 三维加权
- **执行约束**: bar 容量限制 + 最小订单 + 冲击成本
- **多基准对比**: buy_hold / risk_parity / momentum
- **Walk-Forward**: 滚动窗口选参
- **真实窗口校准**: `backtest/real_window_validation.sh`

### 回测命令

```bash
# 默认回测
./scripts/backtest.sh

# Walk-Forward
./scripts/backtest.sh --walk-forward

# 离线回放
./scripts/backtest.sh --mode offline_replay

# 规则重放
./scripts/backtest.sh --mode offline_rule_replay

# 历史对比
./scripts/backtest.sh --mode compare_history_rule

# 覆盖率检查
./scripts/backtest.sh --check-only

# 真实窗口校准
./scripts/backtest/real_window_validation.sh
```

---

## 关键文件引用

| 服务 | 关键文件 |
|:---|:---|
| data-service | `services/data-service/src/collectors/ws.py:131` |
| trading-service IO | `services/trading-service/src/core/io.py:13-35` |
| trading-service Compute | `services/trading-service/src/core/compute.py` |
| trading-service Storage | `services/trading-service/src/core/storage.py:14-27` |
| signal-service SQLite | `services/signal-service/src/engines/sqlite_engine.py:67-100` |
| signal-service PG | `services/signal-service/src/engines/pg_engine.py` |
| signal-service 规则 | `services/signal-service/src/rules/__init__.py` |
| tui-service | `services-preview/tui-service/src/db.py:50-80` |
| 回测引擎 | `services/signal-service/src/backtest/` |

---

## 配置项分类

| 分类 | 关键配置项 |
|:---|:---|
| **网络代理** | `HTTP_PROXY`, `HTTPS_PROXY` |
| **数据库连接** | `DATABASE_URL` (默认端口 5434) |
| **Telegram Bot** | `BOT_TOKEN`, `ADMIN_USER_IDS` |
| **币种管理** | `SYMBOLS_GROUPS`, `SYMBOLS_EXTRA`, `SYMBOLS_EXCLUDE` |
| **周期配置** | `INTERVALS`, `KLINE_INTERVALS`, `FUTURES_INTERVALS` |
| **数据采集** | `BACKFILL_MODE`, `MAX_CONCURRENT`, `RATE_LIMIT_PER_MINUTE` |
| **指标计算** | `MAX_WORKERS`, `COMPUTE_BACKEND` |
| **信号服务** | `SIGNAL_DATA_MAX_AGE`, `COOLDOWN_SECONDS` |
| **新闻采集** | `NEWS_RSS_FEEDS`, `NEWS_RSS_POLL_INTERVAL_SECONDS` |

---

## 共享库模块 (libs/common/)

| 模块 | 功能 |
|:---|:---|
| `config_loader` | 配置加载 (解析 .env) |
| `db_url` | 数据库 URL 解析 |
| `i18n` | 国际化 (gettext 封装) |
| `proxy_manager` | 代理管理 (带重试和冷却) |
| `scheduler` | 调度器 (指数退避) |
| `symbols` | 币种分组管理 |
| `utils/gemini_client` | Gemini CLI 封装 |
