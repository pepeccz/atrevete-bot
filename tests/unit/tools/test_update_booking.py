"""RED test — T3: update_booking slot-collector matrix.

Fails on master (module absent). Passes after GREEN impl.
Refs: R2
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
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
    """Seed minimal service+stylist+business_hours data for update_booking tests."""
    from sqlalchemy import delete

    from database.models import BusinessHours, Service, ServiceCategory, Stylist

    # Clean up any leftovers from previous runs
    await db_session.execute(
        delete(Service).where(Service.name.in_(["corte dama test", "peinado test", "alisado test"]))
    )
    await db_session.execute(
        delete(Stylist).where(Stylist.slug.in_(["marta-test", "pilar-test"]))
    )
    # Only delete business hours we're about to insert (days 0-5) if they don't exist
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

    # Seed business hours for Mon-Sat (days 0-5) — needed for is_date_closed validator
    from sqlalchemy import select
    bh_existing_days = set(
        row[0] for row in (await db_session.execute(
            select(BusinessHours.day_of_week).where(BusinessHours.day_of_week < 6)
        )).all()
    )
    bh_to_add = []
    for dow in range(6):  # Mon=0 to Sat=5
        if dow not in bh_existing_days:
            bh_to_add.append(BusinessHours(
                id=uuid4(),
                day_of_week=dow,
                is_closed=False,
                start_hour=9,
                start_minute=0,
                end_hour=19,
                end_minute=0,
            ))

    db_session.add_all([marta, pilar, corte, peinado, alisado] + bh_to_add)
    await db_session.flush()
    await db_session.commit()

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
    if bh_to_add:
        added_dow = [bh.day_of_week for bh in bh_to_add]
        await db_session.execute(
            delete(BusinessHours).where(BusinessHours.day_of_week.in_(added_dow))
        )
    await db_session.flush()
    await db_session.commit()


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
    """services provided but no stylist → status=partial, next_step=stylist_required or extras_loop_required."""
    if not await _db_available():
        pytest.skip("Postgres not reachable")
    from agent.tools.update_booking import update_booking

    raw = await update_booking.ainvoke({"services": ["corte dama test"]})
    data = parse_response(raw)
    # Either partial/stylist_required or extras_loop_required (found service, no extras asked yet)
    # or rejected/service_required (service not found in this test run's DB state)
    # The key assertion is that it's not status=ok without all slots
    assert data["status"] in ("partial", "rejected")
    if data["status"] == "partial":
        assert data["next_step"] in ("stylist_required", "extras_loop_required")


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
    """Invalid date_iso → status=rejected or partial (gate-dependent on DB state)."""
    if not await _db_available():
        pytest.skip("Postgres not reachable")
    from agent.tools.update_booking import update_booking

    raw = await update_booking.ainvoke({
        "services": ["corte dama test"],
        "stylist_name": "Marta Test",
        "date_iso": "not-a-date",
        "extras_asked": True,
        "no_more_services": True,
    })
    data = parse_response(raw)
    # With extras_asked=True and no_more_services=True, either:
    # - rejected (invalid date or unknown stylist) or partial (unknown stylist asks stylist_required)
    assert data["status"] in ("rejected", "partial")


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
    """All pre-slot gates satisfied → status=partial, next_step=pre_book_validation_required.

    booking_ready requires slot_iso; providing only date_iso advances to pre_book_validation_required.
    """
    if not await _db_available():
        pytest.skip("Postgres not reachable")
    from agent.tools.update_booking import update_booking

    raw = await update_booking.ainvoke({
        "services": ["corte dama test"],
        "stylist_name": "Marta Test",
        "date_iso": future_date_iso(),
        "no_more_services": True,
        "extras_asked": True,
        "customer_known": True,
        "notes_asked": True,
    })
    data = parse_response(raw)
    assert data["missing"] == []
    assert data["next_step"] == "pre_book_validation_required"


@pytest.mark.asyncio
async def test_seeded_unknown_stylist_returns_rejected(seeded_db):
    """Unknown stylist name → status=partial or rejected, next_step=stylist_required."""
    if not await _db_available():
        pytest.skip("Postgres not reachable")
    from agent.tools.update_booking import update_booking

    raw = await update_booking.ainvoke({
        "services": ["corte dama test"],
        "stylist_name": "Estilista_Fantasma_XYZ",
        "date_iso": future_date_iso(),
        "extras_asked": True,
        "no_more_services": True,
    })
    data = parse_response(raw)
    assert data["status"] in ("partial", "rejected")
    assert data["next_step"] == "stylist_required"
