"""S3 — State-contract regression net.

Two-layer test suite locking the InjectedState read surface before any src changes land.

Layer 1 — Static AST/regex scan:
    Enumerate every AgentState field that a tool in agent/tools/*.py reads via
    InjectedState (pattern: ``state.get("X")`` / ``(state or {}).get("X")``).
    Assert the found set equals exactly the 5-field TOOL_READ_CONTRACT. A future
    tool adding a 6th InjectedState read will FAIL this test until someone wires
    checkpoint persistence — that is the point.

Layer 2 — Dynamic real-path test:
    Drive the REAL middleware → checkpoint → tool path using MemorySaver.
    MemorySaver stores live Python objects and would NOT catch the UUID/orjson
    serde bug class. Therefore checkpoint values are ALSO round-tripped through
    JsonPlusSerializer (LangGraph's Redis-compatible serde) to catch type issues.

    JsonPlusSerializer import path (LangGraph >= 0.2):
        langgraph.checkpoint.serde.jsonplus.JsonPlusSerializer
    Verified on the installed version; import is guarded with a skip if the path
    has changed in a future LangGraph release.

Spec: REQ-S3-1 through REQ-S3-7
Design: ADR-4 (S3 test architecture)
"""

from __future__ import annotations

import ast
import re
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent.parent
TOOLS_DIR = PROJECT_ROOT / "agent" / "tools"
CONV_ID = "test-state-contract-conv-1"
CUSTOMER_PHONE = "+34999000001"
CUSTOMER_UUID = uuid.uuid4()

# Layer 1: authoritative contract. Every tool read via InjectedState MUST appear here.
# If a new field is added to tools without a middleware persist entry, the static scan
# will fail pointing here — that is the intended tripwire.
#
# Format: { field_key: "provenance description" }
TOOL_READ_CONTRACT: dict[str, str] = {
    "messages": "graph-input (add_messages reducer)",
    "customer_phone": "graph-input (conversation setup)",
    "conversation_id": "graph-input (conversation setup)",
    "customer_id": "CustomerResolveMiddleware → ExtendedModelResponse Command(update=...)",
    "recently_offered_slots": "AvailabilityContextMiddleware → ExtendedModelResponse Command(update=...)",
    "customer_memories": "CustomerResolveMiddleware → state_delta (REQ-S1-8, customer_resolve.py)",
}


# ---------------------------------------------------------------------------
# Layer 1 — Static read-surface scan
# ---------------------------------------------------------------------------


def _collect_state_get_keys_ast(source: str) -> set[str]:
    """Return all string keys passed to state.get(X) via AST parse.

    Matches direct reads:
        state.get("key")
        state.get('key')
        (state or {}).get("key")

    Also matches the alias pattern common in tools:
        _state = state or {}
        _state.get("key")   ← the alias variable is tracked by scanning assignments
    """
    keys: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return keys

    # Pass 1: collect names that are aliases of `state or {}` or `state`
    # Pattern: `_state = state or {}` or `_state = state`
    state_aliases: set[str] = {"state"}  # "state" is always in scope
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        # RHS must be `state` or `state or {}`
        rhs = node.value
        rhs_is_state_alias = False
        if isinstance(rhs, ast.Name) and rhs.id == "state":
            rhs_is_state_alias = True
        elif isinstance(rhs, ast.BoolOp):
            for val in rhs.values:
                if isinstance(val, ast.Name) and val.id == "state":
                    rhs_is_state_alias = True
                    break
        if rhs_is_state_alias:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    state_aliases.add(target.id)

    # Pass 2: find <alias>.get("key") call nodes
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr != "get":
            continue
        if not node.args:
            continue
        first_arg = node.args[0]
        if not isinstance(first_arg, ast.Constant):
            continue
        key = first_arg.value
        if not isinstance(key, str):
            continue

        receiver = func.value
        # Direct alias name: state.get / _state.get
        if isinstance(receiver, ast.Name) and receiver.id in state_aliases:
            keys.add(key)
            continue
        # BoolOp: (state or {}).get(...)
        if isinstance(receiver, ast.BoolOp):
            for val in receiver.values:
                if isinstance(val, ast.Name) and val.id in state_aliases:
                    keys.add(key)
                    break

    return keys


