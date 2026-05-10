"""RED → GREEN tests for _resolve_audience_variants — audience/variant axis discrimination.

Covers:
- H1: multi-PRINCIPAL same-dimension different-audience → kind=="audience"
- H3: multi-VARIANT same-parent → kind=="variant" (regression guard)
- false-positive guard: single-principal unambiguous → kind=="none"

Refs: design Decision 5, spec H1/H3/U3
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


@pytest.fixture
async def audience_services(db_session):
    """Seed three PRINCIPAL services sharing dimension='cut_test_dim':
      - 'Corte Test' with audience=None (the ambiguous null-audience principal)
      - 'Corte de Mujer Test' with audience='adult_female'
      - 'Corte de Hombre Test' with audience='adult_male'

    Per design §2 Slice 2 (Task 2.3), the audience gate fires only when the
    INPUT row has audience=None.  Querying 'Corte Test' (null) → kind='audience'.
    Querying 'Corte de Mujer Test' (adult_female) → kind='none' (already specific).
    """
    from uuid import uuid4
    from sqlalchemy import delete
    from database.models import Service, ServiceCategory

    dim = "cut_test_dim"
    service_rows = [
        ("Corte Test", None),
        ("Corte de Mujer Test", "adult_female"),
        ("Corte de Hombre Test", "adult_male"),
    ]
    names = [n for n, _ in service_rows]

    await db_session.execute(delete(Service).where(Service.name.in_(names)))
    await db_session.flush()

    for name, aud in service_rows:
        svc = Service(
            id=uuid4(),
            name=name,
            category=ServiceCategory.HAIRDRESSING,
            duration_minutes=40,
            is_active=True,
            audience=aud,
            metadata_={"service_type": "principal", "dimension": dim, "parent_service_name": None},
        )
        db_session.add(svc)
    await db_session.flush()

    yield {"dimension": dim, "names": names, "null_principal": "Corte Test"}

    await db_session.execute(delete(Service).where(Service.name.in_(names)))
    await db_session.flush()


@pytest.fixture
async def variant_services(db_session):
    """Seed two VARIANT services sharing parent_service_name='Cera Test'."""
    from uuid import uuid4
    from sqlalchemy import delete
    from database.models import Service, ServiceCategory

    parent = "Cera Test Padre"
    names = ["Cera Axilas Test", "Cera Piernas Test"]

    await db_session.execute(delete(Service).where(Service.name.in_(names)))
    await db_session.flush()

    for name in names:
        svc = Service(
            id=uuid4(),
            name=name,
            category=ServiceCategory.AESTHETICS,
            duration_minutes=20,
            is_active=True,
            metadata_={"service_type": "variant", "dimension": "wax", "parent_service_name": parent},
        )
        db_session.add(svc)
    await db_session.flush()

    yield {"parent": parent, "names": names}

    await db_session.execute(delete(Service).where(Service.name.in_(names)))
    await db_session.flush()


@pytest.fixture
async def single_service(db_session):
    """Seed one PRINCIPAL service with no peers sharing its dimension."""
    from uuid import uuid4
    from sqlalchemy import delete
    from database.models import Service, ServiceCategory

    name = "Manicura Solo Test"
    await db_session.execute(delete(Service).where(Service.name == name))
    await db_session.flush()

    svc = Service(
        id=uuid4(),
        name=name,
        category=ServiceCategory.AESTHETICS,
        duration_minutes=45,
        is_active=True,
        audience=None,
        metadata_={"service_type": "principal", "dimension": "manicure_solo_dim", "parent_service_name": None},
    )
    db_session.add(svc)
    await db_session.flush()

    yield name

    await db_session.execute(delete(Service).where(Service.name == name))
    await db_session.flush()


@pytest.mark.asyncio
async def test_null_audience_principal_in_multi_audience_dimension_returns_audience_kind(
    db_session, audience_services
):
    """H1 (updated): null-audience PRINCIPAL in a dimension with audience-tagged peers
    → kind=='audience' (gate fires because the input is ambiguous).

    Per design §2 Slice 2 Task 2.3: the gate triggers only when input_audience is None.
    """
    if not await _db_available():
        pytest.skip("Postgres not reachable")

    from agent.tools._booking_helpers import _resolve_audience_variants

    kind, family, candidates = await _resolve_audience_variants(
        db_session, audience_services["null_principal"]  # audience=None → gate fires
    )
    assert kind == "audience", f"Expected kind='audience', got '{kind}'"
    assert len(candidates) >= 2
    for name in audience_services["names"]:
        assert name in candidates, f"Expected '{name}' in candidates"


@pytest.mark.asyncio
async def test_audience_tagged_principal_in_multi_audience_dimension_returns_none(
    db_session, audience_services
):
    """H1b (new): audience-tagged PRINCIPAL in a multi-audience dimension
    → kind=='none' (already specific — no gate needed).

    Per design §2 Slice 2 Task 2.3: gate only fires when input_audience is None.
    """
    if not await _db_available():
        pytest.skip("Postgres not reachable")

    from agent.tools._booking_helpers import _resolve_audience_variants

    # Query the audience-tagged principal "Corte de Mujer Test" (adult_female)
    kind, family, candidates = await _resolve_audience_variants(
        db_session, "Corte de Mujer Test"  # audience='adult_female' → gate must NOT fire
    )
    assert kind in ("none", "variant"), (
        f"Expected kind='none' for audience-tagged principal, got '{kind}'. "
        "A service with a known audience is already specific — no disambiguation needed."
    )


@pytest.mark.asyncio
async def test_variant_with_shared_parent_returns_variant_kind(db_session, variant_services):
    """H3: VARIANT siblings sharing parent_service_name → kind=='variant'."""
    if not await _db_available():
        pytest.skip("Postgres not reachable")

    from agent.tools._booking_helpers import _resolve_audience_variants

    kind, family, candidates = await _resolve_audience_variants(
        db_session, variant_services["names"][0]
    )
    assert kind == "variant", f"Expected kind='variant', got '{kind}'"
    assert family == variant_services["parent"]
    assert len(candidates) >= 2


@pytest.mark.asyncio
async def test_unambiguous_service_returns_none(db_session, single_service):
    """False-positive guard: single-principal with unique dimension → kind=='none'."""
    if not await _db_available():
        pytest.skip("Postgres not reachable")

    from agent.tools._booking_helpers import _resolve_audience_variants

    kind, family, candidates = await _resolve_audience_variants(db_session, single_service)
    assert kind == "none", f"Expected kind='none', got '{kind}'"
    assert candidates == []
