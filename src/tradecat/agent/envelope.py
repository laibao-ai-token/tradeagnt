"""Standard JSON envelope for agent CLI stdout."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


ENVELOPE_SCHEMA = "tradeagnt.agent_envelope.v1"
ENVELOPE_VERSION = "1.0.0"


@dataclass
class Envelope:
    ok: bool
    data: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    audit_ref: str | None = None
    schema: str = ENVELOPE_SCHEMA
    schema_version: str = ENVELOPE_VERSION

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        return {k: v for k, v in out.items() if v is not None and v != []}

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


def fail(code: str, message: str, *, gate: str | None = None, warnings: list[str] | None = None) -> Envelope:
    err: dict[str, Any] = {"code": code, "message": message}
    if gate:
        err["gate"] = gate
    return Envelope(ok=False, error=err, warnings=warnings or [])
