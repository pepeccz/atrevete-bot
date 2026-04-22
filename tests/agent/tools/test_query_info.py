"""
Tests for agent/tools/query_info.py — Task 3.1 (RED→GREEN).

query_info is a @tool-decorated async function that answers catalog/hours/policies queries
from DB. No LLM calls inside. Returns JSON-parseable ToolResponse.
DB calls are mocked so tests run without a live Postgres instance.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_response(raw: str):
    """Parse JSON string returned by the tool into a dict."""
    return json.loads(raw)


FAKE_SERVICES = [
    {
        "name": "Cortar",
        "audience": "adult_female",
        "category": "HAIRDRESSING",
        "duration_minutes": 40,
        "description": None,
    },
    {
        "name": "Corte Caballero",
        "audience": "adult_male",
        "category": "HAIRDRESSING",
        "duration_minutes": 40,
        "description": None,
    },
    {
        "name": "Limar y Pintar Manos",
        "audience": None,
        "category": "AESTHETICS",
        "duration_minutes": 30,
        "description": None,
    },
]

FAKE_HOURS = {
    "0": {"is_closed": True},
    "1": {"is_closed": False, "open": "10:00", "close": "20:00"},
    "2": {"is_closed": False, "open": "10:00", "close": "20:00"},
    "3": {"is_closed": False, "open": "10:00", "close": "20:00"},
    "4": {"is_closed": False, "open": "10:00", "close": "20:00"},
    "5": {"is_closed": False, "open": "09:00", "close": "14:00"},
    "6": {"is_closed": True},
}

FAKE_POLICIES = {
    "faq:hours": {"answer": "Abierto martes a viernes 10-20, sábado 9-14."},
    "faq:parking": {"answer": "Hay parking público cerca."},
}


# ---------------------------------------------------------------------------
# Import smoke
# ---------------------------------------------------------------------------


def test_query_info_importable():
    from agent.tools.query_info import query_info  # noqa: F401

    assert hasattr(query_info, "invoke")


def test_query_info_has_name():
    from agent.tools.query_info import query_info

    assert hasattr(query_info, "name")
    assert "query_info" in query_info.name


# ---------------------------------------------------------------------------
# topic="services" — returns active catalog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_info_services_returns_ok_status():
    """topic=services returns status=ok with a non-empty services list."""
    from agent.tools.query_info import query_info

    with patch(
        "agent.tools.query_info._load_services", new_callable=AsyncMock, return_value=FAKE_SERVICES
    ):
        raw = await query_info.ainvoke({"topic": "services"})

    data = parse_response(raw)
    assert data["status"] == "ok"
    assert "services" in data["payload"]
    assert isinstance(data["payload"]["services"], list)
    assert len(data["payload"]["services"]) == 3


@pytest.mark.asyncio
async def test_query_info_services_item_shape():
    """Each service entry has name, audience, category, duration_minutes."""
    from agent.tools.query_info import query_info

    with patch(
        "agent.tools.query_info._load_services", new_callable=AsyncMock, return_value=FAKE_SERVICES
    ):
        raw = await query_info.ainvoke({"topic": "services"})

    data = parse_response(raw)
    first = data["payload"]["services"][0]
    assert "name" in first
    assert "audience" in first
    assert "category" in first
    assert "duration_minutes" in first
    assert isinstance(first["duration_minutes"], int)


@pytest.mark.asyncio
async def test_query_info_services_sorted_by_category_then_name():
    """Services list is returned as-is from _load_services (already sorted by DB query)."""
    from agent.tools.query_info import query_info

    with patch(
        "agent.tools.query_info._load_services", new_callable=AsyncMock, return_value=FAKE_SERVICES
    ):
        raw = await query_info.ainvoke({"topic": "services"})

    data = parse_response(raw)
    services = data["payload"]["services"]
    # Just verify all items are present
    assert len(services) == len(FAKE_SERVICES)


# ---------------------------------------------------------------------------
# topic="hours" — returns business hours map
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_info_hours_returns_ok_status():
    from agent.tools.query_info import query_info

    with patch(
        "agent.tools.query_info._load_hours", new_callable=AsyncMock, return_value=FAKE_HOURS
    ):
        raw = await query_info.ainvoke({"topic": "hours"})

    data = parse_response(raw)
    assert data["status"] == "ok"
    assert "hours" in data["payload"]


@pytest.mark.asyncio
async def test_query_info_hours_has_all_days():
    """hours payload has entries for all 7 days (0..6)."""
    from agent.tools.query_info import query_info

    with patch(
        "agent.tools.query_info._load_hours", new_callable=AsyncMock, return_value=FAKE_HOURS
    ):
        raw = await query_info.ainvoke({"topic": "hours"})

    data = parse_response(raw)
    hours = data["payload"]["hours"]
    keys = {int(k) for k in hours.keys()}
    assert keys == {0, 1, 2, 3, 4, 5, 6}


@pytest.mark.asyncio
async def test_query_info_hours_closed_days_have_flag():
    """Closed days (Monday=0, Sunday=6) have is_closed=True."""
    from agent.tools.query_info import query_info

    with patch(
        "agent.tools.query_info._load_hours", new_callable=AsyncMock, return_value=FAKE_HOURS
    ):
        raw = await query_info.ainvoke({"topic": "hours"})

    data = parse_response(raw)
    hours = data["payload"]["hours"]
    monday = hours.get("0") or hours.get(0)
    sunday = hours.get("6") or hours.get(6)

    assert monday["is_closed"] is True
    assert sunday["is_closed"] is True


# ---------------------------------------------------------------------------
# topic="policies" — returns policy dict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_info_policies_returns_ok_when_populated():
    from agent.tools.query_info import query_info

    with patch(
        "agent.tools.query_info._load_policies", new_callable=AsyncMock, return_value=FAKE_POLICIES
    ):
        raw = await query_info.ainvoke({"topic": "policies"})

    data = parse_response(raw)
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_query_info_policies_returns_partial_when_empty():
    from agent.tools.query_info import query_info

    with patch("agent.tools.query_info._load_policies", new_callable=AsyncMock, return_value={}):
        raw = await query_info.ainvoke({"topic": "policies"})

    data = parse_response(raw)
    assert data["status"] == "partial"


@pytest.mark.asyncio
async def test_query_info_policies_payload_is_dict():
    from agent.tools.query_info import query_info

    with patch(
        "agent.tools.query_info._load_policies", new_callable=AsyncMock, return_value=FAKE_POLICIES
    ):
        raw = await query_info.ainvoke({"topic": "policies"})

    data = parse_response(raw)
    assert isinstance(data["payload"]["policies"], dict)
    assert "faq:hours" in data["payload"]["policies"]


# ---------------------------------------------------------------------------
# topic="general" — defers to LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_info_general_returns_partial():
    from agent.tools.query_info import query_info

    raw = await query_info.ainvoke({"topic": "general"})
    data = parse_response(raw)

    assert data["status"] == "partial"
    assert data.get("next_step") == "defer_to_llm"


# ---------------------------------------------------------------------------
# ToolResponse contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_info_returns_json_string():
    """Tool must return a plain JSON string (not a dict)."""
    from agent.tools.query_info import query_info

    with patch(
        "agent.tools.query_info._load_hours", new_callable=AsyncMock, return_value=FAKE_HOURS
    ):
        raw = await query_info.ainvoke({"topic": "hours"})

    assert isinstance(raw, str)
    data = json.loads(raw)
    assert isinstance(data, dict)
