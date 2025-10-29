"""
Unit tests for pack suggestion nodes (Story 3.4).

Tests cover:
- Pack query and selection logic
- Savings calculation accuracy
- Pack suggestion formatting
- Customer response handling (accept/decline/unclear)
- Edge cases (no packs, multiple packs, tie-breaking)
"""

import pytest
from decimal import Decimal
from uuid import uuid4
from unittest.mock import AsyncMock, Mock, patch

from agent.nodes.pack_suggestion_nodes import (
    calculate_pack_savings,
    select_best_pack,
    format_pack_suggestion,
    suggest_pack,
    handle_pack_response,
)
from agent.state.schemas import ConversationState
from database.models import Pack, Service


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_service_mechas():
    """Mock MECHAS service."""
    return Service(
        id=uuid4(),
        name="MECHAS",
        category="Hairdressing",
        duration_minutes=120,
        price_euros=Decimal("60.00"),
        is_active=True,
    )


@pytest.fixture
def mock_service_corte():
    """Mock Corte service."""
    return Service(
        id=uuid4(),
        name="Corte",
        category="Hairdressing",
        duration_minutes=60,
        price_euros=Decimal("25.00"),
        is_active=True,
    )


@pytest.fixture
def mock_pack_mechas_corte(mock_service_mechas, mock_service_corte):
    """Mock Mechas + Corte pack."""
    return Pack(
        id=uuid4(),
        name="Mechas + Corte",
        included_service_ids=[mock_service_mechas.id, mock_service_corte.id],
        duration_minutes=60,
        price_euros=Decimal("80.00"),
        description="Pack ahorro mechas con corte",
        is_active=True,
    )


@pytest.fixture
def mock_pack_premium(mock_service_mechas, mock_service_corte):
    """Mock premium pack with higher savings."""
    return Pack(
        id=uuid4(),
        name="Pack Premium",
        included_service_ids=[mock_service_mechas.id, mock_service_corte.id],
        duration_minutes=90,
        price_euros=Decimal("75.00"),  # Better savings than mechas_corte
        description="Pack premium con más ahorro",
        is_active=True,
    )


@pytest.fixture
def mock_pack_express(mock_service_mechas, mock_service_corte):
    """Mock express pack with same savings as premium but shorter duration."""
    return Pack(
        id=uuid4(),
        name="Pack Express",
        included_service_ids=[mock_service_mechas.id, mock_service_corte.id],
        duration_minutes=45,  # Shorter than premium
        price_euros=Decimal("75.00"),  # Same savings as premium
        description="Pack express rápido",
        is_active=True,
    )


# ============================================================================
# Test calculate_pack_savings
# ============================================================================


def test_calculate_pack_savings_accurate(mock_pack_mechas_corte, mock_service_mechas, mock_service_corte):
    """Test savings calculation accuracy with Decimal precision."""
    individual_total = Decimal("85.00")  # MECHAS (60) + Corte (25)
    service_ids = [mock_service_mechas.id, mock_service_corte.id]

    result = calculate_pack_savings(mock_pack_mechas_corte, service_ids, individual_total)

    assert result["pack"] == mock_pack_mechas_corte
    assert result["individual_total"] == Decimal("85.00")
    assert result["pack_price"] == Decimal("80.00")
    assert result["savings_amount"] == Decimal("5.00")
    assert result["savings_percentage"] == pytest.approx(5.88, rel=0.01)
    assert result["duration"] == 60


def test_calculate_pack_savings_no_savings(mock_service_mechas, mock_service_corte):
    """Test pack with no savings (same price as individual)."""
    # Create pack with same price as individual total
    no_savings_pack = Pack(
        id=uuid4(),
        name="Pack Sin Ahorro",
        included_service_ids=[mock_service_mechas.id, mock_service_corte.id],
        duration_minutes=60,
        price_euros=Decimal("85.00"),  # Same as individual
        is_active=True,
    )

    individual_total = Decimal("85.00")
    service_ids = [mock_service_mechas.id, mock_service_corte.id]

    result = calculate_pack_savings(no_savings_pack, service_ids, individual_total)

    assert result["savings_amount"] == Decimal("0.00")
    assert result["savings_percentage"] == 0.0


