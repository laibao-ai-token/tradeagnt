import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import ExecutionEvent, ExecutionState, ExecutionPhase, ExecutionStatus


class ExecutionProtocol:
    def __init__(self, log_dir: Optional[str] = None):
        self._states: dict[str, ExecutionState] = {}
        self._log_dir = Path(log_dir or "artifacts/execution_audit")
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def start_execution(
        self,
        intent_id: str,
        order_id: str,
        symbol: str,
        side: str,
        size_pct: float,
    ) -> ExecutionState:
        trace_id = f"trace_{uuid.uuid4().hex[:12]}"
        state = ExecutionState(
            trace_id=trace_id,
            intent_id=intent_id,
            order_id=order_id,
        )
        self._states[trace_id] = state
        self._record_event(state, ExecutionPhase.PROPOSE, ExecutionStatus.IN_PROGRESS, {
            "symbol": symbol,
            "side": side,
            "size_pct": size_pct,
        })
        return state

    def _get_state(self, trace_id: str) -> Optional[ExecutionState]:
        state = self._states.get(trace_id)
        if state is not None:
            return state
        return self._load_state_from_file(trace_id)

    def _load_state_from_file(self, trace_id: str) -> Optional[ExecutionState]:
        log_file = self._log_dir / f"{trace_id}.jsonl"
        if not log_file.exists():
            return None
        events_raw = []
        for line in log_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events_raw.append(json.loads(line))
        if not events_raw:
            return None

        first = events_raw[0]
        state = ExecutionState(
            trace_id=trace_id,
            intent_id=first.get("intent_id") or "",
            order_id=first.get("order_id") or "",
        )
        try:
            state.started_at = datetime.fromisoformat(first.get("timestamp"))
        except Exception:
            state.started_at = datetime.now(timezone.utc)
        state.events = []
        for item in events_raw:
            try:
                event_phase = ExecutionPhase(item.get("phase"))
            except Exception:
                event_phase = ExecutionPhase.PROPOSE
            try:
                event_status = ExecutionStatus(item.get("status"))
            except Exception:
                event_status = ExecutionStatus.FAILED
            try:
                event_ts = datetime.fromisoformat(item.get("timestamp"))
            except Exception:
                event_ts = datetime.now(timezone.utc)
            state.events.append(
                ExecutionEvent(
                    event_id=item.get("event_id") or "",
                    trace_id=trace_id,
                    intent_id=item.get("intent_id") or state.intent_id,
                    order_id=item.get("order_id") or state.order_id,
                    phase=event_phase,
                    status=event_status,
                    timestamp=event_ts,
                    details=item.get("details") or {},
                    error=item.get("error"),
                )
            )
        last = state.events[-1]
        state.current_phase = last.phase
        state.status = last.status
        if last.status in {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.REJECTED}:
            state.completed_at = last.timestamp
        self._states[trace_id] = state
        return state

    def validate(self, trace_id: str, passed: bool, reasons: list[str] = None) -> Optional[ExecutionState]:
        state = self._get_state(trace_id)
        if not state:
            return None
        if passed:
            self._record_event(state, ExecutionPhase.VALIDATE, ExecutionStatus.IN_PROGRESS)
        else:
            self._record_event(state, ExecutionPhase.VALIDATE, ExecutionStatus.REJECTED, {
                "reasons": reasons or [],
            })
            state.status = ExecutionStatus.REJECTED
            state.completed_at = datetime.now(timezone.utc)
        return state

    def fail(self, trace_id: str, phase: ExecutionPhase, reason: str, details: dict | None = None) -> Optional[ExecutionState]:
        state = self._get_state(trace_id)
        if not state:
            return None
        payload = dict(details or {})
        payload["reason"] = reason
        self._record_event(state, phase, ExecutionStatus.FAILED, payload)
        state.status = ExecutionStatus.FAILED
        state.completed_at = datetime.now(timezone.utc)
        return state

    def stage(self, trace_id: str) -> Optional[ExecutionState]:
        state = self._get_state(trace_id)
        if not state:
            return None
        self._record_event(state, ExecutionPhase.STAGE, ExecutionStatus.IN_PROGRESS)
        return state

    def confirm(self, trace_id: str) -> Optional[ExecutionState]:
        state = self._get_state(trace_id)
        if not state:
            return None
        self._record_event(state, ExecutionPhase.CONFIRM, ExecutionStatus.IN_PROGRESS)
        return state

    def execute(self, trace_id: str, fill_price: float) -> Optional[ExecutionState]:
        state = self._get_state(trace_id)
        if not state:
            return None
        self._record_event(state, ExecutionPhase.EXECUTE, ExecutionStatus.IN_PROGRESS, {
            "fill_price": fill_price,
        })
        return state

    def sync(self, trace_id: str) -> Optional[ExecutionState]:
        state = self._get_state(trace_id)
        if not state:
            return None
        self._record_event(state, ExecutionPhase.SYNC, ExecutionStatus.COMPLETED)
        state.status = ExecutionStatus.COMPLETED
        state.completed_at = datetime.now(timezone.utc)
        return state

    def _record_event(
        self,
        state: ExecutionState,
        phase: ExecutionPhase,
        status: ExecutionStatus,
        details: dict | None = None,
    ):
        event = ExecutionEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            trace_id=state.trace_id,
            intent_id=state.intent_id,
            order_id=state.order_id,
            phase=phase,
            status=status,
            timestamp=datetime.now(timezone.utc),
            details=details or {},
        )
        state.events.append(event)
        state.current_phase = phase
        self._write_event(event)

    def _write_event(self, event: ExecutionEvent):
        log_file = self._log_dir / f"{event.trace_id}.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "event_id": event.event_id,
                "trace_id": event.trace_id,
                "intent_id": event.intent_id,
                "order_id": event.order_id,
                "phase": event.phase.value,
                "status": event.status.value,
                "timestamp": event.timestamp.isoformat(),
                "details": event.details,
                "error": event.error,
            }, default=str) + "\n")

    def replay(self, trace_id: str) -> Optional[dict]:
        state = self._states.get(trace_id)
        if state:
            return self._build_replay(state)
        log_file = self._log_dir / f"{trace_id}.jsonl"
        if log_file.exists():
            events = []
            for line in open(log_file, encoding="utf-8"):
                line = line.strip()
                if line:
                    events.append(json.loads(line))
            if events:
                return {
                    "trace_id": trace_id,
                    "intent_id": events[0].get("intent_id"),
                    "order_id": events[0].get("order_id"),
                    "status": events[-1].get("status"),
                    "current_phase": events[-1].get("phase"),
                    "started_at": events[0].get("timestamp"),
                    "completed_at": events[-1].get("timestamp") if events[-1].get("status") == "COMPLETED" else None,
                    "events": events,
                    "source": "file",
                }
        return None

    def _build_replay(self, state) -> dict:
        return {
            "trace_id": state.trace_id,
            "intent_id": state.intent_id,
            "order_id": state.order_id,
            "status": state.status.value,
            "current_phase": state.current_phase.value,
            "started_at": state.started_at.isoformat(),
            "completed_at": state.completed_at.isoformat() if state.completed_at else None,
            "events": [
                {
                    "phase": e.phase.value,
                    "status": e.status.value,
                    "timestamp": e.timestamp.isoformat(),
                    "details": e.details,
                    "error": e.error,
                }
                for e in state.events
            ],
            "source": "memory",
        }

    def get_all_traces(self) -> list[str]:
        in_memory = list(self._states.keys())
        on_disk = []
        if self._log_dir.exists():
            for f in self._log_dir.glob("*.jsonl"):
                on_disk.append(f.stem)
        return sorted(set(in_memory + on_disk))