def _collect_state_get_keys_regex(source: str) -> set[str]:
    """Fallback regex collector to complement AST parse.

    Matches patterns that appear in tool source:
        state.get("key") / state.get('key')
        (state or {}).get("key") / (state or {}).get('key')
        _state.get("key") / _state.get('key')

    This is a secondary pass; AST is authoritative.
    """
    pattern = re.compile(r"""(?:\(state\s+or\s+\{\}\)|_?state)\.get\(\s*["']([^"']+)["']""")
    return set(pattern.findall(source))


def _scan_tool_injected_state_reads() -> set[str]:
    """Walk agent/tools/*.py and collect all keys read from InjectedState.

    Only files that import InjectedState are included in the scan (other .py
    files in agent/tools/ use state differently or not at all).
    """
    found_keys: set[str] = set()
    for tool_file in sorted(TOOLS_DIR.glob("*.py")):
        source = tool_file.read_text(encoding="utf-8")
        # Only scan files that actually use InjectedState
        if "InjectedState" not in source:
            continue
        # Collect via AST (primary)
        ast_keys = _collect_state_get_keys_ast(source)
        # Collect via regex (secondary, catches anything AST might miss)
        regex_keys = _collect_state_get_keys_regex(source)
        found_keys.update(ast_keys | regex_keys)
    return found_keys


def test_tool_read_surface_is_declared() -> None:
    """S3-T1.1: Every InjectedState field read by tools must be in TOOL_READ_CONTRACT.

    This test is the tripwire: if a new tool starts reading a field from state
    without a corresponding middleware persist entry, this test FAILS with a
    descriptive message pointing to the contract.

    Conversely, if a contract entry is present but no tool reads it, the contract
    entry is stale — that also FAILS (the contract must stay tight).

    Spec: REQ-S3-1, REQ-S3-2, REQ-S3-5
    """
    found = _scan_tool_injected_state_reads()
    declared = set(TOOL_READ_CONTRACT.keys())

    undeclared = found - declared
    stale = declared - found

    assert not undeclared, (
        f"\n\nUNDECLARED InjectedState reads found in agent/tools/:\n"
        f"  Fields: {sorted(undeclared)}\n\n"
        "These fields are read by tools but have NO declared persistence provenance "
        "in TOOL_READ_CONTRACT.\n"
        "Action required: add a middleware that persists each field to the LangGraph "
        "checkpoint via ExtendedModelResponse(command=Command(update={field: value})), "
        "then add the field + provenance to TOOL_READ_CONTRACT in this file, AND add a "
        "Layer-2 assertion in test_injected_state_contract().\n"
        f"\nCurrent TOOL_READ_CONTRACT keys: {sorted(declared)}"
    )

    assert not stale, (
        f"\n\nSTALE entries in TOOL_READ_CONTRACT (declared but no tool reads them):\n"
        f"  Fields: {sorted(stale)}\n\n"
        "Either a tool was removed/refactored and its InjectedState read was dropped, "
        "or the contract entry was added prematurely.\n"
        "Action required: remove the stale entry from TOOL_READ_CONTRACT."
    )


# ---------------------------------------------------------------------------
# Layer 2 — Dynamic real-path test helpers
# ---------------------------------------------------------------------------


def _get_json_plus_serializer() -> Any:
    """Return a JsonPlusSerializer instance, or None if the import path has changed.

    Import path for LangGraph >= 0.2: langgraph.checkpoint.serde.jsonplus
    Guarded here so the test skips gracefully if LangGraph removes or renames
    the module in a future version.
    """
    try:
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer  # noqa: PLC0415

        return JsonPlusSerializer()
    except ImportError:
        return None


