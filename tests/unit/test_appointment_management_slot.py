"""Tests for F6 — conditional _slot_appointment_management (AS8, AS9a, AS9b, AS10).

F6: appointment_management_flow.md must NOT be in the unconditional loader.
    AppointmentContextMiddleware injects _slot_appointment_management ONLY when
    the customer has upcoming appointments (non-empty slot).
    SLOT_REGISTRY must include _slot_appointment_management.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# AS8 — appointment_management_flow.md removed from base loader
# ---------------------------------------------------------------------------

_MGMT_FLOW_SENTINEL = "appointment_management_flow.md"
_LOADER_PATH = (
    Path(__file__).parent.parent.parent / "agent" / "prompts" / "loader.py"
)


class TestLoaderExcludesAppointmentManagementFlow:
    """AS8 — appointment_management_flow.md must not be in the unconditional load list."""

    def test_mgmt_flow_absent_from_loader_source(self) -> None:
        """loader.py must not have a _read('appointment_management_flow.md') call."""
        source = _LOADER_PATH.read_text(encoding="utf-8")
        assert '_read("appointment_management_flow.md")' not in source, (
            "appointment_management_flow.md must be removed from loader.py unconditional "
            "load — it is now conditionally injected by AppointmentContextMiddleware."
        )

    def test_mgmt_flow_absent_from_assembled_prompt(self) -> None:
        """load_system_prompt() must not include appointment_management_flow.md content."""

        from agent.prompts import loader

        loader.load_system_prompt.cache_clear()
        prompt = loader.load_system_prompt()

        # The management flow file starts with a recognizable header
        # We check for a phrase unique to appointment_management_flow.md
        mgmt_sentinel = "Gestión de citas existentes"
        assert mgmt_sentinel not in prompt, (
            "appointment_management_flow.md content found in base prompt. "
            "It must be moved to conditional slot injection."
        )
        loader.load_system_prompt.cache_clear()


# ---------------------------------------------------------------------------
# AS10 — SLOT_REGISTRY updated
# ---------------------------------------------------------------------------


class TestSlotRegistryHasAppointmentManagement:
    """AS10 — _slot_appointment_management must be in SLOT_REGISTRY."""

    def test_slot_registered(self) -> None:
        """SLOT_REGISTRY must contain _slot_appointment_management."""
        from agent.state import SLOT_REGISTRY

        assert "_slot_appointment_management" in SLOT_REGISTRY, (
            f"_slot_appointment_management must be in SLOT_REGISTRY. "
            f"Current: {SLOT_REGISTRY}"
        )

    def test_slot_declared_in_agent_state(self) -> None:
        """AgentState must declare _slot_appointment_management as NotRequired[str]."""
        import typing
        from typing import NotRequired

        import agent.state as state_module

        hints = typing.get_type_hints(state_module.AgentState, include_extras=True)
        assert "_slot_appointment_management" in hints, (
            "AgentState must declare _slot_appointment_management field"
        )
        assert hints["_slot_appointment_management"] == NotRequired[str], (
            f"_slot_appointment_management must be NotRequired[str], "
            f"got {hints['_slot_appointment_management']}"
        )

    def test_slot_registry_drift_guard_passes(self) -> None:
        """_validate_registry() must not raise after the new slot is added."""
        from agent.state import _validate_registry

        # This will raise RuntimeError if SLOT_REGISTRY and AgentState are out of sync
        _validate_registry()

    def test_slot_after_upcoming_appointments_in_registry(self) -> None:
        """_slot_appointment_management must come after _slot_upcoming_appointments."""
        from agent.state import SLOT_REGISTRY

        appt_idx = SLOT_REGISTRY.index("_slot_appointment_management")
        upcoming_idx = SLOT_REGISTRY.index("_slot_upcoming_appointments")
        assert appt_idx > upcoming_idx, (
            "_slot_appointment_management must be after _slot_upcoming_appointments "
            "in SLOT_REGISTRY for semantic clustering and readable prompt assembly."
        )


# ---------------------------------------------------------------------------
# AS9a — slot absent for customers with no upcoming appointments
# AS9b — slot present for customers with upcoming appointments
# ---------------------------------------------------------------------------


def _make_minimal_request(state: dict):
    """Build a minimal ModelRequest-like mock."""
    request = MagicMock()
    request.state = state
    return request


class TestAppointmentManagementSlotInjection:
    """AS9a, AS9b — middleware injects slot iff upcoming_appointments non-empty."""

    @pytest.mark.asyncio
    async def test_slot_absent_when_no_upcoming_appointments(self) -> None:
        """AS9a — customer with zero upcoming appts → _slot_appointment_management absent."""
        from agent.middleware.appointment_context import AppointmentContextMiddleware

        middleware = AppointmentContextMiddleware()
        captured_state: dict = {}

        async def mock_handler(req):
            captured_state.update(req.state or {})
            return MagicMock()

        # Patch _fetch_upcoming_appointments to return empty list
        with patch(
            "agent.middleware.appointment_context._fetch_upcoming_appointments",
            new_callable=AsyncMock,
            return_value=[],
        ):
            request = _make_minimal_request({
                "customer_id": "some-uuid",
                "customer_phone": "+34600000001",
            })
            request.override = lambda state: _make_minimal_request(state)

            await middleware.awrap_model_call(request, mock_handler)

        assert "_slot_appointment_management" not in captured_state, (
            "_slot_appointment_management must NOT be injected when upcoming_appointments is empty"
        )

    @pytest.mark.asyncio
    async def test_slot_present_when_has_upcoming_appointments(self) -> None:
        """AS9b — customer with upcoming appts → _slot_appointment_management injected."""
        from agent.middleware.appointment_context import AppointmentContextMiddleware

        middleware = AppointmentContextMiddleware()
        captured_state: dict = {}

        # Build a fake appointment object that passes _format_block
        fake_appt = MagicMock()
        fake_appt.id = "appt-uuid-1"
        fake_appt.start_time = MagicMock()
        fake_appt.start_time.astimezone = MagicMock(return_value=fake_appt.start_time)
        fake_appt.start_time.strftime = MagicMock(return_value="10:00")
        fake_appt.stylist = MagicMock()
        fake_appt.stylist.name = "Lucía"
        fake_appt.service_ids = []
        fake_appt.status = MagicMock()
        fake_appt.status.name = "CONFIRMED"
        fake_appt._injected_service_names = "Corte Dama"

        async def mock_handler(req):
            captured_state.update(req.state or {})
            return MagicMock()

        with (
            patch(
                "agent.middleware.appointment_context._fetch_upcoming_appointments",
                new_callable=AsyncMock,
                return_value=[fake_appt],
            ),
            patch(
                "agent.middleware.appointment_context._get_service_names_for_middleware",
                new_callable=AsyncMock,
                return_value="Corte Dama",
            ),
            patch(
                "agent.middleware.appointment_context._format_date_spanish",
                return_value="lunes, 9 de junio de 2026",
            ),
        ):
            initial_state = {
                "customer_id": "some-uuid",
                "customer_phone": "+34600000001",
            }
            saved_request = None

            async def capturing_handler(req):
                captured_state.update(req.state or {})
                return MagicMock()

            request = MagicMock()
            request.state = initial_state

            def override_fn(state):
                r2 = MagicMock()
                r2.state = state
                return r2

            request.override = override_fn

            await middleware.awrap_model_call(request, capturing_handler)

        assert "_slot_appointment_management" in captured_state, (
            "_slot_appointment_management must be injected when customer has upcoming appointments"
        )
        slot_value = captured_state["_slot_appointment_management"]
        assert "<appointment_management>" in slot_value, (
            f"slot must be wrapped in <appointment_management> tags. Got: {slot_value!r}"
        )
