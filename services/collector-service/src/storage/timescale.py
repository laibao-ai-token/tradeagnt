"""Shared TimescaleDB storage helpers for collector-service."""

from __future__ import absolute_import

from contextlib import contextmanager
from threading import Lock
from typing import Any, Dict, Iterator, Optional

try:
    from psycopg_pool import ConnectionPool
except Exception:
    ConnectionPool = None

from src.config import load_config


class _RuntimeState(object):
    def __init__(self):
        # type: () -> None
        self.shared_pool = None
        self.shared_pool_key = None
        self.shared_pool_lock = Lock()


_RUNTIME_STATE = _RuntimeState()


def reset_shared_pool():
    # type: () -> None
    pool = _RUNTIME_STATE.shared_pool
    if pool is not None:
        try:
            pool.close()
        except Exception:
            pass
    _RUNTIME_STATE.shared_pool = None
    _RUNTIME_STATE.shared_pool_key = None


def get_shared_pool(db_url=None, pool_factory=None, pool_kwargs=None):
    # type: (Optional[str], Optional[Any], Optional[Dict[str, Any]]) -> Any
    cfg = load_config()
    resolved_db_url = db_url or cfg.database.database_url
    resolved_pool_factory = pool_factory or ConnectionPool
    resolved_pool_kwargs = dict(pool_kwargs or {})
    if resolved_pool_factory is None:
        raise RuntimeError("psycopg_pool is not available")

    key = (resolved_db_url, tuple(sorted(resolved_pool_kwargs.items())))
    if _RUNTIME_STATE.shared_pool is None or _RUNTIME_STATE.shared_pool_key != key:
        with _RUNTIME_STATE.shared_pool_lock:
            if _RUNTIME_STATE.shared_pool is None or _RUNTIME_STATE.shared_pool_key != key:
                if _RUNTIME_STATE.shared_pool is not None:
                    try:
                        _RUNTIME_STATE.shared_pool.close()
                    except Exception:
                        pass
                _RUNTIME_STATE.shared_pool = resolved_pool_factory(resolved_db_url, **resolved_pool_kwargs)
                _RUNTIME_STATE.shared_pool_key = key
    return _RUNTIME_STATE.shared_pool


class TimescaleStorage(object):
    """Base storage wrapper with shared/private pool management."""

    def __init__(
        self,
        db_url=None,
        default_db_url=None,
        pool_min=2,
        pool_max=10,
        timeout=30.0,
        pool_factory=None,
    ):
        # type: (Optional[str], Optional[str], int, int, float, Optional[Any]) -> None
        cfg = load_config()
        self.db_url = db_url or cfg.database.database_url
        self.default_db_url = default_db_url or cfg.database.database_url
        self._pool_min = int(pool_min)
        self._pool_max = int(pool_max)
        self._timeout = float(timeout)
        self._pool_factory = pool_factory or ConnectionPool
        self._pool = None

    def _pool_kwargs(self):
        # type: () -> Dict[str, Any]
        return {
            "min_size": self._pool_min,
            "max_size": self._pool_max,
            "timeout": self._timeout,
            "max_idle": 300,
            "max_lifetime": 3600,
        }

    @property
    def pool(self):
        # type: () -> Any
        if self._pool_factory is None:
            raise RuntimeError("psycopg_pool is not available")
        if self.db_url == self.default_db_url:
            return get_shared_pool(
                db_url=self.db_url,
                pool_factory=self._pool_factory,
                pool_kwargs=self._pool_kwargs(),
            )
        if self._pool is None:
            self._pool = self._pool_factory(self.db_url, **self._pool_kwargs())
        return self._pool

    def close(self):
        # type: () -> None
        if self._pool is not None and self.db_url != self.default_db_url:
            self._pool.close()
            self._pool = None

    @contextmanager
    def connection(self):
        # type: () -> Iterator[Any]
        with self.pool.connection() as conn:
            yield conn
