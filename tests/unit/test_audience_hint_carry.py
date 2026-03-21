"""
Unit tests for ADR-4: Context Carry-Over — Widen service_audience_hint Admission Gate.

Tests that booking-shaped content in the first greeting turn causes
_build_booking_handoff_context to be called and service_audience_hint is
preserved in mode_context regardless of whether last_intent is strictly "book".

Covered scenarios:
- "caballero" in greeting (greet intent) → service_audience_hint in mode_context
- "hija" / "niña" in greeting (greet intent) → service_audience_hint = child_female
- "corte de caballero" without booking verb → hint extracted, mode = GENERAL
- Pure "Hola!" with no booking content → no handoff context built (no regression)
- Pure "Buenos días" → no booking context contamination
- Returning customer with booking content → hint preserved
- last_intent="book" + booking content → hint preserved AND mode = BOOKING
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.greeting_mode import GreetingMode, _build_booking_handoff_context, _has_booking_content
from agent.state.schemas import create_initial_state


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_mode() -> GreetingMode:
    mock_llm = MagicMock()
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    mock_llm.ainvoke = AsyncMock()
    return GreetingMode(tools=[], llm_client=mock_llm)


def make_new_customer_state(user_message: str, last_intent: str = "greet") -> dict:
    state = create_initial_state("conv-hint-carry", "+34600000100")
    state["customer_name"] = None
    state["pending_whatsapp_name"] = "Ana"
    state["messages"] = [
        {"role": "user", "content": user_message, "timestamp": "2026-03-20T10:00:00"}
    ]
    state["mode_context"] = {
        "last_intent": last_intent,
        "last_intent_confidence": 0.85,
    }
    return state


def make_returning_customer_state(user_message: str, last_intent: str = "greet") -> dict:
    state = create_initial_state("conv-hint-returning", "+34600000200")
    state["customer_name"] = "Carlos"
    state["customer_id"] = "cust-returning"
    state["is_first_interaction"] = False
    state["messages"] = [
        {"role": "user", "content": user_message, "timestamp": "2026-03-20T10:00:00"}
    ]
    state["mode_context"] = {
        "last_intent": last_intent,
        "last_intent_confidence": 0.90,
    }
    return state


# ── Module-level helper checks ────────────────────────────────────────────────


class TestHasBookingContent:
    def test_caballero_is_booking_content(self) -> None:
        assert _has_booking_content("quiero turno para un caballero") is True

    def test_corte_is_booking_content(self) -> None:
        assert _has_booking_content("necesito un corte") is True

    def test_dama_is_booking_content(self) -> None:
        assert _has_booking_content("para dama") is True

    def test_nina_is_booking_content(self) -> None:
        assert _has_booking_content("es para mi niña") is True

    def test_pure_greeting_is_not_booking_content(self) -> None:
        assert _has_booking_content("Hola!") is False

    def test_buenos_dias_is_not_booking_content(self) -> None:
        assert _has_booking_content("Buenos días") is False

    def test_empty_string_is_not_booking_content(self) -> None:
        assert _has_booking_content("") is False

    def test_complaint_is_not_booking_content(self) -> None:
        assert _has_booking_content("tengo un problema con mi pedido") is False

    def test_color_is_booking_content(self) -> None:
        assert _has_booking_content("quiero hacerme el color") is True


class TestBuildBookingHandoffContext:
    def test_caballero_extracts_audience_hint(self) -> None:
        ctx = _build_booking_handoff_context("quiero turno para un caballero")
        assert ctx.get("service_audience_hint") == "adult_male"

    def test_nina_extracts_child_female_hint(self) -> None:
        ctx = _build_booking_handoff_context("quiero turno para mi niña")
        assert ctx.get("service_audience_hint") == "child_female"

    def test_preserves_opening_booking_request(self) -> None:
        msg = "corte de dama"
        ctx = _build_booking_handoff_context(msg)
        assert ctx.get("opening_booking_request") == msg

    def test_empty_message_returns_empty_dict(self) -> None:
        ctx = _build_booking_handoff_context("")
        assert ctx == {}


# ── New customer: booking content on ambiguous/greet intent ───────────────────


@pytest.mark.asyncio
async def test_caballero_in_greeting_hint_preserved_in_mode_context() -> None:
    """'caballero' in greeting message → service_audience_hint in mode_context."""
    mode = make_mode()
    state = make_new_customer_state("quiero un turno para un caballero", last_intent="greet")

    with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
        mock_mc.ainvoke = AsyncMock(return_value={"id": "cust-101", "first_name": "Ana"})
        result = await mode.handle(state, MagicMock())

    mc = result.get("mode_context", {})
    assert mc.get("service_audience_hint") == "adult_male", (
        f"Expected 'adult_male' in mode_context, got: {mc}"
    )


@pytest.mark.asyncio
async def test_hija_in_greeting_hint_preserved_as_child_female() -> None:
    """'hija' maps to child_female audience hint."""
    mode = make_mode()
    state = make_new_customer_state("quiero turno para mi hija", last_intent="greet")

    with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
        mock_mc.ainvoke = AsyncMock(return_value={"id": "cust-102", "first_name": "Ana"})
        result = await mode.handle(state, MagicMock())

    mc = result.get("mode_context", {})
    assert mc.get("service_audience_hint") == "child_female", (
        f"Expected 'child_female', got: {mc}"
    )


@pytest.mark.asyncio
async def test_corte_de_caballero_without_booking_verb_hint_extracted() -> None:
    """'corte de caballero' with greet intent → hint extracted, mode stays GENERAL."""
    mode = make_mode()
    state = make_new_customer_state("corte de caballero", last_intent="greet")

    with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
        mock_mc.ainvoke = AsyncMock(return_value={"id": "cust-103"})
        result = await mode.handle(state, MagicMock())

    # Mode should be GENERAL (no explicit booking verb/intent)
    assert result.get("current_mode") == "GENERAL"
    mc = result.get("mode_context", {})
    # Hint should be extracted and preserved in the new mode_context
    assert mc.get("service_audience_hint") == "adult_male", (
        f"Expected adult_male hint even with greet intent, got: {mc}"
    )


@pytest.mark.asyncio
async def test_opening_booking_request_preserved_in_mode_context() -> None:
    """opening_booking_request must be set in mode_context when booking content detected."""
    mode = make_mode()
    msg = "quiero hacer un corte"
    state = make_new_customer_state(msg, last_intent="greet")

    with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
        mock_mc.ainvoke = AsyncMock(return_value={"id": "cust-104"})
        result = await mode.handle(state, MagicMock())

    mc = result.get("mode_context", {})
    assert mc.get("opening_booking_request") == msg, (
        f"Expected opening_booking_request='{msg}', got: {mc}"
    )


# ── Pure greeting — no booking context contamination ─────────────────────────


@pytest.mark.asyncio
async def test_pure_hola_does_not_build_booking_context() -> None:
    """'Hola!' with no booking content → mode_context has no audience hint."""
    mode = make_mode()
    state = make_new_customer_state("Hola!", last_intent="greet")

    with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
        mock_mc.ainvoke = AsyncMock(return_value={"id": "cust-105"})
        result = await mode.handle(state, MagicMock())

    mc = result.get("mode_context", {})
    assert "service_audience_hint" not in mc, (
        f"Pure greeting must NOT set service_audience_hint, got: {mc}"
    )
    assert "opening_booking_request" not in mc, (
        f"Pure greeting must NOT set opening_booking_request, got: {mc}"
    )


@pytest.mark.asyncio
async def test_buenos_dias_does_not_build_booking_context() -> None:
    """'Buenos días' with no booking content → no booking handoff context."""
    mode = make_mode()
    state = make_new_customer_state("Buenos días", last_intent="greet")

    with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
        mock_mc.ainvoke = AsyncMock(return_value={"id": "cust-106"})
        result = await mode.handle(state, MagicMock())

    mc = result.get("mode_context", {})
    assert "service_audience_hint" not in mc
    assert "opening_booking_request" not in mc


# ── Returning customer ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_returning_customer_with_caballero_hint_preserved() -> None:
    """Returning customer: booking content → hint preserved in mode_context."""
    mode = make_mode()
    state = make_returning_customer_state("corte para caballero", last_intent="greet")

    result = await mode.handle(state, MagicMock())

    mc = result.get("mode_context", {})
    assert mc.get("service_audience_hint") == "adult_male", (
        f"Expected adult_male for returning customer, got: {mc}"
    )


@pytest.mark.asyncio
async def test_returning_customer_pure_greeting_no_contamination() -> None:
    """Returning customer pure 'Hola' → no booking context."""
    mode = make_mode()
    state = make_returning_customer_state("Hola", last_intent="greet")

    result = await mode.handle(state, MagicMock())

    mc = result.get("mode_context", {})
    assert "service_audience_hint" not in mc


# ── Explicit book intent (regression: must still work) ───────────────────────


@pytest.mark.asyncio
async def test_explicit_book_intent_still_routes_to_booking() -> None:
    """last_intent='book' still routes to BOOKING mode (regression check)."""
    mode = make_mode()
    state = make_new_customer_state("Hola, quiero un turno", last_intent="book")
    state["mode_context"]["last_intent"] = "book"

    with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
        mock_mc.ainvoke = AsyncMock(return_value={"id": "cust-107"})
        result = await mode.handle(state, MagicMock())

    assert result.get("current_mode") == "BOOKING"


@pytest.mark.asyncio
async def test_book_intent_with_caballero_preserves_hint_in_booking() -> None:
    """book intent + caballero → BOOKING mode WITH audience hint in context."""
    mode = make_mode()
    state = make_new_customer_state("quiero turno para un caballero", last_intent="book")
    state["mode_context"]["last_intent"] = "book"

    with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
        mock_mc.ainvoke = AsyncMock(return_value={"id": "cust-108"})
        result = await mode.handle(state, MagicMock())

    assert result.get("current_mode") == "BOOKING"
    mc = result.get("mode_context", {})
    assert mc.get("service_audience_hint") == "adult_male"