def test_calculate_pack_savings_negative(mock_service_mechas, mock_service_corte):
    """Test pack more expensive than individual (negative savings)."""
    expensive_pack = Pack(
        id=uuid4(),
        name="Pack Caro",
        included_service_ids=[mock_service_mechas.id, mock_service_corte.id],
        duration_minutes=60,
        price_euros=Decimal("90.00"),  # More expensive than individual
        is_active=True,
    )

    individual_total = Decimal("85.00")
    service_ids = [mock_service_mechas.id, mock_service_corte.id]

    result = calculate_pack_savings(expensive_pack, service_ids, individual_total)

    assert result["savings_amount"] == Decimal("-5.00")
    assert result["savings_percentage"] < 0


# ============================================================================
# Test select_best_pack
# ============================================================================


def test_select_best_pack_single_pack(mock_pack_mechas_corte, mock_service_mechas, mock_service_corte):
    """Test selection with single pack available."""
    packs = [mock_pack_mechas_corte]
    individual_total = Decimal("85.00")
    service_ids = [mock_service_mechas.id, mock_service_corte.id]

    result = select_best_pack(packs, service_ids, individual_total)

    assert result is not None
    assert result["pack"] == mock_pack_mechas_corte
    assert result["savings_amount"] == Decimal("5.00")


def test_select_best_pack_multiple_highest_savings(
    mock_pack_mechas_corte, mock_pack_premium, mock_service_mechas, mock_service_corte
):
    """Test selection of pack with highest savings percentage."""
    packs = [mock_pack_mechas_corte, mock_pack_premium]
    individual_total = Decimal("85.00")
    service_ids = [mock_service_mechas.id, mock_service_corte.id]

    result = select_best_pack(packs, service_ids, individual_total)

    # Premium pack has better savings (75€ vs 80€)
    assert result["pack"] == mock_pack_premium
    assert result["savings_amount"] == Decimal("10.00")
    assert result["savings_percentage"] == pytest.approx(11.76, rel=0.01)


def test_select_best_pack_tie_breaker_shorter_duration(
    mock_pack_premium, mock_pack_express, mock_service_mechas, mock_service_corte
):
    """Test tie-breaker: when savings are equal, select shorter duration."""
    # Both packs have same price (75€) but different durations
    packs = [mock_pack_premium, mock_pack_express]
    individual_total = Decimal("85.00")
    service_ids = [mock_service_mechas.id, mock_service_corte.id]

    result = select_best_pack(packs, service_ids, individual_total)

    # Express pack should win due to shorter duration (45min vs 90min)
    assert result["pack"] == mock_pack_express
    assert result["duration"] == 45


def test_select_best_pack_empty_list():
    """Test selection with no packs available."""
    packs = []
    individual_total = Decimal("85.00")
    service_ids = [uuid4()]

    result = select_best_pack(packs, service_ids, individual_total)

    assert result is None


# ============================================================================
# Test format_pack_suggestion
# ============================================================================


def test_format_pack_suggestion_single_service(mock_pack_mechas_corte):
    """Test formatting for single service suggestion."""
    suggested_pack = {
        "pack": mock_pack_mechas_corte,
        "pack_price": Decimal("80.00"),
        "savings_amount": Decimal("5.00"),
        "duration": 60,
    }

    individual_service_info = "MECHAS tiene un precio de 60€ y una duración de 120 minutos"
    service_names = ["MECHAS"]

    result = format_pack_suggestion(suggested_pack, service_names, individual_service_info)

    # Verify all required elements are present
    assert "MECHAS tiene un precio de 60€" in result
    assert "mechas + corte" in result.lower()
    assert "80" in result and "€" in result  # Accept 80€ or 80.00€
    assert "60 minutos" in result
    assert "ahorras" in result.lower() and "5" in result  # Accept 5€ or 5.00€
    assert "¿Quieres que te reserve ese pack?" in result


def test_format_pack_suggestion_format_matches_scenario(mock_pack_mechas_corte):
    """Test that format matches Scenario 1 template."""
    suggested_pack = {
        "pack": mock_pack_mechas_corte,
        "pack_price": Decimal("80.00"),
        "savings_amount": Decimal("5.00"),
        "duration": 60,
    }

    individual_service_info = "Las mechas tienen un precio de 60€ y una duración de 120 minutos"
    service_names = ["Las mechas"]

    result = format_pack_suggestion(suggested_pack, service_names, individual_service_info)

    # Should follow pattern: {individual info} **pero también contamos con** {pack} **por {price}€**...
    assert "**pero también contamos con**" in result
    assert "**por 80€**" in result or "**por 80.00€**" in result
    assert "**y con el que además ahorras" in result


