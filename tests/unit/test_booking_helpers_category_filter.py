"""T-1, T-3 — BookingQueryService.resolve_service_categories + resolve_active_stylists.

Covers:
- resolve_service_categories: returns correct ServiceCategory set per input
- resolve_active_stylists(service_ids): filters by category matrix

Post-PR#2: tests now call BookingQueryService methods directly.
Fixtures commit data so the service's new session can see it.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# DB availability helper
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


@pytest.fixture
async def db_session():
    if not await _db_available():
        pytest.skip("Postgres not reachable")
    from database.connection import get_async_session

    async with get_async_session() as session:
        yield session


# ---------------------------------------------------------------------------
# Fixtures — services + stylists seeded per test
# ---------------------------------------------------------------------------


@pytest.fixture
async def category_services(db_session):
    """Seed 3 services: one HAIRDRESSING, one AESTHETICS, one BOTH."""
    from uuid import uuid4
    from sqlalchemy import delete
    from database.models import Service, ServiceCategory

    hair_name = "_test_hair_service_cat"
    aesth_name = "_test_aesth_service_cat"
    both_name = "_test_both_service_cat"
    names = [hair_name, aesth_name, both_name]

    await db_session.execute(delete(Service).where(Service.name.in_(names)))
    await db_session.commit()

    hair_id = uuid4()
    aesth_id = uuid4()
    both_id = uuid4()

    db_session.add(
        Service(
            id=hair_id,
            name=hair_name,
            category=ServiceCategory.HAIRDRESSING,
            duration_minutes=30,
            is_active=True,
        )
    )
    db_session.add(
        Service(
            id=aesth_id,
            name=aesth_name,
            category=ServiceCategory.AESTHETICS,
            duration_minutes=30,
            is_active=True,
        )
    )
    db_session.add(
        Service(
            id=both_id,
            name=both_name,
            category=ServiceCategory.BOTH,
            duration_minutes=30,
            is_active=True,
        )
    )
    await db_session.commit()

    yield {
        "hair_id": str(hair_id),
        "aesth_id": str(aesth_id),
        "both_id": str(both_id),
    }

    await db_session.execute(delete(Service).where(Service.name.in_(names)))
    await db_session.commit()


@pytest.fixture
async def category_stylists(db_session):
    """Seed 3 active stylists: HAIRDRESSING, AESTHETICS, BOTH + 1 inactive HAIRDRESSING."""
    from uuid import uuid4
    from sqlalchemy import delete
    from database.models import Stylist, ServiceCategory

    names = [
        "_test_stylist_hair",
        "_test_stylist_aesth",
        "_test_stylist_both",
        "_test_stylist_hair_inactive",
    ]

    await db_session.execute(delete(Stylist).where(Stylist.name.in_(names)))
    await db_session.commit()

    hair_id = uuid4()
    aesth_id = uuid4()
    both_id = uuid4()
    inactive_id = uuid4()

    db_session.add(
        Stylist(
            id=hair_id,
            name="_test_stylist_hair",
            category=ServiceCategory.HAIRDRESSING,
            is_active=True,
        )
    )
    db_session.add(
        Stylist(
            id=aesth_id,
            name="_test_stylist_aesth",
            category=ServiceCategory.AESTHETICS,
            is_active=True,
        )
    )
    db_session.add(
        Stylist(
            id=both_id,
            name="_test_stylist_both",
            category=ServiceCategory.BOTH,
            is_active=True,
        )
    )
    db_session.add(
        Stylist(
            id=inactive_id,
            name="_test_stylist_hair_inactive",
            category=ServiceCategory.HAIRDRESSING,
            is_active=False,
        )
    )
    await db_session.commit()

    yield {
        "hair_id": str(hair_id),
        "aesth_id": str(aesth_id),
        "both_id": str(both_id),
        "inactive_id": str(inactive_id),
    }

    await db_session.execute(delete(Stylist).where(Stylist.name.in_(names)))
    await db_session.commit()


# ---------------------------------------------------------------------------
# T-1: BookingQueryService.resolve_service_categories
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_service_categories_hairdressing_only(db_session, category_services):
    """HAIRDRESSING-only service_ids → {HAIRDRESSING}."""
    from database.models import ServiceCategory
    from agent.services.booking_query_service import BookingQueryService

    result = await BookingQueryService.resolve_service_categories([category_services["hair_id"]])
    assert result == {ServiceCategory.HAIRDRESSING}


@pytest.mark.asyncio
async def test_resolve_service_categories_aesthetics_only(db_session, category_services):
    """AESTHETICS-only service_ids → {AESTHETICS}."""
    from database.models import ServiceCategory
    from agent.services.booking_query_service import BookingQueryService

    result = await BookingQueryService.resolve_service_categories([category_services["aesth_id"]])
    assert result == {ServiceCategory.AESTHETICS}


@pytest.mark.asyncio
async def test_resolve_service_categories_mixed_hair_and_aesth(db_session, category_services):
    """HAIRDRESSING + AESTHETICS input → {HAIRDRESSING, AESTHETICS}."""
    from database.models import ServiceCategory
    from agent.services.booking_query_service import BookingQueryService

    result = await BookingQueryService.resolve_service_categories(
        [category_services["hair_id"], category_services["aesth_id"]]
    )
    assert result == {ServiceCategory.HAIRDRESSING, ServiceCategory.AESTHETICS}


@pytest.mark.asyncio
async def test_resolve_service_categories_both_present(db_session, category_services):
    """BOTH-category service present → {BOTH} in result."""
    from database.models import ServiceCategory
    from agent.services.booking_query_service import BookingQueryService

    result = await BookingQueryService.resolve_service_categories([category_services["both_id"]])
    assert ServiceCategory.BOTH in result


@pytest.mark.asyncio
async def test_resolve_service_categories_empty_list(db_session):
    """Empty list → empty set."""
    from agent.services.booking_query_service import BookingQueryService

    result = await BookingQueryService.resolve_service_categories([])
    assert result == set()


# ---------------------------------------------------------------------------
# T-3: BookingQueryService.resolve_active_stylists(service_ids) — extended signature
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_active_stylists_no_service_ids_returns_all(
    db_session, category_stylists
):
    """service_ids=None → all active stylists (legacy path)."""
    from agent.services.booking_query_service import BookingQueryService

    result = await BookingQueryService.resolve_active_stylists()
    # All 3 active test stylists should appear by first name prefix
    assert any("_test_stylist_hair" in n for n in result) or any(
        n.startswith("_test") for n in result
    ), f"Expected test stylists in result: {result}"
    # Inactive must not appear
    assert "_test_stylist_hair_inactive" not in " ".join(result)


@pytest.mark.asyncio
async def test_resolve_active_stylists_hairdressing_services_excludes_aesthetics(
    db_session, category_services, category_stylists
):
    """HAIRDRESSING services → only HAIRDRESSING + BOTH stylists returned."""
    from agent.services.booking_query_service import BookingQueryService

    result = await BookingQueryService.resolve_active_stylists(
        service_ids=[category_services["hair_id"]]
    )
    # First names of the test stylists
    result_names = " ".join(result)
    assert "_test_stylist_hair" in result_names, f"HAIR stylist missing: {result}"
    assert "_test_stylist_both" in result_names, f"BOTH stylist missing: {result}"
    assert "_test_stylist_aesth" not in result_names, f"AESTH stylist must be excluded: {result}"
    assert "_test_stylist_hair_inactive" not in result_names, f"Inactive must be excluded: {result}"


@pytest.mark.asyncio
async def test_resolve_active_stylists_aesthetics_services_excludes_hairdressing(
    db_session, category_services, category_stylists
):
    """AESTHETICS services → only AESTHETICS + BOTH stylists returned."""
    from agent.services.booking_query_service import BookingQueryService

    result = await BookingQueryService.resolve_active_stylists(
        service_ids=[category_services["aesth_id"]]
    )
    result_names = " ".join(result)
    assert "_test_stylist_aesth" in result_names, f"AESTH stylist missing: {result}"
    assert "_test_stylist_both" in result_names, f"BOTH stylist missing: {result}"
    assert "_test_stylist_hair" not in result_names, f"HAIR stylist must be excluded: {result}"


@pytest.mark.asyncio
async def test_resolve_active_stylists_mixed_returns_empty(
    db_session, category_services, category_stylists
):
    """Mixed HAIRDRESSING + AESTHETICS services → [] (fail-closed)."""
    from agent.services.booking_query_service import BookingQueryService

    result = await BookingQueryService.resolve_active_stylists(
        service_ids=[category_services["hair_id"], category_services["aesth_id"]]
    )
    assert result == [], f"Expected empty list for mixed, got: {result}"


@pytest.mark.asyncio
async def test_resolve_active_stylists_empty_service_ids_returns_empty(
    db_session, category_stylists
):
    """Empty service_ids list → [] (fail-closed — no unresolved IDs should open the gate)."""
    from agent.services.booking_query_service import BookingQueryService

    result = await BookingQueryService.resolve_active_stylists(service_ids=[])
    assert result == [], f"Expected empty list for empty service_ids, got: {result}"


@pytest.mark.asyncio
async def test_resolve_active_stylists_all_both_services_returns_all_active(
    db_session, category_services, category_stylists
):
    """All-BOTH services → all active stylists."""
    from agent.services.booking_query_service import BookingQueryService

    result = await BookingQueryService.resolve_active_stylists(
        service_ids=[category_services["both_id"]]
    )
    result_names = " ".join(result)
    assert "_test_stylist_hair" in result_names
    assert "_test_stylist_aesth" in result_names
    assert "_test_stylist_both" in result_names
    assert "_test_stylist_hair_inactive" not in result_names


@pytest.mark.asyncio
async def test_resolve_active_stylists_hair_plus_both_returns_hair_and_both(
    db_session, category_services, category_stylists
):
    """HAIR + BOTH service → HAIRDRESSING + BOTH stylists (BOTH service is compatible)."""
    from agent.services.booking_query_service import BookingQueryService

    result = await BookingQueryService.resolve_active_stylists(
        service_ids=[category_services["hair_id"], category_services["both_id"]]
    )
    result_names = " ".join(result)
    assert "_test_stylist_hair" in result_names
    assert "_test_stylist_both" in result_names
    assert "_test_stylist_aesth" not in result_names
