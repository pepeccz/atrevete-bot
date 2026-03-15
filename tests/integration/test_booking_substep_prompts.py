"""Integration coverage for booking substep prompt overlays."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from agent.modes.booking_context import BookingSubstep
from agent.prompts.loader import build_layered_messages, clear_prompt_cache, load_markdown


@pytest.mark.parametrize(
    ("substep", "expected_snippet"),
    [
        (BookingSubstep.SERVICE_SELECTION, "Subpaso: Seleccion de Servicio"),
        (BookingSubstep.STYLIST_SELECTION, "Subpaso: Seleccion de Estilista"),
        (BookingSubstep.SLOT_SELECTION, "Subpaso: Seleccion de Horario"),
        (BookingSubstep.NOTES, "Subpaso: Notas"),
        (BookingSubstep.CONFIRMATION, "Subpaso: Confirmacion"),
        (BookingSubstep.COMPLETED, "Subpaso: Reserva Completada"),
    ],
)
@pytest.mark.asyncio
async def test_booking_substep_prompt_overlay_loads(substep: BookingSubstep, expected_snippet: str):
    """Each booking substep should load its dedicated prompt overlay."""

    clear_prompt_cache()
    state = {"user_message": "quiero seguir con mi turno"}
    mode_context = {"booking_step": substep.value, "service_name": "Cortar"}

    messages = await build_layered_messages(
        state,
        mode_context,
        include_history=False,
        mode_name="BOOKING",
        substep=substep.value,
    )

    assert len(messages) == 3
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], SystemMessage)
    assert isinstance(messages[2], HumanMessage)
    assert expected_snippet in messages[1].content


@pytest.mark.asyncio
async def test_booking_legacy_customer_data_alias_loads_notes_prompt():
    """Legacy booking step names should still resolve to the new notes prompt."""

    clear_prompt_cache()
    messages = await build_layered_messages(
        {"user_message": "no, nada mas"},
        {"booking_step": "customer_data", "service_name": "Cortar"},
        include_history=False,
        mode_name="BOOKING",
        substep="customer_data",
    )

    assert "Subpaso: Notas" in messages[1].content


@pytest.mark.asyncio
async def test_booking_substep_prompts_flag_false_uses_legacy_booking_overlay():
    """Disabling substep prompts should restore the legacy booking overlay."""

    clear_prompt_cache()
    legacy_prompt = load_markdown("booking.md", "modes")

    with patch(
        "agent.prompts.loader.get_settings",
        return_value=SimpleNamespace(USE_SUBSTEP_PROMPTS=False),
    ):
        messages = await build_layered_messages(
            {"user_message": "quiero reservar"},
            {"booking_step": BookingSubstep.SERVICE_SELECTION.value},
            include_history=False,
            mode_name="BOOKING",
            substep=BookingSubstep.SERVICE_SELECTION.value,
        )

    assert len(messages) == 3
    assert messages[1].content == legacy_prompt
    assert "Modo RESERVA" in messages[1].content


@pytest.mark.asyncio
async def test_booking_stylist_prompt_context_surfaces_recurrent_stylist_offer():
    clear_prompt_cache()
    messages = await build_layered_messages(
        {"user_message": "sigamos con el turno"},
        {
            "booking_step": BookingSubstep.STYLIST_SELECTION.value,
            "service_name": "Cortar",
            "recurrent_stylist_name": "María",
            "recurrent_stylist_slot_summary": "mañana a las 10:30",
        },
        include_history=False,
        mode_name="BOOKING",
        substep=BookingSubstep.STYLIST_SELECTION.value,
    )

    assert "Estilista habitual: María (mañana a las 10:30)" in messages[2].content
