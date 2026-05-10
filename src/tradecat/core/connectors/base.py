"""Base connector interface."""
from __future__ import annotations

from abc import ABC, abstractmethod

from tradecat.core.models.connector import ConnectorStatus


class BaseConnector(ABC):
    """Abstract base for all exchange / wallet connectors."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def status(self) -> ConnectorStatus: ...

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def health_check(self) -> bool: ...
