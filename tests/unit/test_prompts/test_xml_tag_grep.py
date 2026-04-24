"""Tests that each middleware writes XML-fenced blocks to _slot_* keys."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, SystemMessage


class _FakeModelResponse:
    def __init__(self, msg=None):
        self.result = [msg or AIMessage(content="ok")]
        self.structured_response = None


def _make_request(system_content: str = "base", state: dict | None = None):
    """Return a FakeRequest whose override() captures kwargs."""
    captured = {}
    initial_state = state or {}

    class FakeRequest:
        def __init__(self, sys_msg=None, st=None):
            self.system_message = sys_msg or SystemMessage(content=system_content)
            self._state = st if st is not None else dict(initial_state)

        @property
        def state(self):
            return self._state

        def override(self, **kwargs):
            captured.update(kwargs)
            new_sys = kwargs.get("system_message", self.system_message)
            new_st = kwargs.get("state", self._state)
            return FakeRequest(sys_msg=new_sys, st=new_st)

    return FakeRequest(), captured


# ---------------------------------------------------------------------------
# B1: CustomerResolveMiddleware
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_customer_resolve_emits_xml_tag():
    """CustomerResolveMiddleware must write <customer>...</customer> to _slot_customer."""
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    phone = "+34600000001"
    req, captured = _make_request(state={"customer_phone": phone})

    customer_data = {"id": "uuid-1", "name": "Ana García", "is_returning": True}

    async def fake_handler(r):
        return _FakeModelResponse()

    with patch(
        "agent.middleware.customer_resolve._lookup_customer",
        new=AsyncMock(return_value=customer_data),
    ):
        mw = CustomerResolveMiddleware()
        await mw.awrap_model_call(req, fake_handler)

    state_written = captured.get("state", {})
    slot = state_written.get("_slot_customer", "")
    assert slot.startswith("<customer>"), f"_slot_customer must start with <customer>, got: {slot!r}"
    assert slot.rstrip().endswith("</customer>"), f"_slot_customer must end with </customer>, got: {slot!r}"
    assert "Ana García" in slot


@pytest.mark.asyncio
async def test_customer_resolve_unknown_customer_emits_xml_tag():
    """Unknown customer (phone-only) still emits <customer> block."""
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    phone = "+34600000002"
    req, captured = _make_request(state={"customer_phone": phone})

    async def fake_handler(r):
        return _FakeModelResponse()

    with patch(
        "agent.middleware.customer_resolve._lookup_customer",
        new=AsyncMock(return_value=None),
    ):
        mw = CustomerResolveMiddleware()
        await mw.awrap_model_call(req, fake_handler)

    state_written = captured.get("state", {})
    slot = state_written.get("_slot_customer", "")
    assert "<customer>" in slot
    assert "</customer>" in slot


# ---------------------------------------------------------------------------
# B1: AppointmentContextMiddleware
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_appointment_context_emits_xml_tag():
    """AppointmentContextMiddleware writes <upcoming_appointments>...</upcoming_appointments>."""
    from agent.middleware.appointment_context import AppointmentContextMiddleware

    import uuid
    customer_id = uuid.uuid4()
    req, captured = _make_request(state={"customer_id": customer_id})

    from unittest.mock import MagicMock
    from datetime import datetime, timezone

    appt = MagicMock()
    appt.id = uuid.uuid4()
    appt.start_time = datetime(2026, 5, 10, 10, 0, tzinfo=timezone.utc)
    appt.stylist = MagicMock()
    appt.stylist.name = "Pilar"
    appt.service_ids = []
    appt.status = MagicMock()
    appt.status.name = "CONFIRMED"
    from database.models import AppointmentStatus
    appt.status = AppointmentStatus.CONFIRMED
    appt.confirmation_sent_at = None
    appt.reminder_sent_at = None

    async def fake_handler(r):
        return _FakeModelResponse()

    with (
        patch(
            "agent.middleware.appointment_context._fetch_upcoming_appointments",
            new=AsyncMock(return_value=[appt]),
        ),
        patch(
            "agent.middleware.appointment_context._get_service_names_for_middleware",
            new=AsyncMock(return_value="Corte"),
        ),
    ):
        mw = AppointmentContextMiddleware()
        await mw.awrap_model_call(req, fake_handler)

    state_written = captured.get("state", {})
    slot = state_written.get("_slot_upcoming_appointments", "")
    assert slot.startswith("<upcoming_appointments>"), (
        f"_slot_upcoming_appointments must start with <upcoming_appointments>, got: {slot!r}"
    )
    assert slot.rstrip().endswith("</upcoming_appointments>"), (
        f"_slot_upcoming_appointments must end with </upcoming_appointments>, got: {slot!r}"
    )


# ---------------------------------------------------------------------------
# B1: DynamicPromptMiddleware
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dynamic_prompt_emits_xml_tags():
    """DynamicPromptMiddleware writes <catalog> and <business_hours> to _slot_* keys."""
    from agent.middleware.dynamic_prompt import DynamicPromptMiddleware

    req, captured = _make_request(state={})

    async def fake_handler(r):
        return _FakeModelResponse()

    with (
        patch(
            "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
            new=AsyncMock(return_value="## Catálogo\n- Corte: 30min"),
        ),
        patch(
            "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
            new=AsyncMock(return_value={"lunes": "10:00-20:00"}),
        ),
    ):
        mw = DynamicPromptMiddleware()
        await mw.awrap_model_call(req, fake_handler)

    state_written = captured.get("state", {})

    catalog_slot = state_written.get("_slot_catalog", "")
    assert "<catalog>" in catalog_slot, f"_slot_catalog must contain <catalog>, got: {catalog_slot!r}"
    assert "</catalog>" in catalog_slot

    hours_slot = state_written.get("_slot_business_hours", "")
    assert "<business_hours>" in hours_slot, (
        f"_slot_business_hours must contain <business_hours>, got: {hours_slot!r}"
    )
    assert "</business_hours>" in hours_slot
