# 008-03 Provider 与数据层

**Issue ID**: #008-03 | **Priority**: High | **Dependencies**: #008-02

## 目标
实现 Provider 插件化 + 统一 PG schema，删除 SQLite 依赖。

## 任务清单

### Provider 层
- [ ] `core/providers/base.py` — `DataProvider` ABC（`fetch_klines`, `fetch_latest`, `supported_symbols`）
- [ ] `core/providers/registry.py` — 注册表 + 动态加载
- [ ] `core/providers/binance.py` — BinanceProvider（crypto）
- [ ] `core/providers/gate.py` — GateProvider（crypto）
- [ ] `core/providers/rss_news.py` — RSSNewsProvider（新闻）
- [ ] `core/providers/yahoo.py` — YahooProvider（占位，Phase 2）
- [ ] `core/providers/eastmoney.py` — EastMoneyProvider（占位，Phase 2）

### 数据层
- [ ] `data/pg.py` — asyncpg 连接池封装
- [ ] 统一 PG Schema（所有服务共用）：
  - `market_data.candles_1m/5m/15m/1h/4h/1d`（已存在，不改动）
  - `signal.history`（信号记录）
  - `signal.cooldown`（冷却记录）
  - `alternative.news_articles`（新闻）
- [ ] 新增 `paper_*` 系列表（详见 008-08）
- [ ] Alembic 迁移脚本
- [ ] 删除 `libs/database/` 下 SQLite 文件引用
- [ ] `grep -r "sqlite3\|to_sql\|read_sql" src/tradecat/` 返回 0

## 验收标准

- [ ] `tradecat fetch BTCUSDT --provider binance` 输出 DataFrame
- [ ] `tradecat analyze BTCUSDT` 走通：Provider → PG → Indicator
- [ ] 删除所有 `import sqlite3` 代码路径
- [ ] `pg_stat_user_tables` 显示所有表已创建
