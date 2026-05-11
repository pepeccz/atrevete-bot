"""
Catalog axis classification audit — integration tests.

TDD RED state: these tests fail until migration a3b4c5d6e7f8 is applied (T1.3).

Covers:
  - REQ-TE-1: 7 reclassified services must have service_type=addon, parent=null
  - REQ-DR-8: Barro Gold Extra must be standalone principal (dimension=facial)

TDD progression:
  - T1.1 / T1.2 [RED]  — tests written, migration not yet applied → fail
  - T1.3 / T1.4 [GREEN] — migration + seed update applied → pass
"""

from __future__ import annotations

import socket

import pytest
import pytest_asyncio
from sqlalchemy import text

from database.connection import AsyncSessionLocal
from database.seeds.services import seed_services

# ---------------------------------------------------------------------------
# Services under reclassification
# ---------------------------------------------------------------------------

ADDON_RECLASSIFIED_SERVICES: list[str] = [
    "Tinte Extra",
    "Mechas Extras",
    "Barro Extra",
    "Tratamiento Facial + Radiofrecuencia (15 min)",
    "Tratamiento Facial + Radiofrecuencia (30 min)",
    "Tratamiento Anticelulítico + Radiofrecuencia (30 min)",
    "Piernas Perfectas + Presoterapia (30 min)",
]

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


# ---------------------------------------------------------------------------
# Module-scoped fixture: TRUNCATE + seed once
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded_session():
    """Clean, seeded session for all audit tests in this module."""
    if not _postgres_reachable():
        pytest.skip("Postgres not reachable — skipping catalog axis audit tests")

    async with AsyncSessionLocal() as setup_session:
        await setup_session.execute(text("TRUNCATE services CASCADE"))
        await setup_session.commit()

    await seed_services()

    async with AsyncSessionLocal() as session:
        yield session

    async with AsyncSessionLocal() as teardown_session:
        await teardown_session.execute(text("TRUNCATE services CASCADE"))
        await teardown_session.commit()


# ---------------------------------------------------------------------------
# T1.1 [RED → GREEN] — 7 reclassified services are addon without parent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("service_name", ADDON_RECLASSIFIED_SERVICES)
@pytest.mark.asyncio(loop_scope="module")
async def test_reclassified_service_is_addon(seeded_session, service_name: str) -> None:
    """REQ-TE-1: Each reclassified service must have service_type=addon and no parent.

    RED before migration a3b4c5d6e7f8; GREEN after.
    """
    result = await seeded_session.execute(
        text("""
            SELECT
                metadata->>'service_type' AS service_type,
                metadata->>'parent_service_name' AS parent_service_name,
                is_active
            FROM services
            WHERE name = :name
        """),
        {"name": service_name},
    )
    row = result.fetchone()
    assert row is not None, f"'{service_name}' not found in seeded data"
    assert row.is_active is True, f"'{service_name}' must be active"
    assert row.service_type == "addon", (
        f"Expected service_type='addon' for '{service_name}', got '{row.service_type}'. "
        "Migration a3b4c5d6e7f8 must reclassify this service from variant to addon."
    )
    assert row.parent_service_name is None, (
        f"Expected parent_service_name IS NULL for '{service_name}', "
        f"got '{row.parent_service_name}'. Migration must clear the parent reference."
    )


# ---------------------------------------------------------------------------
# T1.2 [RED → GREEN] — Barro Gold Extra is standalone principal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="module")
async def test_barro_gold_extra_is_standalone_principal(seeded_session) -> None:
    """REQ-DR-8: Barro Gold Extra must be service_type=principal, dimension=facial,
    parent_service_name IS NULL after migration a3b4c5d6e7f8.

    Current data error: parent_service_name='Tratamiento Facial' (cross-category mismatch).
    RED before migration; GREEN after.
    """
    result = await seeded_session.execute(text("""
        SELECT
            metadata->>'service_type' AS service_type,
            metadata->>'parent_service_name' AS parent_service_name,
            metadata->>'dimension' AS dimension
        FROM services
        WHERE name = 'Barro Gold Extra'
    """))
    row = result.fetchone()
    assert row is not None, "Barro Gold Extra not found in seeded data"
    assert row.service_type == "principal", (
        f"Expected service_type='principal' for Barro Gold Extra, got '{row.service_type}'. "
        "Design I-1 determined this is a standalone AESTHETICS facial service."
    )
    assert row.parent_service_name is None, (
        f"Expected parent_service_name IS NULL for Barro Gold Extra, "
        f"got '{row.parent_service_name}'. The cross-category parenting to "
        "'Tratamiento Facial' was a data error."
    )
    assert row.dimension == "facial", (
        f"Expected dimension='facial' for Barro Gold Extra, got '{row.dimension}'. "
        "Design assigns facial dimension consistent with its AESTHETICS category."
    )
