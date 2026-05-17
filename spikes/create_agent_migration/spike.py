"""Spike: validate 5 migration patterns for create_agent + middleware.

Throwaway code. Run: ./venv/bin/python spikes/create_agent_migration/spike.py
"""
from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import Any, NotRequired

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    AgentState,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.runtime import Runtime

warnings.filterwarnings("ignore")


class ScriptedModel(FakeMessagesListChatModel):
    """FakeMessagesListChatModel that tolerates `bind_tools()` (no-op)."""

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):  # type: ignore[override]
        return self

# ---------- shared tools ----------
_call_counter: dict[str, int] = {"update_booking": 0, "check_availability": 0, "book": 0}


@tool
def update_booking(services: str | None = None, stylist: str | None = None) -> str:
    """Update booking context with services/stylist."""
    _call_counter["update_booking"] += 1
    return f"updated services={services} stylist={stylist}"


@tool
def check_availability(day: str) -> str:
    """Check availability."""
    _call_counter["check_availability"] += 1
    return f"available on {day}"


@tool
def book(day: str) -> str:
    """Book the appointment."""
    _call_counter["book"] += 1
    return f"booked {day}"


def _reset_counters() -> None:
    for k in _call_counter:
        _call_counter[k] = 0


def _scripted_model(responses: list[AIMessage]) -> ScriptedModel:
    return ScriptedModel(responses=responses)


# =====================================================================
# PATTERN 1+2: dynamic tool filtering by state + conditional tool_choice
# =====================================================================
class BookingState(AgentState):
    has_services: NotRequired[bool]
    has_stylist: NotRequired[bool]


class BookingContextMiddleware(AgentMiddleware):
    state_schema = BookingState
    tool_choice_log: list[Any] = []
    tools_log: list[list[str]] = []

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        state = request.state
        has_services = state.get("has_services", False)
        has_stylist = state.get("has_stylist", False)

        allowed = {"update_booking"}
        if has_services and has_stylist:
            allowed.add("check_availability")
        if has_services and has_stylist:
            # For simplicity here: book available when complete too.
            allowed.add("book")

        filtered = [t for t in request.tools if getattr(t, "name", None) in allowed]

        last = state["messages"][-1] if state.get("messages") else None
        tool_choice = "required" if isinstance(last, HumanMessage) else None

        self.tools_log.append([getattr(t, "name", "?") for t in filtered])
        self.tool_choice_log.append(tool_choice)

        from dataclasses import replace
        new_req = replace(request, tools=filtered, tool_choice=tool_choice)
        return handler(new_req)

    def after_model(
        self, state: BookingState, runtime: Runtime
    ) -> dict[str, Any] | None:
        # Watch outgoing tool calls from the last AIMessage and update context flags.
        msgs = state["messages"]
        last = msgs[-1] if msgs else None
        if not isinstance(last, AIMessage) or not last.tool_calls:
            return None
        updates: dict[str, Any] = {}
        for tc in last.tool_calls:
            if tc["name"] == "update_booking":
                args = tc.get("args") or {}
                if args.get("services"):
                    updates["has_services"] = True
                if args.get("stylist"):
                    updates["has_stylist"] = True
        return updates or None


