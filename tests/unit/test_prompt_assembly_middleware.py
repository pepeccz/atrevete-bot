"""C2/C3a/C3b-RED: Tests for PromptAssemblyMiddleware."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, SystemMessage


class _FakeModelResponse:
    def __init__(self, msg=None):
        self.result = [msg or AIMessage(content="ok")]
        self.structured_response = None


class FakeRequest:
    def __init__(self, system_content: str = "base", state: dict | None = None):
        self.system_message = SystemMessage(content=system_content)
        self._state = dict(state or {})

    @property
    def state(self):
        return self._state

    def override(self, **kwargs):
        new = FakeRequest(state=kwargs.get("state", self._state))
        new.system_message = kwargs.get("system_message", self.system_message)
        return new


# ---------------------------------------------------------------------------
# C2: slot-writers must NOT touch system_message.content
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_slot_writers_do_not_mutate_system_message_customer():
    """CustomerResolveMiddleware must not mutate system_message.content."""
    from unittest.mock import patch
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    phone = "+34600111222"
    req = FakeRequest(system_content="original", state={"customer_phone": phone})

    received_system_content: list[str] = []

    async def handler(r):
        received_system_content.append(r.system_message.content)
        return _FakeModelResponse()

    with patch(
        "agent.middleware.customer_resolve._lookup_customer",
        new=AsyncMock(return_value={"id": "uuid-x", "name": "Test", "is_returning": False}),
    ):
        mw = CustomerResolveMiddleware()
        await mw.awrap_model_call(req, handler)

    assert received_system_content[0] == "original", (
        f"CustomerResolve must not mutate system_message; got: {received_system_content[0]!r}"
    )


@pytest.mark.asyncio
async def test_slot_writers_do_not_mutate_system_message_appointment():
    """AppointmentContextMiddleware must not mutate system_message.content."""
    import uuid
    from datetime import datetime, timezone
    from unittest.mock import patch
    from agent.middleware.appointment_context import AppointmentContextMiddleware
    from database.models import AppointmentStatus

    customer_id = uuid.uuid4()
    req = FakeRequest(system_content="original", state={"customer_id": customer_id})

    appt = MagicMock()
    appt.id = uuid.uuid4()
    appt.start_time = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    appt.stylist = MagicMock()
    appt.stylist.name = "Pilar"
    appt.service_ids = []
    appt.status = AppointmentStatus.CONFIRMED
    appt.confirmation_sent_at = None
    appt.reminder_sent_at = None

    received_system_content: list[str] = []

    async def handler(r):
        received_system_content.append(r.system_message.content)
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
        await mw.awrap_model_call(req, handler)

    assert received_system_content[0] == "original", (
        f"AppointmentContext must not mutate system_message; got: {received_system_content[0]!r}"
    )


@pytest.mark.asyncio
async def test_slot_writers_do_not_mutate_system_message_dynamic():
    """DynamicPromptMiddleware must not mutate system_message.content."""
    from unittest.mock import patch
    from agent.middleware.dynamic_prompt import DynamicPromptMiddleware

    req = FakeRequest(system_content="original", state={})

    received_system_content: list[str] = []

    async def handler(r):
        received_system_content.append(r.system_message.content)
        return _FakeModelResponse()

    with (
        patch(
            "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
            new=AsyncMock(return_value="catalog data"),
        ),
        patch(
            "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
            new=AsyncMock(return_value={"lunes": "10:00-20:00"}),
        ),
    ):
        mw = DynamicPromptMiddleware()
        await mw.awrap_model_call(req, handler)

    assert received_system_content[0] == "original", (
        f"DynamicPrompt must not mutate system_message; got: {received_system_content[0]!r}"
    )


# ---------------------------------------------------------------------------
# C3a: assembled prompt order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_order_of_assembled_blocks():
    """All 4 slots populated → assembled prompt contains them in order: customer → upcoming_appointments → business_hours → catalog."""
    from agent.middleware.prompt_assembly import PromptAssemblyMiddleware

    state = {
        "_slot_customer": "<customer>MARKER_CUSTOMER</customer>",
        "_slot_upcoming_appointments": "<upcoming_appointments>MARKER_APPTS</upcoming_appointments>",
        "_slot_business_hours": "<business_hours>MARKER_HOURS</business_hours>",
        "_slot_catalog": "<catalog>MARKER_CATALOG</catalog>",
    }
    req = FakeRequest(system_content="base_system", state=state)

    received_content: list[str] = []

    async def handler(r):
        received_content.append(r.system_message.content)
        return _FakeModelResponse()

    mw = PromptAssemblyMiddleware()
    await mw.awrap_model_call(req, handler)

    content = received_content[0]
    assert "base_system" in content
    assert "MARKER_CUSTOMER" in content
    assert "MARKER_APPTS" in content
    assert "MARKER_HOURS" in content
    assert "MARKER_CATALOG" in content

    # Order check
    idx_customer = content.index("MARKER_CUSTOMER")
    idx_appts = content.index("MARKER_APPTS")
    idx_hours = content.index("MARKER_HOURS")
    idx_catalog = content.index("MARKER_CATALOG")

    assert idx_customer < idx_appts < idx_hours < idx_catalog, (
        f"Blocks must appear in order customer→upcoming_appointments→business_hours→catalog. "
        f"Got positions: customer={idx_customer}, appts={idx_appts}, hours={idx_hours}, catalog={idx_catalog}"
    )


# ---------------------------------------------------------------------------
# C3b: missing slot skipped silently
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_slot_skipped_silently():
    """When _slot_upcoming_appointments is absent, assembled prompt omits it without error."""
    from agent.middleware.prompt_assembly import PromptAssemblyMiddleware

    state = {
        "_slot_customer": "<customer>CUSTOMER_BLOCK</customer>",
        # _slot_upcoming_appointments intentionally absent
        "_slot_business_hours": "<business_hours>HOURS_BLOCK</business_hours>",
        "_slot_catalog": "<catalog>CATALOG_BLOCK</catalog>",
    }
    req = FakeRequest(system_content="base", state=state)

    received_content: list[str] = []

    async def handler(r):
        received_content.append(r.system_message.content)
        return _FakeModelResponse()

    mw = PromptAssemblyMiddleware()
    await mw.awrap_model_call(req, handler)  # must not raise

    content = received_content[0]
    assert "CUSTOMER_BLOCK" in content
    assert "HOURS_BLOCK" in content
    assert "CATALOG_BLOCK" in content
    assert "<upcoming_appointments>" not in content
