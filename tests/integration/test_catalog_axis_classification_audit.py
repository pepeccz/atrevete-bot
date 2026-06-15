"""
Catalog axis classification audit — integration tests.

TDD RED state (Slice 1): these tests fail until migration a3b4c5d6e7f8 is applied (T1.3).
TDD RED state (Slice 2, T2.6/T2.7): these tests fail until migration is applied to a live DB.

Covers:
  - REQ-TE-1: 7 reclassified services must have service_type=addon, parent=null
  - REQ-DR-8: Barro Gold Extra must be standalone principal (dimension=facial)
  - REQ-TE-2: ex-parent principals (Tinte, Mechas, Anticelulítico Completo) no longer
    fire variant_required after their duration-delta children are reclassified
  - REQ-TE-6: prod replay "corte y tinte" — Tinte does NOT trigger variant_required

TDD progression:
  - T1.1 / T1.2 [RED]  — tests written, migration not yet applied → fail
  - T1.3 / T1.4 [GREEN] — migration + seed update applied → pass
  - T2.6 / T2.7 [RED]  — tests written; pass once migration a3b4c5d6e7f8 is on live DB
"""

from __future__ import annotations

import json
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


# ---------------------------------------------------------------------------
# Helpers for update_booking tests (T2.6 / T2.7)
# ---------------------------------------------------------------------------

# Ex-parents that must NOT fire variant_required after migration a3b4c5d6e7f8.
# Design AR4: Barro and Tratamiento Facial omitted — they retain legitimate variants.
EX_PARENTS_NOW_CLEAN: list[str] = [
    "Tinte",
    # "Mechas" excluded: retains legitimate zone-based variants (Mechas Localizadas,
    # Mechas Localizadas Exprés) that are NOT duration-delta — variant gate correctly fires.
    "Tratamiento Anticelulítico Completo",
]

# Valid next_step values when the variant gate does NOT fire.
_CLEAN_STEPS = {"offer_slots", "extras_loop_required", "stylist_required", "name_required"}


async def _call_update_booking(services: list[str]) -> dict:
    """Call _update_booking_impl directly, bypassing InjectedState decorator.

    Mirrors the pattern established in tests/integration/booking/test_corte_y_tinte_ambiguous.py.
    """
    from agent.tools.update_booking import _update_booking_impl

    result_json = await _update_booking_impl(
        services=services,
        stylist_name=None,
        no_preference_stylist=False,
        date_iso=None,
        audience=None,
        date_text=None,
        customer_full_name=None,
        notes=None,
        no_more_services=False,
        extras_asked=False,
        notes_asked=False,
        customer_known=False,
        slot_iso=None,
        messages=[],
    )
    return json.loads(result_json)


# ---------------------------------------------------------------------------
# T2.6 [RED → GREEN] — Prod replay: "corte y tinte" no Tinte variant gate
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_prod_replay_corte_y_tinte_no_tinte_variant_required(seeded_session) -> None:
    """REQ-TE-6: Prod replay — update_booking(['corte de mujer', 'tinte']) must NOT
    return variant_required for a Tinte-family service after migration a3b4c5d6e7f8.

    Acceptable outcomes:
      - next_step='audience_required' for Corte (valid audience disambiguation)
      - next_step in _CLEAN_STEPS once both services are resolved
      - variant_required ONLY if the candidates are NOT Tinte-family duration variants

    NOT acceptable:
      - variant_required where payload.candidates contain 'Tinte Extra' or any
        duration-delta Tinte child.

    GREEN after migration a3b4c5d6e7f8 is applied — Tinte has no variant children.
    RED if Tinte Extra is still service_type='variant' with parent='Tinte'.
    """
    if not _postgres_reachable():
        pytest.skip("Postgres not reachable — skipping prod replay integration test")

    result = await _call_update_booking(services=["corte de mujer", "tinte"])

    next_step = result.get("next_step")
    payload = result.get("payload", {})
    candidates = payload.get("candidates", [])

    if next_step == "variant_required":
        # Allowed ONLY if the candidates are NOT Tinte-family duration variants
        tinte_family = {
            "tinte extra",
            "tinte normal",
        }
        candidate_terms = {
            (c.get("service_term") or c.get("name") or "").lower()
            for c in candidates
            if isinstance(c, dict)
        }
        duration_gate_candidates = candidate_terms & tinte_family
        assert not duration_gate_candidates, (
            f"variant_required fired for Tinte-family duration variant(s): "
            f"{duration_gate_candidates}. "
            "After migration a3b4c5d6e7f8, Tinte Extra must be service_type=addon — "
            "the variant gate must NOT present it as a customer choice. "
            f"Full result: {result}"
        )
    # If next_step is audience_required (for corte) or any clean step, test passes.
    # No assertion needed — the guard above is the key invariant.


# ---------------------------------------------------------------------------
# T2.7 [RED → GREEN] — Parametrized: ex-parents do not fire variant_required
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("principal_name", EX_PARENTS_NOW_CLEAN)
async def test_ex_parent_no_longer_triggers_variant_gate(principal_name: str) -> None:
    """REQ-TE-2: Ex-parent principals (Tinte, Mechas, Anticelulítico Completo) must
    NOT return variant_required after migration a3b4c5d6e7f8 removes their only
    duration-delta variant children.

    Design AR4: Barro and Tratamiento Facial are intentionally excluded from this
    parametrization because they retain legitimate customer-facing variant children
    (Barro Gold and none respectively — but Tratamiento Facial's status depends on
    whether other children remain).

    GREEN after migration a3b4c5d6e7f8. RED if duration-delta children are still
    present as service_type='variant'.
    """
    if not _postgres_reachable():
        pytest.skip("Postgres not reachable — skipping ex-parent variant gate test")

    result = await _call_update_booking(services=[principal_name])
    next_step = result.get("next_step")

    assert next_step != "variant_required", (
        f"update_booking(services=['{principal_name}']) returned next_step='variant_required'. "
        f"After migration a3b4c5d6e7f8, {principal_name} must have no duration-delta variant "
        f"children — the variant gate must NOT fire. "
        f"Full result: {result}"
    )
