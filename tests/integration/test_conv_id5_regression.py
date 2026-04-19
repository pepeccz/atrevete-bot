"""
Integration regression — conv id=5 (audit #4144, 2026-04-18 21:03–21:05 UTC).

This test suite is the PERMANENT regression fence for the three failure modes
documented in that conversation:

  FM-1  add-more loop — bot re-asked "¿algo más?" after stylist selection
  FM-2  disambiguation skip — "corte de pelo" added without audience question
  FM-3  service-capture race — "¿algo más?" asked before update_booking called

Architecture under test (USE_CAPABILITY_BOOKING=True path):

  Tier 1 — Pure functions (S32, S33, S34, S35, S36):
    - compute_next_prompt(state)  — 13-branch pure action selector
    - BookingInvariantMiddleware._check()  — precondition gate
    These already pass; they document the structural invariants.

  Tier 2 — Node integration (S28, S35 affirmation wiring):
    - BookingModeNode.handle() with USE_CAPABILITY_BOOKING=True
    - Affirmation resolver MUST be wired pre-loop between negation and create_agent
    These WILL FAIL until T5.2 wires the affirmation hook (R32).

Spec refs: S28, S32, S33, S34, S35, S36
Design refs: §4, §5.2, §11, §12 commit #19
Requirements: R2, R7, R10, R12, R20, R32
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent.booking.grounding import compute_next_prompt
from agent.booking.middleware.invariants import BookingInvariantMiddleware
from agent.booking.models import ServiceCatalogEntry
from agent.modes.booking_mode import BookingModeNode
from agent.state.schemas import create_initial_state


# ---------------------------------------------------------------------------
# Catalog fixture — mirrors the actual salon catalog for the two services
# mentioned in audit #4144: Óleo Argán (no audience) and Corte (has audience)
# ---------------------------------------------------------------------------

_OLEO_ENTRY = ServiceCatalogEntry(
    name="Óleo",
    audience=None,
    siblings=[],
)

_CORTE_SENORA_ENTRY = ServiceCatalogEntry(
    name="Corte Señora",
    audience="adult_female",
    siblings=["Corte Señora", "Corte Caballero", "Corte Niño"],
)

_CORTE_CABALLERO_ENTRY = ServiceCatalogEntry(
    name="Corte Caballero",
    audience="adult_male",
    siblings=["Corte Señora", "Corte Caballero", "Corte Niño"],
)

_CORTE_NINO_ENTRY = ServiceCatalogEntry(
    name="Corte Niño",
    audience="child",
    siblings=["Corte Señora", "Corte Caballero", "Corte Niño"],
)

CATALOG = [_OLEO_ENTRY, _CORTE_SENORA_ENTRY, _CORTE_CABALLERO_ENTRY, _CORTE_NINO_ENTRY]


# ---------------------------------------------------------------------------
# Invariant middleware factory (pure — no DB, no Redis)
# ---------------------------------------------------------------------------

def _make_middleware(booking_context: dict[str, Any]) -> BookingInvariantMiddleware:
    """Build an InvariantMiddleware wired to a fixed in-memory state."""
    state = {"current_mode": "BOOKING", "booking_context": booking_context}
    return BookingInvariantMiddleware(
        get_state_fn=lambda: state,
        get_catalog_fn=lambda: CATALOG,
        mode_name="BOOKING",
    )


def _tool_call(name: str, args: dict[str, Any], id: str = "tc-001") -> dict[str, Any]:
    """Build a minimal tool call dict for _check()."""
    return {"name": name, "args": args, "id": id}


# ---------------------------------------------------------------------------
# Node factory — BookingModeNode with mocked I/O (Tier 2 tests)
# ---------------------------------------------------------------------------

def _make_node() -> BookingModeNode:
    """Build a BookingModeNode with mocked LLM and no-op async helpers."""
    with patch("agent.modes.booking_mode.BaseModeNode.__init__", return_value=None):
        node = BookingModeNode.__new__(BookingModeNode)
    node.llm = MagicMock()
    node.llm.bind_tools = MagicMock(return_value=node.llm)
    node._cached_stylists_by_category = {}
    node._cached_service_names = CATALOG
    node._booking_context = {}
    node._mode_context = {}
    node._current_state = {}
    return node


def _make_state(
    user_message: str,
    booking_context: dict[str, Any] | None = None,
    messages: list | None = None,
) -> dict:
    """Build a minimal ConversationState for one booking turn."""
    state = create_initial_state("conv-id5-regression", "+34600000099")
    state["user_message"] = user_message
    state["current_mode"] = "BOOKING"
    state["customer_name"] = "Cliente Test"
    state["is_first_interaction"] = False
    state["error_count"] = 0
    state["escalation_triggered"] = False
    state["ai_disclosure_sent"] = True
    state["booking_context"] = booking_context or {}
    state["mode_context"] = {}
    state["messages"] = messages or [{"role": "user", "content": user_message}]
    return state


def _make_agent(reply: str = "¿Qué estilista preferís?") -> MagicMock:
    """Build a mock create_agent that returns a deterministic reply."""

    async def _ainvoke(input_: dict, *args, **kwargs) -> dict:
        msgs = list(input_.get("messages", []))
        msgs.append(AIMessage(content=reply))
        return {"messages": msgs}

    agent_mock = MagicMock()
    agent_mock.ainvoke = _ainvoke
    return agent_mock


@pytest.fixture
def _common_patches():
    """Patch all I/O that BookingModeNode.handle() touches."""
    with (
        patch(
            "agent.modes.booking_mode.BookingModeNode._load_stylists_by_category",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "agent.modes.booking_mode.BookingModeNode._load_service_names",
            new_callable=AsyncMock,
            return_value=CATALOG,
        ),
        patch(
            "agent.modes.booking_mode.build_layered_messages",
            new_callable=AsyncMock,
            return_value=([HumanMessage(content="system stub")], 0),
        ),
        patch(
            "agent.modes.booking_mode.get_booking_config",
            new_callable=AsyncMock,
            return_value=MagicMock(
                tool_choice_policy=MagicMock(value="never_force")
            ),
        ),
        patch(
            "agent.modes.booking_mode.BookingModeNode._maybe_prepend_intro",
            side_effect=lambda text, state: (text, False),
        ),
        patch(
            "agent.modes.booking_mode.BookingModeNode._sanitize_response",
            side_effect=lambda text: text,
        ),
        patch(
            "agent.modes.booking_mode.BookingModeNode._resolve_service_category",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "agent.modes.booking_mode.write_customer_memories",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.dict(os.environ, {"USE_CAPABILITY_BOOKING": "true"}),
        patch(
            "shared.config.get_settings",
            return_value=MagicMock(
                USE_CAPABILITY_BOOKING=True,
                ENABLE_STATUS_LINE_MIDDLEWARE=False,
                OPENROUTER_API_KEY="test",
                OPENAI_API_KEY="test",
                LLM_MODEL="test",
            ),
        ),
    ):
        yield


# ===========================================================================
# TIER 1 — Pure function tests (S32-S36, structural invariants)
# These document correctness of compute_next_prompt and invariant middleware.
# They pass immediately; they are permanent regression documentation.
# ===========================================================================

# ---------------------------------------------------------------------------
# S32 — Turn 1: compute_next_prompt returns ASK_SERVICE on fresh state (FM-3)
# ---------------------------------------------------------------------------

class TestS32ServiceCaptureBeforeAddMore:
    """S32: grounding enforces service-first, add-more-second order (FM-3 fix)."""

    def test_empty_state_returns_ask_service(self) -> None:
        """With no booking_context, directive must be ASK_SERVICE (not ASK_MORE_SERVICES)."""
        state: dict[str, Any] = {"booking_context": {}}
        directive = compute_next_prompt(state)
        assert directive.action == "ASK_SERVICE", (
            f"Expected ASK_SERVICE for empty state, got {directive.action!r}. "
            "FM-3 fix: grounding must not skip to ASK_MORE_SERVICES "
            "before update_booking has been called."
        )

    def test_after_update_booking_returns_ask_more_services(self) -> None:
        """After update_booking, last_services is set → directive becomes ASK_MORE_SERVICES."""
        state: dict[str, Any] = {
            "booking_context": {
                "last_services": ["Óleo"],
                "add_more_asked": False,
            }
        }
        directive = compute_next_prompt(state)
        assert directive.action == "ASK_MORE_SERVICES", (
            f"Expected ASK_MORE_SERVICES after last_services set, got {directive.action!r}."
        )

    def test_services_empty_list_returns_ask_service(self) -> None:
        """Empty list (not None) for last_services also triggers ASK_SERVICE."""
        state: dict[str, Any] = {
            "booking_context": {"last_services": [], "add_more_asked": False}
        }
        directive = compute_next_prompt(state)
        assert directive.action == "ASK_SERVICE", (
            f"Empty last_services must yield ASK_SERVICE, got {directive.action!r}."
        )


# ---------------------------------------------------------------------------
# S33 — Turn 1b: Óleo has no audience siblings → invariant passes
# ---------------------------------------------------------------------------

class TestS33OleoPassesThroughInvariant:
    """S33: Óleo is unambiguous → invariant middleware does NOT block."""

    def test_oleo_update_booking_passes(self) -> None:
        """update_booking(services=['Óleo']) must pass through — no audience siblings."""
        bc: dict[str, Any] = {}
        mw = _make_middleware(bc)
        tool = _tool_call("update_booking", {"services": ["Óleo"]})
        error = mw._check(tool, bc, CATALOG)
        assert error is None, (
            f"Expected no error for 'Óleo' (no siblings), got {error!r}."
        )

    def test_oleo_not_flagged_as_ambiguous(self) -> None:
        """ServiceCatalogEntry for Óleo must report has_audience_siblings=False."""
        assert not _OLEO_ENTRY.has_audience_siblings

    def test_after_oleo_state_flows_to_ask_more_services(self) -> None:
        """After Óleo recorded, next directive is ASK_MORE_SERVICES."""
        state: dict[str, Any] = {
            "booking_context": {
                "last_services": ["Óleo"],
                "add_more_asked": False,
                "pending_disambiguations": [],
            }
        }
        directive = compute_next_prompt(state)
        assert directive.action == "ASK_MORE_SERVICES", (
            f"Expected ASK_MORE_SERVICES after Óleo registered, got {directive.action!r}."
        )


# ---------------------------------------------------------------------------
# S34 — Turn 2: "corte de pelo" triggers AUDIENCE_REQUIRED block (FM-2 fix)
# ---------------------------------------------------------------------------

class TestS34CorteTriggersDisambiguation:
    """S34: Corte has audience siblings → invariant blocks without hint (FM-2 fix)."""

    def test_corte_senora_blocked_without_hint(self) -> None:
        """update_booking(services=['Corte Señora']) without hint → AUDIENCE_REQUIRED."""
        bc: dict[str, Any] = {"last_services": ["Óleo"], "add_more_asked": True}
        mw = _make_middleware(bc)
        tool = _tool_call("update_booking", {"services": ["Corte Señora"]})
        error = mw._check(tool, bc, CATALOG)
        assert error is not None and error.startswith("AUDIENCE_REQUIRED"), (
            f"Expected AUDIENCE_REQUIRED, got {error!r}."
        )

    def test_corte_allowed_with_audience_hint(self) -> None:
        """update_booking(services=['Corte Señora']) WITH hint → passes."""
        bc: dict[str, Any] = {
            "last_services": ["Óleo"],
            "add_more_asked": True,
            "service_audience_hint": "adult_female",
        }
        mw = _make_middleware(bc)
        tool = _tool_call("update_booking", {"services": ["Corte Señora"]})
        error = mw._check(tool, bc, CATALOG)
        assert error is None, f"Expected no error with hint set, got {error!r}."

    def test_corte_flagged_as_ambiguous_in_catalog(self) -> None:
        """Corte Señora entry must report has_audience_siblings=True."""
        assert _CORTE_SENORA_ENTRY.has_audience_siblings

    def test_pending_disambiguations_blocks_ask_availability_via_grounding(self) -> None:
        """While pending_disambiguations non-empty, compute_next_prompt returns ASK_AUDIENCE (R7)."""
        state: dict[str, Any] = {
            "booking_context": {
                "last_services": ["Óleo"],
                "add_more_asked": True,
                "pending_disambiguations": [
                    {"family": "Corte", "variants": ["Corte Señora", "Corte Caballero", "Corte Niño"], "resolved_as": None}
                ],
            }
        }
        directive = compute_next_prompt(state)
        assert directive.action == "ASK_AUDIENCE", (
            f"Expected ASK_AUDIENCE with pending_disambiguations, got {directive.action!r}."
        )

    def test_check_availability_blocked_while_pending_disambiguation(self) -> None:
        """check_availability must be blocked by DISAMBIGUATION_PENDING (R12)."""
        bc: dict[str, Any] = {
            "last_services": ["Óleo"],
            "add_more_asked": True,
            "pending_disambiguations": [
                {"family": "Corte", "variants": ["Corte Señora", "Corte Caballero", "Corte Niño"], "resolved_as": None}
            ],
        }
        mw = _make_middleware(bc)
        tool = _tool_call("check_availability", {})
        error = mw._check(tool, bc, CATALOG)
        assert error == "DISAMBIGUATION_PENDING", (
            f"Expected DISAMBIGUATION_PENDING, got {error!r}."
        )


# ---------------------------------------------------------------------------
# S35 — Turn 3: negation "Nada mas" advances flow (FM-1 fix)
# ---------------------------------------------------------------------------

class TestS35NegationAdvancesFlow:
    """S35: After add_more_asked set by negation resolver, flow → ASK_STYLIST (FM-1)."""

    def test_add_more_asked_true_routes_to_ask_stylist(self) -> None:
        """add_more_asked=True and no stylist → next directive is ASK_STYLIST."""
        state: dict[str, Any] = {
            "booking_context": {
                "last_services": ["Óleo", "Corte Señora"],
                "add_more_asked": True,
                "pending_disambiguations": [],
            }
        }
        directive = compute_next_prompt(state)
        assert directive.action == "ASK_STYLIST", (
            f"Expected ASK_STYLIST when add_more_asked=True and no stylist, "
            f"got {directive.action!r}."
        )

    def test_add_more_asked_false_still_returns_ask_more_services(self) -> None:
        """Control: add_more_asked=False → still ASK_MORE_SERVICES."""
        state: dict[str, Any] = {
            "booking_context": {
                "last_services": ["Óleo", "Corte Señora"],
                "add_more_asked": False,
                "pending_disambiguations": [],
            }
        }
        directive = compute_next_prompt(state)
        assert directive.action == "ASK_MORE_SERVICES"

    def test_stylist_not_asked_again_after_negation(self) -> None:
        """After add_more_asked=True, action is NOT ASK_MORE_SERVICES."""
        state: dict[str, Any] = {
            "booking_context": {
                "last_services": ["Óleo", "Corte Señora"],
                "add_more_asked": True,
                "pending_disambiguations": [],
                "last_stylist": None,
            }
        }
        directive = compute_next_prompt(state)
        assert directive.action != "ASK_MORE_SERVICES", (
            f"After add_more_asked=True, grounding must NOT return ASK_MORE_SERVICES. "
            f"Got {directive.action!r}. This is the FM-1 loop we're breaking."
        )


# ---------------------------------------------------------------------------
# S36 — Turn 4→5: stylist selection → ASK_AVAILABILITY, not add-more (FM-1)
# ---------------------------------------------------------------------------

class TestS36StylistDoesNotRetriggerAddMore:
    """S36: Stylist set → ASK_AVAILABILITY, NOT ASK_MORE_SERVICES (FM-1 post-condition)."""

    def test_stylist_set_routes_to_ask_availability(self) -> None:
        """add_more_asked=True, stylist='Pilar', no slots → ASK_AVAILABILITY."""
        state: dict[str, Any] = {
            "booking_context": {
                "last_services": ["Óleo", "Corte Señora"],
                "add_more_asked": True,
                "pending_disambiguations": [],
                "last_stylist": "Pilar",
                "offered_slots": None,
            }
        }
        directive = compute_next_prompt(state)
        assert directive.action == "ASK_AVAILABILITY", (
            f"Expected ASK_AVAILABILITY after stylist set, got {directive.action!r}. "
            "POST-CONDITION FM-1: stylist must advance flow to availability check."
        )

    def test_stylist_set_mandatory_next_call_is_check_availability(self) -> None:
        """ASK_AVAILABILITY directive must carry mandatory_next_call='check_availability'."""
        state: dict[str, Any] = {
            "booking_context": {
                "last_services": ["Óleo", "Corte Señora"],
                "add_more_asked": True,
                "pending_disambiguations": [],
                "last_stylist": "Pilar",
            }
        }
        directive = compute_next_prompt(state)
        assert directive.mandatory_next_call == "check_availability", (
            f"Got mandatory_next_call={directive.mandatory_next_call!r}."
        )

    def test_update_booking_stylist_passes_when_services_set(self) -> None:
        """update_booking(stylist_name='Pilar') must pass when services registered."""
        bc: dict[str, Any] = {
            "last_services": ["Óleo", "Corte Señora"],
            "add_more_asked": True,
        }
        mw = _make_middleware(bc)
        tool = _tool_call("update_booking", {"stylist_name": "Pilar"})
        error = mw._check(tool, bc, CATALOG)
        assert error is None, f"Expected no error, got {error!r}."

    def test_no_preference_stylist_also_routes_to_availability(self) -> None:
        """Triangulation: no_preference_stylist=True also yields ASK_AVAILABILITY."""
        state: dict[str, Any] = {
            "booking_context": {
                "last_services": ["Óleo"],
                "add_more_asked": True,
                "pending_disambiguations": [],
                "no_preference_stylist": True,
                "offered_slots": None,
            }
        }
        directive = compute_next_prompt(state)
        assert directive.action == "ASK_AVAILABILITY", (
            f"'sin preferencia' must advance to ASK_AVAILABILITY, got {directive.action!r}."
        )


# ===========================================================================
# TIER 2 — Node integration tests (S28: affirmation hook wiring)
# These WILL FAIL until T5.2 wires is_affirmation into BookingModeNode.handle()
# per design §10 (R32): "affirmation resolver pre-loop hook SHALL be added to
# handle() between negation resolver and create_agent invocation".
# ===========================================================================

class TestS28AffirmationResolverWiringInHandle:
    """S28: affirmation resolver must run in handle() pre-loop and set confirmed=True (R32).

    EXPECTED TO FAIL until T5.2 wires infra.resolvers.affirmation.is_affirmation
    into BookingModeNode.handle() at the correct position.

    This is the FM-1 final mile: after confirmation is shown, user says "dale" →
    confirmed=True must be set BEFORE create_agent runs, so the LLM calls book().
    Without this wiring the bot loops back asking for confirmation again.
    """

    @pytest.mark.asyncio
    async def test_affirmation_dale_sets_confirmed_true(self, _common_patches) -> None:
        """User says 'dale' after _confirmation_shown=True → confirmed must be True in result.

        FAILS until is_affirmation is wired into handle() (R32, design §10).
        """
        node = _make_node()

        # Pre-condition: confirmation was shown, waiting for user to confirm
        booking_ctx = {
            "last_services": ["Óleo"],
            "add_more_asked": True,
            "last_stylist": "Pilar",
            "selected_slot": "2026-04-22 10:00",
            "customer_name": "Juan",
            "notes_state": "skipped",
            "_confirmation_shown": True,
            "confirmed": False,
        }
        state = _make_state(
            "dale",
            booking_context=booking_ctx,
            messages=[
                {"role": "assistant", "content": "Aquí está el resumen de tu cita. ¿Confirmás?"},
                {"role": "user", "content": "dale"},
            ],
        )

        agent_mock = _make_agent("¡Perfecto! Tu cita fue reservada.")
        with patch("langchain.agents.create_agent", return_value=agent_mock):
            result = await node.handle(state, intent=None)

        result_bc = result.get("booking_context") or {}
        assert result_bc.get("confirmed") is True, (
            f"Expected confirmed=True after user said 'dale' with _confirmation_shown=True. "
            f"Got booking_context={result_bc!r}. "
            "FAILS because is_affirmation is not yet wired into handle() (R32). "
            "T5.2 must add the pre-loop hook to fix this."
        )

    @pytest.mark.asyncio
    async def test_affirmation_si_sets_confirmed_true(self, _common_patches) -> None:
        """User says 'sí' after _confirmation_shown=True → confirmed must be True (triangulation)."""
        node = _make_node()

        booking_ctx = {
            "last_services": ["Corte Señora"],
            "add_more_asked": True,
            "last_stylist": "Pilar",
            "selected_slot": "2026-04-22 11:00",
            "customer_name": "María",
            "notes_state": "skipped",
            "_confirmation_shown": True,
            "confirmed": False,
        }
        state = _make_state(
            "sí",
            booking_context=booking_ctx,
            messages=[
                {"role": "assistant", "content": "¿Confirmás la reserva?"},
                {"role": "user", "content": "sí"},
            ],
        )

        agent_mock = _make_agent("¡Reserva confirmada!")
        with patch("langchain.agents.create_agent", return_value=agent_mock):
            result = await node.handle(state, intent=None)

        result_bc = result.get("booking_context") or {}
        assert result_bc.get("confirmed") is True, (
            f"Expected confirmed=True after 'sí', got booking_context={result_bc!r}. "
            "Triangulation for T5.2 affirmation wiring."
        )

    @pytest.mark.asyncio
    async def test_affirmation_not_set_when_confirmation_not_shown(self, _common_patches) -> None:
        """Negative: affirmation resolver must NOT run when _confirmation_shown=False (R20)."""
        node = _make_node()

        # Confirmation NOT shown — "sí" refers to a different question
        booking_ctx = {
            "last_services": ["Óleo"],
            "add_more_asked": False,
            "_confirmation_shown": False,
            "confirmed": False,
        }
        state = _make_state(
            "sí",
            booking_context=booking_ctx,
            messages=[
                {"role": "assistant", "content": "¿Querés agregar algo más?"},
                {"role": "user", "content": "sí"},
            ],
        )

        agent_mock = _make_agent("¿Qué otro servicio querés?")
        with patch("langchain.agents.create_agent", return_value=agent_mock):
            result = await node.handle(state, intent=None)

        result_bc = result.get("booking_context") or {}
        # confirmed must remain False — user was answering "¿algo más?" not confirming booking
        assert not result_bc.get("confirmed"), (
            f"confirmed must remain False when _confirmation_shown=False. "
            f"Got booking_context={result_bc!r}. "
            "Affirmation resolver must be gated on _confirmation_shown=True (R20)."
        )
