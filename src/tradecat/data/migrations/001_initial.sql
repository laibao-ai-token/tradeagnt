-- TradeCat Phase 1 schema (TimescaleDB)
-- Migration: 001_initial

------------------------------------------------------------------------------
-- Extensions
------------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS timescaledb;

------------------------------------------------------------------------------
-- Schema namespaces
------------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS schema;
CREATE SCHEMA IF NOT EXISTS signal;
CREATE SCHEMA IF NOT EXISTS crypto;
CREATE SCHEMA IF NOT EXISTS forex;

------------------------------------------------------------------------------
-- Migration tracking
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema.migrations (
    name        TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ DEFAULT NOW(),
    md5         TEXT
);

------------------------------------------------------------------------------
-- Signal history (hypertable)
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signal.history (
    id          BIGSERIAL,
    symbol      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    direction   TEXT NOT NULL,
    strength    INTEGER,
    rule_id     TEXT,
    rule_name   TEXT,
    timestamp   TIMESTAMPTZ NOT NULL,
    price       NUMERIC,
    message     TEXT,
    raw_data    JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('signal.history', 'timestamp',
    if_not_exists => TRUE, migrate_data => TRUE);

CREATE INDEX IF NOT EXISTS idx_signal_history_symbol
    ON signal.history(symbol, timestamp DESC);

------------------------------------------------------------------------------
-- Signal cooldown
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signal.cooldown (
    symbol      TEXT PRIMARY KEY,
    last_fired  TIMESTAMPTZ NOT NULL,
    cool_until  TIMESTAMPTZ NOT NULL
);

------------------------------------------------------------------------------
-- Crypto klines (hypertable)
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crypto.timeframes (
    symbol      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    timestamp   TIMESTAMPTZ NOT NULL,
    open        NUMERIC,
    high        NUMERIC,
    low         NUMERIC,
    close       NUMERIC,
    volume      NUMERIC
);

SELECT create_hypertable('crypto.timeframes', 'timestamp',
    if_not_exists => TRUE, migrate_data => TRUE);

CREATE UNIQUE INDEX IF NOT EXISTS idx_crypto_timeframes_unique
    ON crypto.timeframes(symbol, timeframe, timestamp);

------------------------------------------------------------------------------
-- Forex klines (hypertable)
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS forex.timeframes (
    symbol      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    timestamp   TIMESTAMPTZ NOT NULL,
    open        NUMERIC,
    high        NUMERIC,
    low         NUMERIC,
    close       NUMERIC,
    volume      NUMERIC
);

SELECT create_hypertable('forex.timeframes', 'timestamp',
    if_not_exists => TRUE, migrate_data => TRUE);

CREATE UNIQUE INDEX IF NOT EXISTS idx_forex_timeframes_unique
    ON forex.timeframes(symbol, timeframe, timestamp);
