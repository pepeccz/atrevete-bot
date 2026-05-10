"""RED test — Task 2.2: _resolve_audience_variants null-audience gate.

Asserts that when a PRINCIPAL service has audience=None AND at least one peer
in the same dimension has a non-null audience, the function returns the
audience axis descriptor — regardless of the None-audience principal being
the one queried.

Bug: line 189 of _booking_helpers.py uses `if p[1] is not None` when building
distinct_audiences, which excludes None from the set.  When the *input* row's
own audience is None and all non-null peers are counted as distinct, the gate
must still fire because the null principal is truly ambiguous.

Refs: design §2 Slice 2, spec R2.1, task 2.2/2.3
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
async def null_audience_principal_with_tagged_peers(db_session):
    """Seed dimension 'cut_null_test' with three principals:
      - 'Corte Null Test'         audience=None   ← queried input
      - 'Corte Mujer Null Test'   audience='adult_female'
      - 'Corte Hombre Null Test'  audience='adult_male'

    The null-audience principal lives in a dimension where audience-tagged
    peers exist, so _resolve_audience_variants MUST return kind='audience'.
    """
    from uuid import uuid4
    from sqlalchemy import delete
    from database.models import Service, ServiceCategory

    dim = "cut_null_test_dim"
    services = [
        ("Corte Null Test", None),
        ("Corte Mujer Null Test", "adult_female"),
        ("Corte Hombre Null Test", "adult_male"),
    ]
    names = [n for n, _ in services]

    await db_session.execute(delete(Service).where(Service.name.in_(names)))
    await db_session.flush()

    for name, audience in services:
        svc = Service(
            id=uuid4(),
            name=name,
            category=ServiceCategory.HAIRDRESSING,
            duration_minutes=35,
            is_active=True,
            audience=audience,
            metadata_={
                "service_type": "principal",
                "dimension": dim,
                "parent_service_name": None,
            },
        )
        db_session.add(svc)
    await db_session.flush()

    yield {"null_principal": "Corte Null Test", "dimension": dim, "names": names}

    await db_session.execute(delete(Service).where(Service.name.in_(names)))
    await db_session.flush()


@pytest.fixture
async def single_null_audience_principal(db_session):
    """Seed dimension 'manicura_null_dim' with ONLY a null-audience principal — no tagged peers.

    This is the false-positive guard: a null-audience principal that is the ONLY
    principal in its dimension must NOT trigger the audience gate.
    """
    from uuid import uuid4
    from sqlalchemy import delete
    from database.models import Service, ServiceCategory

    dim = "manicura_null_dim"
    name = "Manicura Null Test"

    await db_session.execute(delete(Service).where(Service.name == name))
    await db_session.flush()

    svc = Service(
        id=uuid4(),
        name=name,
        category=ServiceCategory.AESTHETICS,
        duration_minutes=45,
        is_active=True,
        audience=None,
        metadata_={
            "service_type": "principal",
            "dimension": dim,
            "parent_service_name": None,
        },
    )
    db_session.add(svc)
    await db_session.flush()

    yield name

    await db_session.execute(delete(Service).where(Service.name == name))
    await db_session.flush()


@pytest.mark.asyncio
async def test_null_audience_principal_with_tagged_peers_fires_audience_gate(
    db_session, null_audience_principal_with_tagged_peers
):
    """Querying a null-audience principal whose dimension has audience-tagged peers
    MUST return kind='audience', not kind='none'.

    This is the RED test — it fails before the null-sentinel fix is applied in Task 2.3.
    """
    from agent.tools._booking_helpers import _resolve_audience_variants

    kind, family, candidates = await _resolve_audience_variants(
        db_session,
        null_audience_principal_with_tagged_peers["null_principal"],
    )

    assert kind == "audience", (
        f"Expected kind='audience' for null-audience principal with tagged peers, got '{kind}'. "
        "The null-sentinel fix (Task 2.3) is needed: distinct_audiences must include None."
    )
    assert family == null_audience_principal_with_tagged_peers["dimension"]
    # All three principals (including the null one) must be in candidates
    for name in null_audience_principal_with_tagged_peers["names"]:
        assert name in candidates, f"Expected '{name}' in candidates={candidates}"


@pytest.mark.asyncio
async def test_null_audience_principal_candidates_include_null_principal(
    db_session, null_audience_principal_with_tagged_peers
):
    """The null-audience principal itself MUST appear in candidates, not be silently excluded."""
    from agent.tools._booking_helpers import _resolve_audience_variants

    kind, family, candidates = await _resolve_audience_variants(
        db_session,
        null_audience_principal_with_tagged_peers["null_principal"],
    )

    assert kind == "audience"
    assert "Corte Null Test" in candidates, (
        f"Null-audience principal must be in candidates, got: {candidates}"
    )


@pytest.mark.asyncio
async def test_null_audience_only_principal_does_not_fire_audience_gate(
    db_session, single_null_audience_principal
):
    """False-positive guard: null-audience principal with NO tagged peers
    in its dimension must NOT fire the audience gate.
    """
    from agent.tools._booking_helpers import _resolve_audience_variants

    kind, family, candidates = await _resolve_audience_variants(
        db_session, single_null_audience_principal
    )

    # A solo null-audience principal in its dimension is unambiguous
    assert kind in ("none", "ok"), (
        f"Expected kind='none' for solo null-audience principal, got '{kind}'"
    )
