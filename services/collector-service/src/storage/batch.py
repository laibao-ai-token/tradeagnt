"""Batch lineage helpers for collector-service storage writes."""

from __future__ import absolute_import

from typing import Any, Optional

from src.config import load_config
from src.storage.timescale import get_shared_pool


def _validate_identifier(value, label):
    # type: (str, str) -> str
    text = (value or "").strip()
    if not text:
        raise ValueError("Missing {0}".format(label))
    first = text[0]
    if not (first.isalpha() or first == "_"):
        raise ValueError("Invalid {0}: {1}".format(label, value))
    for char in text[1:]:
        if not (char.isalnum() or char == "_"):
            raise ValueError("Invalid {0}: {1}".format(label, value))
    return text


def start_batch(
    source,
    data_type,
    market=None,
    symbol=None,
    t_start=None,
    t_end=None,
    pool=None,
    db_url=None,
    quality_db_schema=None,
    pool_factory=None,
    raise_on_error=True,
):
    # type: (str, str, Optional[str], Optional[str], Optional[Any], Optional[Any], Optional[Any], Optional[str], Optional[str], Optional[Any], bool) -> int
    cfg = load_config()
    schema_name = _validate_identifier(quality_db_schema or cfg.database.quality_db_schema, "schema")
    resolved_pool = pool or get_shared_pool(
        db_url=db_url or cfg.database.database_url,
        pool_factory=pool_factory,
        pool_kwargs={
            "min_size": 2,
            "max_size": 10,
            "timeout": 30.0,
            "max_idle": 300,
            "max_lifetime": 3600,
        },
    )
    query = "SELECT {0}.start_batch(%s, %s, %s, %s, %s, %s)".format(schema_name)
    try:
        with resolved_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (source, data_type, market, symbol, t_start, t_end))
                result = cur.fetchone()
                conn.commit()
                if not result:
                    return 0
                return int(result[0])
    except Exception:
        if raise_on_error:
            raise
        return 0
