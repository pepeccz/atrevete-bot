"""
Tests for Bug 3 fix: Customer Name Pre-populated Without Asking.

Verifies that _resolve_customer_from_state() sets _suggested_customer_name
instead of customer_name, and that _build_dynamic_context() and
_build_flow_hint() handle the suggestion correctly.
"""

import pytest


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def booking_node():
    """BookingModeNode with empty context."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    node._mode_context = {}
    return node


def _make_state(**kwargs) -> dict:
    """Build a minimal ConversationState-like dict."""
    defaults: dict = {
        "messages": [],
        "customer_phone": "+34612345678",
        "conversation_summary": None,
        "customer_id": None,
        "customer_name": None,
        "customer_first_name": None,
    }
    defaults.update(kwargs)
    return defaults


# ──────────────────────────────────────────────────────────────────────
# T-08: _resolve_customer_from_state
# ──────────────────────────────────────────────────────────────────────


def test_returning_customer_sets_suggested_not_confirmed():
    """Scenario 1: returning customer → _suggested_customer_name set, customer_name NOT set."""
    from agent.modes.booking_mode import BookingModeNode

    state = _make_state(customer_first_name="Pablo García")
    ctx: dict = {}

    BookingModeNode._resolve_customer_from_state(state, ctx)

    assert ctx.get("_suggested_customer_name") == "Pablo García", (
        "_suggested_customer_name must be set from state"
    )
    assert "customer_name" not in ctx, (
        "customer_name must NOT be set — user hasn't confirmed in this conversation"
    )


def test_new_customer_no_suggestion_no_name():
    """Scenario 2: new customer → neither _suggested_customer_name nor customer_name set."""
    from agent.modes.booking_mode import BookingModeNode

    state = _make_state(customer_first_name=None, customer_name=None)
    ctx: dict = {}

    BookingModeNode._resolve_customer_from_state(state, ctx)

    assert "_suggested_customer_name" not in ctx
    assert "customer_name" not in ctx


def test_resolve_does_not_overwrite_existing_suggestion():
    """If _suggested_customer_name already set, _resolve_customer_from_state is a no-op for name."""
    from agent.modes.booking_mode import BookingModeNode

    state = _make_state(customer_first_name="Nuevo Nombre")
    ctx: dict = {"_suggested_customer_name": "Nombre Anterior"}

    BookingModeNode._resolve_customer_from_state(state, ctx)

    assert ctx["_suggested_customer_name"] == "Nombre Anterior", (
        "Existing suggestion must not be overwritten"
    )


def test_resolve_does_not_overwrite_confirmed_name():
    """If customer_name already confirmed, _resolve_customer_from_state doesn't add suggestion."""
    from agent.modes.booking_mode import BookingModeNode

    state = _make_state(customer_first_name="Pablo García")
    ctx: dict = {"customer_name": "Pablo García"}

    BookingModeNode._resolve_customer_from_state(state, ctx)

    assert "_suggested_customer_name" not in ctx, (
        "No suggestion should be added when customer_name is already confirmed"
    )


def test_resolve_uses_customer_name_fallback_when_no_first_name():
    """Falls back to state.customer_name when customer_first_name is absent."""
    from agent.modes.booking_mode import BookingModeNode

    state = _make_state(customer_first_name=None, customer_name="María López")
    ctx: dict = {}

    BookingModeNode._resolve_customer_from_state(state, ctx)

    assert ctx.get("_suggested_customer_name") == "María López"
    assert "customer_name" not in ctx


def test_resolve_injects_customer_id():
    """customer_id is still injected directly (not a suggestion)."""
    from agent.modes.booking_mode import BookingModeNode

    state = _make_state(customer_id="some-uuid-123")
    ctx: dict = {}

    BookingModeNode._resolve_customer_from_state(state, ctx)

    assert ctx.get("customer_id") == "some-uuid-123"


# ──────────────────────────────────────────────────────────────────────
# T-09: _build_dynamic_context — <suggested_name> block
# ──────────────────────────────────────────────────────────────────────


def test_dynamic_context_with_suggestion_shows_suggested_name_block(booking_node):
    """Scenario 3: suggestion present → <suggested_name> block appears, NOT in <collected_data>."""
    state = _make_state()
    ctx = {
        "last_services": ["Cortar"],
        "last_stylist": "Marta",
        "selected_slot": {"date": "miércoles 18", "time": "10:00"},
        "_suggested_customer_name": "Pablo García",
    }
    booking_node._cached_stylists_by_category = {}

    result = booking_node._build_dynamic_context(ctx, state)

    assert "<suggested_name>" in result, "<suggested_name> block must appear when suggestion exists"
    assert "Pablo García" in result
    assert "PREGUNTÁ si la reserva va a ese nombre" in result

    # Must NOT appear inside <collected_data>
    collected_start = result.find("<collected_data>")
    collected_end = result.find("</collected_data>")
    if collected_start != -1 and collected_end != -1:
        collected_section = result[collected_start:collected_end]
        assert "Pablo García" not in collected_section, (
            "_suggested_customer_name must NOT appear inside <collected_data>"
        )
        assert "✅ Nombre:" not in collected_section


def test_dynamic_context_without_suggestion_no_suggested_name_block(booking_node):
    """Scenario 4: no suggestion → no <suggested_name> block."""
    state = _make_state()
    ctx = {
        "last_services": ["Cortar"],
        "last_stylist": "Marta",
        "selected_slot": {"date": "miércoles 18", "time": "10:00"},
    }
    booking_node._cached_stylists_by_category = {}

    result = booking_node._build_dynamic_context(ctx, state)

    assert "<suggested_name>" not in result, (
        "<suggested_name> block must NOT appear when there is no suggestion"
    )


