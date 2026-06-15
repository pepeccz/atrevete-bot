"""RED test — Task 2.4: _resolve_service_ids_strict ambiguous descriptor shape.

Asserts that the new sibling function _resolve_service_ids_strict returns a
3-tuple (resolved_ids, unknown_names, ambiguous_descriptors) where the third
element contains structured dicts when a service term is ambiguous.

Ambiguous descriptor shape (design §2 Slice 2):
{
    "status": "ambiguous",
    "axis": "audience" | "variant",
    "service_term": str,
    "family_label": str,
    "candidates": [list of service names],
    "question_hint": "audience_required" | "variant_required",
}

Tests FAIL before Task 2.5 implements _resolve_service_ids_strict.

Refs: design §2 Slice 2, spec R2.1-R2.3, task 2.4/2.5
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
async def audience_ambiguous_catalog(db_session):
    """Seed a null-audience principal 'Corte Strict Test' with audience-tagged peers.

    Simulates the real-catalog scenario: when user says "corte" the LLM passes the
    null-audience principal name, triggering the audience gate.
    """
    from uuid import uuid4

    from sqlalchemy import delete

    from database.models import Service, ServiceCategory

    dim = "corte_strict_dim"
    services = [
        ("Corte Strict Test", None),  # null-audience → ambiguous
        ("Corte Dama Strict Test", "adult_female"),
        ("Corte Caballero Strict Test", "adult_male"),
        ("Corte Niña Strict Test", "child_female"),
    ]
    names = [n for n, _ in services]

    await db_session.execute(delete(Service).where(Service.name.in_(names)))
    await db_session.flush()

    for name, aud in services:
        svc = Service(
            id=uuid4(),
            name=name,
            category=ServiceCategory.HAIRDRESSING,
            duration_minutes=35,
            is_active=True,
            audience=aud,
            metadata_={
                "service_type": "principal",
                "dimension": dim,
                "parent_service_name": None,
            },
        )
        db_session.add(svc)
    await db_session.flush()

    yield {
        "null_principal": "Corte Strict Test",
        "dimension": dim,
        "names": names,
    }

    await db_session.execute(delete(Service).where(Service.name.in_(names)))
    await db_session.flush()


@pytest.fixture
async def variant_ambiguous_catalog(db_session):
    """Seed a 'Depilación Strict Test' principal with multiple variant children.

    Simulates the wax-zone scenario: when user says "depilación" the principal
    has variants (zones) and the variant gate fires.
    """
    from uuid import uuid4

    from sqlalchemy import delete

    from database.models import Service, ServiceCategory

    parent_name = "Depilación Strict Test"
    variant_names = [
        "Axilas Strict Test",
        "Piernas Enteras Strict Test",
        "Brasileña Strict Test",
    ]
    all_names = [parent_name] + variant_names

    await db_session.execute(delete(Service).where(Service.name.in_(all_names)))
    await db_session.flush()

    # Principal row — duration_minutes=1 (placeholder; check_duration_positive requires > 0)
    db_session.add(
        Service(
            id=uuid4(),
            name=parent_name,
            category=ServiceCategory.AESTHETICS,
            duration_minutes=1,
            is_active=True,
            audience=None,
            metadata_={
                "service_type": "principal",
                "dimension": "wax_strict",
                "parent_service_name": None,
            },
        )
    )
    # Variants
    for vname in variant_names:
        db_session.add(
            Service(
                id=uuid4(),
                name=vname,
                category=ServiceCategory.AESTHETICS,
                duration_minutes=30,
                is_active=True,
                audience=None,
                metadata_={
                    "service_type": "variant",
                    "dimension": "wax_strict",
                    "parent_service_name": parent_name,
                },
            )
        )
    await db_session.flush()

    yield {
        "principal": parent_name,
        "variants": variant_names,
        "all_names": all_names,
    }

    await db_session.execute(delete(Service).where(Service.name.in_(all_names)))
    await db_session.flush()


@pytest.fixture
async def unambiguous_catalog(db_session):
    """Seed a single unambiguous service 'Manicura Strict Test' with no peers."""
    from uuid import uuid4

    from sqlalchemy import delete

    from database.models import Service, ServiceCategory

    name = "Manicura Strict Test"
    await db_session.execute(delete(Service).where(Service.name == name))
    await db_session.flush()

    db_session.add(
        Service(
            id=uuid4(),
            name=name,
            category=ServiceCategory.AESTHETICS,
            duration_minutes=45,
            is_active=True,
            audience=None,
            metadata_={
                "service_type": "principal",
                "dimension": "manicure_strict_dim",
                "parent_service_name": None,
            },
        )
    )
    await db_session.flush()

    yield name

    await db_session.execute(delete(Service).where(Service.name == name))
    await db_session.flush()


# ---------------------------------------------------------------------------
# Task 2.4 RED tests — these fail because _resolve_service_ids_strict does not exist yet
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strict_resolver_is_importable():
    """Task 2.4 RED: _resolve_service_ids_strict must be importable from _booking_helpers."""
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    assert callable(_resolve_service_ids_strict)


@pytest.mark.asyncio
async def test_strict_resolver_returns_4_tuple_shape(db_session, unambiguous_catalog):
    """Task 2.4 / T2.2: strict resolver returns (resolved_ids, unknown, descriptors, partial_ids)."""
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    result = await _resolve_service_ids_strict(db_session, [unambiguous_catalog])
    assert isinstance(result, tuple)
    assert len(result) == 4, f"Expected 4-tuple, got {len(result)}-tuple"

    resolved_ids, unknown, descriptors, partial_ids = result
    assert isinstance(resolved_ids, list)
    assert isinstance(unknown, list)
    assert isinstance(descriptors, list)
    assert isinstance(partial_ids, list)


@pytest.mark.asyncio
async def test_strict_resolver_audience_ambiguous_returns_descriptor(
    db_session, audience_ambiguous_catalog
):
    """Task 2.4 RED: null-audience principal in multi-audience dimension returns
    ambiguous descriptor with axis='audience'.
    """
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    null_principal = audience_ambiguous_catalog["null_principal"]
    resolved_ids, unknown, descriptors, _partial = await _resolve_service_ids_strict(
        db_session, [null_principal]
    )

    assert (
        len(descriptors) == 1
    ), f"Expected 1 ambiguous descriptor for '{null_principal}', got {len(descriptors)}: {descriptors}"
    desc = descriptors[0]

    # Shape validation
    assert desc["status"] == "ambiguous"
    assert desc["axis"] == "audience"
    assert desc["service_term"] == null_principal
    assert "family_label" in desc
    assert "candidates" in desc
    assert len(desc["candidates"]) >= 2
    assert desc["question_hint"] == "audience_required"

    # UUID must NOT be in resolved_ids when ambiguous
    assert (
        len(resolved_ids) == 0
    ), f"Ambiguous service must not commit a UUID, got resolved_ids={resolved_ids}"


@pytest.mark.asyncio
async def test_strict_resolver_variant_ambiguous_returns_descriptor(
    db_session, variant_ambiguous_catalog
):
    """Task 2.4 RED: principal with variant children returns ambiguous descriptor
    with axis='variant'.
    """
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    principal = variant_ambiguous_catalog["principal"]
    resolved_ids, unknown, descriptors, _partial = await _resolve_service_ids_strict(
        db_session, [principal]
    )

    assert (
        len(descriptors) == 1
    ), f"Expected 1 ambiguous descriptor for '{principal}', got {len(descriptors)}: {descriptors}"
    desc = descriptors[0]

    assert desc["status"] == "ambiguous"
    assert desc["axis"] == "variant"
    assert desc["service_term"] == principal
    assert "family_label" in desc
    assert "candidates" in desc
    assert len(desc["candidates"]) >= 2
    assert desc["question_hint"] == "variant_required"

    # UUID must NOT be in resolved_ids when ambiguous
    assert (
        len(resolved_ids) == 0
    ), f"Ambiguous service must not commit a UUID, got resolved_ids={resolved_ids}"


@pytest.mark.asyncio
async def test_strict_resolver_unambiguous_returns_empty_descriptors(
    db_session, unambiguous_catalog
):
    """Task 2.4 RED: unambiguous service returns empty descriptors list and resolved UUID."""
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    resolved_ids, unknown, descriptors, partial_ids = await _resolve_service_ids_strict(
        db_session, [unambiguous_catalog]
    )

    assert (
        descriptors == []
    ), f"Expected empty descriptors for unambiguous service, got: {descriptors}"
    assert (
        len(resolved_ids) == 1
    ), f"Expected 1 resolved UUID for unambiguous service, got: {resolved_ids}"
    assert unknown == []
    assert partial_ids == [], f"Expected partial_ids=[] for unambiguous service, got: {partial_ids}"


@pytest.mark.asyncio
async def test_strict_resolver_existing_wrapper_unchanged(db_session, unambiguous_catalog):
    """Task 2.4 RED: _resolve_service_ids (2-tuple wrapper) still works after strict addition."""
    from agent.tools._booking_helpers import _resolve_service_ids

    resolved_ids, unknown = await _resolve_service_ids(db_session, [unambiguous_catalog])
    assert isinstance(resolved_ids, list)
    assert isinstance(unknown, list)
    # The 2-tuple signature is preserved — no 3-tuple leakage
    assert len(resolved_ids) == 1


# ---------------------------------------------------------------------------
# Task T2.1 RED tests — 4-tuple return with partial_resolved_ids
# Refs: REQ-TL-3, design ADR-DR-2
# These FAIL until T2.2 refactors _resolve_service_ids_strict to return 4-tuple.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strict_resolver_returns_4_tuple(db_session, unambiguous_catalog):
    """T2.1 RED: _resolve_service_ids_strict MUST return a 4-tuple.

    The 4th element is partial_resolved_ids: list[str].
    """
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    result = await _resolve_service_ids_strict(db_session, [unambiguous_catalog])
    assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
    assert len(result) == 4, (
        f"Expected 4-tuple (resolved_ids, unknown, ambiguous, partial_resolved_ids), "
        f"got {len(result)}-tuple"
    )

    resolved_ids, unknown, ambiguous, partial_resolved_ids = result
    assert isinstance(resolved_ids, list)
    assert isinstance(unknown, list)
    assert isinstance(ambiguous, list)
    assert isinstance(partial_resolved_ids, list)


@pytest.mark.asyncio
async def test_strict_resolver_partial_resolved_ids_populated_on_mixed_input(
    db_session, variant_ambiguous_catalog, unambiguous_catalog
):
    """T2.1 RED: when one service is ambiguous and one is clean, partial_resolved_ids
    contains the UUID of the clean service.

    Scenario A (REQ-TL-3): input [ambiguous_principal, clean_service] →
      resolved_ids=[]  (nothing committed this turn)
      ambiguous=[{axis='variant', ...}]
      partial_resolved_ids=[<clean-service-uuid>]
    """
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    principal = variant_ambiguous_catalog["principal"]
    # Input: one ambiguous principal + one unambiguous service
    resolved_ids, unknown, ambiguous_descs, partial_resolved_ids = (
        await _resolve_service_ids_strict(db_session, [principal, unambiguous_catalog])
    )

    # Nothing committed this turn when any ambiguity exists
    assert (
        resolved_ids == []
    ), f"resolved_ids must be [] when any ambiguity exists, got: {resolved_ids}"

    # Ambiguous descriptor for the principal
    assert (
        len(ambiguous_descs) == 1
    ), f"Expected 1 ambiguous descriptor for '{principal}', got: {ambiguous_descs}"
    assert ambiguous_descs[0]["axis"] == "variant"

    # Clean service UUID ends up in partial_resolved_ids
    assert len(partial_resolved_ids) == 1, (
        f"Expected 1 partial_resolved_id for '{unambiguous_catalog}', "
        f"got: {partial_resolved_ids}"
    )
    assert isinstance(partial_resolved_ids[0], str), "UUID must be a string"


@pytest.mark.asyncio
async def test_strict_resolver_partial_resolved_ids_empty_when_all_unambiguous(
    db_session, unambiguous_catalog
):
    """T2.1 RED: when all services resolve cleanly, partial_resolved_ids is [].

    No ambiguity → resolved_ids contains the UUID, partial_resolved_ids is empty.
    This is the non-ambiguous branch — partial_resolved_ids only populated under ambiguity.
    """
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    resolved_ids, unknown, ambiguous_descs, partial_resolved_ids = (
        await _resolve_service_ids_strict(db_session, [unambiguous_catalog])
    )

    assert ambiguous_descs == []
    assert len(resolved_ids) == 1
    assert partial_resolved_ids == [], (
        f"partial_resolved_ids must be [] when all services resolve cleanly, "
        f"got: {partial_resolved_ids}"
    )


@pytest.mark.asyncio
async def test_strict_resolver_partial_resolved_ids_empty_when_all_ambiguous(
    db_session, variant_ambiguous_catalog
):
    """T2.1 RED: when all services are ambiguous, partial_resolved_ids is [].

    Nothing resolved cleanly → both resolved_ids and partial_resolved_ids are [].
    """
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    principal = variant_ambiguous_catalog["principal"]
    resolved_ids, unknown, ambiguous_descs, partial_resolved_ids = (
        await _resolve_service_ids_strict(db_session, [principal])
    )

    assert resolved_ids == []
    assert len(ambiguous_descs) == 1
    assert partial_resolved_ids == [], (
        f"partial_resolved_ids must be [] when nothing resolved cleanly, "
        f"got: {partial_resolved_ids}"
    )
