from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .agent_events import (
    AssistantMessageEvent,
    SessionEndEvent,
    SessionStartEvent,
    SessionUserMessageEvent,
    SystemLogEvent,
    ToolEndEvent,
    ToolStartEvent,
)

AGENT_SCROLL_BOTTOM = 10**9


@dataclass(frozen=True)
class AgentShellMessage:
    role: str
    text: str
    timestamp: str = ""


@dataclass(frozen=True)
class AgentToolEvent:
    tool_name: str
    status: str
    summary: str


@dataclass
class AgentShellState:
    session_name: str = "tradecat-main"
    session_id: str = ""
    current_turn_id: str = ""
    turn_count: int = 0
    event_count: int = 0
    model_name: str = "tradecat-shell"
    connection_state: str = "shell-only"
    status_text: str = "backend pending"
    final_status: str = "idle"
    last_event_type: str = ""
    last_event_at: float = 0.0
    events_log_enabled: bool = False
    events_log_path: str = ""
    input_buffer: str = ""
    message_scroll: int = AGENT_SCROLL_BOTTOM
    messages: list[AgentShellMessage] = field(default_factory=list)
    tool_events: list[AgentToolEvent] = field(default_factory=list)


def _agent_now_text() -> str:
    return datetime.now().strftime("%H:%M")


def _new_agent_session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"sess_{stamp}_{uuid.uuid4().hex[:8]}"


def _new_agent_session_name() -> str:
    return f"tradecat-{datetime.now().strftime('%m%d-%H%M')}"


