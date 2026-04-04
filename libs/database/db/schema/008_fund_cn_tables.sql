-- ============================================================================
-- 008_fund_cn_tables.sql
-- ----------------------------------------------------------------------------
-- 目的: 创建中国基金相关数据表（场内ETF + 场外基金估值）
-- 依赖: 001_timescaledb.sql (TimescaleDB 扩展)
-- 
-- 表结构:
--   - market_data.fund_cn_etf: 场内基金行情（ETF/LOF）
--   - market_data.fund_cn_offmarket: 场外基金估值
--
-- 使用说明:
--   docker exec -i tradecat-timescaledb psql -U postgres -d market_data < 008_fund_cn_tables.sql
-- ============================================================================

-- 创建 schema（如果不存在）
CREATE SCHEMA IF NOT EXISTS market_data;

-- 设置 schema 搜索路径
SET search_path TO market_data, public;

-- ============================================================================
-- 1. 场内基金表 (ETF/LOF)
-- ============================================================================

-- 创建表
CREATE TABLE IF NOT EXISTS market_data.fund_cn_etf (
    symbol      TEXT        NOT NULL,    -- 基金代码: SH510300, SZ159915
    timestamp   TIMESTAMPTZ NOT NULL,    -- 时间戳
    open        REAL,                     -- 开盘价
    high        REAL,                     -- 最高价
    low         REAL,                     -- 最低价
    close       REAL,                     -- 收盘价
    volume      REAL,                     -- 成交量
    amount      REAL,                     -- 成交额
    PRIMARY KEY (symbol, timestamp)
);

-- 转换为 Hypertable
SELECT create_hypertable(
    'market_data.fund_cn_etf',
    'timestamp',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- 启用压缩
ALTER TABLE IF EXISTS market_data.fund_cn_etf
    SET (timescaledb.compress = TRUE,
         timescaledb.compress_segmentby = 'symbol',
         timescaledb.compress_orderby = 'timestamp DESC');

-- 添加压缩策略（7天后压缩）
DO $$
BEGIN
    PERFORM add_compression_policy('market_data.fund_cn_etf', INTERVAL '7 days');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END$$;

-- 添加保留策略（90天后删除）
DO $$
BEGIN
    PERFORM add_retention_policy('market_data.fund_cn_etf', INTERVAL '90 days');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END$$;

-- 创建索引（按 symbol 查询优化）
CREATE INDEX IF NOT EXISTS idx_fund_cn_etf_symbol 
    ON market_data.fund_cn_etf (symbol, timestamp DESC);

-- ============================================================================
-- 2. 场外基金估值表
-- ============================================================================

-- 创建表
CREATE TABLE IF NOT EXISTS market_data.fund_cn_offmarket (
    fund_code            TEXT        NOT NULL,    -- 6位基金代码: 024389
    timestamp            TIMESTAMPTZ NOT NULL,    -- 时间戳
    estimated_nav        REAL,                     -- 估值净值
    estimated_change_pct REAL,                     -- 估值涨跌幅 (%)
    PRIMARY KEY (fund_code, timestamp)
);

-- 转换为 Hypertable
SELECT create_hypertable(
    'market_data.fund_cn_offmarket',
    'timestamp',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- 启用压缩
ALTER TABLE IF EXISTS market_data.fund_cn_offmarket
    SET (timescaledb.compress = TRUE,
         timescaledb.compress_segmentby = 'fund_code',
         timescaledb.compress_orderby = 'timestamp DESC');

-- 添加压缩策略（7天后压缩）
DO $$
BEGIN
    PERFORM add_compression_policy('market_data.fund_cn_offmarket', INTERVAL '7 days');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END$$;

-- 添加保留策略（90天后删除）
DO $$
BEGIN
    PERFORM add_retention_policy('market_data.fund_cn_offmarket', INTERVAL '90 days');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END$$;

-- 创建索引（按 fund_code 查询优化）
CREATE INDEX IF NOT EXISTS idx_fund_cn_offmarket_code 
    ON market_data.fund_cn_offmarket (fund_code, timestamp DESC);

-- ============================================================================
-- 3. 权限设置
-- ============================================================================

-- 授权（根据实际用户调整）
-- GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA market_data TO your_user;

-- ============================================================================
-- 验证
-- ============================================================================

-- 查看表结构
\d market_data.fund_cn_etf
\d market_data.fund_cn_offmarket

-- 查看 hypertable 信息
SELECT hypertable_name, num_chunks 
FROM timescaledb_information.hypertables 
WHERE hypertable_schema = 'market_data' 
  AND hypertable_name IN ('fund_cn_etf', 'fund_cn_offmarket');

-- 查看压缩策略
SELECT hypertable_name, compression_state 
FROM timescaledb_information.hypertables 
WHERE hypertable_schema = 'market_data' 
  AND hypertable_name IN ('fund_cn_etf', 'fund_cn_offmarket');
