from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ExecutionPhase(Enum):
    PROPOSE = "propose"
    VALIDATE = "validate"
    STAGE = "stage"
    CONFIRM = "confirm"
    EXECUTE = "execute"
    SYNC = "sync"


class ExecutionStatus(Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


@dataclass
class ExecutionEvent:
    event_id: str
    trace_id: str
    intent_id: str
    order_id: str
    phase: ExecutionPhase
    status: ExecutionStatus
    timestamp: datetime
    details: dict = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class ExecutionState:
    trace_id: str
    intent_id: str
    order_id: str
    current_phase: ExecutionPhase = ExecutionPhase.PROPOSE
    status: ExecutionStatus = ExecutionStatus.PENDING
    events: list[ExecutionEvent] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
