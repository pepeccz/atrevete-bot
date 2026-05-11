"""Scenario A — Audience disambiguation for 'corte y tinte' (HARD FAIL).

Tests that:
  - _resolve_service_ids_strict returns status=ambiguous, axis=audience for
    the term "corte" (generic, null-audience principal with audience-tagged peers).
  - update_booking returns status="ambiguous", next_step="audience_required".
  - No UUID for "corte" is committed (resolved_ids is empty).

These are TOOL-LEVEL tests — no LLM in the loop.
All assertions are HARD FAIL (no xfail). They must pass GREEN on the PR-1+PR-2
merged implementation.

Refs: spec Scenario A, tasks 4.2, design §2 Slice 4
"""

from __future__ import annotations

import json

import pytest

# ---------------------------------------------------------------------------
# Tool-level: _resolve_service_ids_strict (DB-dependent)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_corte_strict_resolver_returns_ambiguous_axis_audience(db_with_seeds):
    """_resolve_service_ids_strict("corte") → non-empty ambiguous descriptors, axis=audience."""
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    resolved_ids, unknown_names, ambiguous_descriptors = await _resolve_service_ids_strict(
        db_with_seeds, ["corte"]
    )

    assert len(ambiguous_descriptors) > 0, (
        "Expected at least one ambiguous descriptor for 'corte' — the generic term "
        "should map to a null-audience principal with audience-tagged peers. "
        "Verify that PR-2 (_resolve_service_ids_strict) is merged and PR-1 data "
        "(Tinte.audience='adult_female') is applied."
    )

    desc = ambiguous_descriptors[0]
    assert desc["status"] == "ambiguous", f"Expected status='ambiguous', got {desc['status']}"
    assert (
        desc["axis"] == "audience"
    ), f"Expected axis='audience' for 'corte' term, got '{desc['axis']}'"
    assert "candidates" in desc, "Descriptor must include 'candidates' list"
    assert len(desc["candidates"]) > 0, "Candidates list must not be empty for 'corte'"
    assert (
        desc["question_hint"] == "audience_required"
    ), f"Expected question_hint='audience_required', got '{desc['question_hint']}'"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_corte_strict_resolver_no_uuid_committed(db_with_seeds):
    """When 'corte' is ambiguous, resolved_ids must be empty (no UUID committed)."""
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    resolved_ids, unknown_names, ambiguous_descriptors = await _resolve_service_ids_strict(
        db_with_seeds, ["corte"]
    )

    # Ambiguous terms must not appear in resolved_ids (spec R2.3)
    assert len(resolved_ids) == 0, (
        f"resolved_ids must be empty when 'corte' is ambiguous. "
        f"Got: {resolved_ids}. The gate in _resolve_service_ids_strict must "
        "skip UUID commitment for ambiguous principals."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_corte_candidates_include_cut_variants(db_with_seeds):
    """Candidates for 'corte' must include at least Corte de Mujer and Corte de Hombre."""
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    _, _, ambiguous_descriptors = await _resolve_service_ids_strict(db_with_seeds, ["corte"])

    assert len(ambiguous_descriptors) > 0, "Expected ambiguous descriptor for 'corte'"
    candidates = ambiguous_descriptors[0]["candidates"]

    # At minimum, the corte family should have female and male variants
    candidate_lower = [c.lower() for c in candidates]
    has_female = any("mujer" in c or "dama" in c for c in candidate_lower)
    has_male = any("hombre" in c or "caballero" in c for c in candidate_lower)

    assert has_female, f"Expected a female cut variant in candidates. Got: {candidates}"
    assert has_male, f"Expected a male cut variant in candidates. Got: {candidates}"


# ---------------------------------------------------------------------------
# Tool-level: update_booking (DB-dependent, requires InjectedState bypass)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_booking_corte_returns_ambiguous(db_with_seeds):
    """update_booking(services=['corte']) returns status='ambiguous', next_step='audience_required'.

    We call _update_booking_impl directly to bypass the InjectedState decorator
    — same approach used in unit tests for update_booking.
    """
    from agent.tools.update_booking import _update_booking_impl

    result_json = await _update_booking_impl(
        services=["corte"],
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
        f"Expected status='ambiguous' for update_booking(services=['corte']). "
        f"Got status='{result['status']}'. Full response: {result}"
    )
    assert (
        result.get("next_step") == "audience_required"
    ), f"Expected next_step='audience_required', got '{result.get('next_step')}'"
    # Payload must carry the descriptor with axis=audience
    payload = result.get("payload", {})
    assert (
        payload.get("axis") == "audience"
    ), f"Expected payload.axis='audience', got '{payload.get('axis')}'"