def _append_agent_event_jsonl(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        fh.write("\n")


def _next_agent_event_id(state: AgentShellState, event_type: str) -> str:
    state.event_count += 1
    anchor = state.current_turn_id or state.session_id or "agent"
    safe_type = str(event_type or "event").replace(".", "_")
    return f"{anchor}_{state.event_count:06d}_{safe_type}"


def _record_agent_event(state: AgentShellState, event, *, default_log_path: Path) -> None:
    payload = event.to_dict()
    state.last_event_type = str(payload.get("type", "") or "")
    try:
        state.last_event_at = float(payload.get("ts", 0.0) or 0.0)
    except Exception:
        state.last_event_at = 0.0
    if state.events_log_enabled:
        target = Path(state.events_log_path).expanduser().resolve() if state.events_log_path else default_log_path
        try:
            _append_agent_event_jsonl(target, payload)
        except Exception as exc:
            state.status_text = f"log write failed: {exc.__class__.__name__}"


def _ensure_agent_session_started(state: AgentShellState, *, default_log_path: Path) -> None:
    if not (state.session_id or "").strip():
        state.session_id = _new_agent_session_id()
    if state.event_count > 0:
        return
    now_ts = time.time()
    _record_agent_event(
        state,
        SessionStartEvent(
            ts=now_ts,
            event_id=_next_agent_event_id(state, "session.start"),
            session_id=state.session_id,
            source="tradecat",
            config={
                "session_name": state.session_name,
                "model": state.model_name,
                "connection_state": state.connection_state,
            },
        ),
        default_log_path=default_log_path,
    )


def _start_agent_turn(state: AgentShellState, *, default_log_path: Path) -> str:
    _ensure_agent_session_started(state, default_log_path=default_log_path)
    state.turn_count += 1
    state.current_turn_id = f"turn_{state.turn_count:05d}"
    state.final_status = "running"
    return state.current_turn_id


def seed_agent_shell_state(*, default_log_path: Path) -> AgentShellState:
    state = AgentShellState(
        session_id=_new_agent_session_id(),
        events_log_enabled=True,
        events_log_path=str(default_log_path),
        status_text="local demo ready",
    )
    state.messages = [
        AgentShellMessage("system", "右侧 Agent Shell 已就绪；当前仅保留本地 UI 骨架，后续按新编排方案接真实 backend。", "BOOT"),
        AgentShellMessage("assistant", "可先用这里做分析草稿、命令入口与 tool 事件占位。", "READY"),
        AgentShellMessage("tool", "预留工具桥: tr_get_quotes / tr_get_signals / tr_get_news", "TOOLS"),
    ]
    state.tool_events = [
        AgentToolEvent("tr_get_quotes", "stub", "等待 #003-02 接线"),
        AgentToolEvent("tr_get_signals", "stub", "等待 #003-02 接线"),
        AgentToolEvent("tr_get_news", "stub", "等待 #003-02 接线"),
    ]
    return state


def _append_agent_message(state: AgentShellState, role: str, text: str, *, timestamp: str = "") -> None:
    msg = AgentShellMessage(
        role=(role or "assistant").strip().lower(),
        text=str(text or "").strip(),
        timestamp=(timestamp or _agent_now_text()).strip(),
    )
    state.messages.append(msg)
    if len(state.messages) > 120:
        state.messages = state.messages[-120:]
    state.message_scroll = AGENT_SCROLL_BOTTOM


def _append_agent_tool_event(state: AgentShellState, tool_name: str, status: str, summary: str) -> None:
    event = AgentToolEvent(
        tool_name=(tool_name or "tool").strip(),
        status=(status or "--").strip(),
        summary=str(summary or "").strip(),
    )
    state.tool_events.append(event)
    if len(state.tool_events) > 8:
        state.tool_events = state.tool_events[-8:]


def submit_agent_shell_input(state: AgentShellState, *, default_log_path: Path) -> bool:
    raw = (state.input_buffer or "").strip()
    if not raw:
        return False

    turn_id = _start_agent_turn(state, default_log_path=default_log_path)
    now_ts = time.time()
    _record_agent_event(
        state,
        SessionUserMessageEvent(
            ts=now_ts,
            event_id=_next_agent_event_id(state, "session.user_message"),
            session_id=state.session_id,
            turn_id=turn_id,
            source="tradecat",
            message_id=f"user_{state.turn_count:05d}",
            content=raw,
        ),
        default_log_path=default_log_path,
    )
    _append_agent_message(state, "user", raw)

    if raw.startswith("/new"):
        old_session_id = state.session_id
        _record_agent_event(
            state,
            SessionEndEvent(
                ts=time.time(),
                event_id=_next_agent_event_id(state, "session.end"),
                session_id=old_session_id,
                turn_id=turn_id,
                source="tradecat",
                reason="restart",
            ),
            default_log_path=default_log_path,
        )
        state.session_name = _new_agent_session_name()
        state.session_id = _new_agent_session_id()
        state.current_turn_id = ""
        state.status_text = "local demo session reset"
        state.final_status = "success"
        _append_agent_message(state, "system", "已切到新的本地演示 session；真实 session 对接将在 #003-02 接入。")
        _record_agent_event(
            state,
            SessionStartEvent(
                ts=time.time(),
                event_id=_next_agent_event_id(state, "session.start"),
                session_id=state.session_id,
                source="tradecat",
                config={
                    "session_name": state.session_name,
                    "model": state.model_name,
                    "connection_state": state.connection_state,
                },
            ),
            default_log_path=default_log_path,
        )
    elif raw.startswith("/model"):
        state.status_text = "model placeholder"
        state.final_status = "success"
        _append_agent_message(state, "system", "model 切换已占位；当前仍使用本地演示模型 tradecat-shell。")
        _record_agent_event(
            state,
            SystemLogEvent(
                ts=time.time(),
                event_id=_next_agent_event_id(state, "system.log"),
                session_id=state.session_id,
                turn_id=turn_id,
                source="tradecat",
                level="info",
                message="local demo /model placeholder",
                data={"input": raw, "model_name": state.model_name},
            ),
            default_log_path=default_log_path,
        )
    elif raw.startswith("/tools"):
        tool_call_id = f"tool_registry_{state.turn_count:05d}"
        _record_agent_event(
            state,
            ToolStartEvent(
                ts=time.time(),
                event_id=_next_agent_event_id(state, "tool.start"),
                session_id=state.session_id,
                turn_id=turn_id,
                source="tradecat",
                tool_call_id=tool_call_id,
                tool_name="tool_registry",
                args={"command": raw},
            ),
            default_log_path=default_log_path,
        )
        _append_agent_tool_event(state, "tool_registry", "stub", "展示预留的 TradeCat -> Agent 工具桥")
        _record_agent_event(
            state,
            ToolEndEvent(
                ts=time.time(),
                event_id=_next_agent_event_id(state, "tool.end"),
                session_id=state.session_id,
                turn_id=turn_id,
                source="tradecat",
                tool_call_id=tool_call_id,
                tool_name="tool_registry",
                output={"text": "预留工具: tr_get_quotes / tr_get_signals / tr_get_news / tr_get_backtest。"},
            ),
            default_log_path=default_log_path,
        )
        state.status_text = "tool registry placeholder"
        state.final_status = "success"
        _append_agent_message(state, "tool", "预留工具: tr_get_quotes / tr_get_signals / tr_get_news / tr_get_backtest。")
    else:
        tool_call_id = f"local_echo_{state.turn_count:05d}"
        _record_agent_event(
            state,
            ToolStartEvent(
                ts=time.time(),
                event_id=_next_agent_event_id(state, "tool.start"),
                session_id=state.session_id,
                turn_id=turn_id,
                source="tradecat",
                tool_call_id=tool_call_id,
                tool_name="local_echo",
                args={"prompt": raw},
            ),
            default_log_path=default_log_path,
        )
        _append_agent_tool_event(state, "local_echo", "ok", "本地 shell 已接住输入，等待真实 backend。")
        _record_agent_event(
            state,
            ToolEndEvent(
                ts=time.time(),
                event_id=_next_agent_event_id(state, "tool.end"),
                session_id=state.session_id,
                turn_id=turn_id,
                source="tradecat",
                tool_call_id=tool_call_id,
                tool_name="local_echo",
                output={"text": "local demo accepted input"},
            ),
            default_log_path=default_log_path,
        )
        reply = "输入已进入本地 Agent Shell；真实 backend、streaming 和 tool call 将在后续 issue 接入。"
        _append_agent_message(state, "assistant", reply)
        _record_agent_event(
            state,
            AssistantMessageEvent(
                ts=time.time(),
                event_id=_next_agent_event_id(state, "assistant.message"),
                session_id=state.session_id,
                turn_id=turn_id,
                source="tradecat",
                message_id=f"assistant_{state.turn_count:05d}",
                content=reply,
                finish_reason="stop",
            ),
            default_log_path=default_log_path,
        )
        state.status_text = "local demo reply ready"
        state.final_status = "success"

    state.input_buffer = ""
    return True


def agent_shell_signature(state: AgentShellState) -> tuple:
    return (
        (state.session_name or "").strip(),
        (state.session_id or "").strip(),
        (state.current_turn_id or "").strip(),
        int(state.turn_count),
        int(state.event_count),
        (state.model_name or "").strip(),
        (state.connection_state or "").strip(),
        (state.status_text or "").strip(),
        (state.final_status or "").strip(),
        (state.last_event_type or "").strip(),
        float(state.last_event_at or 0.0),
        bool(state.events_log_enabled),
        (state.events_log_path or "").strip(),
        (state.input_buffer or ""),
        int(state.message_scroll),
        tuple((msg.role, msg.text, msg.timestamp) for msg in state.messages),
        tuple((event.tool_name, event.status, event.summary) for event in state.tool_events),
    )


def render_agent_message_lines(
    messages: Iterable[AgentShellMessage],
    width: int,
    *,
    wrap_text: Callable[[str, int], list[str]],
    truncate: Callable[[str, int], str],
) -> list[tuple[str, str]]:
    if width <= 0:
        return []

    lines: list[tuple[str, str]] = []
    labels = {"system": "sys", "user": "usr", "assistant": "ast", "tool": "tool"}
    for message in messages:
        role = (message.role or "assistant").strip().lower()
        label = labels.get(role, role[:4] or "msg")
        prefix = f"[{label}]"
        if (message.timestamp or "").strip():
            prefix += f" {message.timestamp.strip()}"
        prefix += " "
        body_width = max(8, width - len(prefix))
        body_lines = wrap_text(message.text, body_width)
        if not body_lines:
            lines.append((role, truncate(prefix.rstrip(), width)))
            continue
        lines.append((role, truncate(prefix + body_lines[0], width)))
        indent = " " * len(prefix)
        for extra in body_lines[1:]:
            lines.append(("", truncate(indent + extra, width)))
        lines.append(("", ""))

    if lines and not lines[-1][1]:
        lines.pop()
    return lines
