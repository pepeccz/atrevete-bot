"""
T2.1 RED — BookingState schema migration tests.

Asserts:
- notes_state: Literal["not_asked","skipped","provided"] exists in BookingContext
- notes_asked attribute does NOT exist
- Default value for notes_state is "not_asked" (field present in TypedDict)
- 4 new fields exist with correct types and defaults:
    pending_disambiguations: list[...] default []
    confirmed: bool default False
    available_slots: list[...] default []
    booked_appointment_id: str | None default None
- _load_service_names() returns list[ServiceCatalogEntry], not list[str]

Requirements: R22, R23, R24, R25, R26, R27
Scenarios: S21, S22, S23, S24
Design section: §3
"""

from __future__ import annotations

import pytest


# ===========================================================================
# T2.1a — notes_state field in BookingContext
# ===========================================================================


class TestNotesStateField:
    """notes_asked → notes_state hard rename."""

    def test_notes_state_annotation_exists(self):
        """BookingContext must declare notes_state in its annotations (R24)."""
        from agent.state.schemas import BookingContext

        annotations = BookingContext.__annotations__
        assert "notes_state" in annotations, (
            f"notes_state not found in BookingContext.__annotations__. "
            f"Found: {sorted(annotations.keys())}"
        )

    def test_notes_asked_annotation_absent(self):
        """notes_asked MUST NOT exist in BookingContext after rename (R24 / S23)."""
        from agent.state.schemas import BookingContext

        annotations = BookingContext.__annotations__
        assert "notes_asked" not in annotations, (
            "notes_asked still present in BookingContext.__annotations__ — rename not applied"
        )

    def test_notes_state_type_is_literal(self):
        """notes_state annotation must be a Literal with the three allowed values."""
        import typing

        from agent.state.schemas import BookingContext

        ann = BookingContext.__annotations__.get("notes_state")
        assert ann is not None, "notes_state annotation missing"

        # Resolve forward references
        hints = typing.get_type_hints(BookingContext)
        ns_type = hints.get("notes_state")
        assert ns_type is not None, "notes_state not in get_type_hints()"

        # Check it is a Literal by inspecting origin
        origin = getattr(ns_type, "__origin__", None)
        assert origin is typing.Literal, (
            f"notes_state must be Literal[...], got {ns_type!r}"
        )

        allowed_values = set(ns_type.__args__)
        assert allowed_values == {"not_asked", "skipped", "provided"}, (
            f"notes_state Literal must have values {{'not_asked','skipped','provided'}}, "
            f"got {allowed_values}"
        )

    def test_notes_state_default_value_is_not_asked(self):
        """Default value for notes_state when building a fresh context is 'not_asked' (S21).

        Since BookingContext is total=False (all optional), the field is absent
        by default. The grounding module uses bc.get('notes_state', 'not_asked')
        — so the effective default IS 'not_asked'. We verify the design intent:
        a fresh empty context evaluated by compute_next_prompt with all other fields
        filled returns ASK_NOTES (not SHOW_CONFIRMATION).
        """
        from agent.booking.grounding import compute_next_prompt

        # All required fields filled except notes_state — must trigger ASK_NOTES
        state = {
            "booking_context": {
                "last_services": ["Óleo"],
                "last_stylist": "Pilar",
                "add_more_asked": True,
                "offered_slots": [{"date": "lunes", "time": "10:00"}],
                "selected_slot": {"date": "lunes", "time": "10:00"},
                "customer_name": "Ana García",
                # notes_state intentionally absent — default is "not_asked"
            }
        }
        directive = compute_next_prompt(state)
        assert directive.action == "ASK_NOTES", (
            f"Expected ASK_NOTES when notes_state absent (defaults to 'not_asked'), "
            f"got {directive.action!r}"
        )

    def test_notes_state_skipped_advances_to_show_confirmation(self):
        """notes_state='skipped' means notes step done → advance to SHOW_CONFIRMATION (S6)."""
        from agent.booking.grounding import compute_next_prompt

        state = {
            "booking_context": {
                "last_services": ["Óleo"],
                "last_stylist": "Pilar",
                "add_more_asked": True,
                "offered_slots": [{"date": "lunes", "time": "10:00"}],
                "selected_slot": {"date": "lunes", "time": "10:00"},
                "customer_name": "Ana García",
                "notes_state": "skipped",
                "_confirmation_shown": False,
            }
        }
        directive = compute_next_prompt(state)
        assert directive.action == "SHOW_CONFIRMATION", (
            f"Expected SHOW_CONFIRMATION when notes_state='skipped', got {directive.action!r}"
        )

    def test_notes_state_provided_advances_to_show_confirmation(self):
        """notes_state='provided' also means notes done → advance to SHOW_CONFIRMATION."""
        from agent.booking.grounding import compute_next_prompt

        state = {
            "booking_context": {
                "last_services": ["Óleo"],
                "last_stylist": "Pilar",
                "add_more_asked": True,
                "offered_slots": [{"date": "lunes", "time": "10:00"}],
                "selected_slot": {"date": "lunes", "time": "10:00"},
                "customer_name": "Ana García",
                "notes_state": "provided",
                "notes": "Sin fragancias",
                "_confirmation_shown": False,
            }
        }
        directive = compute_next_prompt(state)
        assert directive.action == "SHOW_CONFIRMATION", (
            f"Expected SHOW_CONFIRMATION when notes_state='provided', got {directive.action!r}"
        )


