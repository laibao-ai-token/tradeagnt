from __future__ import annotations

from pathlib import Path
import sys
import tempfile


SERVICE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(SERVICE_SRC) not in sys.path:
    sys.path.insert(0, str(SERVICE_SRC))

from execution_protocol.models import ExecutionPhase
from execution_protocol.protocol import ExecutionProtocol


def test_execution_protocol_full_replay() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        protocol = ExecutionProtocol(log_dir=tmp_dir)
        state = protocol.start_execution("intent-1", "order-1", "BTCUSDT", "LONG", 0.1)
        trace_id = state.trace_id

        protocol.validate(trace_id, True)
        protocol.stage(trace_id)
        protocol.confirm(trace_id)
        protocol.execute(trace_id, 50000.0)
        protocol.sync(trace_id)

        replay = protocol.replay(trace_id)
        assert replay is not None
        assert replay["status"] == "COMPLETED"
        assert replay["current_phase"] == "sync"
        assert [event["phase"] for event in replay["events"]] == [
            "propose",
            "validate",
            "stage",
            "confirm",
            "execute",
            "sync",
        ]


def test_execution_protocol_failure_is_persisted() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        protocol = ExecutionProtocol(log_dir=tmp_dir)
        state = protocol.start_execution("intent-2", "order-2", "ETHUSDT", "SHORT", 0.2)
        trace_id = state.trace_id
        protocol.validate(trace_id, True)
        protocol.stage(trace_id)
        protocol.fail(trace_id, ExecutionPhase.CONFIRM, "manual rejection")

        replay = protocol.replay(trace_id)
        assert replay is not None
        assert replay["status"] == "FAILED"
        assert replay["current_phase"] == "confirm"
        assert replay["events"][-1]["details"]["reason"] == "manual rejection"


def test_execution_protocol_can_resume_from_disk() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        protocol_a = ExecutionProtocol(log_dir=tmp_dir)
        state = protocol_a.start_execution("intent-3", "order-3", "SOLUSDT", "LONG", 0.05)
        trace_id = state.trace_id
        protocol_a.validate(trace_id, True)

        protocol_b = ExecutionProtocol(log_dir=tmp_dir)
        resumed = protocol_b.stage(trace_id)
        assert resumed is not None
        protocol_b.confirm(trace_id)
        protocol_b.execute(trace_id, 180.0)
        protocol_b.sync(trace_id)

        replay = protocol_b.replay(trace_id)
        assert replay is not None
        assert replay["status"] == "COMPLETED"
        assert replay["current_phase"] == "sync"
        assert len(replay["events"]) == 6
