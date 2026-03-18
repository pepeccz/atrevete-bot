from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.booking_mode import BookingMode
from agent.state.schemas import create_initial_state


def _make_mode() -> BookingMode:
    llm = AsyncMock()
    llm.bind_tools.return_value = llm
    return BookingMode(tools=[], llm_client=llm)


@pytest.mark.asyncio
async def test_create_customer_if_needed_calls_manage_customer_for_new_customer() -> None:
    mode = _make_mode()
    state = create_initial_state("conv-booking-create", "+34600000003")
    state["customer_phone"] = "+34600000003"
    state["customer_id"] = None

    manage_customer = MagicMock()
    manage_customer.ainvoke = AsyncMock(return_value={"id": "uuid-123"})

    with patch("agent.tools.customer_tools.manage_customer", new=manage_customer):
        customer_id = await mode._create_customer_if_needed(state, "Ana")

    assert customer_id == "uuid-123"
    manage_customer.ainvoke.assert_awaited_once_with(
        {
            "action": "create",
            "phone": "+34600000003",
            "data": {"first_name": "Ana"},
        }
    )


@pytest.mark.asyncio
async def test_create_customer_if_needed_skips_when_customer_id_already_exists() -> None:
    mode = _make_mode()
    state = create_initial_state("conv-booking-existing", "+34600000004")
    state["customer_phone"] = "+34600000004"
    state["customer_id"] = "existing-uuid"

    manage_customer = MagicMock()
    manage_customer.ainvoke = AsyncMock()

    with patch("agent.tools.customer_tools.manage_customer", new=manage_customer):
        customer_id = await mode._create_customer_if_needed(state, "Ana")

    assert customer_id == "existing-uuid"
    manage_customer.ainvoke.assert_not_awaited()