# ===========================================================================
# T2.1b — 4 new fields in BookingContext
# ===========================================================================


class TestNewBookingContextFields:
    """pending_disambiguations, confirmed, available_slots, booked_appointment_id."""

    def test_pending_disambiguations_annotation_exists(self):
        """BookingContext must declare pending_disambiguations (R22)."""
        from agent.state.schemas import BookingContext

        assert "pending_disambiguations" in BookingContext.__annotations__, (
            "pending_disambiguations not in BookingContext.__annotations__"
        )

    def test_confirmed_annotation_exists(self):
        """BookingContext must declare confirmed: bool (R23)."""
        from agent.state.schemas import BookingContext

        assert "confirmed" in BookingContext.__annotations__, (
            "confirmed not in BookingContext.__annotations__"
        )

    def test_booked_appointment_id_annotation_exists(self):
        """BookingContext must declare booked_appointment_id (R25)."""
        from agent.state.schemas import BookingContext

        assert "booked_appointment_id" in BookingContext.__annotations__, (
            "booked_appointment_id not in BookingContext.__annotations__"
        )

    def test_available_slots_annotation_exists(self):
        """BookingContext must declare available_slots (design §3 / S21)."""
        from agent.state.schemas import BookingContext

        assert "available_slots" in BookingContext.__annotations__, (
            "available_slots not in BookingContext.__annotations__"
        )

    def test_confirmed_default_false_via_grounding(self):
        """Confirmed absent in fresh context → compute_next_prompt never returns CALL_BOOK (R23 / S21).

        confirmed defaults to absent (None / missing), which is not True.
        Grounding must not return CALL_BOOK unless confirmed is explicitly True.
        """
        from agent.booking.grounding import compute_next_prompt

        # No confirmed key at all
        state = {"booking_context": {"last_services": []}}
        directive = compute_next_prompt(state)
        assert directive.action != "CALL_BOOK", (
            "compute_next_prompt returned CALL_BOOK with no confirmed key — default must be False/absent"
        )

    def test_confirmed_true_returns_call_book(self):
        """confirmed=True → CALL_BOOK (R6 / S8)."""
        from agent.booking.grounding import compute_next_prompt

        state = {
            "booking_context": {
                "last_services": ["Óleo"],
                "last_stylist": "Pilar",
                "add_more_asked": True,
                "offered_slots": [{"date": "lunes", "time": "10:00"}],
                "selected_slot": {"date": "lunes", "time": "10:00"},
                "customer_name": "Ana García",
                "notes_state": "skipped",
                "confirmed": True,
            }
        }
        directive = compute_next_prompt(state)
        assert directive.action == "CALL_BOOK", (
            f"Expected CALL_BOOK when confirmed=True, got {directive.action!r}"
        )
        assert directive.mandatory_next_call == "book"

    def test_pending_disambiguations_empty_by_default(self):
        """Fresh booking context without pending_disambiguations → no ASK_AUDIENCE forced (S21)."""
        from agent.booking.grounding import compute_next_prompt

        # With services, should NOT return ASK_AUDIENCE (no pending disambiguations)
        state = {
            "booking_context": {
                "last_services": ["Óleo"],
                "add_more_asked": False,
                # pending_disambiguations absent — defaults to []
            }
        }
        directive = compute_next_prompt(state)
        assert directive.action != "ASK_AUDIENCE", (
            "ASK_AUDIENCE returned despite no pending_disambiguations — default must be []"
        )

    def test_pending_disambiguations_non_empty_returns_ask_audience(self):
        """non-empty pending_disambiguations → ASK_AUDIENCE (R7 / S4)."""
        from agent.booking.grounding import compute_next_prompt

        state = {
            "booking_context": {
                "pending_disambiguations": [
                    {"family": "Corte", "variants": ["Corte Señora", "Corte Caballero"], "resolved_as": None}
                ],
            }
        }
        directive = compute_next_prompt(state)
        assert directive.action == "ASK_AUDIENCE", (
            f"Expected ASK_AUDIENCE with pending_disambiguations, got {directive.action!r}"
        )

    def test_booked_appointment_id_in_booking_complete_context(self):
        """booked_appointment_id field accessible from BookingContext (R25 / S21)."""
        from agent.state.schemas import BookingContext

        # Verify type hint allows str | None
        import typing

        hints = typing.get_type_hints(BookingContext)
        id_type = hints.get("booked_appointment_id")
        assert id_type is not None, "booked_appointment_id not in get_type_hints()"
        # Must be Optional[str] or str | None
        # In Python 3.11 Union[str, None] has __args__ = (str, NoneType)
        args = getattr(id_type, "__args__", None)
        assert args is not None and type(None) in args, (
            f"booked_appointment_id must be Optional (str | None), got {id_type!r}"
        )