@pytest.mark.xfail(strict=True, reason="state-first-booking Batch 4: _build_flow_hint deleted — test needs rewrite, issue #TBD")
def test_dynamic_context_confirmed_name_shows_in_flow_hint_not_suggested(booking_node):
    """When customer_name is confirmed, it shows in <flow_hint>, no <suggested_name> block."""
    state = _make_state()
    ctx = {
        "last_services": ["Cortar"],
        "last_stylist": "Marta",
        "selected_slot": {"date": "miércoles 18", "time": "10:00"},
        "customer_name": "Pablo García",
    }
    booking_node._cached_stylists_by_category = {}

    result = booking_node._build_dynamic_context(ctx, state)

    assert "<suggested_name>" not in result, (
        "No <suggested_name> block when customer_name is already confirmed"
    )
    assert "Pablo García" in result, "Confirmed name should appear in flow_hint"


def test_dynamic_context_suggestion_hidden_when_name_confirmed(booking_node):
    """If both _suggested_customer_name and customer_name are set, only confirmed name shown."""
    state = _make_state()
    ctx = {
        "last_services": ["Cortar"],
        "customer_name": "Pablo García",
        "_suggested_customer_name": "Pablo García",  # same value, but confirmed
    }
    booking_node._cached_stylists_by_category = {}

    result = booking_node._build_dynamic_context(ctx, state)

    assert "<suggested_name>" not in result, (
        "No <suggested_name> block when customer_name is already confirmed"
    )


# ──────────────────────────────────────────────────────────────────────
# T-10: _build_flow_hint — Phase 4a differentiation
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.xfail(
    reason="state-first-booking Batch 4: _build_flow_hint deleted, test needs rewrite — issue #TBD",
    strict=True,
)
def test_flow_hint_name_pending_no_suggestion():
    """No name, no suggestion → nombre listed as pending."""
    from agent.modes.booking_mode import BookingModeNode

    ctx = {
        "last_services": ["Cortar"],
        "last_stylist": "Marta",
        "offered_slots": [{"date": "miércoles 18", "time": "10:00"}],
        "selected_slot": {"date": "miércoles 18", "time": "10:00"},
    }

    result = BookingModeNode._build_flow_hint(ctx)

    assert "nombre" in result.lower(), "nombre must appear as pending"
    assert "pendiente" in result.lower()


@pytest.mark.xfail(
    reason="state-first-booking Batch 4: _build_flow_hint deleted, test needs rewrite — issue #TBD",
    strict=True,
)
def test_flow_hint_name_pending_with_suggestion():
    """Suggestion present but not confirmed → nombre still pending (suggestion in dynamic ctx)."""
    from agent.modes.booking_mode import BookingModeNode

    ctx = {
        "last_services": ["Cortar"],
        "last_stylist": "Marta",
        "offered_slots": [{"date": "miércoles 18", "time": "10:00"}],
        "selected_slot": {"date": "miércoles 18", "time": "10:00"},
        "_suggested_customer_name": "Pablo García",
    }

    result = BookingModeNode._build_flow_hint(ctx)

    # nombre is still pending (suggestion ≠ confirmed name)
    assert "nombre" in result.lower(), "nombre must be pending even with suggestion"
    assert "pendiente" in result.lower()


@pytest.mark.xfail(
    reason="state-first-booking Batch 4: _build_flow_hint deleted, test needs rewrite — issue #TBD",
    strict=True,
)
def test_flow_hint_name_collected():
    """Name confirmed → nombre in collected. Notes are optional (R8/C5): not in pending."""
    from agent.modes.booking_mode import BookingModeNode

    ctx = {
        "last_services": ["Cortar"],
        "last_stylist": "Marta",
        "offered_slots": [{"date": "miércoles 18", "time": "10:00"}],
        "selected_slot": {"date": "miércoles 18", "time": "10:00"},
        "customer_name": "Pablo García",
    }

    result = BookingModeNode._build_flow_hint(ctx)

    assert "Pablo García" in result, "Confirmed name must appear in collected"
    # Notes are optional (R8/C5): must NOT appear in pending when notes_asked=False
    if "Pendiente:" in result:
        pending_segment = result.split("Pendiente:")[1].split("</flow_hint>")[0]
        assert "notas" not in pending_segment.lower(), (
            f"notas must not be in pending when notes_asked=False. Got: {pending_segment!r}"
        )


# ──────────────────────────────────────────────────────────────────────
# T-12 Scenario 5: After update_booking confirms name → customer_name set
# (via _post_tool_result patch mechanism)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_tool_result_update_booking_sets_customer_name(booking_node):
    """Scenario 5: update_booking patch sets customer_name, suggestion should be cleared."""
    import json

    booking_node._booking_context = {
        "_suggested_customer_name": "Pablo García",
    }
    booking_node._mode_context = booking_node._booking_context

    patch_result = {
        "_booking_context_patch": {
            "customer_first_name": "Pablo",
            "customer_last_name": "García",
            "customer_name": "Pablo García",
            "_suggested_customer_name": None,  # cleared explicitly by update_booking
        }
    }

    await booking_node._post_tool_result("update_booking", {}, json.dumps(patch_result))

    assert booking_node._booking_context.get("customer_name") == "Pablo García"
    assert "_suggested_customer_name" not in booking_node._booking_context, (
        "_suggested_customer_name must be cleared after explicit confirmation"
    )
