"""
Phase 4 — Deterministic Leaf Nodes: RED tests.

fetch_availability and execute_book assemble args exclusively from booking_context.
The LLM never touches tool arguments.

Conv_id=5 regression: services preserved across date change —
fetch_availability must use booking_context.last_services, NOT any LLM arg.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agent.booking.nodes.leaf_deterministic import execute_book, fetch_availability
from agent.booking.nodes.resolve_pre_turn import ANY_AVAILABLE


# ---------------------------------------------------------------------------
# Helpers — minimal booking_context builders
# ---------------------------------------------------------------------------


def _state(bc: dict) -> dict:
    """Wrap booking_context in a ConversationState-like dict."""
    return {"booking_context": bc}


def _bc(
    last_services: list[str] | None = None,
    date_hint: str | None = None,
    stylist: str | None = None,
    selected_slot: dict | None = None,
    customer_name: str | None = None,
    customer_phone: str | None = None,
    notes: str | None = None,
    conversation_id: str | None = None,
    **extra,
) -> dict:
    bc: dict = {}
    if last_services is not None:
        bc["last_services"] = last_services
    if date_hint is not None:
        bc["date_hint"] = date_hint
    if stylist is not None:
        bc["stylist"] = stylist
    if selected_slot is not None:
        bc["selected_slot"] = selected_slot
    if customer_name is not None:
        bc["customer_name"] = customer_name
    if customer_phone is not None:
        bc["customer_phone"] = customer_phone
    if notes is not None:
        bc["notes"] = notes
    if conversation_id is not None:
        bc["conversation_id"] = conversation_id
    bc.update(extra)
    return bc


# ===========================================================================
# fetch_availability — Task 4.1
# ===========================================================================


class TestFetchAvailabilityServiceNames:
    """Spec: fetch_availability reads service_names from booking_context.last_services."""

    @pytest.mark.asyncio
    async def test_qualified_service_name_passed_through(self):
        """
        Conv_id=5 regression: 'Cortar Señora' must NOT be collapsed to 'Cortar'.
        booking_context.last_services is passed as-is to check_availability_impl.
        """
        bc = _bc(
            last_services=["Cortar Señora"],
            date_hint="miércoles 29",
            stylist="María",
        )
        captured_kwargs = {}

        async def fake_check(**kwargs):
            captured_kwargs.update(kwargs)
            return {
                "success": True,
                "available_slots": [
                    {
                        "index": 1,
                        "time": "10:00",
                        "end_time": "11:00",
                        "stylist_name": "María",
                        "stylist_id": "uuid-1",
                        "date": "2026-04-29",
                        "day_label": "miércoles 29 de abril",
                        "full_datetime": "2026-04-29T10:00:00",
                    }
                ],
                "alternative_dates": False,
            }

        with patch(
            "agent.booking.nodes.leaf_deterministic.check_availability_impl",
            side_effect=fake_check,
        ):
            cmd = await fetch_availability(_state(bc))

        assert captured_kwargs["service_names"] == ["Cortar Señora"], (
            "Must preserve qualified service name — 'Cortar Señora' not 'Cortar'"
        )
        assert cmd.goto == "route_action"

    @pytest.mark.asyncio
    async def test_multiple_services_passed_as_list(self):
        """Multi-service: all names forwarded to check_availability_impl."""
        bc = _bc(
            last_services=["Cortar Señora", "Coloración"],
            date_hint="lunes",
        )
        captured_kwargs = {}

        async def fake_check(**kwargs):
            captured_kwargs.update(kwargs)
            return {"success": False, "available_slots": [], "error_code": "NO_SLOTS"}

        with patch(
            "agent.booking.nodes.leaf_deterministic.check_availability_impl",
            side_effect=fake_check,
        ):
            await fetch_availability(_state(bc))

        assert captured_kwargs["service_names"] == ["Cortar Señora", "Coloración"]

    @pytest.mark.asyncio
    async def test_date_hint_forwarded(self):
        """date_hint from booking_context is forwarded as 'date' kwarg."""
        bc = _bc(last_services=["Manicura"], date_hint="viernes próximo")
        captured_kwargs = {}

        async def fake_check(**kwargs):
            captured_kwargs.update(kwargs)
            return {"success": False, "available_slots": [], "error_code": "NO_SLOTS"}

        with patch(
            "agent.booking.nodes.leaf_deterministic.check_availability_impl",
            side_effect=fake_check,
        ):
            await fetch_availability(_state(bc))

        assert captured_kwargs.get("date") == "viernes próximo"

    @pytest.mark.asyncio
    async def test_stylist_name_forwarded(self):
        """Named stylist from booking_context passed to check_availability_impl."""
        bc = _bc(last_services=["Tinte"], stylist="Laura")
        captured_kwargs = {}

        async def fake_check(**kwargs):
            captured_kwargs.update(kwargs)
            return {"success": False, "available_slots": [], "error_code": "NO_SLOTS"}

        with patch(
            "agent.booking.nodes.leaf_deterministic.check_availability_impl",
            side_effect=fake_check,
        ):
            await fetch_availability(_state(bc))

        assert captured_kwargs.get("stylist_name") == "Laura"


class TestFetchAvailabilityAnyAvailable:
    """Spec: ANY_AVAILABLE sentinel → no stylist_name arg passed (all stylists queried)."""

    @pytest.mark.asyncio
    async def test_any_available_sentinel_passes_no_stylist_name(self):
        """When stylist=ANY_AVAILABLE, check_availability_impl gets no stylist_name."""
        bc = _bc(last_services=["Cortar Caballero"], stylist=ANY_AVAILABLE)
        captured_kwargs = {}

        async def fake_check(**kwargs):
            captured_kwargs.update(kwargs)
            return {"success": False, "available_slots": [], "error_code": "NO_SLOTS"}

        with patch(
            "agent.booking.nodes.leaf_deterministic.check_availability_impl",
            side_effect=fake_check,
        ):
            await fetch_availability(_state(bc))

        # ANY_AVAILABLE must not be forwarded as stylist_name — None or missing
        assert captured_kwargs.get("stylist_name") is None


class TestFetchAvailabilityResultPatching:
    """fetch_availability patches offered_slots into booking_context on success."""

    @pytest.mark.asyncio
    async def test_success_patches_offered_slots_into_booking_context(self):
        """On success, booking_context.offered_slots is populated from the result."""
        slots = [
            {
                "index": 1,
                "time": "10:00",
                "end_time": "11:00",
                "stylist_name": "María",
                "stylist_id": "uuid-1",
                "date": "2026-04-29",
                "day_label": "miércoles 29 de abril",
                "full_datetime": "2026-04-29T10:00:00",
            }
        ]
        bc = _bc(last_services=["Cortar Señora"], date_hint="miércoles 29")

        with patch(
            "agent.booking.nodes.leaf_deterministic.check_availability_impl",
            return_value={"success": True, "available_slots": slots},
        ):
            cmd = await fetch_availability(_state(bc))

        # Command must carry updated booking_context with offered_slots
        updated_bc = cmd.update.get("booking_context", {})
        assert updated_bc.get("offered_slots") == slots

    @pytest.mark.asyncio
    async def test_failure_keeps_offered_slots_empty_and_stores_error(self):
        """On failure, offered_slots stays empty and error info is stored."""
        bc = _bc(last_services=["Cortar Señora"], date_hint="ayer")  # 3-day rule

        with patch(
            "agent.booking.nodes.leaf_deterministic.check_availability_impl",
            return_value={
                "success": False,
                "available_slots": [],
                "date_too_soon": True,
                "error_code": "DATE_CLOSED",
                "error_message": "La fecha es demasiado pronto.",
            },
        ):
            cmd = await fetch_availability(_state(bc))

        updated_bc = cmd.update.get("booking_context", {})
        assert updated_bc.get("offered_slots", []) == []
        # error info must be surfaced so route_action / LLM leaf can explain it
        assert updated_bc.get("last_error") is not None


class TestFetchAvailabilityThreeDayRule:
    """Spec: 3-day rule rejection → error stored, routed back to route_action."""

    @pytest.mark.asyncio
    async def test_three_day_rule_routes_to_route_action(self):
        """Even on rejection, must route to route_action (not error_recovery directly)."""
        bc = _bc(last_services=["Cortar Señora"], date_hint="mañana")

        with patch(
            "agent.booking.nodes.leaf_deterministic.check_availability_impl",
            return_value={
                "success": False,
                "available_slots": [],
                "date_too_soon": True,
                "min_valid_date": "2026-04-24",
                "error_code": "DATE_CLOSED",
                "error_message": "La fecha mínima es 24 de abril.",
            },
        ):
            cmd = await fetch_availability(_state(bc))

        assert cmd.goto == "route_action"


# ===========================================================================
# execute_book — Task 4.1
# ===========================================================================


class TestExecuteBookArgs:
    """execute_book assembles args exclusively from booking_context."""

    @pytest.mark.asyncio
    async def test_exact_values_from_booking_context(self):
        """book_impl called with slot/customer/services from booking_context verbatim."""
        slot = {
            "stylist_id": "uuid-abc",
            "stylist_name": "María",
            "full_datetime": "2026-04-29T10:00:00",
            "time": "10:00",
            "end_time": "11:00",
            "date": "2026-04-29",
        }
        bc = _bc(
            selected_slot=slot,
            customer_name="Ana García",
            customer_phone="+34612345678",
            last_services=["Cortar Señora"],
            notes="Sin flecos",
            conversation_id="conv-42",
        )
        captured_kwargs = {}

        async def fake_book(**kwargs):
            captured_kwargs.update(kwargs)
            return {
                "success": True,
                "appointment_id": "appt-1",
                "customer_id": "cust-1",
                "customer_name": "Ana García",
                "stylist_name": "María",
                "start_time": "2026-04-29T10:00:00",
                "end_time": "2026-04-29T11:00:00",
                "duration_minutes": 60,
                "services": [{"name": "Cortar Señora", "duration_minutes": 60}],
                "_internal_flags": {"appointment_created": True},
            }

        with patch(
            "agent.booking.nodes.leaf_deterministic.book_impl",
            side_effect=fake_book,
        ):
            cmd = await execute_book(_state(bc))

        assert captured_kwargs["services"] == ["Cortar Señora"]
        assert captured_kwargs["stylist_id"] == "uuid-abc"
        assert captured_kwargs["start_time"] == "2026-04-29T10:00:00"
        assert captured_kwargs["customer_name"] == "Ana García"
        assert captured_kwargs["customer_phone"] == "+34612345678"

    @pytest.mark.asyncio
    async def test_booking_completed_set_true_on_success(self):
        """_booking_completed must be True in returned booking_context after success."""
        slot = {
            "stylist_id": "uuid-abc",
            "full_datetime": "2026-04-29T10:00:00",
            "time": "10:00",
            "end_time": "11:00",
            "date": "2026-04-29",
        }
        bc = _bc(
            selected_slot=slot,
            customer_name="Ana",
            customer_phone="+34612345678",
            last_services=["Manicura"],
        )

        with patch(
            "agent.booking.nodes.leaf_deterministic.book_impl",
            return_value={
                "success": True,
                "appointment_id": "appt-99",
                "_internal_flags": {"appointment_created": True},
            },
        ):
            cmd = await execute_book(_state(bc))

        updated_bc = cmd.update.get("booking_context", {})
        assert updated_bc.get("_booking_completed") is True
        assert updated_bc.get("appointment_id") == "appt-99"

    @pytest.mark.asyncio
    async def test_booking_completed_false_on_failure(self):
        """On book_impl failure, _booking_completed must NOT be set True."""
        slot = {
            "stylist_id": "uuid-abc",
            "full_datetime": "2026-04-29T10:00:00",
            "time": "10:00",
            "end_time": "11:00",
            "date": "2026-04-29",
        }
        bc = _bc(
            selected_slot=slot,
            customer_name="Ana",
            customer_phone="+34612345678",
            last_services=["Manicura"],
        )

        with patch(
            "agent.booking.nodes.leaf_deterministic.book_impl",
            return_value={
                "success": False,
                "error_code": "SLOT_TAKEN",
                "error_message": "El turno ya fue tomado.",
            },
        ):
            cmd = await execute_book(_state(bc))

        updated_bc = cmd.update.get("booking_context", {})
        assert updated_bc.get("_booking_completed") is not True

    @pytest.mark.asyncio
    async def test_routes_to_route_action(self):
        """execute_book always re-enters route_action after running."""
        slot = {
            "stylist_id": "uuid-abc",
            "full_datetime": "2026-04-29T10:00:00",
            "time": "10:00",
            "end_time": "11:00",
            "date": "2026-04-29",
        }
        bc = _bc(
            selected_slot=slot,
            customer_name="Ana",
            customer_phone="+34612345678",
            last_services=["Manicura"],
        )

        with patch(
            "agent.booking.nodes.leaf_deterministic.book_impl",
            return_value={"success": True, "appointment_id": "x", "_internal_flags": {}},
        ):
            cmd = await execute_book(_state(bc))

        assert cmd.goto == "route_action"


class TestExecuteBookConvId5Regression:
    """
    Conv_id=5 regression: services=['Cortar Señora'] must be preserved end-to-end.

    The sequence is: audience resolved → date changed → fetch_availability →
    slot selected → confirmed → execute_book. At execute_book time,
    last_services must still be ['Cortar Señora'], not 'Cortar'.
    """

    @pytest.mark.asyncio
    async def test_last_services_preserved_after_date_change(self):
        """
        Simulates the state AFTER a date change: audience='señora',
        last_services=['Cortar Señora'] are still in booking_context.
        execute_book passes 'Cortar Señora' (not 'Cortar') to book_impl.
        """
        slot = {
            "stylist_id": "uuid-maria",
            "full_datetime": "2026-04-29T10:00:00+02:00",
            "time": "10:00",
            "end_time": "11:00",
            "date": "2026-04-29",
        }
        bc = _bc(
            last_services=["Cortar Señora"],  # qualified — audience already resolved
            audience="señora",
            selected_slot=slot,
            customer_name="Cliente Test",
            customer_phone="+34612345678",
        )
        captured_services = []

        async def fake_book(**kwargs):
            captured_services.extend(kwargs.get("services", []))
            return {
                "success": True,
                "appointment_id": "appt-conv5",
                "_internal_flags": {"appointment_created": True},
            }

        with patch(
            "agent.booking.nodes.leaf_deterministic.book_impl",
            side_effect=fake_book,
        ):
            await execute_book(_state(bc))

        assert captured_services == ["Cortar Señora"], (
            f"Expected ['Cortar Señora'] but got {captured_services!r}. "
            "Audience qualifier must be preserved through date change."
        )
