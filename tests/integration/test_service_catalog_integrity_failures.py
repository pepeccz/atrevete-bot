"""
Failure injection tests for service catalog integrity guard.

These tests verify that each invariant-check helper correctly detects
synthetic violations inserted into the database. Written FIRST (strict TDD
RED step) — at the time of writing, ``_service_catalog_invariants`` does not
exist, so the suite initially fails with ImportError.

TDD transitions documented per task:
- Task 1.1: ImportError (RED)
- Task 1.2: AssertionError — stubs return [] (RED)
- Task 1.3: I1 GREEN, I4/I6 still RED
- Task 1.4: I1+I4 GREEN, I6 still RED
- Task 1.6: all 3 GREEN
"""

import socket
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text

from database.connection import AsyncSessionLocal
from database.seeds.services import seed_services

# This import will fail until Task 1.2 creates the module (RED state for Task 1.1)
from tests.integration._service_catalog_invariants import (  # noqa: E402
    CHECKERS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _postgres_reachable() -> bool:
    try:
        s = socket.create_connection(("localhost", 5432), timeout=1)
        s.close()
        return True
    except OSError:
        return False


def _random_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Shared setup: truncate + seed (once per fixture call)
# ---------------------------------------------------------------------------


async def _truncate_and_seed() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(text("TRUNCATE services CASCADE"))
        await session.commit()
    await seed_services()


# ---------------------------------------------------------------------------
# Fixture for I1 failure: inject orphan variant
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def session_with_orphan_variant() -> AsyncGenerator:
    if not _postgres_reachable():
        pytest.skip("Postgres not reachable")

    await _truncate_and_seed()

    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                INSERT INTO services (id, name, category, duration_minutes, is_active, audience, metadata)
                VALUES (
                    :id, :name, 'HAIRDRESSING', 30, true, null,
                    '{"service_type": "variant", "dimension": "cut", "parent_service_name": "NonExistentParent"}'::jsonb
                )
                """),
            {
                "id": _random_uuid(),
                "name": "SyntheticOrphanVariant_I1",
            },
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        yield session

    async with AsyncSessionLocal() as session:
        await session.execute(text("TRUNCATE services CASCADE"))
        await session.commit()


# ---------------------------------------------------------------------------
# Fixture for I4 failure: inject duplicate principal
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def session_with_duplicate_principal() -> AsyncGenerator:
    if not _postgres_reachable():
        pytest.skip("Postgres not reachable")

    await _truncate_and_seed()

    # Find an existing principal to duplicate
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("""
                SELECT name, metadata->>'dimension' AS dim
                FROM services
                WHERE metadata->>'service_type' = 'principal'
                LIMIT 1
                """))
        row = result.fetchone()
        assert row is not None, "No principals found in seeded data"
        existing_name = row.name
        existing_dim = row.dim

    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                INSERT INTO services (id, name, category, duration_minutes, is_active, audience, metadata)
                VALUES (
                    :id, :name, 'HAIRDRESSING', 30, true, null,
                    :meta::jsonb
                )
                """),
            {
                "id": _random_uuid(),
                "name": existing_name,
                "meta": f'{{"service_type": "principal", "dimension": "{existing_dim}", '
                f'"parent_service_name": null}}',
            },
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        yield session

    async with AsyncSessionLocal() as session:
        await session.execute(text("TRUNCATE services CASCADE"))
        await session.commit()


# ---------------------------------------------------------------------------
# Fixture for I6 failure: inject service with unknown dimension
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def session_with_dimension_drift() -> AsyncGenerator:
    if not _postgres_reachable():
        pytest.skip("Postgres not reachable")

    await _truncate_and_seed()

    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                INSERT INTO services (id, name, category, duration_minutes, is_active, audience, metadata)
                VALUES (
                    :id, :name, 'HAIRDRESSING', 30, true, null,
                    '{"service_type": "variant", "dimension": "unknown_dim", "parent_service_name": "Corte de Mujer"}'::jsonb
                )
                """),
            {
                "id": _random_uuid(),
                "name": "SyntheticDimensionDrift_I6",
            },
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        yield session

    async with AsyncSessionLocal() as session:
        await session.execute(text("TRUNCATE services CASCADE"))
        await session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failure_orphan_variant_i1(session_with_orphan_variant) -> None:
    """I1: helper detects variant whose parent_service_name has no matching principal."""
    violations = await CHECKERS["I1"](session_with_orphan_variant)

    assert violations, "Expected at least one I1 violation but got none"
    names = [v.service_name for v in violations]
    assert (
        "SyntheticOrphanVariant_I1" in names
    ), f"Expected 'SyntheticOrphanVariant_I1' in violations, got: {names}"
    # Verify the detail message contains the bad parent name
    for v in violations:
        if v.service_name == "SyntheticOrphanVariant_I1":
            assert (
                "NonExistentParent" in v.detail
            ), f"Expected detail to mention 'NonExistentParent', got: {v.detail!r}"


@pytest.mark.asyncio
async def test_failure_duplicate_principal_i4(session_with_duplicate_principal) -> None:
    """I4: helper detects two principals with same (name, dimension) pair."""
    violations = await CHECKERS["I4"](session_with_duplicate_principal)

    assert violations, "Expected at least one I4 violation but got none"
    # The violation detail should mention count > 1
    for v in violations:
        assert (
            "2" in v.detail or "principal" in v.detail.lower()
        ), f"Expected detail to reference duplicate count, got: {v.detail!r}"


@pytest.mark.asyncio
async def test_failure_dimension_drift_i6(session_with_dimension_drift) -> None:
    """I6: helper detects service whose dimension is not in the principal-derived set."""
    violations = await CHECKERS["I6"](session_with_dimension_drift)

    assert violations, "Expected at least one I6 violation but got none"
    names = [v.service_name for v in violations]
    assert (
        "SyntheticDimensionDrift_I6" in names
    ), f"Expected 'SyntheticDimensionDrift_I6' in violations, got: {names}"
    for v in violations:
        if v.service_name == "SyntheticDimensionDrift_I6":
            assert (
                "unknown_dim" in v.detail
            ), f"Expected detail to mention 'unknown_dim', got: {v.detail!r}"
