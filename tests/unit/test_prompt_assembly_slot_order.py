"""T7 — PromptAssemblyMiddleware _slot_availability position.

Tests spec R1.6 / ADR-1.
_slot_availability must appear AFTER _slot_business_hours and BEFORE _slot_catalog.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, SystemMessage


class FakeRequest:
    def __init__(self, state=None, system_content="base"):
        self._state = dict(state or {})
        self.system_message = SystemMessage(content=system_content)

    @property
    def state(self):
        return self._state

    def override(self, **kwargs):
        new = FakeRequest(state=kwargs.get("state", self._state))
        new.system_message = kwargs.get("system_message", self.system_message)
        return new


class FakeModelResponse:
    def __init__(self):
        self.result = [AIMessage(content="ok")]
        self.structured_response = None


@pytest.mark.asyncio
async def test_availability_slot_between_business_hours_and_catalog():
    """<availability> block must appear after <business_hours> and before <catalog>."""
    from agent.middleware.prompt_assembly import PromptAssemblyMiddleware

    state = {
        "_slot_today": "<today>TODAY</today>",
        "_slot_customer": "<customer>CUSTOMER</customer>",
        "_slot_upcoming_appointments": "<upcoming_appointments>APPTS</upcoming_appointments>",
        "_slot_business_hours": "<business_hours>HOURS</business_hours>",
        "_slot_availability": "<availability>AVAIL</availability>",
        "_slot_catalog": "<catalog>CATALOG</catalog>",
    }
    req = FakeRequest(state=state)

    received_content: list[str] = []

    async def handler(r):
        received_content.append(r.system_message.content)
        return FakeModelResponse()

    mw = PromptAssemblyMiddleware()
    await mw.awrap_model_call(req, handler)

    content = received_content[0]
    idx_hours = content.index("HOURS")
    idx_avail = content.index("AVAIL")
    idx_catalog = content.index("CATALOG")

    assert idx_hours < idx_avail < idx_catalog, (
        f"Expected HOURS < AVAIL < CATALOG. "
        f"Got: hours={idx_hours}, avail={idx_avail}, catalog={idx_catalog}"
    )


@pytest.mark.asyncio
async def test_availability_slot_absent_when_not_set():
    """Missing _slot_availability → <availability> tag absent from assembled prompt."""
    from agent.middleware.prompt_assembly import PromptAssemblyMiddleware

    state = {
        "_slot_business_hours": "<business_hours>HOURS</business_hours>",
        "_slot_catalog": "<catalog>CATALOG</catalog>",
        # _slot_availability intentionally absent
    }
    req = FakeRequest(state=state)

    received_content: list[str] = []

    async def handler(r):
        received_content.append(r.system_message.content)
        return FakeModelResponse()

    mw = PromptAssemblyMiddleware()
    await mw.awrap_model_call(req, handler)

    content = received_content[0]
    assert "<availability>" not in content
    assert "HOURS" in content
    assert "CATALOG" in content
