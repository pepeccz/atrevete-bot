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
