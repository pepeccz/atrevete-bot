"""RED → GREEN tests for the R32 audience gate backstop.

REQ-1 (spec slim-booking-protocol): _resolve_audience_variants MUST fire
'audience_required' whenever a PRINCIPAL shares its dimension with peers that
have a DIFFERENT audience value — regardless of whether the matched row's own
audience column is non-null.

Scenarios:
  SCN-1: corte service, no explicit audience → gate fires
  SCN-2: explicit audience arg bypasses outer Step-1 guard entirely
  SCN-3: audience-specific internal name (e.g. "corte de mujer"), no explicit
          audience arg → gate STILL fires (internal name ≠ client intent)
  SCN-4: service with no audience peers (single-audience dimension) → gate silent

Refs: spec slim-booking-protocol REQ-1 (SCN-1..SCN-4)
"""

from __future__ import annotations

import json

import pytest

# ---------------------------------------------------------------------------
# Helpers
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


_CATALOG_SEEDED_R32: bool = False


async def _ensure_catalog_seeded_r32() -> None:
    """Seed services catalog if the table is empty (idempotent)."""
    global _CATALOG_SEEDED_R32
    if _CATALOG_SEEDED_R32:
        return

    from sqlalchemy import text

    from database.connection import get_async_session
    from database.seeds.services import seed_services

    async with get_async_session() as s:
        row = await s.execute(text("SELECT COUNT(*) FROM services"))
        count = row.scalar()

    if count == 0:
        await seed_services()

    _CATALOG_SEEDED_R32 = True


@pytest.fixture
async def db_session():
    if not await _db_available():
        pytest.skip("Postgres not reachable")

    try:
        await _ensure_catalog_seeded_r32()
    except Exception as exc:
        pytest.skip(f"Catalog seed failed ({type(exc).__name__}: {exc})")

    from database.connection import get_async_session

    async with get_async_session() as session:
        yield session


# ---------------------------------------------------------------------------
# Fixtures — use real seeded services where possible (Corte de Mujer /
# Corte de Hombre are guaranteed present by database/seeds/services.py).
# For SCN-4, seed a single-audience dimension that is isolated.
# ---------------------------------------------------------------------------


@pytest.fixture
async def isolated_service(db_session):
    """Seed one PRINCIPAL service in a dimension with no other principals.

    Used for SCN-4: gate must be silent when the dimension has only one audience value.
    """
    from uuid import uuid4

    from sqlalchemy import delete

    from database.models import Service, ServiceCategory

    name = "Manicura R32 Solo"
    dim = "manicure_r32_solo_dim"

    await db_session.execute(delete(Service).where(Service.name == name))
    await db_session.flush()

    svc = Service(
        id=uuid4(),
        name=name,
        category=ServiceCategory.AESTHETICS,
        duration_minutes=45,
        is_active=True,
        audience=None,
        metadata_={"service_type": "principal", "dimension": dim, "parent_service_name": None},
    )
    db_session.add(svc)
    await db_session.flush()

    yield name

    await db_session.execute(delete(Service).where(Service.name == name))
    await db_session.flush()


# ---------------------------------------------------------------------------
# SCN-1: ambiguous cut service, no explicit audience → gate must fire
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_corte_without_audience_triggers_gate(db_session):
    """SCN-1: _resolve_audience_variants called with a null-audience principal
    ("Corte de Mujer" — which IS audience-tagged) in a dimension that has
    multiple audience values (cut dimension contains Corte de Mujer/adult_female
    and Corte de Hombre/adult_male).

    Per REQ-1: the gate MUST fire regardless of whether the row's own audience
    column is non-null.  Pre-fix this returned ('none', '', []).
    """
    if not await _db_available():
        pytest.skip("Postgres not reachable")

    from agent.tools._booking_helpers import _resolve_audience_variants

    # "Corte de Mujer" has audience=adult_female but its dimension='cut' has peers
    # with a different audience value (Corte de Hombre=adult_male).
    # REQ-1: gate fires regardless of the row's own audience.
    kind, dimension, candidates = await _resolve_audience_variants(db_session, "Corte de Mujer")

    assert kind == "audience", (
        f"SCN-1 FAILED: Expected kind='audience', got '{kind}'. "
        "The audience gate must fire whenever dimension peers have differing audience values, "
        "even if the matched row itself is already audience-tagged."
    )
    assert dimension == "cut", f"Expected dimension='cut', got '{dimension}'"
    assert len(candidates) >= 2, f"Expected >=2 candidates, got: {candidates}"


