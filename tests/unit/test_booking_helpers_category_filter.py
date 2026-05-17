"""T-1, T-3 — RED tests for category-filtered stylist resolution.

Covers:
- _resolve_service_categories: returns correct ServiceCategory set per input
- _resolve_active_stylists(session, service_ids): filters by category matrix

Strict TDD: tests written BEFORE implementation; all must FAIL on first run.
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
    await db_session.flush()

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
    await db_session.flush()

    yield {
        "hair_id": str(hair_id),
        "aesth_id": str(aesth_id),
        "both_id": str(both_id),
    }

    await db_session.execute(delete(Service).where(Service.name.in_(names)))
    await db_session.flush()


@pytest.fixture
async def category_stylists(db_session):
    """Seed 3 active stylists: HAIRDRESSING, AESTHETICS, BOTH + 1 inactive HAIRDRESSING."""
    from uuid import uuid4

    from sqlalchemy import delete

    from database.models import ServiceCategory, Stylist

    names = [
        "_test_stylist_hair",
        "_test_stylist_aesth",
        "_test_stylist_both",
        "_test_stylist_hair_inactive",
    ]

    await db_session.execute(delete(Stylist).where(Stylist.name.in_(names)))
    await db_session.flush()

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
    await db_session.flush()

    yield {
        "hair_id": str(hair_id),
        "aesth_id": str(aesth_id),
        "both_id": str(both_id),
        "inactive_id": str(inactive_id),
    }

    await db_session.execute(delete(Stylist).where(Stylist.name.in_(names)))
    await db_session.flush()


# ---------------------------------------------------------------------------
# T-1: _resolve_service_categories
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_service_categories_hairdressing_only(db_session, category_services):
    """HAIRDRESSING-only service_ids → {HAIRDRESSING}."""
    from agent.tools._booking_helpers import _resolve_service_categories
    from database.models import ServiceCategory

    result = await _resolve_service_categories(db_session, [category_services["hair_id"]])
    assert result == {ServiceCategory.HAIRDRESSING}


@pytest.mark.asyncio
async def test_resolve_service_categories_aesthetics_only(db_session, category_services):
    """AESTHETICS-only service_ids → {AESTHETICS}."""
    from agent.tools._booking_helpers import _resolve_service_categories
    from database.models import ServiceCategory

    result = await _resolve_service_categories(db_session, [category_services["aesth_id"]])
    assert result == {ServiceCategory.AESTHETICS}


@pytest.mark.asyncio
async def test_resolve_service_categories_mixed_hair_and_aesth(db_session, category_services):
    """HAIRDRESSING + AESTHETICS input → {HAIRDRESSING, AESTHETICS}."""
    from agent.tools._booking_helpers import _resolve_service_categories
    from database.models import ServiceCategory

    result = await _resolve_service_categories(
        db_session,
        [category_services["hair_id"], category_services["aesth_id"]],
    )
    assert result == {ServiceCategory.HAIRDRESSING, ServiceCategory.AESTHETICS}


@pytest.mark.asyncio
async def test_resolve_service_categories_both_present(db_session, category_services):
    """BOTH-category service present → {BOTH} in result."""
    from agent.tools._booking_helpers import _resolve_service_categories
    from database.models import ServiceCategory

    result = await _resolve_service_categories(db_session, [category_services["both_id"]])
    assert ServiceCategory.BOTH in result


@pytest.mark.asyncio
async def test_resolve_service_categories_empty_list(db_session):
    """Empty list → empty set."""
    from agent.tools._booking_helpers import _resolve_service_categories

    result = await _resolve_service_categories(db_session, [])
    assert result == set()


# ---------------------------------------------------------------------------
# T-3: _resolve_active_stylists(session, service_ids) — extended signature
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_active_stylists_no_service_ids_returns_all(
    db_session, category_stylists
):
    """service_ids=None → all active stylists (legacy path)."""
    from agent.tools._booking_helpers import _resolve_active_stylists

    result = await _resolve_active_stylists(db_session)
    names = result if isinstance(result[0], str) else [s for s in result]
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
    from agent.tools._booking_helpers import _resolve_active_stylists

    result = await _resolve_active_stylists(
        db_session, service_ids=[category_services["hair_id"]]
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
    from agent.tools._booking_helpers import _resolve_active_stylists

    result = await _resolve_active_stylists(
        db_session, service_ids=[category_services["aesth_id"]]
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
    from agent.tools._booking_helpers import _resolve_active_stylists

    result = await _resolve_active_stylists(
        db_session,
        service_ids=[category_services["hair_id"], category_services["aesth_id"]],
    )
    assert result == [], f"Expected empty list for mixed, got: {result}"


@pytest.mark.asyncio
async def test_resolve_active_stylists_empty_service_ids_returns_empty(
    db_session, category_stylists
):
    """Empty service_ids list → [] (fail-closed — no unresolved IDs should open the gate)."""
    from agent.tools._booking_helpers import _resolve_active_stylists

    result = await _resolve_active_stylists(db_session, service_ids=[])
    assert result == [], f"Expected empty list for empty service_ids, got: {result}"


@pytest.mark.asyncio
async def test_resolve_active_stylists_all_both_services_returns_all_active(
    db_session, category_services, category_stylists
):
    """All-BOTH services → all active stylists."""
    from agent.tools._booking_helpers import _resolve_active_stylists

    result = await _resolve_active_stylists(
        db_session, service_ids=[category_services["both_id"]]
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
    from agent.tools._booking_helpers import _resolve_active_stylists

    result = await _resolve_active_stylists(
        db_session,
        service_ids=[category_services["hair_id"], category_services["both_id"]],
    )
    result_names = " ".join(result)
    assert "_test_stylist_hair" in result_names
    assert "_test_stylist_both" in result_names
    assert "_test_stylist_aesth" not in result_names