# ============================================================================
# Test suggest_pack node
# ============================================================================


@pytest.mark.asyncio
async def test_suggest_pack_single_service_pack_found(
    mock_pack_mechas_corte, mock_service_mechas, mock_service_corte
):
    """Test suggest_pack with single service finding a pack."""
    state = ConversationState(
        conversation_id="test-123",
        customer_phone="+34612345678",
        customer_name="Laura",
        messages=[],
        requested_services=[mock_service_mechas.id],
        metadata={},
    )

    # Mock tool functions
    with patch("agent.nodes.pack_suggestion_nodes.get_packs_containing_service") as mock_get_packs:
        with patch("agent.nodes.pack_suggestion_nodes.calculate_total") as mock_calc_total:
            mock_get_packs.return_value = [mock_pack_mechas_corte]
            mock_calc_total.return_value = {
                "total_price": Decimal("85.00"),
                "total_duration": 180,
                "services": [mock_service_mechas, mock_service_corte],
            }

            result = await suggest_pack(state)

            # Verify pack was suggested
            assert result["matching_packs"] == [mock_pack_mechas_corte]
            assert result["suggested_pack"] is not None
            assert result["suggested_pack"]["pack"] == mock_pack_mechas_corte
            assert result["bot_response"] is not None
            assert "80" in result["bot_response"] and "€" in result["bot_response"]  # Accept 80€ or 80.00€


@pytest.mark.asyncio
async def test_suggest_pack_no_packs_found(mock_service_mechas):
    """Test suggest_pack when no packs contain the service."""
    state = ConversationState(
        conversation_id="test-456",
        customer_phone="+34612345678",
        customer_name="Laura",
        messages=[],
        requested_services=[mock_service_mechas.id],
        metadata={},
    )

    with patch("agent.nodes.pack_suggestion_nodes.get_packs_containing_service") as mock_get_packs:
        mock_get_packs.return_value = []

        result = await suggest_pack(state)

        # Verify no pack suggested
        assert result["matching_packs"] == []
        assert result["suggested_pack"] is None
        assert result["bot_response"] is None


@pytest.mark.asyncio
async def test_suggest_pack_multiple_services(
    mock_pack_mechas_corte, mock_service_mechas, mock_service_corte
):
    """Test suggest_pack with multiple services."""
    state = ConversationState(
        conversation_id="test-789",
        customer_phone="+34612345678",
        customer_name="Laura",
        messages=[],
        requested_services=[mock_service_mechas.id, mock_service_corte.id],
        metadata={},
    )

    with patch("agent.nodes.pack_suggestion_nodes.get_packs_for_multiple_services") as mock_get_packs:
        with patch("agent.nodes.pack_suggestion_nodes.calculate_total") as mock_calc_total:
            mock_get_packs.return_value = [mock_pack_mechas_corte]
            mock_calc_total.return_value = {
                "total_price": Decimal("85.00"),
                "total_duration": 180,
                "services": [mock_service_mechas, mock_service_corte],
            }

            result = await suggest_pack(state)

            # Verify correct query function was called
            mock_get_packs.assert_called_once_with([mock_service_mechas.id, mock_service_corte.id])
            assert result["suggested_pack"] is not None


@pytest.mark.asyncio
async def test_suggest_pack_no_requested_services():
    """Test suggest_pack with empty requested_services."""
    state = ConversationState(
        conversation_id="test-empty",
        customer_phone="+34612345678",
        customer_name="Laura",
        messages=[],
        requested_services=[],
        metadata={},
    )

    result = await suggest_pack(state)

    # Should return early with no suggestion
    assert result["matching_packs"] == []
    assert result["suggested_pack"] is None


# ============================================================================
# Test handle_pack_response node
# ============================================================================


