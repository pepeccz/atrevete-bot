"""Q1 regression tests — memory-service audience pinning.

Covers:
- _infer_audience_from_service_name: pure-function tests for each qualifier group
- _resolve_service_ids_strict: when a memory-stored service name encodes audience
  (e.g. "Corte de Mujer"), the audience_required gate must NOT fire and the
  correct audience-variant UUID must be returned (no invalid_service_ids path).

Refs: Change Q task Q1 (P1 blocker for cliente-leal scenario).
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Pure-function tests for _infer_audience_from_service_name (no DB needed)
# ---------------------------------------------------------------------------


def test_infer_audience_mujer_returns_adult_female():
    from agent.tools._booking_helpers import _infer_audience_from_service_name

    assert _infer_audience_from_service_name("Corte de Mujer") == "adult_female"


def test_infer_audience_dama_returns_adult_female():
    from agent.tools._booking_helpers import _infer_audience_from_service_name

    assert _infer_audience_from_service_name("Corte Dama") == "adult_female"


def test_infer_audience_senora_returns_adult_female():
    from agent.tools._booking_helpers import _infer_audience_from_service_name

    # accent variant
    assert _infer_audience_from_service_name("Corte Señora") == "adult_female"


def test_infer_audience_chica_returns_adult_female():
    from agent.tools._booking_helpers import _infer_audience_from_service_name

    assert _infer_audience_from_service_name("Peinado Chica") == "adult_female"


def test_infer_audience_caballero_returns_adult_male():
    from agent.tools._booking_helpers import _infer_audience_from_service_name

    assert _infer_audience_from_service_name("Corte Caballero") == "adult_male"


def test_infer_audience_hombre_returns_adult_male():
    from agent.tools._booking_helpers import _infer_audience_from_service_name

    assert _infer_audience_from_service_name("Corte de Hombre") == "adult_male"


def test_infer_audience_nino_returns_child_male():
    from agent.tools._booking_helpers import _infer_audience_from_service_name

    assert _infer_audience_from_service_name("Corte Niño") == "child_male"


def test_infer_audience_nina_returns_child_female():
    from agent.tools._booking_helpers import _infer_audience_from_service_name

    assert _infer_audience_from_service_name("Corte Niña") == "child_female"


def test_infer_audience_bebe_returns_baby():
    from agent.tools._booking_helpers import _infer_audience_from_service_name

    assert _infer_audience_from_service_name("Corte Bebé") == "baby"


def test_infer_audience_no_qualifier_returns_none():
    """Unambiguous service name without audience qualifier → None."""
    from agent.tools._booking_helpers import _infer_audience_from_service_name

    assert _infer_audience_from_service_name("Manicura") is None


def test_infer_audience_manicura_pedicura_returns_none():
    from agent.tools._booking_helpers import _infer_audience_from_service_name

    assert _infer_audience_from_service_name("Manicura y Pedicura") is None


def test_infer_audience_tinte_returns_none():
    from agent.tools._booking_helpers import _infer_audience_from_service_name

    assert _infer_audience_from_service_name("Tinte") is None


def test_infer_audience_empty_returns_none():
    from agent.tools._booking_helpers import _infer_audience_from_service_name

    assert _infer_audience_from_service_name("") is None


# ---------------------------------------------------------------------------
# DB-dependent: audience gate does not fire for memory-resolved names (Q1 blocker)
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


@pytest.fixture
async def audience_cut_services(db_session):
    """Seed catalog shape mirroring the real 'Corte' family used in cliente-leal QA.

    Three PRINCIPAL services sharing dimension='cut_q1_test':
    - 'Corte de Mujer Q1'  audience='adult_female'   ← memory-stored name
    - 'Corte de Hombre Q1' audience='adult_male'
    - 'Corte Q1'            audience=None             ← ambiguous principal

    When the LLM passes "Corte de Mujer Q1" (from customer memories) without an explicit
    audience param, _infer_audience_from_service_name must pin it to adult_female and
    bypass the audience_required gate, returning the correct UUID directly.
    """
    from uuid import uuid4

    from sqlalchemy import delete

    from database.models import Service, ServiceCategory

    dim = "cut_q1_test"
    rows = [
        ("Corte de Mujer Q1", "adult_female"),
        ("Corte de Hombre Q1", "adult_male"),
        ("Corte Q1", None),
    ]
    names = [n for n, _ in rows]
    ids: dict[str, str] = {}

    await db_session.execute(delete(Service).where(Service.name.in_(names)))
    await db_session.flush()

    for name, aud in rows:
        svc_id = uuid4()
        ids[name] = str(svc_id)
        db_session.add(
            Service(
                id=svc_id,
                name=name,
                category=ServiceCategory.HAIRDRESSING,
                duration_minutes=40,
                is_active=True,
                audience=aud,
                metadata_={
                    "service_type": "principal",
                    "dimension": dim,
                    "parent_service_name": None,
                },
            )
        )
    await db_session.flush()

    yield {"ids": ids, "names": names}

    await db_session.execute(delete(Service).where(Service.name.in_(names)))
    await db_session.flush()


@pytest.mark.asyncio
async def test_memory_service_name_with_audience_qualifier_bypasses_audience_gate(
    db_session, audience_cut_services
):
    """Q1 core regression: 'Corte de Mujer Q1' from customer memories must resolve to
    the adult_female UUID without triggering audience_required.

    Before the fix: _resolve_service_ids_strict called _resolve_audience_variants with
    input_audience=None → gate fired → returned ambiguous/audience_required, then book
    received no valid service_id and returned invalid_service_ids.

    After the fix: _infer_audience_from_service_name detects "mujer" → adult_female and
    passes effective_audience="adult_female" to _resolve_audience_variants → gate bypassed
    → UUID committed directly.
    """
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    ids = audience_cut_services["ids"]
    female_uuid = ids["Corte de Mujer Q1"]

    resolved_ids, unknown, ambiguous, partial = await _resolve_service_ids_strict(
        db_session,
        ["Corte de Mujer Q1"],  # typical_services name as stored by memory service
        audience=None,  # LLM did NOT pass audience — simulates the cliente-leal scenario
    )

    assert (
        ambiguous == []
    ), f"audience_required gate must NOT fire for 'Corte de Mujer Q1': got ambiguous={ambiguous}"
    assert unknown == [], f"Service must be resolved: got unknown={unknown}"
    assert resolved_ids == [
        female_uuid
    ], f"Must resolve to adult_female UUID {female_uuid}, got {resolved_ids}"
    assert partial == [], "No partial IDs expected when resolution is clean"


@pytest.mark.asyncio
async def test_memory_service_name_hombre_bypasses_audience_gate(db_session, audience_cut_services):
    """Q1 regression guard for adult_male variant.

    'Corte de Hombre Q1' must resolve to adult_male UUID without audience_required.
    """
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    ids = audience_cut_services["ids"]
    male_uuid = ids["Corte de Hombre Q1"]

    resolved_ids, unknown, ambiguous, partial = await _resolve_service_ids_strict(
        db_session,
        ["Corte de Hombre Q1"],
        audience=None,
    )

    assert (
        ambiguous == []
    ), f"audience_required gate must NOT fire for 'Corte de Hombre Q1': got {ambiguous}"
    assert resolved_ids == [
        male_uuid
    ], f"Must resolve to adult_male UUID {male_uuid}, got {resolved_ids}"


@pytest.mark.asyncio
async def test_ambiguous_principal_without_qualifier_still_fires_gate(
    db_session, audience_cut_services
):
    """Regression guard: a bare ambiguous principal 'Corte Q1' (no qualifier)
    must still trigger audience_required when no audience is passed.

    Ensures the Q1 fix does not suppress the gate for genuinely ambiguous names.
    """
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    resolved_ids, unknown, ambiguous, partial = await _resolve_service_ids_strict(
        db_session,
        ["Corte Q1"],
        audience=None,
    )

    assert (
        ambiguous != []
    ), "audience_required gate MUST fire for ambiguous 'Corte Q1' with no qualifier"
    assert resolved_ids == [], "No UUID must be committed when gate fires"


@pytest.mark.asyncio
async def test_explicit_audience_param_still_works_alongside_inference(
    db_session, audience_cut_services
):
    """When an explicit audience param is already provided (from LLM), inference
    must not override it. The gate bypass works via the explicit param path.
    """
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    ids = audience_cut_services["ids"]
    female_uuid = ids["Corte de Mujer Q1"]

    resolved_ids, unknown, ambiguous, partial = await _resolve_service_ids_strict(
        db_session,
        ["Corte de Mujer Q1"],
        audience="adult_female",  # explicit — both paths should work
    )

    assert ambiguous == []
    assert resolved_ids == [female_uuid]
