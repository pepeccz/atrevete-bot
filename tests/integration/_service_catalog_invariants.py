"""
Service catalog invariant checks — pure SQL helpers.

Each ``_check_invariant_N(session)`` returns a list of ``Violation`` objects
(empty list = invariant passes). No pytest dependency — usable from both the
green-guard test (test_service_catalog_integrity.py) and the red-injection
test (test_service_catalog_integrity_failures.py).

SQL column note: The Service ORM model uses ``metadata_`` as the Python attribute
name but the SQL column is ``metadata`` (without underscore). All raw SQL here
uses ``metadata->>'key'``, NOT ``metadata_->>'key'``.

Postmortem reference: deploy/service-disambiguation-postmortem (Engram obs #5260).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Violation dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    """A single invariant violation for a row in the services table."""

    invariant_id: str
    service_name: str
    detail: str


# ---------------------------------------------------------------------------
# Invariant descriptions (used for failure message headers)
# ---------------------------------------------------------------------------

INVARIANT_DESCRIPTIONS: dict[str, str] = {
    "I1": "No orphan variants — parent_service_name must match an existing principal",
    "I2": "Same-dimension parent — variant and its parent principal share dimension",
    "I3": "Valid audience — one of {adult_female, adult_male, child_female, child_male, unisex, NULL}",
    "I4": "No duplicate principals by (name, dimension)",
    "I5": "Every variant has a non-null parent_service_name",
    "I6": "Valid dimension — derived from principals at runtime",
}

# ---------------------------------------------------------------------------
# Valid audience values (I3)
# ---------------------------------------------------------------------------

VALID_AUDIENCES: frozenset[str] = frozenset(
    {"adult_female", "adult_male", "child_female", "child_male", "unisex"}
)

# ---------------------------------------------------------------------------
# Invariant check stubs (Task 1.2) — each returns [] until implemented
# ---------------------------------------------------------------------------


async def _check_invariant_1(session: AsyncSession) -> list[Violation]:
    """I1: Every variant's parent_service_name resolves to an existing principal's name."""
    result = await session.execute(text("""
            SELECT v.name AS variant_name, v.metadata->>'parent_service_name' AS parent_name
            FROM services v
            WHERE v.metadata->>'service_type' = 'variant'
              AND v.metadata->>'parent_service_name' IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM services p
                WHERE p.metadata->>'service_type' = 'principal'
                  AND p.name = v.metadata->>'parent_service_name'
              )
            """))
    rows = result.fetchall()
    return [
        Violation(
            invariant_id="I1",
            service_name=row.variant_name,
            detail=f"parent_service_name='{row.parent_name}' (no matching principal)",
        )
        for row in rows
    ]


async def _check_invariant_2(session: AsyncSession) -> list[Violation]:
    """I2: A variant and its referenced principal share the same dimension."""
    result = await session.execute(text("""
            SELECT
                v.name AS variant_name,
                v.metadata->>'dimension' AS v_dim,
                p.metadata->>'dimension' AS p_dim,
                v.metadata->>'parent_service_name' AS parent_name
            FROM services v
            JOIN services p
              ON p.name = v.metadata->>'parent_service_name'
             AND p.metadata->>'service_type' = 'principal'
            WHERE v.metadata->>'service_type' = 'variant'
              AND v.metadata->>'dimension' != p.metadata->>'dimension'
            """))
    rows = result.fetchall()
    return [
        Violation(
            invariant_id="I2",
            service_name=row.variant_name,
            detail=(
                f"dimension='{row.v_dim}' but parent '{row.parent_name}'"
                f" has dimension='{row.p_dim}'"
            ),
        )
        for row in rows
    ]


async def _check_invariant_3(session: AsyncSession) -> list[Violation]:
    """I3: Every service's audience is in the valid set or NULL."""
    valid_list = ", ".join(f"'{v}'" for v in sorted(VALID_AUDIENCES))
    result = await session.execute(text(f"""
            SELECT name, audience
            FROM services
            WHERE audience IS NOT NULL
              AND audience NOT IN ({valid_list})
            """))
    rows = result.fetchall()
    return [
        Violation(
            invariant_id="I3",
            service_name=row.name,
            detail=f"audience='{row.audience}' (not in valid set)",
        )
        for row in rows
    ]


async def _check_invariant_4(session: AsyncSession) -> list[Violation]:
    """I4: No two principals share the same (name, dimension) pair."""
    result = await session.execute(text("""
            SELECT name, metadata->>'dimension' AS dim, COUNT(*) AS cnt
            FROM services
            WHERE metadata->>'service_type' = 'principal'
            GROUP BY name, metadata->>'dimension'
            HAVING COUNT(*) > 1
            """))
    rows = result.fetchall()
    return [
        Violation(
            invariant_id="I4",
            service_name=row.name,
            detail=(f"{row.cnt} principals share" f" (name='{row.name}', dimension='{row.dim}')"),
        )
        for row in rows
    ]


async def _check_invariant_5(session: AsyncSession) -> list[Violation]:
    """I5: No service with service_type='variant' has NULL or empty parent_service_name."""
    result = await session.execute(text("""
            SELECT name
            FROM services
            WHERE metadata->>'service_type' = 'variant'
              AND (
                metadata->>'parent_service_name' IS NULL
                OR metadata->>'parent_service_name' = ''
              )
            """))
    rows = result.fetchall()
    return [
        Violation(
            invariant_id="I5",
            service_name=row.name,
            detail="service_type='variant' but parent_service_name IS NULL or empty",
        )
        for row in rows
    ]


async def _check_invariant_6(session: AsyncSession) -> list[Violation]:
    """I6: Every service's dimension is one of the dimension values present in principals (runtime-derived)."""
    # Step 1: derive valid dimension set from principals at runtime
    dim_result = await session.execute(text("""
            SELECT DISTINCT metadata->>'dimension' AS d
            FROM services
            WHERE metadata->>'service_type' = 'principal'
              AND metadata->>'dimension' IS NOT NULL
            """))
    principal_dims: set[str] = {row.d for row in dim_result.fetchall()}

    if not principal_dims:
        return []

    # Step 2: find services (non-principal) whose dimension is not in principal_dims
    result = await session.execute(text("""
            SELECT name, metadata->>'dimension' AS dim
            FROM services
            WHERE metadata->>'dimension' IS NOT NULL
              AND metadata->>'service_type' != 'principal'
            """))
    rows = result.fetchall()
    return [
        Violation(
            invariant_id="I6",
            service_name=row.name,
            detail=f"dimension='{row.dim}' (not in principal-derived set {sorted(principal_dims)})",
        )
        for row in rows
        if row.dim not in principal_dims
    ]


# ---------------------------------------------------------------------------
# CHECKERS registry — maps invariant ID → checker function
# ---------------------------------------------------------------------------

CHECKERS: dict[str, Callable[..., object]] = {
    "I1": _check_invariant_1,
    "I2": _check_invariant_2,
    "I3": _check_invariant_3,
    "I4": _check_invariant_4,
    "I5": _check_invariant_5,
    "I6": _check_invariant_6,
}