def _make_scripted_llm(tool_name: str = "check_availability") -> Any:
    """Build a fake chat model that implements bind_tools and returns a deterministic sequence.

    Sequence:
        Turn 1 call:  AIMessage with tool_call for `tool_name`
        Turn 2+ call: AIMessage with plain text (no more tool calls)

    The LLM is created as a MagicMock that mimics BaseChatModel enough for
    create_agent. It must implement:
        - bind_tools(tools, ...) → self (returns the same instance)
        - ainvoke(messages, ...) → AIMessage (deterministic)

    Note: create_agent calls model.bind_tools() at construction time. The returned
    bound model is what actually receives ainvoke() during graph execution.
    """
    from langchain_core.messages import AIMessage

    call_count = {"n": 0}

    tool_call_id = f"tc_{uuid.uuid4().hex[:8]}"
    tool_call_args: dict[str, Any] = {}

    # Tool-specific args so LangChain tool validation passes
    if tool_name == "check_availability":
        tool_call_args = {"service_id": str(uuid.uuid4()), "day": "2026-07-01"}
    elif tool_name == "get_next_available_options":
        tool_call_args = {"service_id": str(uuid.uuid4())}

    ai_with_tool = AIMessage(
        content="",
        tool_calls=[
            {
                "name": tool_name,
                "args": tool_call_args,
                "id": tool_call_id,
                "type": "tool_call",
            }
        ],
    )
    ai_final = AIMessage(content="Entendido, ya revisé la disponibilidad.")

    async def _ainvoke(messages: Any, *args: Any, **kwargs: Any) -> AIMessage:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return ai_with_tool
        return ai_final

    # Build a MagicMock that looks like a bound chat model
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(side_effect=_ainvoke)
    # bind_tools must return an object with the same ainvoke signature
    bound_model = MagicMock()
    bound_model.ainvoke = AsyncMock(side_effect=_ainvoke)
    fake_model.bind_tools = MagicMock(return_value=bound_model)
    bound_model.bind_tools = MagicMock(return_value=bound_model)

    # call_count reference kept for inspection
    fake_model._call_count = call_count
    bound_model._call_count = call_count

    return fake_model


def _make_customer_fixture() -> dict:
    """Return a customer dict with a real uuid.UUID id (as produced by DB layer)."""
    return {
        "id": CUSTOMER_UUID,  # raw uuid.UUID — CustomerResolve must coerce to str
        "name": "Test User",
        "phone": CUSTOMER_PHONE,
        "is_returning": True,
        "notes": None,
        "policy_accepted_at": None,
        "policy_version": None,
    }


def _make_memories_fixture() -> dict:
    """Return a customer memories dict as produced by read_customer_memories."""
    return {
        "visit_count": 3,
        "preferred_stylist_name": "Ana",
        "no_preference_stylist": False,
        "typical_services": ["Corte Dama"],
        "typical_day_of_week": "lunes",
        "typical_time_of_day": "mañana",
        "agent_notes": "Le gusta el corte en capas.",
    }


# ---------------------------------------------------------------------------
# Layer 2 — Monkeypatching helpers (I/O boundary isolation)
# ---------------------------------------------------------------------------


def _patch_customer_resolve_io(monkeypatch: Any, customer: dict, memories: dict) -> None:
    """Monkeypatch all I/O boundaries in CustomerResolveMiddleware."""
    monkeypatch.setattr(
        "agent.middleware.customer_resolve._get_cached_customer",
        AsyncMock(return_value=None),  # force DB path
    )
    monkeypatch.setattr(
        "agent.middleware.customer_resolve._set_cached_customer",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "agent.middleware.customer_resolve._lookup_customer",
        AsyncMock(return_value=customer),
    )
    monkeypatch.setattr(
        "agent.middleware.customer_resolve.read_customer_memories",
        AsyncMock(return_value=memories),
    )
    # Redis client used elsewhere in middleware — patch get_redis_client to avoid conn
    monkeypatch.setattr(
        "agent.middleware.customer_resolve.get_redis_client",
        MagicMock(return_value=MagicMock()),
    )


def _patch_availability_context_io(monkeypatch: Any) -> None:
    """Monkeypatch all I/O boundaries in AvailabilityContextMiddleware.

    Returns empty availability data so the middleware takes the path that
    inspects existing recently_offered_slots from tool messages.
    We need at least one check_availability ToolMessage in the messages list
    for the middleware to pick up a slot — that is handled in the test body.
    """
    monkeypatch.setattr(
        "agent.middleware.availability_context.get_availability_window",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "agent.middleware.availability_context._get_redis",
        MagicMock(return_value=None),
    )


def _patch_appointment_context_io(monkeypatch: Any) -> None:
    """Patch DB I/O in AppointmentContextMiddleware."""
    monkeypatch.setattr(
        "agent.middleware.appointment_context._fetch_upcoming_appointments",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "agent.middleware.appointment_context._get_service_names_for_middleware",
        AsyncMock(return_value="Corte Dama"),
    )