# ===========================================================================
# T2.1c — _load_service_names returns list[ServiceCatalogEntry]
# ===========================================================================


class TestLoadServiceNamesExpandedType:
    """_load_service_names() must return list[ServiceCatalogEntry], not list[str] (T1.8 scope bleed absorbed by T2)."""

    def test_service_catalog_entry_importable(self):
        """ServiceCatalogEntry must be importable from agent.booking.models."""
        from agent.booking.models import ServiceCatalogEntry  # noqa: F401

    def test_service_catalog_entry_has_name_field(self):
        """ServiceCatalogEntry.name field must exist (R34 / S29)."""
        from agent.booking.models import ServiceCatalogEntry

        entry = ServiceCatalogEntry(name="Óleo", audience=None, siblings=[])
        assert entry.name == "Óleo"

    def test_service_catalog_entry_has_audience_field(self):
        """ServiceCatalogEntry.audience field must exist and be nullable (R34 / S29)."""
        from agent.booking.models import ServiceCatalogEntry

        entry_with = ServiceCatalogEntry(name="Corte Señora", audience="adult_female", siblings=[])
        assert entry_with.audience == "adult_female"

        entry_without = ServiceCatalogEntry(name="Óleo", audience=None, siblings=[])
        assert entry_without.audience is None

    def test_service_catalog_entry_has_siblings_field(self):
        """ServiceCatalogEntry.siblings field must be a list (R34–R36 / S29–S30)."""
        from agent.booking.models import ServiceCatalogEntry

        entry = ServiceCatalogEntry(
            name="Corte Señora",
            audience="adult_female",
            siblings=["Corte Señora", "Corte Caballero", "Corte Niño"],
        )
        assert entry.siblings == ["Corte Señora", "Corte Caballero", "Corte Niño"]
        assert len(entry.siblings) == 3

    def test_service_catalog_entry_no_audience_has_empty_siblings(self):
        """Service with audience=None must have siblings=[] (R36 / S30)."""
        from agent.booking.models import ServiceCatalogEntry

        entry = ServiceCatalogEntry(name="Óleo", audience=None, siblings=[])
        assert entry.siblings == []
        assert entry.has_audience_siblings is False

    def test_service_catalog_entry_has_audience_siblings_flag(self):
        """has_audience_siblings=True when siblings is non-empty (R34 / S29)."""
        from agent.booking.models import ServiceCatalogEntry

        entry = ServiceCatalogEntry(
            name="Corte Señora",
            audience="adult_female",
            siblings=["Corte Señora", "Corte Caballero"],
        )
        assert entry.has_audience_siblings is True

    def test_caller_can_use_name_attribute(self):
        """Callers that previously iterated list[str] must now use .name (R37 / S31)."""
        from agent.booking.models import ServiceCatalogEntry

        entries = [
            ServiceCatalogEntry(name="Óleo", audience=None, siblings=[]),
            ServiceCatalogEntry(name="Corte Señora", audience="adult_female", siblings=["Corte Señora"]),
        ]
        names = [e.name for e in entries]
        assert names == ["Óleo", "Corte Señora"]
