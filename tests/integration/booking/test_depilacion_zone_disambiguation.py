"""Scenario B — Variant disambiguation for 'depilación' (HARD FAIL).

Tests that:
  - Post-migration DB has "Depilación" principal (not "Depilación de Piernas Enteras").
  - _resolve_service_ids_strict("depilación") returns axis=variant with candidates
    that include "Piernas Enteras" (the new variant from PR-1).
  - No UUID is committed before a zone is selected.

These are TOOL-LEVEL tests — no LLM in the loop.
All assertions are HARD FAIL (no xfail). Must pass GREEN on PR-1+PR-2 merged impl.

Refs: spec Scenario B, R1.2, R2.2, tasks 4.3, design §2 Slice 4
"""

from __future__ import annotations

import json

import pytest

# ---------------------------------------------------------------------------
# DB structural: Depilación principal exists post-migration (DB-dependent)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_depilacion_principal_exists_post_migration(db_with_seeds):
    """Post-migration: 'Depilación' principal row exists; old name is gone."""
    from sqlalchemy import text

    # New principal name
    result = await db_with_seeds.execute(
        text(
            "SELECT COUNT(*) FROM services "
            "WHERE name = 'Depilación' "
            "AND metadata_->>'service_type' = 'principal'"
        )
    )
    count = result.scalar()
    assert count == 1, (
        f"Expected exactly 1 'Depilación' principal row post-migration. Got {count}. "
        "Verify PR-1 migration (a7b8c9d0e1f2) has been applied."
    )

    # Old principal name must be gone
    result_old = await db_with_seeds.execute(
        text(
            "SELECT COUNT(*) FROM services "
            "WHERE name = 'Depilación de Piernas Enteras' "
            "AND metadata_->>'service_type' = 'principal'"
        )
    )
    old_count = result_old.scalar()
    assert old_count == 0, (
        f"Old principal 'Depilación de Piernas Enteras' must not exist post-migration. "
        f"Found {old_count} row(s). Run: alembic upgrade head."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_piernas_enteras_variant_exists(db_with_seeds):
    """Post-migration: 'Piernas Enteras' variant row exists under 'Depilación'."""
    from sqlalchemy import text

    result = await db_with_seeds.execute(
        text(
            "SELECT COUNT(*) FROM services "
            "WHERE name = 'Piernas Enteras' "
            "AND metadata_->>'parent_service_name' = 'Depilación'"
        )
    )
    count = result.scalar()
    assert count == 1, (
        f"Expected 'Piernas Enteras' variant under 'Depilación'. Got {count} row(s). "
        "Verify PR-1 migration inserted the new variant."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_depilacion_has_twelve_variants(db_with_seeds):
    """Post-migration: exactly 12 depilación variants point to 'Depilación' parent."""
    from sqlalchemy import text

    result = await db_with_seeds.execute(
        text(
            "SELECT COUNT(*) FROM services "
            "WHERE metadata_->>'parent_service_name' = 'Depilación'"
        )
    )
    count = result.scalar()
    assert count == 12, (
        f"Expected 12 wax variants with parent_service_name='Depilación'. Got {count}. "
        "11 original variants + 'Piernas Enteras' = 12. "
        "Verify PR-1 migration updated all parent_service_name references."
    )


# ---------------------------------------------------------------------------
# Tool-level: _resolve_service_ids_strict (DB-dependent)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_depilacion_strict_resolver_returns_ambiguous_axis_variant(db_with_seeds):
    """_resolve_service_ids_strict('depilación') → axis=variant, non-empty candidates."""
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    resolved_ids, unknown_names, ambiguous_descriptors, _partial = (
        await _resolve_service_ids_strict(db_with_seeds, ["depilación"])
    )

    assert len(ambiguous_descriptors) > 0, (
        "Expected ambiguous descriptor for 'depilación' — the principal has 12 variants "
        "and no single one should be auto-selected. "
        "Verify PR-2 _resolve_service_ids_strict is merged and PR-1 data is applied."
    )

    desc = ambiguous_descriptors[0]
    assert desc["status"] == "ambiguous", f"Expected status='ambiguous', got {desc['status']}"
    assert desc["axis"] == "variant", (
        f"Expected axis='variant' for 'depilación' (multi-variant principal). "
        f"Got axis='{desc['axis']}'. "
        "The variant disambiguation gate must fire for depilación."
    )
    assert (
        desc["question_hint"] == "variant_required"
    ), f"Expected question_hint='variant_required', got '{desc['question_hint']}'"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_depilacion_candidates_include_piernas_enteras(db_with_seeds):
    """Candidates for 'depilación' must include the new 'Piernas Enteras' variant (PR-1)."""
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    _, _, ambiguous_descriptors, _ = await _resolve_service_ids_strict(db_with_seeds, ["depilación"])

    assert len(ambiguous_descriptors) > 0, "Expected ambiguous descriptor for 'depilación'"
    candidates = ambiguous_descriptors[0]["candidates"]

    candidate_lower = [c.lower() for c in candidates]
    assert any("piernas enteras" in c for c in candidate_lower), (
        f"Expected 'Piernas Enteras' in candidates for 'depilación'. Got: {candidates}. "
        "Verify PR-1 inserted the Piernas Enteras variant."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_depilacion_no_uuid_committed_before_zone_selected(db_with_seeds):
    """No UUID committed to resolved_ids when 'depilación' is ambiguous (spec R2.3)."""
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    resolved_ids, unknown_names, ambiguous_descriptors, _partial = (
        await _resolve_service_ids_strict(db_with_seeds, ["depilación"])
    )

    assert len(resolved_ids) == 0, (
        f"resolved_ids must be empty when 'depilación' is ambiguous. Got: {resolved_ids}. "
        "The gate must block UUID commitment until zone is selected."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_booking_depilacion_returns_ambiguous(db_with_seeds):
    """update_booking(services=['depilación']) → status='ambiguous', axis='variant'."""
    from agent.tools.update_booking import _update_booking_impl

    result_json = await _update_booking_impl(
        services=["depilación"],
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

    result = json.loads(result_json)
    assert result["status"] == "ambiguous", (
        f"Expected status='ambiguous' for update_booking(services=['depilación']). "
        f"Got: {result}"
    )
    payload = result.get("payload", {})
    assert (
        payload.get("axis") == "variant"
    ), f"Expected payload.axis='variant', got '{payload.get('axis')}'"