def _patch_dynamic_prompt_io(monkeypatch: Any) -> None:
    """Patch DB/async I/O in DynamicPromptMiddleware.

    The middleware imports two async loaders into its module namespace:
    ``build_catalog_prompt_section`` (returns a catalog section string, later
    wrapped by ``_format_catalog``) and ``load_business_hours_snapshot``
    (returns a ``dict`` of day->hours, consumed by ``_format_hours``).
    """
    monkeypatch.setattr(
        "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
        AsyncMock(return_value="test catalog"),
    )
    monkeypatch.setattr(
        "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
        AsyncMock(return_value={"lunes": "09:00-18:00"}),
    )


def _patch_summarize_io(monkeypatch: Any) -> None:
    """Patch get_summarizer_llm so SummarizeMiddleware never calls the real LLM."""
    fake_summarizer = MagicMock()
    fake_summarizer.ainvoke = AsyncMock(return_value=MagicMock(content="Resumen de prueba."))
    monkeypatch.setattr(
        "agent.middleware.summarize.get_summarizer_llm",
        MagicMock(return_value=fake_summarizer),
    )


def _patch_groundedness_io(monkeypatch: Any) -> None:
    """Patch ResponseGroundednessMiddleware to no-op (optional middleware)."""
    try:
        monkeypatch.setattr(
            "agent.middleware.response_groundedness.ResponseGroundednessMiddleware"
            ".awrap_model_call",
            AsyncMock(side_effect=lambda self_ref, req, handler: handler(req)),
        )
    except (AttributeError, ModuleNotFoundError):
        pass  # middleware may not be present — no-op


def _patch_tool_io(monkeypatch: Any) -> None:
    """Patch heavy I/O inside tools so they don't need real DB/GCal connections."""
    # check_availability — patch availability service
    try:
        monkeypatch.setattr(
            "agent.tools.check_availability.availability_service",
            MagicMock(
                probe=AsyncMock(return_value=[]),
                get_stylist_availability=AsyncMock(return_value=[]),
            ),
        )
    except (AttributeError, ModuleNotFoundError):
        pass

    # Disable GCal push in book tool
    try:
        monkeypatch.setattr(
            "agent.tools.book.push_to_google_calendar",
            AsyncMock(return_value=None),
        )
    except (AttributeError, ModuleNotFoundError):
        pass


def _patch_disclosure_io(monkeypatch: Any) -> None:
    """Ensure DisclosureMiddleware doesn't read Redis conversation history."""
    try:
        monkeypatch.setattr(
            "agent.middleware.disclosure._get_redis",
            MagicMock(return_value=None),
        )
    except (AttributeError, ModuleNotFoundError):
        pass


def _patch_llm_trace_io(monkeypatch: Any) -> None:
    """Patch LLMTraceMiddleware to no-op (trace middleware uses Langfuse)."""
    try:
        monkeypatch.setattr(
            "agent.middleware.llm_trace.LLMTraceMiddleware.awrap_model_call",
            AsyncMock(side_effect=lambda self_ref, req, handler: handler(req)),
        )
    except (AttributeError, ModuleNotFoundError):
        pass


