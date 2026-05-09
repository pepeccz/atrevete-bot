"""T-02, T-03 — BookingQueryService.resolve_audience_variants (principal-side) + resolve_active_stylists.

Tests for the principal-side variant gate and the stylist list helper.

Post-PR#2: these tests call BookingQueryService methods directly (each opens its own
session via get_async_session). DB fixtures still seed data for the queries to find.
"""
from __future__ import annotations

import pytest


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
# Fixtures for variant gate tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def principal_with_children(db_session):
    """Seed principal 'Peinado Test' + active children 'Peinado Novia Test', 'Peinado Fiesta Test'."""
    from uuid import uuid4
    from sqlalchemy import delete
    from database.models import Service, ServiceCategory

    principal_name = "Peinado Test"
    child_names = ["Peinado Novia Test", "Peinado Fiesta Test"]
    all_names = [principal_name] + child_names

    await db_session.execute(delete(Service).where(Service.name.in_(all_names)))
    await db_session.flush()

    # Principal row
    db_session.add(
        Service(
            id=uuid4(),
            name=principal_name,
            category=ServiceCategory.HAIRDRESSING,
            duration_minutes=30,
            is_active=True,
            metadata_={"service_type": "principal", "parent_service_name": None},
        )
    )
    # Children
    for child_name in child_names:
        db_session.add(
            Service(
                id=uuid4(),
                name=child_name,
                category=ServiceCategory.HAIRDRESSING,
                duration_minutes=45,
                is_active=True,
                metadata_={"service_type": "variant", "parent_service_name": principal_name},
            )
        )
    await db_session.flush()

    yield {"principal": principal_name, "children": child_names}

    await db_session.execute(delete(Service).where(Service.name.in_(all_names)))
    await db_session.flush()


@pytest.fixture
async def child_with_sibling(db_session):
    """Seed 'Peinado Fiesta Test2' with sibling 'Peinado Novia Test2', parent 'Peinado Test2'."""
    from uuid import uuid4
    from sqlalchemy import delete
    from database.models import Service, ServiceCategory

    parent_name = "Peinado Test2"
    child_names = ["Peinado Novia Test2", "Peinado Fiesta Test2"]

    await db_session.execute(delete(Service).where(Service.name.in_(child_names)))
    await db_session.flush()

    for child_name in child_names:
        db_session.add(
            Service(
                id=uuid4(),
                name=child_name,
                category=ServiceCategory.HAIRDRESSING,
                duration_minutes=45,
                is_active=True,
                metadata_={"service_type": "variant", "parent_service_name": parent_name},
            )
        )
    await db_session.flush()

    yield {"parent": parent_name, "children": child_names}

    await db_session.execute(delete(Service).where(Service.name.in_(child_names)))
    await db_session.flush()


@pytest.fixture
async def principal_no_children(db_session):
    """Seed 'Manicura Test' principal with NO active children."""
    from uuid import uuid4
    from sqlalchemy import delete
    from database.models import Service, ServiceCategory

    name = "Manicura Test"

    await db_session.execute(delete(Service).where(Service.name == name))
    await db_session.flush()

    db_session.add(
        Service(
            id=uuid4(),
            name=name,
            category=ServiceCategory.AESTHETICS,
            duration_minutes=45,
            is_active=True,
            metadata_={"service_type": "principal", "parent_service_name": None},
        )
    )
    await db_session.flush()

    yield name

    await db_session.execute(delete(Service).where(Service.name == name))
    await db_session.flush()


@pytest.fixture
async def child_no_siblings(db_session):
    """Seed 'Corte de Mujer Test' as only child of 'Corte Test' — no siblings."""
    from uuid import uuid4
    from sqlalchemy import delete
    from database.models import Service, ServiceCategory

    parent_name = "Corte Test"
    child_name = "Corte de Mujer Test"

    await db_session.execute(delete(Service).where(Service.name == child_name))
    await db_session.flush()

    db_session.add(
        Service(
            id=uuid4(),
            name=child_name,
            category=ServiceCategory.HAIRDRESSING,
            duration_minutes=35,
            is_active=True,
            metadata_={"service_type": "variant", "parent_service_name": parent_name},
        )
    )
    await db_session.flush()

    yield child_name

    await db_session.execute(delete(Service).where(Service.name == child_name))
    await db_session.flush()


# ---------------------------------------------------------------------------
# T-02: variant gate — principal-side case
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_principal_with_active_children_returns_variant(db_session, principal_with_children):
    """Principal 'Peinado Test' + active children → ('variant', principal_name, [principal, c1, c2])."""
    from agent.services.booking_query_service import BookingQueryService

    kind, family, candidates = await _resolve_audience_variants(
        db_session, principal_with_children["principal"]
    )

    assert kind == "variant", f"Expected 'variant', got '{kind}'"
    assert family == principal_with_children["principal"]
    assert principal_with_children["principal"] in candidates
    for child in principal_with_children["children"]:
        assert child in candidates


