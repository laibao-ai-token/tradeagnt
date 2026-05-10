# 008-03 Provider 与数据层

**Issue ID**: #008-03 | **Priority**: High | **Dependencies**: #008-02

## 目标
实现 Provider 插件化 + 统一 PG schema，删除 SQLite 依赖。

## 任务清单

### Provider 层
- [x] `core/providers/base.py` — `DataProvider` ABC（`fetch_klines`, `fetch_latest`, `supported_symbols`）
- [x] `core/providers/registry.py` — 注册表 + 动态加载 (`auto_register`)
- [x] `core/providers/binance.py` — BinanceProvider（crypto）
- [x] `core/providers/gate.py` — GateProvider（crypto）
- [x] `core/providers/rss_news.py` — RSSNewsProvider（新闻）
- [ ] `core/providers/yahoo.py` — YahooProvider（占位，Phase 2）
- [ ] `core/providers/eastmoney.py` — EastMoneyProvider（占位，Phase 2）

### 数据层
- [x] `data/pg.py` — asyncpg 连接池封装
- [x] 统一 PG Schema：
  - `market_data.candles_1m/5m/15m/1h/4h/1d`
  - `signal.history`
  - `signal.cooldown`
  - `alternative.news_articles`
- [ ] 新增 `paper_*` 系列表（详见 008-08）
- [x] Alembic 迁移脚本
- [x] 删除 `libs/database/` 下 SQLite 文件引用
- [x] `grep -r "sqlite3\|to_sql\|read_sql" src/tradecat/` 返回 0

## 验收标准

- [x] `tradecat fetch BTCUSDT --provider binance` CLI 可用（网络受限区域无法实测 Binance API）
- [ ] `tradecat analyze BTCUSDT` 走通（依赖 008-04 指标引擎）
- [x] 删除所有 `import sqlite3` 代码路径
- [ ] `pg_stat_user_tables` 显示所有表已创建（需本地 PG 运行后 `alembic upgrade head`）