# ---------------------------------------------------------------------------
# Layer 2 — Core contract tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_injected_state_contract(monkeypatch: Any) -> None:
    """S3-T1.3: All 5 InjectedState contract fields survive one graph turn.

    Builds the REAL agent with MemorySaver, invokes one turn, reads checkpoint,
    asserts each of the 5 fields is present with the expected type. Then
    round-trips checkpoint values through JsonPlusSerializer to catch any
    UUID/datetime type that would crash the Redis saver (orjson).

    Spec: REQ-S3-3, REQ-S3-4, REQ-S3-5
    Design: ADR-4 Layer 2
    """
    from langchain_core.messages import HumanMessage, ToolMessage
    from langgraph.checkpoint.memory import MemorySaver

    from agent.agent_factory import build_conversation_agent

    customer = _make_customer_fixture()
    memories = _make_memories_fixture()

    _patch_customer_resolve_io(monkeypatch, customer, memories)
    _patch_availability_context_io(monkeypatch)
    _patch_appointment_context_io(monkeypatch)
    _patch_dynamic_prompt_io(monkeypatch)
    _patch_summarize_io(monkeypatch)
    _patch_disclosure_io(monkeypatch)
    _patch_llm_trace_io(monkeypatch)
    _patch_tool_io(monkeypatch)

    # Build a slot that will appear in the ToolMessage so AvailabilityContextMiddleware
    # can extract and persist recently_offered_slots
    import json as _json

    slot_iso = "2026-07-01T10:00:00+00:00"
    slot_payload = _json.dumps(
        {
            "status": "ok",
            "payload": {"slots": [{"start_iso": slot_iso, "stylist_id": str(uuid.uuid4())}]},
        }
    )

    # Scripted LLM: returns deterministic tool_call on first invoke, final answer after
    fake_llm = _make_scripted_llm("check_availability")
    checkpointer = MemorySaver()

    graph = build_conversation_agent(
        llm_factory=lambda: fake_llm,
        checkpointer=checkpointer,
    )

    config = {"configurable": {"thread_id": f"v2:{CONV_ID}"}}

    # We need a ToolMessage in the conversation so AvailabilityContextMiddleware
    # can extract recently_offered_slots from it. We pre-seed the messages.
    tool_msg = ToolMessage(
        content=slot_payload,
        tool_call_id="pre_seed_tc",
        name="check_availability",
    )

    initial_state = {
        "conversation_id": CONV_ID,
        "customer_phone": CUSTOMER_PHONE,
        "messages": [
            HumanMessage(content="Quiero reservar un corte"),
            tool_msg,
        ],
    }

    await graph.ainvoke(initial_state, config=config)

    # Read checkpoint
    checkpoint_state = await graph.aget_state(config)
    values = checkpoint_state.values

    # --- Field 1: messages ---
    messages = values.get("messages")
    assert messages and len(messages) > 0, (
        "REQ-S3-4 FAIL: checkpoint 'messages' is empty or missing after turn 1. "
        "The add_messages reducer must populate this field from graph input."
    )

    # --- Field 2: customer_phone ---
    cp_phone = values.get("customer_phone")
    assert cp_phone == CUSTOMER_PHONE, (
        f"REQ-S3-4 FAIL: checkpoint 'customer_phone' is {cp_phone!r}, "
        f"expected {CUSTOMER_PHONE!r}. This is a graph-input field set at turn 0."
    )

    # --- Field 3: conversation_id ---
    cp_conv = values.get("conversation_id")
    assert cp_conv == CONV_ID, (
        f"REQ-S3-4 FAIL: checkpoint 'conversation_id' is {cp_conv!r}, "
        f"expected {CONV_ID!r}. This is a graph-input field set at turn 0."
    )

    # --- Field 4: customer_id ---
    cp_cid = values.get("customer_id")
    assert cp_cid and isinstance(cp_cid, str), (
        f"REQ-S3-4 FAIL: checkpoint 'customer_id' is {cp_cid!r} (type: {type(cp_cid).__name__}). "
        "Expected a non-empty str. CustomerResolveMiddleware must persist customer_id "
        "via ExtendedModelResponse(command=Command(update={...})) — not only via overlay. "
        "If this fails after removing the O2 persist block, that is the intended regression guard."
    )

    # --- Field 5: recently_offered_slots ---
    cp_slots = values.get("recently_offered_slots")
    assert cp_slots and isinstance(cp_slots, list) and len(cp_slots) >= 1, (
        f"REQ-S3-4 FAIL: checkpoint 'recently_offered_slots' is {cp_slots!r}. "
        "Expected a non-empty list. AvailabilityContextMiddleware must persist slots "
        "via ExtendedModelResponse(command=Command(update={...})) — not only via overlay. "
        "If this fails after removing the P-fix persist block, that is the intended regression guard."
    )

    # --- Serializer round-trip (catches UUID/datetime types that orjson would reject) ---
    serde = _get_json_plus_serializer()
    if serde is None:
        pytest.skip(
            "JsonPlusSerializer not found at langgraph.checkpoint.serde.jsonplus — "
            "LangGraph version may have changed the import path. "
            "Serializer round-trip skipped; update the import in _get_json_plus_serializer()."
        )

    try:
        serialized = serde.dumps_typed(values)
        reloaded = serde.loads_typed(serialized)
    except Exception as exc:
        pytest.fail(
            f"JsonPlusSerializer round-trip FAILED on checkpoint values.\n"
            f"Error: {exc}\n\n"
            "This means the checkpoint contains a Python type (UUID, datetime, asyncpg pgproto) "
            "that JsonPlusSerializer (and therefore AsyncRedisSaver) cannot handle.\n"
            "Identify the offending field and add coercion in the responsible middleware "
            "(see ADR-1 coercion table in the design document)."
        )

    # Reloaded values must still contain all 5 contract fields
    assert (
        reloaded.get("customer_phone") == CUSTOMER_PHONE
    ), "JsonPlusSerializer round-trip corrupted 'customer_phone'"
    assert (
        reloaded.get("conversation_id") == CONV_ID
    ), "JsonPlusSerializer round-trip corrupted 'conversation_id'"
    assert isinstance(reloaded.get("customer_id"), str), (
        f"JsonPlusSerializer round-trip: 'customer_id' type is "
        f"{type(reloaded.get('customer_id')).__name__}, expected str. "
        "UUID must be coerced to str before checkpoint persistence."
    )


