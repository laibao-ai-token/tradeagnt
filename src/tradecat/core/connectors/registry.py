"""Connector registry with lifecycle helpers."""
from __future__ import annotations

from tradecat.core.connectors.base import BaseConnector
from tradecat.core.models.connector import ConnectorInfo, ConnectorStatus


class ConnectorRegistry:
    """Registry for exchange / wallet connectors."""

    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}

    def register(self, name: str, connector: BaseConnector) -> None:
        self._connectors[name] = connector

    def get(self, name: str) -> BaseConnector | None:
        return self._connectors.get(name)

    def remove(self, name: str) -> BaseConnector | None:
        return self._connectors.pop(name, None)

    def list(self) -> list[BaseConnector]:
        return list(self._connectors.values())

    def info(self, name: str) -> ConnectorInfo | None:
        c = self.get(name)
        if not c:
            return None
        return ConnectorInfo(
            name=c.name,
            type=type(c).__name__,
            status=c.status,
        )

    def list_info(self) -> list[ConnectorInfo]:
        return [
            ConnectorInfo(name=c.name, type=type(c).__name__, status=c.status)
            for c in self._connectors.values()
        ]

    async def connect_all(self) -> None:
        for c in self._connectors.values():
            if c.status != ConnectorStatus.CONNECTED:
                try:
                    await c.connect()
                except Exception:
                    pass

    async def disconnect_all(self) -> None:
        for c in self._connectors.values():
            if c.status == ConnectorStatus.CONNECTED:
                try:
                    await c.disconnect()
                except Exception:
                    pass
