"""
CI guard: assert structural invariants over the seeded services catalog.

Prevents recurrence of the orphan-variant drift caught at deploy 2026-05-11
(see Engram obs #5260: deploy/service-disambiguation-postmortem). Each
invariant runs as its own parametrized case so multiple regressions surface
together rather than short-circuiting on the first failure.

Invariants covered:
    I1 — No orphan variants (parent_service_name must resolve to a principal)
    I2 — Variant and its parent principal share the same dimension
    I3 — Every service audience is in the valid set or NULL
    I4 — No duplicate principals by (name, dimension)
    I5 — Every variant has a non-null parent_service_name
    I6 — Every dimension is from the runtime-derived principal dimension set
    I7 — No cross-dimension variant parenting (REQ-DR-4, disambiguation-resilience)

Data-reclassification scenarios (disambiguation-resilience PR-1):
    DR-1 — Corte de Flequillo is PRINCIPAL post-migration (REQ-DR-1)
    DR-2 — Barba and Perilla are ADDON post-migration (REQ-DR-2)
    DR-3 — Manicura de Hombre is PRINCIPAL with audience=adult_male (REQ-DR-3)

Fixture isolation note: this module uses its own module-scoped TRUNCATE
services CASCADE + seed_services(). It is independent of
tests/integration/test_transactional_models.py (which also TRUNCATEs). Both
files do their own setup so pytest collection order is irrelevant.

WARNING: TRUNCATE services CASCADE will cascade to appointments in a dev DB
where appointments reference services. Run this guard against a disposable
test DB or an empty CI database.

How to run locally:
    pytest tests/integration/test_service_catalog_integrity.py -v

How to extend: add _check_invariant_7 in _service_catalog_invariants.py
and register it in CHECKERS.
"""

from __future__ import annotations

import socket

import pytest
import pytest_asyncio
from sqlalchemy import text

from database.connection import AsyncSessionLocal
from database.seeds.services import seed_services
from tests.integration._service_catalog_invariants import (
    CHECKERS,
    INVARIANT_DESCRIPTIONS,
    Violation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _postgres_reachable() -> bool:
    """Return True if Postgres is reachable on localhost:5432."""
    try:
        s = socket.create_connection(("localhost", 5432), timeout=1)
        s.close()
        return True
    except OSError:
        return False


def _format_violations(iid: str, vs: list[Violation]) -> str:
    """Format a human-readable failure message listing each violating row.

    Designed to be specific enough that a developer can locate the bad row
    in seeds.py without additional investigation (spec R4).
    """
    desc = INVARIANT_DESCRIPTIONS[iid]
    lines = [
        f"{iid} — {desc}",
        f"  {len(vs)} violation(s):",
    ]
    for v in vs:
        lines.append(f"    • {v.service_name}: {v.detail}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-scoped fixture: TRUNCATE + seed once per test run
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded_services_session():
    """Provide a clean, seeded AsyncSession for all invariant checks.

    Lifecycle:
    1. Skip if Postgres is not reachable (CI without DB service).
    2. TRUNCATE services CASCADE (removes stale rows).
    3. Seed via seed_services() (deterministic UUIDs — idempotent).
    4. Yield a fresh session for test bodies.
    5. TRUNCATE services CASCADE on teardown (leave DB clean).

    WARNING: CASCADE will wipe appointments if any reference services.
    Use a disposable test DB.
    """
    if not _postgres_reachable():
        pytest.skip("Postgres not reachable — skipping service catalog integrity guard")

    # Setup: truncate then seed
    async with AsyncSessionLocal() as setup_session:
        await setup_session.execute(text("TRUNCATE services CASCADE"))
        await setup_session.commit()

    await seed_services()

    # Yield a session for assertions
    async with AsyncSessionLocal() as session:
        yield session

    # Teardown: truncate again to leave DB clean
    async with AsyncSessionLocal() as teardown_session:
        await teardown_session.execute(text("TRUNCATE services CASCADE"))
        await teardown_session.commit()


# ---------------------------------------------------------------------------
# Parametrized integrity guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("invariant_id", list(CHECKERS.keys()))
@pytest.mark.asyncio(loop_scope="module")
async def test_service_catalog_invariant(seeded_services_session, invariant_id: str) -> None:
    """Assert that the seeded production catalog satisfies invariant ``invariant_id``.

    Failure message names every violating row with enough detail to locate
    the bad entry in database/seeds/services.py (spec R4).
    """
    violations = await CHECKERS[invariant_id](seeded_services_session)
    assert not violations, _format_violations(invariant_id, violations)


# ---------------------------------------------------------------------------
# Data-reclassification assertions — disambiguation-resilience PR-1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="module")
async def test_dr1_corte_de_flequillo_is_principal(seeded_services_session) -> None:
    """DR-1 (REQ-DR-1): Corte de Flequillo must be service_type=principal,
    parent_service_name IS NULL, and audience IS NULL after disambiguation-resilience
    migration + seed update.
    """
    result = await seeded_services_session.execute(
        text("""
            SELECT
                metadata->>'service_type' AS service_type,
                metadata->>'parent_service_name' AS parent_service_name,
                audience
            FROM services
            WHERE name = 'Corte de Flequillo'
        """)
    )
    row = result.fetchone()
    assert row is not None, "Corte de Flequillo not found in seeded data"
    assert row.service_type == "principal", (
        f"Expected service_type='principal' for Corte de Flequillo, got '{row.service_type}'"
    )
    assert row.parent_service_name is None, (
        f"Expected parent_service_name IS NULL for Corte de Flequillo, got '{row.parent_service_name}'"
    )
    assert row.audience is None, (
        f"Expected audience IS NULL for Corte de Flequillo, got '{row.audience}'"
    )


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("service_name", ["Barba", "Perilla"])
async def test_dr2_barba_perilla_are_addon(seeded_services_session, service_name: str) -> None:
    """DR-2 (REQ-DR-2): Barba and Perilla must be service_type=addon,
    parent_service_name IS NULL, and category=HAIRDRESSING after
    disambiguation-resilience migration + seed update.
    """
    result = await seeded_services_session.execute(
        text("""
            SELECT
                metadata->>'service_type' AS service_type,
                metadata->>'parent_service_name' AS parent_service_name,
                category
            FROM services
            WHERE name = :name
        """),
        {"name": service_name},
    )
    row = result.fetchone()
    assert row is not None, f"'{service_name}' not found in seeded data"
    assert row.service_type == "addon", (
        f"Expected service_type='addon' for '{service_name}', got '{row.service_type}'"
    )
    assert row.parent_service_name is None, (
        f"Expected parent_service_name IS NULL for '{service_name}', got '{row.parent_service_name}'"
    )
    assert row.category == "HAIRDRESSING", (
        f"Expected category='HAIRDRESSING' for '{service_name}', got '{row.category}'"
    )
