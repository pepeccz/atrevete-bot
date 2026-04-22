"""E2E booking flow test — Task 8.1.

Full interrupt→resume booking scenario using InMemoryCheckpointer.
All external I/O (LLM, DB, availability, book tool) is mocked.

The test verifies WIRING: that the top-level graph routes correctly
through preprocess → router → booking subgraph for all 8 turns
including the interrupt/resume at await_confirmation.
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from agent.booking.schemas import (
    AudienceResponse,
    DateResponse,
    NameResponse,
    NotesResponse,
    SlotResponse,
    StylistResponse,
)
from agent.graph import create_graph

# ── Helpers ──────────────────────────────────────────────────────────────────

THREAD_ID = "e2e-test-thread-001"
CONV_CONFIG = {"configurable": {"thread_id": THREAD_ID}}

FAKE_SERVICE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
FAKE_STYLIST_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
FAKE_APPT_ID = "appt-abc-123"

TOMORROW = date.today().isoformat()

_OFFERED_SLOTS = [
    {"start": "10:00", "end": "10:30", "stylist": "Marta", "stylist_id": str(FAKE_STYLIST_ID)},
    {"start": "11:00", "end": "11:30", "stylist": "Marta", "stylist_id": str(FAKE_STYLIST_ID)},
]


def _make_state(user_message: str, **extra):
    return {
        "conversation_id": THREAD_ID,
        "customer_phone": "+34600000001",
        "user_message": user_message,
        "pending_whatsapp_name": None,
        **extra,
    }


# Mocked LLM chain that returns scripted responses per schema type
def _make_chain_mock(response_obj):
    chain = MagicMock()
    chain.ainvoke = AsyncMock(return_value=response_obj)
    return chain


def _patch_with_structured_output(schema_to_response: dict):
    """Return a side_effect function for llm.with_structured_output(Schema)."""

    def side_effect(schema):
        response = schema_to_response.get(schema)
        if response is None:
            raise ValueError(f"Unexpected schema in with_structured_output: {schema}")
        return _make_chain_mock(response)

    return side_effect


# ── Turn-by-turn scripted LLM responses ──────────────────────────────────────

# Turn 1: "hola, quiero cortarme el pelo"
# → router detects "cortarme" keyword → booking → ask_service
# ask_service LLM response: service selected but audience not yet inferred
_T1_SERVICE = MagicMock(
    selected_service_ids=[FAKE_SERVICE_ID],
    suggested_audience=None,
    needs_clarification=False,
    message="¿Para quién es el corte? ¿Para señora, caballero o niño/a?",
)

# Turn 2: "para señora"
# → audience resolver fills audience → ask_audience fast-path → ask_stylist leaf
_T2_STYLIST = MagicMock(
    inferred_stylist_id=None,
    no_preference=False,
    message="¿Con qué estilista querés? Tenemos a Marta, Ana y Laura.",
)

# Turn 3: "con Marta" → stylist resolver fills stylist_id → ask_stylist fast-path → ask_date
_T3_DATE = MagicMock(
    inferred_date=None,
    message="¿Qué fecha preferís?",
)

# Turn 4: "mañana" → date resolver fills date → ask_date fast-path → fetch_availability (mocked) → ask_slot
_T4_SLOT = MagicMock(
    selected_slot_index=None,
    message="Tenés estos turnos disponibles:\n1. 10:00-10:30\n2. 11:00-11:30\n¿Cuál preferís?",
)

# Turn 5: "la 1" → digit resolver fills slot (index 0) → ask_slot fast-path → ask_name
_T5_NAME = MagicMock(
    first_name=None,
    first_surname=None,
    message="¿A nombre de quién hacemos la reserva?",
)

# Turn 6: "me llamo Pepe García" → name resolver fills customer_full_name → ask_name fast-path → ask_notes
_T6_NOTES = MagicMock(
    notes=None,
    user_declined=False,
    message="¿Tenés alguna nota o pedido especial? (podés decir 'no' para omitir)",
)

# Turn 7: "no, nada más" → negation/notes LLM → _notes_asked=True → await_confirmation (interrupt)
_T7_NOTES_DECLINED = MagicMock(
    notes=None,
    user_declined=True,
    message="Entendido, sin notas especiales.",
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def checkpointer():
    return MemorySaver()


@pytest.fixture()
def mock_llm():
    """Mock LLM with with_structured_output that returns scripted responses per schema."""
    from agent.booking.schemas import (
        ServiceSelectionResponse,
    )

    schema_map = {
        ServiceSelectionResponse: _T1_SERVICE,
        AudienceResponse: _T2_STYLIST,  # After audience resolver fills it, ask_audience fast-paths to ask_stylist
        StylistResponse: _T2_STYLIST,
        DateResponse: _T3_DATE,
        SlotResponse: _T4_SLOT,
        NameResponse: _T5_NAME,
        NotesResponse: _T7_NOTES_DECLINED,
    }

    llm = MagicMock()
    llm.with_structured_output = MagicMock(side_effect=_patch_with_structured_output(schema_map))

    # For general node (create_agent path): bind_tools returns bound model with async ainvoke
    bound = MagicMock()
    bound.ainvoke = AsyncMock(return_value=AIMessage(content="Respuesta genérica."))
    llm.bind_tools = MagicMock(return_value=bound)
    llm.ainvoke = AsyncMock(return_value=AIMessage(content="Respuesta genérica."))
    return llm


@pytest.fixture()
def graph(checkpointer, mock_llm):
    """Build graph with MemorySaver and mocked LLM factory."""
    with (
        patch(
            "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
            new=AsyncMock(return_value="catalog"),
        ),
        patch(
            "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
            new=AsyncMock(return_value={}),
        ),
        patch("agent.nodes.preprocess.get_async_session"),
        patch("agent.nodes.preprocess.Customer"),
    ):
        g = create_graph(checkpointer=checkpointer, llm_factory=lambda: mock_llm)
    return g


# ── Stylist fixture for resolver ─────────────────────────────────────────────

_FAKE_STYLISTS = [
    {"id": str(FAKE_STYLIST_ID), "name": "Marta"},
]


@pytest.fixture(autouse=True)
def patch_resolvers():
    """Patch resolvers that hit DB/external."""
    with (
        patch(
            "agent.booking.prompt_builder.build_catalog_prompt_section",
            new=AsyncMock(return_value="Corte de cabello — 30min"),
        ),
        patch(
            "agent.booking.prompt_builder.load_business_hours_snapshot",
            new=AsyncMock(return_value={"lunes": "09:00-18:00"}),
        ),
        patch(
            "agent.booking.resolvers.stylist._load_active_stylists",
            new=AsyncMock(return_value=_FAKE_STYLISTS),
        ),
        patch(
            "agent.booking.actions.check_availability_tool",
            new=AsyncMock(
                return_value='{"status":"ok","payload":{"slots":[{"start":"10:00","end":"10:30","stylist":"Marta"},{"start":"11:00","end":"11:30","stylist":"Marta"}]},"errors":[],"next_step":null}'
            ),
        ),
        patch(
            "agent.booking.actions.book_tool",
            new=AsyncMock(
                return_value=f'{{"status":"ok","payload":{{"appointment_id":"{FAKE_APPT_ID}"}},"errors":[],"next_step":null}}'
            ),
        ),
    ):
        yield


# ── Test ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_booking_interrupt_resume(graph):
    """Full booking scenario: 7 turns to interrupt + Turn 8 resume confirmation."""
    # ── Turn 1: user wants a haircut ─────────────────────────────────────────
    state1 = _make_state("hola, quiero cortarme el pelo")
    with patch("agent.nodes.preprocess.get_async_session"):
        result1 = await graph.ainvoke(state1, config=CONV_CONFIG)

    msgs1 = result1.get("messages", [])
    assert len(msgs1) > 0, "Turn 1 must produce messages"
    last1 = msgs1[-1]
    last1_content = last1.content if hasattr(last1, "content") else last1.get("content", "")
    assert (
        "señora" in last1_content or "quién" in last1_content or "corte" in last1_content
    ), f"Turn 1: expected audience-related question, got: {last1_content!r}"

    # ── Turn 2: audience ─────────────────────────────────────────────────────
    state2 = _make_state("para señora")
    result2 = await graph.ainvoke(state2, config=CONV_CONFIG)
    msgs2 = result2.get("messages", [])
    assert len(msgs2) > len(msgs1), "Turn 2 must grow message list"

    # ── Turn 3: stylist ───────────────────────────────────────────────────────
    state3 = _make_state("con Marta")
    result3 = await graph.ainvoke(state3, config=CONV_CONFIG)
    msgs3 = result3.get("messages", [])
    assert len(msgs3) > len(msgs2), "Turn 3 must grow message list"

    # ── Turn 4: date ──────────────────────────────────────────────────────────
    state4 = _make_state("mañana")
    result4 = await graph.ainvoke(state4, config=CONV_CONFIG)
    msgs4 = result4.get("messages", [])
    assert len(msgs4) > len(msgs3), "Turn 4 must grow message list"

    # ── Turn 5: slot selection ("la 1" → digit resolver → index 0) ───────────
    state5 = _make_state("la 1")
    result5 = await graph.ainvoke(state5, config=CONV_CONFIG)
    msgs5 = result5.get("messages", [])
    assert len(msgs5) > len(msgs4), "Turn 5 must grow message list"

    # ── Turn 6: name ──────────────────────────────────────────────────────────
    state6 = _make_state("me llamo Pepe García")
    result6 = await graph.ainvoke(state6, config=CONV_CONFIG)
    msgs6 = result6.get("messages", [])
    assert len(msgs6) > len(msgs5), "Turn 6 must grow message list"

    # ── Turn 7: notes declined → await_confirmation (interrupt) ──────────────
    state7 = _make_state("no, nada más")
    # Graph should interrupt here — result contains interrupt info
    from langgraph.errors import GraphInterrupt

    try:
        result7 = await graph.ainvoke(state7, config=CONV_CONFIG)
        # If no interrupt raised, check that the graph state has booking.step == "confirm"
        snapshot7 = await graph.aget_state(CONV_CONFIG)
        assert snapshot7.next, "Graph should be interrupted waiting for confirmation"
    except GraphInterrupt:
        pass  # Expected: graph paused at await_confirmation

    # ── Turn 8: resume with "sí" ──────────────────────────────────────────────
    from langgraph.types import Command

    result8 = await graph.ainvoke(Command(resume="sí"), config=CONV_CONFIG)

    final_booking = result8.get("booking") or {}
    assert (
        final_booking.get("step") == "done"
    ), f"After resume+confirm: expected step='done', got: {final_booking.get('step')!r}"
    assert (
        final_booking.get("appointment_id") == FAKE_APPT_ID
    ), f"appointment_id should be {FAKE_APPT_ID!r}, got: {final_booking.get('appointment_id')!r}"
    msgs8 = result8.get("messages", [])
    assert len(msgs8) > len(msgs6), "Turn 8 must add at least one message"