# ---------------------------------------------------------------------------
# SCN-2: explicit audience arg bypasses the outer Step-1 guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_explicit_audience_bypasses_gate():
    """SCN-2: when update_booking receives an explicit audience arg, the outer
    'if audience is None:' guard at line 447 of update_booking.py skips Step 1
    entirely.  _resolve_audience_variants is never called.  Resolution proceeds
    without audience_required.

    This test verifies the EXISTING guard is intact (regression guard for REQ-3).
    We call update_booking with services=['Corte de Mujer'] AND audience='adult_female'.
    """
    if not await _db_available():
        pytest.skip("Postgres not reachable")

    from agent.tools.update_booking import update_booking

    raw = await update_booking.ainvoke(
        {
            "services": ["Corte de Mujer"],
            "audience": "adult_female",
        }
    )
    data = json.loads(raw)

    # With explicit audience, Step 1 is skipped → next_step must NOT be audience_required
    assert data.get("next_step") != "audience_required", (
        f"SCN-2 FAILED: explicit audience='adult_female' should bypass gate, "
        f"but got next_step='{data.get('next_step')}'. "
        "The outer 'if audience is None:' guard must be intact."
    )


# ---------------------------------------------------------------------------
# SCN-3: audience-specific internal name + no explicit audience arg → gate fires
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_internal_audience_name_still_triggers_gate(db_session):
    """SCN-3: _resolve_audience_variants("Corte de Mujer") with audience=None on
    the call side (Step 1 runs).  Even though the DB row has audience=adult_female,
    the function must fire the gate because the dimension has peers with differing
    audience values.

    This is the core R32 bug: 'corte de mujer' as an internal service name is NOT
    sufficient to establish client intent — only an explicit audience arg from the
    LLM constitutes a client signal.

    Pre-fix this returned ('none', '', []) because of the dead 'and input_audience is None'
    guard that caused the gate to silently pass through.
    """
    if not await _db_available():
        pytest.skip("Postgres not reachable")

    from agent.tools._booking_helpers import _resolve_audience_variants

    # Same call as SCN-1 — but emphasising the "internal name ≠ client intent" contract
    kind, dimension, candidates = await _resolve_audience_variants(db_session, "Corte de Mujer")

    assert kind == "audience", (
        f"SCN-3 FAILED: Expected kind='audience', got '{kind}'. "
        "An audience-tagged service name submitted without an explicit audience arg "
        "must still trigger the audience gate (internal name is not client intent)."
    )
    assert (
        "Corte de Mujer" in candidates or "Corte de Hombre" in candidates
    ), f"Expected cut dimension candidates in result, got: {candidates}"


# ---------------------------------------------------------------------------
# SCN-4: service with no audience peers → gate must be silent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_without_peers_resolves_silently(db_session, isolated_service):
    """SCN-4: a PRINCIPAL in a dimension with only one distinct audience value
    (here: None) must NOT trigger the gate.  len(audience_values)==1 → silent.
    """
    if not await _db_available():
        pytest.skip("Postgres not reachable")

    from agent.tools._booking_helpers import _resolve_audience_variants

    kind, dimension, candidates = await _resolve_audience_variants(db_session, isolated_service)

    assert kind == "none", (
        f"SCN-4 FAILED: Expected kind='none' for isolated service, got '{kind}'. "
        "A service in a single-audience dimension must not trigger the audience gate."
    )
    assert candidates == [], f"Expected empty candidates, got: {candidates}"