@pytest.mark.asyncio
async def test_handle_pack_response_accept(mock_pack_mechas_corte):
    """Test handling pack acceptance."""
    from langchain_core.messages import HumanMessage, AIMessage

    suggested_pack = {
        "pack": mock_pack_mechas_corte,
        "pack_price": Decimal("80.00"),
        "savings_amount": Decimal("5.00"),
        "duration": 60,
    }

    state = ConversationState(
        conversation_id="test-accept",
        customer_phone="+34612345678",
        customer_name="Laura",
        messages=[
            AIMessage(content="Pack suggestion..."),
            HumanMessage(content="Sí, el pack"),
        ],
        suggested_pack=suggested_pack,
        metadata={},
    )

    with patch("agent.nodes.pack_suggestion_nodes.get_llm") as mock_get_llm:
        # Mock LLM to classify as "accept"
        mock_llm = Mock()
        mock_response = Mock()
        mock_response.content = "accept"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm

        result = await handle_pack_response(state)

        # Verify pack was accepted
        assert result["pack_id"] == mock_pack_mechas_corte.id
        assert result["requested_services"] == mock_pack_mechas_corte.included_service_ids
        assert result["total_price"] == Decimal("80.00")
        assert result["total_duration"] == 60
        assert "perfecto" in result["bot_response"].lower()


@pytest.mark.asyncio
async def test_handle_pack_response_decline(mock_pack_mechas_corte):
    """Test handling pack decline."""
    from langchain_core.messages import HumanMessage, AIMessage

    suggested_pack = {
        "pack": mock_pack_mechas_corte,
        "pack_price": Decimal("80.00"),
        "savings_amount": Decimal("5.00"),
        "duration": 60,
    }

    state = ConversationState(
        conversation_id="test-decline",
        customer_phone="+34612345678",
        customer_name="Laura",
        messages=[
            AIMessage(content="Pack suggestion..."),
            HumanMessage(content="No, solo las mechas"),
        ],
        suggested_pack=suggested_pack,
        metadata={},
    )

    with patch("agent.nodes.pack_suggestion_nodes.get_llm") as mock_get_llm:
        # Mock LLM to classify as "decline"
        mock_llm = Mock()
        mock_response = Mock()
        mock_response.content = "decline"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm

        result = await handle_pack_response(state)

        # Verify pack was declined
        assert result["pack_declined"] is True
        assert "entendido" in result["bot_response"].lower()


@pytest.mark.asyncio
async def test_handle_pack_response_unclear(mock_pack_mechas_corte):
    """Test handling unclear response with clarification."""
    from langchain_core.messages import HumanMessage, AIMessage

    suggested_pack = {
        "pack": mock_pack_mechas_corte,
        "pack_price": Decimal("80.00"),
        "savings_amount": Decimal("5.00"),
        "duration": 60,
    }

    state = ConversationState(
        conversation_id="test-unclear",
        customer_phone="+34612345678",
        customer_name="Laura",
        messages=[
            AIMessage(content="Pack suggestion..."),
            HumanMessage(content="Hmm, no sé..."),
        ],
        suggested_pack=suggested_pack,
        clarification_attempts=0,
        metadata={},
    )

    with patch("agent.nodes.pack_suggestion_nodes.get_llm") as mock_get_llm:
        # Mock LLM to classify as "unclear"
        mock_llm = Mock()
        mock_response = Mock()
        mock_response.content = "unclear"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm

        result = await handle_pack_response(state)

        # Verify clarification was requested
        assert result["clarification_attempts"] == 1
        assert "prefieres" in result["bot_response"].lower()


@pytest.mark.asyncio
async def test_handle_pack_response_max_clarification_attempts(mock_pack_mechas_corte):
    """Test that after max clarification attempts, pack is declined."""
    from langchain_core.messages import HumanMessage, AIMessage

    suggested_pack = {
        "pack": mock_pack_mechas_corte,
        "pack_price": Decimal("80.00"),
        "savings_amount": Decimal("5.00"),
        "duration": 60,
    }

    state = ConversationState(
        conversation_id="test-max-clarify",
        customer_phone="+34612345678",
        customer_name="Laura",
        messages=[
            AIMessage(content="Pack suggestion..."),
            HumanMessage(content="No entiendo..."),
        ],
        suggested_pack=suggested_pack,
        clarification_attempts=1,  # Already tried once
        metadata={},
    )

    with patch("agent.nodes.pack_suggestion_nodes.get_llm") as mock_get_llm:
        # Mock LLM to classify as "unclear" again
        mock_llm = Mock()
        mock_response = Mock()
        mock_response.content = "unclear"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm

        result = await handle_pack_response(state)

        # Should assume decline after 2 attempts
        assert result["pack_declined"] is True
        assert result["clarification_attempts"] == 2
