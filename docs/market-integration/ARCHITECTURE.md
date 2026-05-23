# 分层架构

## 总览

```mermaid
flowchart TB
    subgraph Config["配置层"]
        YAML["config/strategies/*.yaml<br>market + symbols + rules"]
    end

    subgraph Entry["入口层"]
        CLI["tradecat cli<br>signal / daemon / backtest / paper"]
        TUI["tradecat tui + signal_poller"]
        Bridge["scripts/tradecat_get_*.py"]
    end

    subgraph Core["核心层（市场无关）"]
        Loader["StrategyLoader"]
        SE["SignalEngine"]
        IND["IndicatorRegistry"]
        PT["PaperTradingEngine"]
        BT["backtest.paper_sim"]
    end

    subgraph Market["市场适配层（按市场扩展）"]
        SYM["symbols/*<br>normalize + default_provider"]
        PR["providers/*<br>DataProvider 插件"]
    end

    subgraph Storage["存储"]
        SH[("signal_history.db")]
        PDB[(".paper_trading.db")]
        PG[("PostgreSQL 可选")]
    end

    subgraph Quote["行情实现（可复用）"]
        TQ["tui/quote.py<br>tencent / nasdaq / gate ..."]
    end

    YAML --> Loader
    CLI --> Loader
    TUI --> Loader
    Loader --> SE
    SE --> IND
    SE --> SYM
    SE --> PR
    PR --> TQ
    SE --> SH
    SE --> PT
    PT --> PDB
    CLI --> PT
    BT --> SE
```

## 各层职责

| 层 | 路径 | 是否随新市场改动 |
|:---|:---|:---:|
| 策略配置 | `config/strategies/` | ✅ 新增 YAML |
| 符号 | `core/symbols/` | ✅ 新增/扩展 |
| 数据源 | `core/providers/` | ✅ 新增 Provider |
| 信号引擎 | `core/signals/` | ❌ 原则上不改 |
| 指标 | `core/indicators/` | ❌ 共用 |
| 模拟盘 | `core/paper_trading/` | ⚠️ 仅扩展归一化 |
| 回测辅助 | `core/backtest/` | ❌ 共用 |
| CLI | `cli/*.py` | ⚠️ 仅当缺 market 透传时改 |
| TUI | `tui/` | ⚠️ poller 读策略 market |

## 运行时序列（daemon 为例）

```mermaid
sequenceDiagram
    participant U as 用户
    participant D as daemon
    participant L as StrategyLoader
    participant S as symbols
    participant E as SignalEngine
    participant P as UsEquityProvider
    participant DB as signal_history.db
    participant Paper as PaperTradingEngine

    U->>D: tradecat daemon --strategy us_fast_5m.yaml
    D->>L: load(strategy)
    L-->>D: market=us_stock, symbols=[NVDA,...]
    D->>S: normalize_symbols + default_provider
    loop 每 interval
        D->>E: run(strategy, NVDA, us_equity)
        E->>P: fetch_klines(5m)
        P-->>E: DataFrame
        E-->>D: SignalEvent[]
        D->>DB: INSERT signal_history
        opt auto-trade
            D->>Paper: from_signal(market=us_stock)
        end
    end
```

## 已接入市场状态

| market | Provider | 符号模块 | 策略示例 | 状态 |
|:---|:---|:---|:---|:---:|
| `crypto` | `gate` / `binance` | `symbols/crypto.py` | `fast_1m.yaml` | 生产 |
| `us_stock` | `us_equity` | `symbols/equity.py` | `us_fast_5m.yaml` | 已接入 |
| `hk_stock` | （待）`hk_equity` | （待）`symbols/hk.py` | （待） | 行情在 TUI |
| `cn_stock` | （待）`cn_equity` | （待）`symbols/cn.py` | （待） | 行情在 TUI |
| `cn_fund` | （待） | （待） | （待） | 行情在 TUI |

TUI `quote.py` 已支持多市场报价；核心 Provider 按上表逐个接入即可。
