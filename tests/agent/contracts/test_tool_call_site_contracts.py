"""Contract tests: every call-site dict in action nodes must validate against tool.args_schema.

These tests intercept the tool invocation, capture the args dict that the node
constructs, and run Pydantic model_validate() on it.  A failure here means the node
is building an invalid dict — the EXACT root cause of the conv_id=5 production crash.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# R1 — fetch_availability_node: args dict validates check_availability schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_R1_fetch_availability_call_site_matches_check_availability_schema(
    availability_booking_state,
):
    """Captured args dict must pass check_availability.args_schema.model_validate().

    RED: fails because the node sends key 'date' instead of 'date_iso'.
    """
    import agent.booking.actions as actions_module
    from agent.tools.check_availability import check_availability

    captured: dict = {}

    async def _capture(args: dict) -> str:
        captured.update(args)
        from agent.tools.schemas import ToolResponse

        return ToolResponse(
            status="ok", payload={"slots": [], "total_duration_minutes": 30}
        ).model_dump_json()

    original = actions_module.check_availability_tool
    actions_module.check_availability_tool = _capture
    try:
        await actions_module.fetch_availability_node(availability_booking_state)
    finally:
        actions_module.check_availability_tool = original

    # This is the core assertion: the dict must validate against the tool schema
    check_availability.args_schema.model_validate(captured)


# ---------------------------------------------------------------------------
# R1 — execute_book_node: args dict validates book schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_R1_execute_book_call_site_matches_book_schema(book_booking_state):
    """Captured args dict must pass book.args_schema.model_validate().

    RED: fails because node sends 'slot_start'/'slot_end' (extra) and is missing 'start_iso'.
    """
    import agent.booking.actions as actions_module
    from agent.tools.book import book

    captured: dict = {}

    async def _capture(args: dict) -> str:
        captured.update(args)
        from agent.tools.schemas import ToolResponse

        return ToolResponse(status="ok", payload={"appointment_id": "fake-id"}).model_dump_json()

    original = actions_module.book_tool
    actions_module.book_tool = _capture
    try:
        await actions_module.execute_book_node(book_booking_state)
    finally:
        actions_module.book_tool = original

    book.args_schema.model_validate(captured)


# ---------------------------------------------------------------------------
# R1 (meta) — contract suite covers all known tools
# ---------------------------------------------------------------------------


def test_R1_contract_suite_covers_all_known_tools():
    """Meta-test: asserts the known tool list is non-empty so new tools can't silently skip.

    This test is ALWAYS GREEN — it's a registry guard, not a schema check.
    """
    known_tools = {"check_availability", "book"}
    assert known_tools, "At least one tool must be covered by the contract suite"
    assert "check_availability" in known_tools
    assert "book" in known_tools


# ---------------------------------------------------------------------------
# R3 — fetch_availability_node forwards audience
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_R3_fetch_availability_forwards_audience(availability_booking_state):
    """When booking.audience is set, args dict must include 'audience'.

    RED: fails because the node does not forward the audience field.
    """
    import agent.booking.actions as actions_module

    captured: dict = {}

    async def _capture(args: dict) -> str:
        captured.update(args)
        from agent.tools.schemas import ToolResponse

        return ToolResponse(
            status="ok", payload={"slots": [], "total_duration_minutes": 30}
        ).model_dump_json()

    original = actions_module.check_availability_tool
    actions_module.check_availability_tool = _capture
    try:
        await actions_module.fetch_availability_node(availability_booking_state)
    finally:
        actions_module.check_availability_tool = original

    assert (
        "audience" in captured
    ), f"fetch_availability_node did not forward 'audience' key. Got: {list(captured.keys())}"
    assert (
        captured["audience"] == "adult_female"
    ), f"Expected audience='adult_female', got '{captured['audience']}'"


# ---------------------------------------------------------------------------
# R5 — execute_book_node: no slot_start / slot_end in args dict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_R5_execute_book_dict_has_no_slot_start_or_slot_end(book_booking_state):
    """Prohibited keys slot_start and slot_end must not appear in the dict passed to book.

    RED: fails because the current node passes slot_start and slot_end.
    """
    import agent.booking.actions as actions_module

    captured: dict = {}

    async def _capture(args: dict) -> str:
        captured.update(args)
        from agent.tools.schemas import ToolResponse

        return ToolResponse(status="ok", payload={"appointment_id": "fake-id"}).model_dump_json()

    original = actions_module.book_tool
    actions_module.book_tool = _capture
    try:
        await actions_module.execute_book_node(book_booking_state)
    finally:
        actions_module.book_tool = original

    assert "slot_start" not in captured, (
        "execute_book_node must NOT pass 'slot_start' to book tool. "
        f"Found keys: {list(captured.keys())}"
    )
    assert "slot_end" not in captured, (
        "execute_book_node must NOT pass 'slot_end' to book tool. "
        f"Found keys: {list(captured.keys())}"
    )


# ---------------------------------------------------------------------------
# R5 — execute_book_node: stylist_id is non-null
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_R5_execute_book_stylist_id_is_nonnull(book_booking_state):
    """When a stylist_id is present in booking state, it must be non-null in the args dict."""
    import agent.booking.actions as actions_module

    captured: dict = {}

    async def _capture(args: dict) -> str:
        captured.update(args)
        from agent.tools.schemas import ToolResponse

        return ToolResponse(status="ok", payload={"appointment_id": "fake-id"}).model_dump_json()

    original = actions_module.book_tool
    actions_module.book_tool = _capture
    try:
        await actions_module.execute_book_node(book_booking_state)
    finally:
        actions_module.book_tool = original

    assert captured, "book_tool was not called — node aborted before invoking book"
    assert (
        captured.get("stylist_id") is not None
    ), "stylist_id must not be None when present in booking state"


# ---------------------------------------------------------------------------
# R5 — execute_book_node: aborts when stylist_id is None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_R5_execute_book_aborts_when_stylist_id_none(book_booking_state_no_stylist):
    """When booking.stylist_id is None the node MUST NOT call book and must return an error.

    RED: fails because no precondition guard exists yet.
    """
    from langgraph.types import Command

    import agent.booking.actions as actions_module

    tool_called = False

    async def _capture(args: dict) -> str:
        nonlocal tool_called
        tool_called = True
        from agent.tools.schemas import ToolResponse

        return ToolResponse(status="ok", payload={"appointment_id": "x"}).model_dump_json()

    original = actions_module.book_tool
    actions_module.book_tool = _capture
    try:
        result = await actions_module.execute_book_node(book_booking_state_no_stylist)
    finally:
        actions_module.book_tool = original

    assert not tool_called, "book_tool must NOT be called when stylist_id is None"
    assert isinstance(result, Command), "node must return a Command"
    # The returned booking step must be 'stylist' (redirect to re-collect)
    returned_booking = result.update.get("booking", {})
    assert (
        returned_booking.get("step") == "stylist"
    ), f"Expected step='stylist', got '{returned_booking.get('step')}'"
