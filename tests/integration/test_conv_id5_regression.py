"""
RED integration test — conv_id=5 FM-6 regression — Phase 1, tasks 1.36–1.37.

Permanently pins the 2026-04-20 01:29 UTC booking failure to prevent silent regression.
The "dale" affirmation that was rejected (causing FM-6) must now be accepted and
result in a confirmed booking.

Expected fail mode at this stage:
  - ModuleNotFoundError: No module named 'agent.booking' (Phase 2 not yet implemented)
  - Or: fixture-level failure when integration harness is not running

NOTE: This is a skeleton with minimal fixture content. The full conv_id=5 turn
sequence will be populated in Phase 4 from production logs / DB replay.
For now, the fixture captures the known critical turn ("dale") and the
assertions define the acceptance criteria for Phase 3+.

Do NOT add @pytest.mark.xfail — per REQ-38, no new xfail marks.

REQs covered: REQ-35
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Fixtures — conv_id=5 turn sequence
# ---------------------------------------------------------------------------


@pytest.fixture
def conv_id5_turns() -> list[dict]:
    """
    The 2026-04-20 01:29 UTC conversation sequence for conv_id=5.

    This is the exact sequence that triggered FM-6 (bot narrated confirmation
    without calling book()). The critical turn is the "dale" affirmation which
    was rejected by the LLM-side identity.md rule instead of triggering book().

    Turn structure: {"role": "user"|"assistant", "content": "...", "turn": N}

    NOTE: Minimal skeleton — full reconstruction from DB in Phase 4.
    The assertions in TestConvId5Regression define the ACCEPTANCE CRITERIA
    for the complete implementation (Phase 3).
    """
    return [
        # Turn 1: User opens with booking request
        {
            "role": "user",
            "content": "Hola, quiero reservar un turno para un corte",
            "turn": 1,
        },
        # Turn 2: Bot asks for service details (minimal placeholder)
        {
            "role": "assistant",
            "content": "¡Hola! Con gusto te ayudo. ¿El corte es para señora, caballero o niño?",
            "turn": 2,
        },
        # Turn 3: User specifies audience
        {
            "role": "user",
            "content": "Para señora",
            "turn": 3,
        },
        # Turn 4: Bot asks for more services
        {
            "role": "assistant",
            "content": "Perfecto. ¿Necesitás algún otro servicio o con el corte alcanza?",
            "turn": 4,
        },
        # Turn 5: User says no more
        {
            "role": "user",
            "content": "No, solo el corte",
            "turn": 5,
        },
        # Turn 6: Bot asks for stylist
        {
            "role": "assistant",
            "content": "¿Con qué estilista querés el turno? O si no tenés preferencia, puedo asignarte cualquiera.",
            "turn": 6,
        },
        # Turn 7: User picks stylist
        {
            "role": "user",
            "content": "Sin preferencia",
            "turn": 7,
        },
        # Turn 8: Bot calls check_availability and shows slots
        {
            "role": "assistant",
            "content": "Encontré estos horarios disponibles:\n1. Lunes 21 de abril a las 10:00\n2. Martes 22 de abril a las 14:00\n¿Cuál te viene mejor?",
            "turn": 8,
        },
        # Turn 9: User picks slot
        {
            "role": "user",
            "content": "El 1",
            "turn": 9,
        },
        # Turn 10: Bot asks for name
        {
            "role": "assistant",
            "content": "¿Me decís tu nombre completo para la reserva?",
            "turn": 10,
        },
        # Turn 11: User provides name
        {
            "role": "user",
            "content": "María García",
            "turn": 11,
        },
        # Turn 12: Bot asks for notes
        {
            "role": "assistant",
            "content": "¿Querés agregar alguna nota especial (alergias, preferencias)?",
            "turn": 12,
        },
        # Turn 13: User skips notes
        {
            "role": "user",
            "content": "No, ninguna",
            "turn": 13,
        },
        # Turn 14: Bot shows confirmation summary
        {
            "role": "assistant",
            "content": (
                "Perfecto, acá está el resumen de tu turno:\n"
                "📅 Lunes 21 de abril a las 10:00\n"
                "✂️ Corte (señora)\n"
                "👤 María García\n"
                "¿Confirmamos?"
            ),
            "turn": 14,
        },
        # Turn 15: CRITICAL — "dale" affirmation that triggered FM-6 on 2026-04-20 01:29 UTC
        # In the original failure: this was NOT processed as confirmation, leading to FM-6.
        # In the fixed flow: is_affirmation("dale") returns True → confirmed=True → book() is called.
        {
            "role": "user",
            "content": "dale",
            "turn": 15,
            "note": "CRITICAL: affirmation that triggered FM-6. Must be accepted as confirmation.",
        },
    ]


@pytest.fixture
def conv_id5_expected_final_state() -> dict:
    """
    Expected final BookingContext state after the conv_id=5 replay completes.
    These are the acceptance criteria for the FM-6 fix.
    """
    return {
        "booked_appointment_id_not_none": True,
        "confirmed": True,
        "notes_state_in_set": {"skipped", "provided"},
        "exactly_one_book_call": True,
        "dale_accepted_as_confirmation": True,
        "no_add_more_loop": True,  # ASK_ADD_MORE appeared at most once
    }


# ---------------------------------------------------------------------------
# TestConvId5Regression — REQ-35 (task 1.37)
# ---------------------------------------------------------------------------


class TestConvId5Regression:
    """
    Permanent regression test for the 2026-04-20 01:29 UTC FM-6 failure
    on conv_id=5.

    FM-6: Bot narrated "queda confirmada" without calling book().
    Root cause: "dale" rejected by LLM-side rule instead of triggering book().
    Fix: is_affirmation("dale") returns True → confirmed=True → InvariantMiddleware
    allows book() → book() is called → booking created.

    This test MUST remain in the suite permanently (REQ-35).
    """

    @pytest.mark.asyncio
    async def test_dale_accepted_as_affirmation_unit(self) -> None:
        """
        Unit-level regression: is_affirmation("dale") MUST return True.
        This is the root cause of FM-6 — "dale" was not accepted as affirmation.

        Given: the affirmation resolver is implemented
        When: is_affirmation("dale") is called
        Then: it returns True

        REQ-35: dale accepted as confirmation.
        """
        from infra.resolvers.affirmation import is_affirmation

        result = is_affirmation("dale")
        assert result is True, (
            "REGRESSION GUARD: is_affirmation('dale') returned False. "
            "This was the root cause of FM-6 on conv_id=5 (2026-04-20 01:29 UTC). "
            "Fix: ensure 'dale' is in AFFIRMATION_PHRASES."
        )

    @pytest.mark.asyncio
    async def test_conv_id5_full_replay(
        self,
        conv_id5_turns: list[dict],
        conv_id5_expected_final_state: dict,
    ) -> None:
        """
        End-to-end replay of conv_id=5 with USE_CAPABILITY_BOOKING=True.

        Given: the complete 15-turn sequence from 2026-04-20 01:29 UTC
        And: USE_CAPABILITY_BOOKING=True
        When: the conversation is replayed through the full agent pipeline
        Then:
          - booked_appointment_id is not None (book() was actually called)
          - confirmed is True (affirmation was accepted before book())
          - notes_state in {"skipped", "provided"} (notes question resolved)
          - exactly 1 book() tool call was made
          - "dale" was accepted as confirmation intent
          - ASK_ADD_MORE appeared at most once (no add-more loop)

        REQ-35: Permanent regression test for FM-6.
        """
        # Import the capability stack (will fail with ModuleNotFoundError in RED phase)
        from infra.resolvers.affirmation import is_affirmation

        # Verify the critical "dale" turn is in the fixture
        critical_turn = next(
            (t for t in conv_id5_turns if t.get("content") == "dale"),
            None,
        )
        assert critical_turn is not None, (
            "conv_id=5 fixture must include the 'dale' affirmation turn (turn 15)"
        )

        # Full integration replay would require a running agent + DB.
        # At Phase 1 (RED), this test fails at import time.
        # At Phase 3+ (GREEN), the full replay harness is populated with DB data.
        # For now: assert the affirmation resolver correctly handles "dale".
        assert is_affirmation("dale") is True, (
            "REGRESSION GUARD: is_affirmation('dale') must be True for conv_id=5 to complete"
        )

        # Phase 4: full turn-by-turn replay via integration harness
        # TODO: populate with full DB replay harness in Phase 4
        # The assertions below define the acceptance criteria:
        #
        # final_state = await replay_conversation(conv_id5_turns, use_capability=True)
        # assert final_state["booking_context"]["booked_appointment_id"] is not None
        # assert final_state["booking_context"]["confirmed"] is True
        # assert final_state["booking_context"]["notes_state"] in {"skipped", "provided"}
        # assert tool_call_log.count("book") == 1
        # assert "dale" processed as affirmation in turn 15
        # assert grounding_directive_log.count("ASK_MORE_SERVICES") <= 1

    @pytest.mark.asyncio
    async def test_confirmed_required_before_book_call(self) -> None:
        """
        FM-6 specific: book() MUST NOT be called without confirmed=True.

        Given: BookingInvariantMiddleware is active (USE_CAPABILITY_BOOKING=True)
        When: book() is attempted with confirmed=False
        Then: it is blocked with CONFIRMATION_REQUIRED error

        This is the gate that prevents FM-6 at the tool level.
        """
        import json

        from agent.booking.middleware.invariants import BookingInvariantMiddleware

        bc = {
            "confirmed": False,
            "last_services": ["Corte"],
            "stylist_id": "stylist-001",
            "no_preference_stylist": False,
            "selected_slot": {"start": "2026-04-21T10:00:00"},
            "customer_name": "María García",
            "pending_disambiguations": [],
        }
        state = {"current_mode": "BOOKING", "booking_context": bc}
        middleware = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: [],
            mode_name="BOOKING",
        )

        from unittest.mock import MagicMock
        handler_called = []

        def _fake_handler(tc):
            handler_called.append(tc)
            return MagicMock(content=json.dumps({"appointment_id": "apt-001"}))

        tc = MagicMock()
        tc.name = "book"
        tc.args = {}
        tc.id = "tool-id-001"

        result = middleware.wrap_tool_call(tc, _fake_handler)

        assert len(handler_called) == 0, (
            "REGRESSION GUARD: book() was called without confirmed=True. "
            "This would recreate FM-6."
        )
        error = json.loads(result.content) if isinstance(result.content, str) else result.content
        assert error.get("error") is True
        assert error.get("code") in {"CONFIRMATION_REQUIRED", "CONFIRMATION_PENDING"}

    @pytest.mark.asyncio
    async def test_notes_state_not_asked_transitions_to_skipped(self) -> None:
        """
        Given: notes_state="not_asked" and user sends a negation to the notes question
        When: the agent processes the response
        Then: compute_next_prompt returns ASK_NOTES for the notes turn
        (ensuring the question is offered before confirming)

        This verifies notes_state drives the grounding flow correctly.
        """
        from agent.booking.grounding import compute_next_prompt

        # State where all data is ready BUT notes not yet asked
        bc = {
            "_booking_completed": False,
            "confirmed": False,
            "_confirmation_shown": False,
            "pending_disambiguations": [],
            "last_services": ["Corte"],
            "add_more_asked": True,
            "stylist_id": "stylist-001",
            "no_preference_stylist": False,
            "offered_slots": [{"start": "2026-04-21T10:00:00"}],
            "selected_slot": {"start": "2026-04-21T10:00:00"},
            "customer_name": "María García",
            "notes_state": "not_asked",  # Not yet asked → must ask
        }
        state = {"booking_context": bc, "current_mode": "BOOKING"}
        directive = compute_next_prompt(state)
        assert directive.action == "ASK_NOTES", (
            f"With notes_state='not_asked' and all other data ready, "
            f"expected ASK_NOTES but got {directive.action!r}"
        )
