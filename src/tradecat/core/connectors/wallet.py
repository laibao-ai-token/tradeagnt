"""Web3 wallet connector (interface stub)."""
from __future__ import annotations

from tradecat.core.connectors.base import BaseConnector
from tradecat.core.models.connector import ConnectorStatus


class WalletConnector(BaseConnector):
    """Wallet connector stub — full web3.py integration TBD."""

    def __init__(
        self,
        name: str,
        chain: str = "ethereum",
        rpc_url: str = "",
    ) -> None:
        self._name = name
        self.chain = chain
        self.rpc_url = rpc_url
        self._status = ConnectorStatus.DISCONNECTED

    @property
    def name(self) -> str:
        return self._name

    @property
    def status(self) -> ConnectorStatus:
        return self._status

    async def connect(self) -> None:
        """Stub: Replace with web3.py AsyncWeb3 connection."""
        self._status = ConnectorStatus.CONNECTED

    async def disconnect(self) -> None:
        self._status = ConnectorStatus.DISCONNECTED

    async def health_check(self) -> bool:
        return self._status == ConnectorStatus.CONNECTED
