"""Connector status models."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class ConnectorStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class ConnectorInfo(BaseModel):
    name: str
    type: str  # exchange | wallet
    status: ConnectorStatus
    metadata: dict[str, Any] = {}