@pytest.mark.asyncio
async def test_child_with_sibling_returns_variant(db_session, child_with_sibling):
    """Child 'Peinado Fiesta Test2' + sibling → ('variant', parent, [parent, siblings...])."""
    from agent.services.booking_query_service import BookingQueryService

    child_name = child_with_sibling["children"][0]
    kind, family, candidates = await BookingQueryService.resolve_audience_variants(child_name)

    assert kind == "variant", f"Expected 'variant', got '{kind}'"
    assert family == child_with_sibling["parent"]
    assert child_with_sibling["parent"] in candidates


@pytest.mark.asyncio
async def test_principal_no_children_returns_ok(db_session, principal_no_children):
    """Principal 'Manicura Test' with no active children → ('ok'/'none', ..., [])."""
    from agent.services.booking_query_service import BookingQueryService

    kind, family, candidates = await BookingQueryService.resolve_audience_variants(principal_no_children)

    assert kind in ("none", "ok"), f"Expected 'none' or 'ok', got '{kind}'"
    assert candidates == []


@pytest.mark.asyncio
async def test_child_no_siblings_returns_ok(db_session, child_no_siblings):
    """Child 'Corte de Mujer Test' with no siblings → ('none', ..., [])."""
    from agent.services.booking_query_service import BookingQueryService

    kind, family, candidates = await BookingQueryService.resolve_audience_variants(child_no_siblings)

    assert kind in ("none", "ok"), f"Expected 'none' or 'ok', got '{kind}'"
    assert candidates == []


@pytest.mark.asyncio
async def test_principal_variant_fires_regardless_of_audience(
    db_session, principal_with_children
):
    """Audience-independence: variant gate fires even when audience is already known.

    This test verifies _resolve_audience_variants itself returns 'variant'
    for a principal with children — the audience argument is irrelevant at the
    helper level (independence is enforced at update_booking level in T-08).
    """
    from agent.services.booking_query_service import BookingQueryService

    # The helper does not receive audience — just call it; result must still be variant.
    kind, family, candidates = await _resolve_audience_variants(
        db_session, principal_with_children["principal"]
    )
    assert kind == "variant"


# ---------------------------------------------------------------------------
# T-03: _resolve_active_stylists helper
# ---------------------------------------------------------------------------


@pytest.fixture
async def stylists_mixed(db_session):
    """Insert 3 active + 1 inactive stylist; clean up after."""
    from uuid import uuid4
    from sqlalchemy import delete
    from database.models import Stylist

    names = [
        "Zara Estilista Test",
        "Ana Peluquera Test",
        "Marta Profesional Test",
        "Inactiva Estilista Test",
    ]

    await db_session.execute(delete(Stylist).where(Stylist.name.in_(names)))
    await db_session.flush()

    for i, name in enumerate(names):
        db_session.add(
            Stylist(
                id=uuid4(),
                name=name,
                is_active=(i < 3),  # first 3 active, last inactive
            )
        )
    await db_session.flush()

    yield names

    await db_session.execute(delete(Stylist).where(Stylist.name.in_(names)))
    await db_session.flush()


@pytest.fixture
async def no_active_stylists(db_session):
    """Insert only inactive stylists for testing empty list scenario."""
    from uuid import uuid4
    from sqlalchemy import delete
    from database.models import Stylist

    names = ["Solo Inactiva Test A", "Solo Inactiva Test B"]

    await db_session.execute(delete(Stylist).where(Stylist.name.in_(names)))
    await db_session.flush()

    for name in names:
        db_session.add(Stylist(id=uuid4(), name=name, is_active=False))
    await db_session.flush()

    yield names

    await db_session.execute(delete(Stylist).where(Stylist.name.in_(names)))
    await db_session.flush()


@pytest.mark.asyncio
async def test_resolve_active_stylists_returns_only_active_first_names(
    db_session, stylists_mixed
):
    """Returns first names of active stylists only, alpha-ordered."""
    from agent.services.booking_query_service import BookingQueryService

    result = await BookingQueryService.resolve_active_stylists()

    # Only first names of active stylists
    active_first_names = {"Zara", "Ana", "Marta"}
    for first_name in active_first_names:
        assert first_name in result, f"Expected '{first_name}' in result: {result}"

    # Inactive stylist must NOT appear
    assert "Inactiva" not in result

    # Must be alpha-ordered (by full name, first name extracted)
    assert result == sorted(result)


@pytest.mark.asyncio
async def test_resolve_active_stylists_returns_empty_when_none_active(
    db_session, no_active_stylists
):
    """Returns [] when no active stylists exist (for the test-inserted ones)."""
    from agent.services.booking_query_service import BookingQueryService

    result = await BookingQueryService.resolve_active_stylists()

    # The test-only inactive stylists are NOT in result
    assert "Solo" not in result
    # Result is a list (possibly non-empty if real active stylists exist in DB)
    assert isinstance(result, list)
