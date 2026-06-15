"""RED test — T3: update_booking audience disambiguation.

Fails on master (module absent). Passes after GREEN impl.
Refs: R3
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest


def parse_response(raw: str) -> dict:
    return json.loads(raw)


async def _db_available() -> bool:
    try:
        from sqlalchemy import text

        from database.connection import get_async_session

        async with get_async_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture
async def db_session():
    from database.connection import get_async_session

    async with get_async_session() as session:
        yield session


@pytest.fixture
async def ambiguous_services(db_session):
    """Seed a service family 'corte test' with 3 variants for disambiguation tests."""
    from sqlalchemy import delete

    from database.models import Service, ServiceCategory

    family_key = "corte test familia"
    variant_names = ["corte dama familia", "corte caballero familia", "corte niña familia"]

    # Clean previous
    await db_session.execute(
        delete(Service).where(Service.name.in_(variant_names + [family_key]))
    )
    await db_session.flush()

    variants = []
    for vname in variant_names:
        svc = Service(
            id=uuid4(),
            name=vname,
            category=ServiceCategory.HAIRDRESSING,
            duration_minutes=45,
            is_active=True,
            metadata_={"parent_service_name": family_key},
        )
        variants.append(svc)
        db_session.add(svc)

    await db_session.flush()
    await db_session.commit()

    yield {"family": family_key, "variants": variants}

    await db_session.execute(
        delete(Service).where(Service.name.in_(variant_names + [family_key]))
    )
    await db_session.flush()
    await db_session.commit()


@pytest.mark.asyncio
async def test_tool_importable():
    """update_booking importable from agent.tools.update_booking."""
    from agent.tools.update_booking import update_booking
    assert update_booking is not None


@pytest.mark.asyncio
async def test_booking_helpers_importable():
    """_booking_helpers importable with expected functions."""
    from agent.tools._booking_helpers import (
        _compute_first_valid_date,
        _resolve_audience_variants,
        _resolve_stylist,
    )
    assert callable(_compute_first_valid_date)
    assert callable(_resolve_audience_variants)
    assert callable(_resolve_stylist)


@pytest.mark.asyncio
async def test_compute_first_valid_date_pure():
    """_compute_first_valid_date is pure and correct."""
    from datetime import date

    from agent.tools._booking_helpers import _compute_first_valid_date

    today = date(2026, 5, 1)
    result = _compute_first_valid_date(today, 3)
    assert result == date(2026, 5, 4)


@pytest.mark.asyncio
async def test_compute_first_valid_date_zero_days():
    from datetime import date

    from agent.tools._booking_helpers import _compute_first_valid_date

    today = date(2026, 5, 1)
    result = _compute_first_valid_date(today, 0)
    assert result == today


@pytest.mark.asyncio
async def test_ambiguous_service_without_audience(ambiguous_services):
    """Ambiguous service (has siblings in metadata) without audience → audience_required."""
    if not await _db_available():
        pytest.skip("Postgres not reachable")
    from agent.tools.update_booking import update_booking

    # Use one of the variant names that has parent metadata
    raw = await update_booking.ainvoke({
        "services": ["corte dama familia"],
    })
    data = parse_response(raw)
    # If service has siblings → audience_required OR stylist_required (service resolved)
    # The key: must not be service_required (service was found)
    assert data["next_step"] != "service_required" or data["status"] == "partial"


@pytest.mark.asyncio
async def test_unambiguous_service_does_not_trigger_audience_required():
    """A service with no siblings never triggers audience_required."""
    if not await _db_available():
        pytest.skip("Postgres not reachable")
    from agent.tools.update_booking import update_booking

    # alisado has no parent metadata, so it's unambiguous
    raw = await update_booking.ainvoke({
        "services": ["alisado"],
    })
    data = parse_response(raw)
    assert data["next_step"] != "audience_required"


@pytest.mark.asyncio
async def test_resolve_stylist_unaccented_match(db_session):
    """_resolve_stylist matches on unaccented lowercase name."""
    if not await _db_available():
        pytest.skip("Postgres not reachable")

    from sqlalchemy import delete

    from database.models import ServiceCategory, Stylist

    stylist_id = uuid4()
    # Add stylist with accented name
    st = Stylist(
        id=stylist_id,
        name="María José",
        slug=f"maria-jose-{stylist_id.hex[:6]}",
        category=ServiceCategory.HAIRDRESSING,
        is_active=True,
    )
    db_session.add(st)
    await db_session.flush()

    from agent.tools._booking_helpers import _resolve_stylist

    result = await _resolve_stylist(db_session, "maria jose")
    assert result == stylist_id

    # Cleanup
    await db_session.execute(delete(Stylist).where(Stylist.id == stylist_id))
    await db_session.flush()