def test_pattern_1_and_2() -> None:
    _reset_counters()
    mw = BookingContextMiddleware()

    # Script: 3 AIMessages. First two call tools, last is plain text (stop).
    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "update_booking", "args": {"services": "cut"}, "id": "c1"}],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "update_booking", "args": {"stylist": "ana"}, "id": "c2"}
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[{"name": "book", "args": {"day": "mon"}, "id": "c3"}],
        ),
        AIMessage(content="done"),
    ]
    agent = create_agent(
        model=_scripted_model(responses),
        tools=[update_booking, check_availability, book],
        middleware=[mw],
    )
    agent.invoke({"messages": [HumanMessage("book me for monday")]})

    iter0, iter1, iter2, iter3 = mw.tools_log[:4]
    # iter0: no context → only update_booking
    ok1 = iter0 == ["update_booking"]
    # iter1: has_services but not stylist → still only update_booking
    ok2 = iter1 == ["update_booking"]
    # iter2: has both → full toolset
    ok3 = set(iter2) == {"update_booking", "check_availability", "book"}
    # Pattern 2: tool_choice required on iter0 (HumanMessage last), None after
    ok4 = mw.tool_choice_log[0] == "required" and mw.tool_choice_log[1] is None

    status1 = "PASS" if (ok1 and ok2 and ok3) else "FAIL"
    status2 = "PASS" if ok4 else "FAIL"
    print(f"[Pattern 1 | dynamic tool filtering] {status1}  tools_log={mw.tools_log[:4]}")
    print(f"[Pattern 2 | conditional tool_choice] {status2}  choice_log={mw.tool_choice_log[:4]}")


# =====================================================================
# PATTERN 3: dedup guard via wrap_tool_call (cache in state)
# =====================================================================
class DedupState(AgentState):
    tool_cache: NotRequired[dict[str, str]]


def _tc_key(tc: dict[str, Any]) -> str:
    return f"{tc['name']}::{sorted((tc.get('args') or {}).items())}"


class DedupMiddleware(AgentMiddleware):
    """Cache lives in message history (ToolMessages).

    `wrap_tool_call` rebuilds the cache from prior ToolMessages seen in state
    and short-circuits if an identical (tool, args) pair has already produced
    a ToolMessage this run.
    """

    state_schema = DedupState

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage],
    ) -> ToolMessage:
        tc = request.tool_call
        key = _tc_key(tc)
        msgs = (request.state or {}).get("messages", [])
        # Build cache from message history (pair AIMessage tool_calls with their ToolMessages by id).
        ai_calls: dict[str, dict] = {}
        for m in msgs:
            if isinstance(m, AIMessage):
                for prev_tc in m.tool_calls or []:
                    ai_calls[prev_tc["id"]] = prev_tc
            elif isinstance(m, ToolMessage):
                origin = ai_calls.get(m.tool_call_id)
                if origin and _tc_key(origin) == key:
                    return ToolMessage(
                        content=str(m.content),
                        tool_call_id=tc["id"],
                        name=tc["name"],
                    )
        return handler(request)


def test_pattern_3() -> None:
    _reset_counters()
    # Same tool call twice, identical args.
    responses = [
        AIMessage(content="", tool_calls=[{"name": "check_availability", "args": {"day": "mon"}, "id": "a1"}]),
        AIMessage(content="", tool_calls=[{"name": "check_availability", "args": {"day": "mon"}, "id": "a2"}]),
        AIMessage(content="done"),
    ]
    agent = create_agent(
        model=_scripted_model(responses),
        tools=[check_availability],
        middleware=[DedupMiddleware()],
    )
    agent.invoke({"messages": [HumanMessage("check monday twice")]})

    # The real tool body should have incremented exactly once.
    actual = _call_counter["check_availability"]
    status = "PASS" if actual == 1 else "FAIL"
    print(f"[Pattern 3 | dedup via wrap_tool_call] {status}  real executions={actual} (expected 1)")


# =====================================================================
# PATTERN 4: final-text recovery when AIMessage has tool_calls + empty content
# =====================================================================
class FinalTextRecoveryMiddleware(AgentMiddleware):
    triggered: bool = False

    def after_model(
        self, state: AgentState, runtime: Runtime
    ) -> dict[str, Any] | None:
        msgs = state["messages"]
        last = msgs[-1] if msgs else None
        if not isinstance(last, AIMessage):
            return None
        content = (last.content or "").strip() if isinstance(last.content, str) else last.content
        if last.tool_calls and not content:
            # Option B: substitute a synthetic assistant message; clear tool calls.
            self.triggered = True
            fixed = AIMessage(
                id=last.id,
                content="(recovered: empty content)",
                tool_calls=[],
            )
            return {"messages": [fixed]}
        return None


