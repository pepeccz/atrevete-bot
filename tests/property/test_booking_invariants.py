"""
Property-based invariant tests for the booking-flow-complete capability path.

Uses hypothesis to verify that compute_next_prompt satisfies 5 universal
invariants across ALL possible BookingContext states.

Design refs: design §11, spec R2, R6, R7
Spec refs: Invariant 1–5 from T5.3 task definition

Invariants:
  1. compute_next_prompt is TOTAL — never raises, always returns a GroundingDirective
  2. CALL_BOOK ⟹ bc.confirmed is True
  3. SHOW_CONFIRMATION ⟹ _booking_complete(bc) is True
  4. Non-empty pending_disambiguations ⟹ action is ASK_AUDIENCE (R7)
  5. add_more_asked=False and services set ⟹ action is ASK_MORE_SERVICES (not stylist/availability)
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from agent.booking.grounding import (
    GroundingDirective,
    compute_next_prompt,
)


# ---------------------------------------------------------------------------
# Strategies — valid BookingContext states
# ---------------------------------------------------------------------------

# Individual field strategies
_services_st = st.one_of(
    st.just(None),
    st.just([]),
    st.lists(st.sampled_from(["Óleo", "Corte Señora", "Corte Caballero", "Mechas", "Tinte"]), min_size=1, max_size=3),
)

_stylist_st = st.one_of(
    st.just(None),
    st.text(min_size=2, max_size=20, alphabet=st.characters(whitelist_categories=("Lu", "Ll"))),
)

_slot_st = st.one_of(
    st.just(None),
    st.just({"date": "2026-04-22", "time": "10:00"}),
    st.just({"date": "2026-04-23", "time": "14:30"}),
)

_name_st = st.one_of(
    st.just(None),
    st.just("María García"),
    st.just("Juan López"),
)

_notes_state_st = st.sampled_from(["not_asked", "skipped", "provided"])

_disambiguation_entry_st = st.fixed_dictionaries({
    "family": st.sampled_from(["Corte", "Tinte", "Mechas"]),
    "variants": st.just(["Corte Señora", "Corte Caballero", "Corte Niño"]),
    "resolved_as": st.just(None),
})

_pending_disambig_st = st.one_of(
    st.just([]),
    st.just(None),
    st.lists(_disambiguation_entry_st, min_size=1, max_size=2),
)


@st.composite
def booking_context_strategy(draw: Any) -> dict[str, Any]:
    """Generate a plausible BookingContext dict with all optional fields."""
    services = draw(_services_st)
    add_more_asked = draw(st.booleans())
    stylist = draw(_stylist_st)
    no_preference = draw(st.booleans())
    offered_slots = draw(st.one_of(st.just(None), st.just(["2026-04-22 10:00", "2026-04-22 11:00"])))
    selected_slot = draw(_slot_st) if offered_slots else None
    customer_name = draw(_name_st)
    notes_state = draw(_notes_state_st)
    pending = draw(_pending_disambig_st)
    confirmed = draw(st.booleans())
    booking_completed = draw(st.booleans())
    confirmation_shown = draw(st.booleans())

    bc: dict[str, Any] = {}
    if services is not None:
        bc["last_services"] = services
    if add_more_asked:
        bc["add_more_asked"] = add_more_asked
    if stylist:
        bc["last_stylist"] = stylist
    if no_preference:
        bc["no_preference_stylist"] = no_preference
    if offered_slots:
        bc["offered_slots"] = offered_slots
    if selected_slot:
        bc["selected_slot"] = selected_slot
    if customer_name:
        bc["customer_name"] = customer_name
    bc["notes_state"] = notes_state
    if pending:
        bc["pending_disambiguations"] = pending
    bc["confirmed"] = confirmed
    bc["_booking_completed"] = booking_completed
    bc["_confirmation_shown"] = confirmation_shown

    return bc


@st.composite
def conversation_state_strategy(draw: Any) -> dict[str, Any]:
    """Generate a ConversationState with a booking_context."""
    bc = draw(booking_context_strategy())
    return {"booking_context": bc}


# ---------------------------------------------------------------------------
# Invariant 1: compute_next_prompt is TOTAL — never raises
# ---------------------------------------------------------------------------

class TestInvariant1Totality:
    """compute_next_prompt(state) must never raise an exception for any BookingContext."""

    @given(state=conversation_state_strategy())
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_never_raises(self, state: dict[str, Any]) -> None:
        """For any booking context, compute_next_prompt must return a GroundingDirective (Invariant 1)."""
        try:
            result = compute_next_prompt(state)
        except Exception as exc:
            pytest.fail(
                f"compute_next_prompt raised {type(exc).__name__}: {exc}\n"
                f"Input state: {state!r}"
            )
        assert isinstance(result, GroundingDirective), (
            f"Expected GroundingDirective, got {type(result)!r}. "
            f"Input state: {state!r}"
        )

    @given(state=conversation_state_strategy())
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_action_is_always_a_known_string(self, state: dict[str, Any]) -> None:
        """Return value always has a non-empty action string."""
        result = compute_next_prompt(state)
        assert isinstance(result.action, str) and result.action, (
            f"action must be a non-empty string, got {result.action!r}."
        )

    def test_empty_state_does_not_raise(self) -> None:
        """Edge case: completely empty state must work."""
        result = compute_next_prompt({})
        assert isinstance(result, GroundingDirective)

    def test_none_booking_context_does_not_raise(self) -> None:
        """Edge case: booking_context=None must work."""
        result = compute_next_prompt({"booking_context": None})
        assert isinstance(result, GroundingDirective)


# ---------------------------------------------------------------------------
# Invariant 2: CALL_BOOK ⟹ confirmed is True
# ---------------------------------------------------------------------------

class TestInvariant2CallBookRequiresConfirmed:
    """If compute_next_prompt returns CALL_BOOK, booking_context.confirmed must be True."""

    @given(state=conversation_state_strategy())
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_call_book_implies_confirmed(self, state: dict[str, Any]) -> None:
        """CALL_BOOK action ⟹ bc.confirmed is True (R6)."""
        result = compute_next_prompt(state)
        if result.action == "CALL_BOOK":
            bc = state.get("booking_context") or {}
            assert bc.get("confirmed") is True, (
                f"CALL_BOOK returned but confirmed={bc.get('confirmed')!r}. "
                f"Violated Invariant 2: CALL_BOOK ⟹ confirmed. "
                f"BookingContext: {bc!r}"
            )

    def test_call_book_when_confirmed_true(self) -> None:
        """Direct case: confirmed=True → action should be CALL_BOOK."""
        state: dict[str, Any] = {"booking_context": {"confirmed": True}}
        result = compute_next_prompt(state)
        assert result.action == "CALL_BOOK", (
            f"Expected CALL_BOOK when confirmed=True, got {result.action!r}."
        )

    def test_call_book_requires_mandatory_next_call(self) -> None:
        """CALL_BOOK must set mandatory_next_call='book'."""
        state: dict[str, Any] = {"booking_context": {"confirmed": True}}
        result = compute_next_prompt(state)
        assert result.mandatory_next_call == "book", (
            f"CALL_BOOK must carry mandatory_next_call='book', got {result.mandatory_next_call!r}."
        )


# ---------------------------------------------------------------------------
# Invariant 3: SHOW_CONFIRMATION ⟹ _booking_complete(bc) is True
# ---------------------------------------------------------------------------

class TestInvariant3ShowConfirmationRequiresComplete:
    """SHOW_CONFIRMATION can only fire when all required slots are filled."""

    @given(state=conversation_state_strategy())
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_show_confirmation_implies_booking_complete(self, state: dict[str, Any]) -> None:
        """SHOW_CONFIRMATION ⟹ services + stylist + slots + name all present (Invariant 3)."""
        result = compute_next_prompt(state)
        if result.action == "SHOW_CONFIRMATION":
            bc = state.get("booking_context") or {}
            assert bool(bc.get("last_services")), (
                f"SHOW_CONFIRMATION but last_services={bc.get('last_services')!r}. "
                f"Invariant 3 violated."
            )
            assert bool(bc.get("last_stylist") or bc.get("no_preference_stylist")), (
                f"SHOW_CONFIRMATION but no stylist. Invariant 3 violated."
            )
            assert bool(bc.get("offered_slots")), (
                f"SHOW_CONFIRMATION but offered_slots={bc.get('offered_slots')!r}. "
                f"Invariant 3 violated."
            )
            assert bool(bc.get("selected_slot")), (
                f"SHOW_CONFIRMATION but selected_slot={bc.get('selected_slot')!r}. "
                f"Invariant 3 violated."
            )
            assert bool(bc.get("customer_name")), (
                f"SHOW_CONFIRMATION but customer_name={bc.get('customer_name')!r}. "
                f"Invariant 3 violated."
            )

    def test_show_confirmation_on_complete_booking(self) -> None:
        """Direct case: all slots filled → SHOW_CONFIRMATION when notes done and not yet shown."""
        state: dict[str, Any] = {
            "booking_context": {
                "last_services": ["Óleo"],
                "last_stylist": "Pilar",
                "offered_slots": [{"date": "2026-04-22", "time": "10:00"}],
                "selected_slot": {"date": "2026-04-22", "time": "10:00"},
                "customer_name": "Juan",
                "notes_state": "skipped",
                "_confirmation_shown": False,
                "confirmed": False,
                "pending_disambiguations": [],
                "add_more_asked": True,
            }
        }
        result = compute_next_prompt(state)
        assert result.action == "SHOW_CONFIRMATION", (
            f"Expected SHOW_CONFIRMATION for complete booking, got {result.action!r}."
        )


# ---------------------------------------------------------------------------
# Invariant 4: Non-empty pending_disambiguations ⟹ action == ASK_AUDIENCE
# ---------------------------------------------------------------------------

class TestInvariant4PendingDisambigBlocksAll:
    """pending_disambiguations non-empty must always force ASK_AUDIENCE (R7)."""

    @given(state=conversation_state_strategy())
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_pending_disambig_always_triggers_ask_audience(self, state: dict[str, Any]) -> None:
        """If pending_disambiguations non-empty AND no higher-priority branch active → ASK_AUDIENCE.

        Precondition: state is consistent (not _booking_completed, not confirmed,
        not _confirmation_shown). _confirmation_shown=True + pending_disambig is an
        inconsistent state that can't occur in practice (design §4 priority ordering).
        """
        bc = (state.get("booking_context") or {}).copy()
        # Inject non-empty pending_disambiguations and clear ALL higher-priority branches:
        #   branch 1: _booking_completed, branch 2: confirmed, branch 3: _confirmation_shown
        bc["pending_disambiguations"] = [
            {"family": "Corte", "variants": ["Corte Señora", "Corte Caballero"], "resolved_as": None}
        ]
        bc["confirmed"] = False
        bc["_booking_completed"] = False
        bc["_confirmation_shown"] = False  # must be False for ASK_AUDIENCE to fire (branch 4 > 3)
        state_with_pending = {"booking_context": bc}
        result = compute_next_prompt(state_with_pending)
        assert result.action == "ASK_AUDIENCE", (
            f"Expected ASK_AUDIENCE when pending_disambiguations non-empty (R7), "
            f"got {result.action!r}. BookingContext: {bc!r}"
        )

    def test_empty_pending_disambig_does_not_force_ask_audience(self) -> None:
        """Control: empty pending_disambiguations must not force ASK_AUDIENCE."""
        state: dict[str, Any] = {
            "booking_context": {
                "last_services": ["Óleo"],
                "add_more_asked": False,
                "pending_disambiguations": [],
            }
        }
        result = compute_next_prompt(state)
        assert result.action != "ASK_AUDIENCE", (
            f"Empty pending_disambiguations must NOT force ASK_AUDIENCE, got {result.action!r}."
        )

    def test_none_pending_disambig_does_not_force_ask_audience(self) -> None:
        """Control: pending_disambiguations=None must not force ASK_AUDIENCE."""
        state: dict[str, Any] = {
            "booking_context": {
                "last_services": ["Óleo"],
                "add_more_asked": False,
                "pending_disambiguations": None,
            }
        }
        result = compute_next_prompt(state)
        assert result.action != "ASK_AUDIENCE", (
            f"pending_disambiguations=None must NOT force ASK_AUDIENCE, got {result.action!r}."
        )


# ---------------------------------------------------------------------------
# Invariant 5: add_more_asked=False and services set ⟹ ASK_MORE_SERVICES
# (stylist question must not fire before add-more is resolved)
# ---------------------------------------------------------------------------

class TestInvariant5StylistBlockedUntilAddMoreResolved:
    """services set and add_more_asked=False must yield ASK_MORE_SERVICES, not ASK_STYLIST."""

    @given(
        services=st.lists(
            st.sampled_from(["Óleo", "Mechas", "Corte Señora"]),
            min_size=1,
            max_size=3,
        )
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_services_set_add_more_not_asked_yields_ask_more_services(
        self, services: list[str]
    ) -> None:
        """Invariant 5: last_services set + add_more_asked=False → ASK_MORE_SERVICES (not ASK_STYLIST)."""
        state: dict[str, Any] = {
            "booking_context": {
                "last_services": services,
                "add_more_asked": False,
                "pending_disambiguations": [],
                "confirmed": False,
                "_booking_completed": False,
            }
        }
        result = compute_next_prompt(state)
        assert result.action == "ASK_MORE_SERVICES", (
            f"Expected ASK_MORE_SERVICES when services={services!r} and add_more_asked=False, "
            f"got {result.action!r}. "
            "Invariant 5: add-more must be resolved before stylist question fires."
        )

    def test_stylist_question_fires_only_after_add_more_resolved(self) -> None:
        """ASK_STYLIST must only fire when add_more_asked=True."""
        state_not_asked: dict[str, Any] = {
            "booking_context": {
                "last_services": ["Óleo"],
                "add_more_asked": False,
                "pending_disambiguations": [],
            }
        }
        result_not_asked = compute_next_prompt(state_not_asked)
        assert result_not_asked.action != "ASK_STYLIST", (
            f"ASK_STYLIST must not fire before add_more_asked=True, "
            f"got {result_not_asked.action!r}."
        )

        state_asked: dict[str, Any] = {
            "booking_context": {
                "last_services": ["Óleo"],
                "add_more_asked": True,
                "pending_disambiguations": [],
            }
        }
        result_asked = compute_next_prompt(state_asked)
        assert result_asked.action == "ASK_STYLIST", (
            f"Expected ASK_STYLIST when add_more_asked=True, got {result_asked.action!r}."
        )
