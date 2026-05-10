"""Exchange connector powered by CCXT (async)."""
from __future__ import annotations

import ccxt.async_support as ccxt

from tradecat.core.connectors.base import BaseConnector
from tradecat.core.models.connector import ConnectorStatus


class ExchangeConnector(BaseConnector):
    """Wrap a CCXT async exchange instance."""

    def __init__(
        self,
        name: str,
        exchange_id: str,
        api_key: str = "",
        secret: str = "",
        sandbox: bool = True,
        options: dict | None = None,
    ) -> None:
        self._name = name
        self.exchange_id = exchange_id
        self.api_key = api_key
        self.secret = secret
        self.sandbox = sandbox
        self.options = options or {}
        self._client: ccxt.Exchange | None = None
        self._status = ConnectorStatus.DISCONNECTED

    @property
    def name(self) -> str:
        return self._name

    @property
    def status(self) -> ConnectorStatus:
        return self._status

    async def connect(self) -> None:
        self._status = ConnectorStatus.CONNECTING
        try:
            cls = getattr(ccxt, self.exchange_id)
            self._client = cls(
                {
                    "apiKey": self.api_key,
                    "secret": self.secret,
                    "sandbox": self.sandbox,
                    **self.options,
                }
            )
            await self._client.load_markets()
            self._status = ConnectorStatus.CONNECTED
        except Exception:
            self._status = ConnectorStatus.ERROR
            raise

    async def disconnect(self) -> None:
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
        self._client = None
        self._status = ConnectorStatus.DISCONNECTED

    async def health_check(self) -> bool:
        if not self._client or self._status != ConnectorStatus.CONNECTED:
            return False
        try:
            await self._client.fetch_time()
            return True
        except Exception:
            return False

    @property
    def client(self) -> ccxt.Exchange | None:
        """Expose raw CCXT client for advanced usage."""
        return self._client