def test_pattern_4() -> None:
    _reset_counters()
    mw = FinalTextRecoveryMiddleware()
    # Model emits tool_calls but empty content, THEN plain text (so loop terminates).
    responses = [
        AIMessage(content="", tool_calls=[{"name": "book", "args": {"day": "mon"}, "id": "x1"}]),
        AIMessage(content="final answer"),
    ]
    agent = create_agent(
        model=_scripted_model(responses),
        tools=[book],
        middleware=[mw],
    )
    result = agent.invoke({"messages": [HumanMessage("hi")]})
    # Verify middleware fired and the message was overwritten.
    overwritten = any(
        isinstance(m, AIMessage) and m.content == "(recovered: empty content)"
        for m in result["messages"]
    )
    status = "PASS" if (mw.triggered and overwritten) else "FAIL"
    print(
        f"[Pattern 4 | final-text recovery] {status}  triggered={mw.triggered} "
        f"overwritten={overwritten}"
    )


# =====================================================================
# PATTERN 5: forced recovery text after N rejection-gate hits (5a approach)
# =====================================================================
class RejectState(AgentState):
    reject_hits: NotRequired[int]


class RejectingToolMiddleware(AgentMiddleware):
    """Wraps `book` to always return error_code=GATE_REJECTED."""

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage],
    ) -> ToolMessage:
        tc = request.tool_call
        if tc["name"] == "book":
            return ToolMessage(
                content="error_code=GATE_REJECTED",
                tool_call_id=tc["id"],
                name="book",
                status="error",
            )
        return handler(request)


RECOVERY_TEXT = "No puedo procesar la reserva en este momento. Por favor intentá más tarde."


class RecoveryCounterMiddleware(AgentMiddleware):
    state_schema = RejectState

    def after_model(
        self, state: RejectState, runtime: Runtime
    ) -> dict[str, Any] | None:
        msgs = state["messages"]
        # Count how many ToolMessages have the rejection code so far.
        hits = sum(
            1
            for m in msgs
            if isinstance(m, ToolMessage) and "GATE_REJECTED" in str(m.content)
        )
        last = msgs[-1] if msgs else None
        if not isinstance(last, AIMessage):
            return None
        # If we've seen >=2 rejections AND the model is trying yet again, abort.
        if hits >= 2 and last.tool_calls:
            fixed = AIMessage(
                id=last.id,
                content=RECOVERY_TEXT,
                tool_calls=[],
            )
            return {"messages": [fixed], "jump_to": "end"}
        return None


def test_pattern_5() -> None:
    _reset_counters()
    # Model persistently retries `book` — 3 attempts, all should hit rejection
    # but middleware should abort before the 3rd gets through.
    responses = [
        AIMessage(content="", tool_calls=[{"name": "book", "args": {"day": "mon"}, "id": "r1"}]),
        AIMessage(content="", tool_calls=[{"name": "book", "args": {"day": "mon"}, "id": "r2"}]),
        AIMessage(content="", tool_calls=[{"name": "book", "args": {"day": "mon"}, "id": "r3"}]),
        AIMessage(content="should never reach here"),
    ]
    agent = create_agent(
        model=_scripted_model(responses),
        tools=[book],
        middleware=[RejectingToolMiddleware(), RecoveryCounterMiddleware()],
    )
    result = agent.invoke({"messages": [HumanMessage("book please")]}, config={"recursion_limit": 20})
    last_ai = [m for m in result["messages"] if isinstance(m, AIMessage)][-1]
    ok = last_ai.content == RECOVERY_TEXT and not last_ai.tool_calls
    status = "PASS" if ok else "FAIL"
    print(
        f"[Pattern 5 | forced recovery after N rejections] {status}  "
        f"final={last_ai.content!r}"
    )


# =====================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("create_agent migration spike — 5 patterns")
    print("=" * 70)
    test_pattern_1_and_2()
    test_pattern_3()
    test_pattern_4()
    test_pattern_5()
    print("=" * 70)
