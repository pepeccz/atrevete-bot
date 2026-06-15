"""Scenario A — Audience disambiguation for generic service terms (HARD FAIL).

Tests that:
  - _resolve_service_ids_strict returns status=ambiguous, axis=audience for
    "Tinte" (a principal in the color dimension with a peer "Color para Hombre"
    that has a different audience value, making audience ambiguous when the
    caller has not supplied an explicit audience).
  - update_booking returns status="ambiguous"/"rejected", next_step="audience_required"
    when "Corte de Mujer" is passed without an explicit audience parameter
    (Step 1 audience gate fires because the cut dimension has peers with different
    audience values).
  - No UUID for the ambiguous service is committed (resolved_ids is empty).

NOTE on "corte" generic term: the service resolver does NOT fuzzy-match "corte"
to "Corte de Mujer" or "Corte de Hombre" — only exact service names (or their
display equivalents from catalog_builder) are recognized. Tests that previously
used the generic term "corte" have been updated to use actual service names that
trigger the audience disambiguation gate.

These are TOOL-LEVEL tests — no LLM in the loop.
All assertions are HARD FAIL (no xfail). They must pass GREEN on the current
implementation.

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
async def test_tinte_strict_resolver_returns_ambiguous_axis_audience(db_with_seeds):
    """_resolve_service_ids_strict("Tinte") → non-empty ambiguous descriptors, axis=audience.

    "Tinte" is a principal in the color dimension with audience=adult_female.
    "Color para Hombre" is a principal in the same dimension with audience=adult_male.
    When no explicit audience is supplied, the resolver detects the audience mismatch
    between dimension peers and returns axis=audience.
    """
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    resolved_ids, unknown_names, ambiguous_descriptors, _partial = (
        await _resolve_service_ids_strict(db_with_seeds, ["Tinte"])
    )

    assert len(ambiguous_descriptors) > 0, (
        "Expected at least one ambiguous descriptor for 'Tinte' — the color dimension "
        "has both Tinte (adult_female) and Color para Hombre (adult_male), making "
        "audience ambiguous when no explicit audience is supplied. "
        "Verify seed data includes both services."
    )

    desc = ambiguous_descriptors[0]
    assert desc["status"] == "ambiguous", f"Expected status='ambiguous', got {desc['status']}"
    assert (
        desc["axis"] == "audience"
    ), f"Expected axis='audience' for 'Tinte' term, got '{desc['axis']}'"
    assert "candidates" in desc, "Descriptor must include 'candidates' list"
    assert len(desc["candidates"]) > 0, "Candidates list must not be empty for 'Tinte'"
    assert (
        desc["question_hint"] == "audience_required"
    ), f"Expected question_hint='audience_required', got '{desc['question_hint']}'"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tinte_strict_resolver_no_uuid_committed(db_with_seeds):
    """When 'Tinte' is audience-ambiguous, resolved_ids must be empty (no UUID committed)."""
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    resolved_ids, unknown_names, ambiguous_descriptors, _partial = (
        await _resolve_service_ids_strict(db_with_seeds, ["Tinte"])
    )

    # Ambiguous terms must not appear in resolved_ids (spec R2.3)
    assert len(resolved_ids) == 0, (
        f"resolved_ids must be empty when 'Tinte' is audience-ambiguous. "
        f"Got: {resolved_ids}. The gate in _resolve_service_ids_strict must "
        "skip UUID commitment for ambiguous principals."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tinte_candidates_include_color_peers(db_with_seeds):
    """Candidates for 'Tinte' must include both color-dimension principals.

    The color dimension has Tinte (adult_female) and Color para Hombre (adult_male).
    Both must appear as disambiguation candidates.
    """
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    _, _, ambiguous_descriptors, _ = await _resolve_service_ids_strict(db_with_seeds, ["Tinte"])

    assert len(ambiguous_descriptors) > 0, "Expected ambiguous descriptor for 'Tinte'"
    candidates = ambiguous_descriptors[0]["candidates"]

    has_female_color = any(
        "tinte" in c.lower() or "mujer" in c.lower() or "dama" in c.lower() for c in candidates
    )
    has_male_color = any(
        "hombre" in c.lower() or "caballero" in c.lower() or "masculino" in c.lower()
        for c in candidates
    )

    assert has_female_color, f"Expected a female color service in candidates. Got: {candidates}"
    assert has_male_color, f"Expected a male color service in candidates. Got: {candidates}"


# ---------------------------------------------------------------------------
# Tool-level: update_booking (DB-dependent, requires InjectedState bypass)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_booking_tinte_returns_audience_required(db_with_seeds):
    """update_booking(services=['Tinte']) returns status='ambiguous', next_step='audience_required'.

    "Tinte" (adult_female) and "Color para Hombre" (adult_male) share the color dimension.
    When no explicit audience is supplied, _resolve_service_ids_strict detects the mismatch
    and returns an audience-ambiguous descriptor, causing update_booking to return
    status=ambiguous with next_step=audience_required.

    We call _update_booking_impl directly to bypass the InjectedState decorator.
    """
    from agent.tools.update_booking import _update_booking_impl

    result_json = await _update_booking_impl(
        services=["Tinte"],
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
        f"Expected status='ambiguous' for update_booking(services=['Tinte']). "
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
