"""G1 schema validation for agent_trade_thesis."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

from tradecat.agent.envelope import Envelope, fail
from tradecat.agent.thesis import schema_path


def _load_schema() -> dict[str, Any]:
    return json.loads(schema_path().read_text(encoding="utf-8"))


def validate_schema(thesis: dict[str, Any]) -> Envelope | None:
    """Return Envelope error on failure, else None."""
    try:
        jsonschema.validate(instance=thesis, schema=_load_schema())
    except jsonschema.ValidationError as exc:
        return fail(
            "agent_thesis_schema_invalid",
            str(exc.message),
            gate="schema",
        )
    except Exception as exc:
        return fail("agent_thesis_schema_invalid", str(exc), gate="schema")
    if thesis.get("ok") is not True:
        return fail("agent_thesis_schema_invalid", "thesis.ok must be true", gate="schema")
    return None
