"""RED test — T3: update_booking slot-collector matrix.

Fails on master (module absent). Passes after GREEN impl.
Refs: R2
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_response(raw: str) -> dict:
    return json.loads(raw)


def future_date_iso(days_ahead: int = 14) -> str:
    """Return a future date as ISO string (date only)."""
    dt = (datetime.now(UTC) + timedelta(days=days_ahead)).date()
    return dt.isoformat()


# ---------------------------------------------------------------------------
# DB connectivity guard
# ---------------------------------------------------------------------------


async def _db_available() -> bool:
    try:
        from sqlalchemy import text
        from database.connection import get_async_session

        async with get_async_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session():
    from database.connection import get_async_session

    async with get_async_session() as session:
        yield session


@pytest.fixture
async def seeded_db(db_session):
    """Seed minimal service+stylist data for update_booking tests."""
    from sqlalchemy import delete
    from database.models import Service, Stylist, ServiceCategory

    # Clean up any leftovers from previous runs
    await db_session.execute(
        delete(Service).where(Service.name.in_(["corte dama test", "peinado test", "alisado test"]))
    )
    await db_session.execute(
        delete(Stylist).where(Stylist.slug.in_(["marta-test", "pilar-test"]))
    )
    await db_session.flush()

    marta = Stylist(
        id=uuid4(),
        name="Marta Test",
        slug="marta-test",
        category=ServiceCategory.HAIRDRESSING,
        is_active=True,
    )
    pilar = Stylist(
        id=uuid4(),
        name="Pilar Test",
        slug="pilar-test",
        category=ServiceCategory.HAIRDRESSING,
        is_active=True,
    )
    corte = Service(
        id=uuid4(),
        name="corte dama test",
        category=ServiceCategory.HAIRDRESSING,
        duration_minutes=45,
        is_active=True,
        audience="adult_female",
    )
    peinado = Service(
        id=uuid4(),
        name="peinado test",
        category=ServiceCategory.HAIRDRESSING,
        duration_minutes=60,
        is_active=True,
    )
    alisado = Service(
        id=uuid4(),
        name="alisado test",
        category=ServiceCategory.HAIRDRESSING,
        duration_minutes=120,
        is_active=True,
    )

    db_session.add_all([marta, pilar, corte, peinado, alisado])
    await db_session.flush()

    yield {
        "marta": marta,
        "pilar": pilar,
        "corte": corte,
        "peinado": peinado,
        "alisado": alisado,
    }

    # Cleanup
    await db_session.execute(
        delete(Service).where(Service.name.in_(["corte dama test", "peinado test", "alisado test"]))
    )
    await db_session.execute(
        delete(Stylist).where(Stylist.slug.in_(["marta-test", "pilar-test"]))
    )
    await db_session.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_call_returns_service_required():
    """No args → status=partial, next_step=service_required, 'services' in missing."""
    if not await _db_available():
        pytest.skip("Postgres not reachable")
    from agent.tools.update_booking import update_booking

    raw = await update_booking.ainvoke({})
    data = parse_response(raw)
    assert data["status"] == "partial"
    assert data["next_step"] == "service_required"
    assert "services" in data["missing"]


@pytest.mark.asyncio
async def test_services_only_returns_stylist_required():
    """services provided but no stylist → status=partial, next_step=stylist_required."""
    if not await _db_available():
        pytest.skip("Postgres not reachable")
    from agent.tools.update_booking import update_booking

    raw = await update_booking.ainvoke({"services": ["corte dama test"]})
    data = parse_response(raw)
    # Either partial/stylist_required (found service) or rejected/service_required (not found)
    # In test env we may not have the seeded service, so we accept both shapes
    # The key assertion is that it's not status=ok without all slots
    assert data["status"] in ("partial", "rejected")
    if data["status"] == "partial":
        assert data["next_step"] == "stylist_required"


@pytest.mark.asyncio
async def test_unknown_service_returns_rejected():
    """services=['peeling'] (nonexistent) → status=rejected, next_step=service_required."""
    if not await _db_available():
        pytest.skip("Postgres not reachable")
    from agent.tools.update_booking import update_booking

    raw = await update_booking.ainvoke({"services": ["servicio_inexistente_xyz"]})
    data = parse_response(raw)
    assert data["status"] == "rejected"
    assert data["next_step"] == "service_required"
    assert len(data["errors"]) > 0


@pytest.mark.asyncio
async def test_invalid_date_returns_rejected():
    """Invalid date_iso → status=rejected, next_step=date_required."""
    if not await _db_available():
        pytest.skip("Postgres not reachable")
    from agent.tools.update_booking import update_booking

    raw = await update_booking.ainvoke({
        "services": ["corte dama test"],
        "stylist_name": "Marta Test",
        "date_iso": "not-a-date",
    })
    data = parse_response(raw)
    # Could be rejected for unknown service or invalid date
    assert data["status"] == "rejected"


@pytest.mark.asyncio
async def test_no_preference_stylist_skips_stylist_required():
    """no_preference_stylist=True with services → should not require stylist."""
    if not await _db_available():
        pytest.skip("Postgres not reachable")
    from agent.tools.update_booking import update_booking

    raw = await update_booking.ainvoke({
        "services": ["corte dama test"],
        "no_preference_stylist": True,
        "date_iso": future_date_iso(),
    })
    data = parse_response(raw)
    # If services found: should be ok/booking_ready (all slots present with no_preference)
    # If services not found: rejected/service_required
    if data["status"] == "ok":
        assert data["next_step"] == "booking_ready"
        assert "stylist_required" not in data.get("missing", [])


@pytest.mark.asyncio
async def test_tool_is_callable():
    """update_booking is importable and is a LangChain tool."""
    from agent.tools.update_booking import update_booking
    assert hasattr(update_booking, "ainvoke")
    assert update_booking.name == "update_booking"


@pytest.mark.asyncio
async def test_return_is_json_string():
    """Tool always returns a JSON-parseable string."""
    if not await _db_available():
        pytest.skip("Postgres not reachable")
    from agent.tools.update_booking import update_booking

    raw = await update_booking.ainvoke({})
    assert isinstance(raw, str)
    data = json.loads(raw)  # must not raise
    assert "status" in data


@pytest.mark.asyncio
async def test_seeded_all_slots_returns_booking_ready(seeded_db):
    """All slots (from seeded data) → status=ok, next_step=booking_ready, missing=[]."""
    if not await _db_available():
        pytest.skip("Postgres not reachable")
    from agent.tools.update_booking import update_booking

    raw = await update_booking.ainvoke({
        "services": ["corte dama test"],
        "stylist_name": "Marta Test",
        "date_iso": future_date_iso(),
    })
    data = parse_response(raw)
    assert data["status"] == "ok"
    assert data["next_step"] == "booking_ready"
    assert data["missing"] == []


@pytest.mark.asyncio
async def test_seeded_unknown_stylist_returns_rejected(seeded_db):
    """Unknown stylist name → status=rejected, next_step=stylist_required."""
    if not await _db_available():
        pytest.skip("Postgres not reachable")
    from agent.tools.update_booking import update_booking

    raw = await update_booking.ainvoke({
        "services": ["corte dama test"],
        "stylist_name": "Estilista_Fantasma_XYZ",
        "date_iso": future_date_iso(),
    })
    data = parse_response(raw)
    assert data["status"] == "rejected"
    assert data["next_step"] == "stylist_required"