@pytest.mark.asyncio
async def test_customer_memories_persisted(monkeypatch: Any) -> None:
    """S3-T1.4: customer_memories is non-null in checkpoint after CustomerResolveMiddleware runs.

    This validates REQ-S3-6 and future-proofs Change T memory work.

    Spec: REQ-S3-6
    """
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import MemorySaver

    from agent.agent_factory import build_conversation_agent

    customer = _make_customer_fixture()
    memories = _make_memories_fixture()

    _patch_customer_resolve_io(monkeypatch, customer, memories)
    _patch_availability_context_io(monkeypatch)
    _patch_appointment_context_io(monkeypatch)
    _patch_dynamic_prompt_io(monkeypatch)
    _patch_summarize_io(monkeypatch)
    _patch_disclosure_io(monkeypatch)
    _patch_llm_trace_io(monkeypatch)
    _patch_tool_io(monkeypatch)

    fake_llm = _make_scripted_llm()
    checkpointer = MemorySaver()

    graph = build_conversation_agent(
        llm_factory=lambda: fake_llm,
        checkpointer=checkpointer,
    )

    config = {"configurable": {"thread_id": f"v2:{CONV_ID}-memories"}}

    await graph.ainvoke(
        {
            "conversation_id": CONV_ID,
            "customer_phone": CUSTOMER_PHONE,
            "messages": [HumanMessage(content="Hola")],
        },
        config=config,
    )

    checkpoint_state = await graph.aget_state(config)
    values = checkpoint_state.values

    # customer_memories must be in the checkpoint — not just the per-turn overlay.
    # Currently (PR-1), this fails because the middleware does not emit a Command.
    # The xfail on this test tracks that gap; it flips green in S1-T2.6 (PR-2).
    cp_memories = values.get("customer_memories")
    assert cp_memories is not None, (
        "REQ-S3-6 FAIL: checkpoint 'customer_memories' is None after "
        "CustomerResolveMiddleware ran with a customer who has memories.\n"
        "CustomerResolveMiddleware must persist 'customer_memories' to the "
        "LangGraph checkpoint via ExtendedModelResponse(command=Command(update={...})).\n"
        "Implemented in S1-T2.6 (Change S PR-2)."
    )


