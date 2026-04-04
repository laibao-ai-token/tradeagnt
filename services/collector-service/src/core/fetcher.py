"""Provider fetcher base classes.

This module keeps the same fetch pipeline shape as markets-service while
remaining compatible with the lightweight system Python used in repo checks.
"""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

try:
    from pydantic import BaseModel  # noqa: F401
except Exception:  # pragma: no cover - optional dependency for local checks
    class BaseModel(object):  # type: ignore[no-redef]
        """Fallback type used when pydantic is unavailable."""


QueryT = TypeVar("QueryT")
DataT = TypeVar("DataT")


class BaseFetcher(ABC, Generic[QueryT, DataT]):
    """Generic provider fetcher following transform-extract-transform."""

    provider = ""

    @abstractmethod
    def transform_query(self, params):
        """Transform raw input parameters into a query object."""

    @abstractmethod
    async def extract(self, query):
        """Fetch raw payloads from an external provider."""

    @abstractmethod
    def transform_data(self, raw):
        """Transform raw provider payloads into normalized records."""

    async def fetch(self, **params):
        """Run the full transform-extract-transform pipeline."""

        query = self.transform_query(params)
        raw = await self.extract(query)
        return self.transform_data(raw)

    def fetch_sync(self, **params):
        """Run the async fetch pipeline from synchronous callers."""

        import asyncio

        runner = getattr(asyncio, "run", None)
        if runner is not None:
            return runner(self.fetch(**params))

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.fetch(**params))
        finally:
            loop.close()
