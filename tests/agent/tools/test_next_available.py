"""Contract tests for the bounded next-available fallback tool."""

from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


def _future_date_iso(days_ahead: int = 5) -> str:
    return (date.today() + timedelta(days=days_ahead)).isoformat()


def _parse_response(raw: str) -> dict:
    return json.loads(raw)


FAKE_SERVICE_ID = uuid4()
FAKE_STYLIST_ID = uuid4()


@pytest.mark.asyncio
async def test_get_next_available_options_returns_ranked_options_payload():
    from agent.tools.next_available import get_next_available_options

    fallback_payload = {
        "options": [
            {
                "start_iso": f"{_future_date_iso(6)}T10:00:00+01:00",
                "end_iso": f"{_future_date_iso(6)}T11:00:00+01:00",
                "date_iso": _future_date_iso(6),
                "stylist_id": str(FAKE_STYLIST_ID),
                "rank_reason": "same_stylist_later_week",
            }
        ],
        "searched_until": _future_date_iso(12),
    }

    with (
        patch(
            "agent.tools.next_available.get_service_durations",
            new_callable=AsyncMock,
            return_value={FAKE_SERVICE_ID: 60},
        ),
        patch(
            "agent.tools.next_available.get_active_stylists_for_services",
            new_callable=AsyncMock,
            return_value=[FAKE_STYLIST_ID],
        ),
        patch(
            "agent.tools.next_available.get_next_available_options_service",
            new_callable=AsyncMock,
            return_value=fallback_payload,
        ),
        patch(
            "agent.tools.next_available.get_stylist_name",
            new_callable=AsyncMock,
            return_value="Marta",
        ),
        patch(
            "agent.tools.next_available.get_service_display_label_by_ids",
            new_callable=AsyncMock,
            return_value="corte de mujer",
        ),
    ):
        raw = await get_next_available_options.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "requested_date_iso": _future_date_iso(),
                "stylist_id": str(FAKE_STYLIST_ID),
                "audience": None,
                "strategy": "same_stylist_then_any",
                "max_options": 3,
                "search_days": 7,
            }
        )

    data = _parse_response(raw)
    assert data["status"] == "ok"
    assert data["payload"]["strategy"] == "same_stylist_then_any"
    assert data["payload"]["total_duration_minutes"] == 60
    assert data["payload"]["requested_date_iso"] == _future_date_iso()
    assert len(data["payload"]["options"]) == 1
    option = data["payload"]["options"][0]
    assert option["stylist_name"] == "Marta"
    assert option["service_label"] == "corte de mujer"
    assert option["rank_reason"] == "same_stylist_later_week"


@pytest.mark.asyncio
async def test_get_next_available_options_rejects_invalid_date():
    from agent.tools.next_available import get_next_available_options

    raw = await get_next_available_options.ainvoke(
        {
            "service_ids": [str(FAKE_SERVICE_ID)],
            "requested_date_iso": "2026-99-99",
            "stylist_id": None,
            "audience": None,
        }
    )

    data = _parse_response(raw)
    assert data["status"] == "rejected"
    assert data["errors"]


@pytest.mark.asyncio
async def test_get_next_available_options_returns_clamped_bounds_metadata():
    from agent.tools.next_available import get_next_available_options

    fallback_payload = {
        "options": [],
        "searched_until": _future_date_iso(12),
        "search_days": 7,
        "max_options": 3,
    }

    with (
        patch(
            "agent.tools.next_available.get_service_durations",
            new_callable=AsyncMock,
            return_value={FAKE_SERVICE_ID: 60},
        ),
        patch(
            "agent.tools.next_available.get_active_stylists_for_services",
            new_callable=AsyncMock,
            return_value=[FAKE_STYLIST_ID],
        ),
        patch(
            "agent.tools.next_available.get_next_available_options_service",
            new_callable=AsyncMock,
            return_value=fallback_payload,
        ) as mock_service,
        patch(
            "agent.tools.next_available.get_service_display_label_by_ids",
            new_callable=AsyncMock,
            return_value="corte de mujer",
        ),
    ):
        raw = await get_next_available_options.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "requested_date_iso": _future_date_iso(),
                "stylist_id": None,
                "audience": None,
                "strategy": "any_stylist",
                "max_options": 99,
                "search_days": 30,
            }
        )

    data = _parse_response(raw)
    assert data["status"] == "ok"
    assert data["payload"]["strategy"] == "any_stylist"
    _, kwargs = mock_service.await_args
    assert kwargs["strategy"] == "any_stylist"
    assert kwargs["max_options"] == 99
    assert kwargs["search_days"] == 30


@pytest.mark.asyncio
async def test_get_next_available_options_rejects_when_no_compatible_stylists_exist():
    from agent.tools.next_available import get_next_available_options

    with (
        patch(
            "agent.tools.next_available.get_service_durations",
            new_callable=AsyncMock,
            return_value={FAKE_SERVICE_ID: 60},
        ),
        patch(
            "agent.tools.next_available.get_active_stylists_for_services",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        raw = await get_next_available_options.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "requested_date_iso": _future_date_iso(),
                "stylist_id": None,
                "audience": None,
            }
        )

    data = _parse_response(raw)
    assert data["status"] == "rejected"
    assert data["errors"] == [
        "No hay estilistas activos disponibles para los servicios solicitados."
    ]