@pytest.mark.asyncio
async def test_gate2_skips_summarizer_llm_on_second_turn(monkeypatch: Any) -> None:
    """S3-T1.5: Gate 2 must skip the summarizer LLM when cursor is persisted (bug #4 guard).

    Scenario:
      - Turn 1: len(messages) > window  → compaction runs → summarizer LLM called once
        → cursor (last_summarized_msg_count) + conversation_summary persisted.
      - Turn 2: same thread, no new messages above SUMMARIZE_NEW_MSG_THRESHOLD
        → Gate 2 reads cursor from checkpoint → summarizer LLM NOT called again.

    Current state (PR-1): summarize.py writes cursor into the per-turn overlay only
    (request.override(state=...)) and does NOT emit a Command to persist it. The
    checkpoint never gets last_summarized_msg_count. On turn 2, cursor is None,
    new_since = total - 0 = total, total > threshold → Gate 2 never fires → redundant
    compaction every single turn (bug #4).

    This xfail will be removed when S1-T2.4 implements the cursor persist fix (ADR-2).

    Spec: REQ-S3-7, REQ-S1-6, Scenario S3-C, Scenario S1-E
    Design: ADR-2
    """
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import MemorySaver

    from agent.agent_factory import build_conversation_agent
    from shared.config import get_settings

    customer = _make_customer_fixture()
    memories = _make_memories_fixture()

    _patch_customer_resolve_io(monkeypatch, customer, memories)
    _patch_availability_context_io(monkeypatch)
    _patch_appointment_context_io(monkeypatch)
    _patch_dynamic_prompt_io(monkeypatch)
    _patch_disclosure_io(monkeypatch)
    _patch_llm_trace_io(monkeypatch)
    _patch_tool_io(monkeypatch)

    # Track summarizer LLM invocations
    summarizer_call_count = {"n": 0}

    async def _fake_summarize(messages: list, llm: Any = None) -> str:
        summarizer_call_count["n"] += 1
        return "Resumen: el cliente quiere un corte."

    monkeypatch.setattr(
        "agent.middleware.summarize._summarize_messages",
        _fake_summarize,
    )

    settings = get_settings()
    window = 20  # SummarizeMiddleware default window
    keep_tail = 10
    threshold = settings.SUMMARIZE_NEW_MSG_THRESHOLD

    # Build a message list longer than window so Gate 1 does NOT short-circuit
    # We need window + threshold + 1 messages to guarantee Gate 2 fires on turn 1
    n_messages = window + threshold + 2
    extra_messages = [
        HumanMessage(content=f"Mensaje {i} de prueba para llenar el contexto.")
        for i in range(n_messages)
    ]

    fake_llm = _make_scripted_llm()
    checkpointer = MemorySaver()

    graph = build_conversation_agent(
        llm_factory=lambda: fake_llm,
        checkpointer=checkpointer,
    )

    conv_id_gate2 = f"{CONV_ID}-gate2"
    config = {"configurable": {"thread_id": f"v2:{conv_id_gate2}"}}

    # Turn 1: invoke with many messages → compaction should run → summarizer called once
    await graph.ainvoke(
        {
            "conversation_id": conv_id_gate2,
            "customer_phone": CUSTOMER_PHONE,
            "messages": extra_messages,
        },
        config=config,
    )

    calls_after_turn1 = summarizer_call_count["n"]
    assert calls_after_turn1 >= 1, (
        f"Summarizer was not called on turn 1 even though len(messages)={n_messages} > window={window}. "
        "Check that Gate 1 is correctly evaluating the message count."
    )

    # Verify cursor is in checkpoint after turn 1
    checkpoint_state = await graph.aget_state(config)
    cursor_in_checkpoint = checkpoint_state.values.get("last_summarized_msg_count")

    # Turn 2: add well-fewer messages than threshold → Gate 2 should block compaction.
    # (This requires cursor to have been persisted from turn 1.)
    # Use threshold // 2 to leave a safety margin for LangGraph-appended messages
    # (AIMessage, ToolMessages) that the add_messages reducer also accumulates in the
    # checkpoint. threshold - 2 is too close to the boundary: if the graph adds 2+
    # messages in this turn, new_since reaches threshold and Gate 3 fires legitimately.
    new_messages = [
        HumanMessage(content=f"Nuevo mensaje {i}") for i in range(max(1, threshold // 2))
    ]

    await graph.ainvoke(
        {
            "messages": new_messages,
        },
        config=config,
    )

    calls_after_turn2 = summarizer_call_count["n"]

    # If cursor was persisted: Gate 2 fires on turn 2 → summarizer NOT called again
    # If cursor was NOT persisted (current bug): cursor=None → new_since=total → summarizer called again
    assert calls_after_turn2 == calls_after_turn1, (
        f"REQ-S3-7 FAIL (bug #4): summarizer LLM was called {calls_after_turn2} times total "
        f"({calls_after_turn2 - calls_after_turn1} additional calls on turn 2). "
        f"Expected 0 additional calls because new messages ({len(new_messages)}) < "
        f"SUMMARIZE_NEW_MSG_THRESHOLD ({threshold}).\n\n"
        f"Root cause: 'last_summarized_msg_count' after turn 1 = {cursor_in_checkpoint!r}. "
        "If this is None, the cursor was NOT persisted to the checkpoint (bug #4). "
        "Gate 2 reads None → new_since = total - 0 = total → threshold not met → "
        "compaction fires on every turn.\n\n"
        "Fix: implement S1-T2.4 — make SummarizeMiddleware return "
        "persist_to_checkpoint(response, {last_summarized_msg_count: cursor, "
        "conversation_summary: text}) instead of writing only to the overlay."
    )
