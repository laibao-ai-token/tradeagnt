"""Initial schema for migrated modular-monolith architecture.

Revision ID: 001
Revises:
Create Date: 2026-05-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Core market-data schema + candles tables
    op.execute("CREATE SCHEMA IF NOT EXISTS market_data")

    for tf in ["1m", "5m", "15m", "1h", "4h", "1d"]:
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS market_data.candles_{tf} (
                time        TIMESTAMPTZ NOT NULL,
                symbol      TEXT        NOT NULL,
                open        NUMERIC,
                high        NUMERIC,
                low         NUMERIC,
                close       NUMERIC,
                volume      NUMERIC,
                PRIMARY KEY (time, symbol)
            )
            """
        )

    # 2. Signal history
    op.execute("CREATE SCHEMA IF NOT EXISTS signal")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS signal.history (
            id          BIGSERIAL PRIMARY KEY,
            timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            symbol      TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            strength    NUMERIC,
            price       NUMERIC,
            provider    TEXT,
            raw_data    JSONB
        )
        """
    )

    # 3. Cooldown tracking
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS signal.cooldown (
            symbol      TEXT PRIMARY KEY,
            last_fired  TIMESTAMPTZ NOT NULL,
            cool_until  TIMESTAMPTZ NOT NULL
        )
        """
    )

    # 4. News / sentiment cache
    op.execute("CREATE SCHEMA IF NOT EXISTS alternative")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS alternative.news_articles (
            id          BIGSERIAL PRIMARY KEY,
            fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            source      TEXT NOT NULL,
            title       TEXT,
            link        TEXT,
            published   TIMESTAMPTZ,
            sentiment   NUMERIC
        )
        """
    )

    # 5. Indices for performance
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_candles_symbol_time ON market_data.candles_1h (symbol, time)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_signal_history_ts ON signal.history (timestamp DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_news_fetched ON alternative.news_articles (fetched_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS alternative.news_articles CASCADE")
    op.execute("DROP TABLE IF EXISTS signal.cooldown CASCADE")
    op.execute("DROP TABLE IF EXISTS signal.history CASCADE")
    for tf in ["1d", "4h", "1h", "15m", "5m", "1m"]:
        op.execute(f"DROP TABLE IF EXISTS market_data.candles_{tf} CASCADE")
    op.execute("DROP SCHEMA IF EXISTS alternative CASCADE")
    op.execute("DROP SCHEMA IF EXISTS signal CASCADE")
    op.execute("DROP SCHEMA IF EXISTS market_data CASCADE")
