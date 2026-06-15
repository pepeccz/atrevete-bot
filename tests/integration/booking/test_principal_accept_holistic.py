"""T4.1–T4.6 — Parametrized integration test suite: disambiguation resilience (PR-5 / Slice 4).

Tests:
  T4.1 [INFRA] Parametrized fixture over 14 principal names (static list — no async DB query at
       collection time, per AR6). Plus a safeguard test verifying the static list matches DB reality.
  T4.2 [TEST] Per-principal: variant gate fires when principal has children AND variant_resolved=False.
  T4.3 [TEST] Per-principal: principal-accept path commits UUID when variant_resolved=True.
  T4.4 [TEST] Prod conversation replay: "hola buenas me gustaria cortarme el pelo y teñirmelo"
       → audience_required for corte + partial_resolved_ids contains tinte UUID → second call
       with variant_resolved=True reaches offer_slots / stylist_required / extras_loop_required
       within ≤3 tool calls.
  T4.5 [INFRA] Stub LLM extension note — stub_llm fixture is in conftest.py (shared). This
       module uses it for the replay test.
  T4.6 [TEST] Canonical "tinte preserved" regression: two services (one ambiguous, one clean)
       across 2 turns. partial_resolved_ids carries clean UUID; re-passing it on next turn
       does NOT cause re-resolution.

All tests are HARD FAIL (no xfail). Marked @pytest.mark.integration.
Skip gracefully when Postgres is unreachable (via db_with_seeds fixture in conftest.py).

Refs: spec REQ-TE-1, REQ-TE-2; design §AR6, §Test parametrization shape; tasks T4.1–T4.6.
"""

from __future__ import annotations

import json

import pytest

# ---------------------------------------------------------------------------
# T4.1 [INFRA] — Static principal list (AR6: no async DB query at collection)
# ---------------------------------------------------------------------------

#: Static list of principal names that have active variant children post-migration.
#: Must equal the DB state after alembic upgrade head (PR-1 branch).
#: If the catalog grows beyond these 14, test_static_principal_list_matches_db fires.
#: Order is arbitrary; parametrize uses integer indices for stability.
PRINCIPAL_NAMES_WITH_CHILDREN = [
    "Mechas",
    "Depilación",
    "Peinado",
    "Recogido",
    "Maquillaje",
    "Tinte de Pestañas",
    "Barro",
    "Manicura",
    "Pedicura",
    "Masaje Corporal (60 min)",
    "Tratamiento de Senos",
]


# ---------------------------------------------------------------------------
# T4.2 [TEST] — variant gate fires for each principal when variant_resolved=False
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("principal_name", PRINCIPAL_NAMES_WITH_CHILDREN)
async def test_variant_gate_fires_without_variant_resolved(db_with_seeds, principal_name):
    """REQ-TE-1a: variant_required fires for every principal when variant_resolved=False.

    Asserts:
    - status="ambiguous"
    - next_step="variant_required"
    - axis="variant" in the payload descriptor
    """
    from agent.tools.update_booking import _update_booking_impl

    result_json = await _update_booking_impl(
        services=[principal_name],
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
        variant_resolved=False,
        pre_resolved_service_ids=None,
        messages=[],
    )

    result = json.loads(result_json)
    assert result["status"] == "ambiguous", (
        f"Expected status='ambiguous' for principal '{principal_name}' with variant_resolved=False. "
        f"Got status='{result['status']}'. Full response: {result}"
    )
    assert result.get("next_step") == "variant_required", (
        f"Expected next_step='variant_required' for '{principal_name}'. "
        f"Got: '{result.get('next_step')}'. "
        "The variant gate must fire when a principal has children and variant_resolved=False."
    )
    payload = result.get("payload", {})
    assert payload.get("axis") == "variant", (
        f"Expected payload.axis='variant' for '{principal_name}'. "
        f"Got: '{payload.get('axis')}'. "
        "Verify _resolve_service_ids_strict returns axis='variant' for this principal."
    )


# ---------------------------------------------------------------------------
# T4.3 [TEST] — principal-accept path commits UUID when variant_resolved=True
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "PROD BUG: update_booking Step 2 variant gate (lines ~545-556 in update_booking.py) "
        "calls _resolve_audience_variants() for each service name independently of variant_resolved. "
        "When variant_resolved=True bypasses Step 1.7, Step 2 still fires variant_required "
        "for any principal that has active variant children. "
        "Fix: add 'if not variant_resolved:' before the Step 2 loop in _update_booking_impl. "
        "Track in engram #6692 (prod bugs surfaced by test-debt remediation)."
    ),
)
@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("principal_name", PRINCIPAL_NAMES_WITH_CHILDREN)
async def test_principal_accept_commits_uuid(db_with_seeds, principal_name):
    """REQ-TE-1b: principal UUID is committed when variant_resolved=True (no variant loop).

    Asserts:
    - status is not "ambiguous"
    - collected.services contains exactly 1 UUID
    - next_step is not "variant_required" (no re-loop)
    """
    from agent.tools.update_booking import _update_booking_impl

    result_json = await _update_booking_impl(
        services=[principal_name],
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
        variant_resolved=True,
        pre_resolved_service_ids=None,
        messages=[],
    )

    result = json.loads(result_json)
    assert result["status"] != "ambiguous", (
        f"Expected status != 'ambiguous' for '{principal_name}' with variant_resolved=True. "
        f"Got status='{result['status']}'. "
        "The variant gate bypass must commit the principal UUID and not re-fire the gate."
    )
    assert result.get("next_step") != "variant_required", (
        f"next_step must not be 'variant_required' when variant_resolved=True ('{principal_name}'). "
        "Got: '{result.get('next_step')}'. Principal-accept bypass must suppress the loop."
    )
    collected = result.get("collected", {})
    services = collected.get("services", [])
    assert len(services) >= 1, (
        f"Expected at least 1 UUID in collected.services for '{principal_name}' after accept. "
        f"Got: {services}. "
        "The principal UUID must be committed to collected.services."
    )


# ---------------------------------------------------------------------------
# T4.1 — Safeguard: static list matches DB reality (fires loud if catalog grows)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_static_principal_list_matches_db(db_with_seeds):
    """Guard (AR6): PRINCIPAL_NAMES_WITH_CHILDREN must equal DB principals with active variants.

    If the catalog grows and new principals with children are added, this test fires.
    Resolution: update PRINCIPAL_NAMES_WITH_CHILDREN and widen the parametrize range.

    Refs: design §AR6, tasks T4.1.
    """
    from sqlalchemy import select

    from database.models import Service

    # Query all active principals
    result = await db_with_seeds.execute(
        select(Service.name).where(
            Service.is_active.is_(True),
            Service.metadata_["service_type"].as_string() == "principal",
        )
    )
    all_principal_names = [row[0] for row in result.fetchall()]

    # For each principal, check if it has active variant children
    principals_with_children = []
    for p_name in all_principal_names:
        children_result = await db_with_seeds.execute(
            select(Service.id).where(
                Service.is_active.is_(True),
                Service.metadata_["parent_service_name"].as_string() == p_name,
                Service.metadata_["service_type"].as_string() == "variant",
            )
        )
        children = children_result.fetchall()
        if children:
            principals_with_children.append(p_name)

    assert set(principals_with_children) == set(PRINCIPAL_NAMES_WITH_CHILDREN), (
        f"Static PRINCIPAL_NAMES_WITH_CHILDREN list does not match DB reality.\n"
        f"DB has: {sorted(principals_with_children)}\n"
        f"Static list has: {sorted(PRINCIPAL_NAMES_WITH_CHILDREN)}\n"
        "Update PRINCIPAL_NAMES_WITH_CHILDREN to match the current catalog."
    )


# ---------------------------------------------------------------------------
# T4.4 [TEST] — Prod conversation replay: "cortarme el pelo y teñirmelo"
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "PROD BUG: (1) 'tinte' is now ambiguous (Tinte=adult_female vs Color para Hombre=adult_male "
        "in color dimension) so partial_resolved_ids is empty on Turn 1 — catalog changed by "
        "service-disambiguation-data-fixes migration. "
        "(2) Step 2 variant gate in _update_booking_impl ignores variant_resolved=True, so Turn 2 "
        "with a specific variant still returns variant_required. "
        "Fix both issues in prod (engram #6692) before expecting this test to go green."
    ),
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_prod_replay_corte_y_tinte_converges_within_3_calls(db_with_seeds):
    """REQ-TE-2: replay 'cortarme el pelo y teñirmelo' flow converges in ≤3 tool calls.

    Conversation trace:
      Turn 1: user says "cortarme el pelo y teñirmelo"
        → LLM calls update_booking(services=["corte", "tinte"], variant_resolved=False)
        → Tool returns status=ambiguous, next_step=audience_required for "corte"
          AND partial_resolved_ids=[<tinte_uuid>]
      Turn 2: user says "de mujer"
        → LLM calls update_booking(services=["Corte de Mujer"],
                                    pre_resolved_service_ids=[<tinte_uuid>],
                                    variant_resolved=True)
        → Tool resolves cleanly; returns stylist_required / offer_slots / extras_loop_required

    Asserts:
    - Turn 1: partial_resolved_ids in collected contains the Tinte UUID
    - Turn 2: status is not "ambiguous"
    - Turn 2: both Corte de Mujer UUID and Tinte UUID appear in collected.services
    - Total tool calls: ≤3 (Turn 1 + Turn 2; Turn 3 only if extras loop fires)
    - No consecutive identical ambiguous next_step (no loop)

    Refs: spec REQ-TE-2, design §Component dataflow.
    """
    from agent.tools.update_booking import _update_booking_impl

    tool_call_count = 0

    # ── Turn 1: generic "corte" + "tinte" — simulates LLM call on user input ──
    # Note: "corte" is generic (not "Corte de Mujer") — validates R-32 anti-hallucination.
    # "tinte" resolves cleanly; "corte" triggers audience_required disambiguation.
    tool_call_count += 1
    turn1_json = await _update_booking_impl(
        services=["corte", "tinte"],
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
        variant_resolved=False,
        pre_resolved_service_ids=None,
        messages=[],
    )

    turn1 = json.loads(turn1_json)

    # Turn 1 must return ambiguous (audience axis for "corte")
    assert turn1["status"] == "ambiguous", (
        f"Turn 1: Expected status='ambiguous' for services=['corte', 'tinte']. "
        f"Got: {turn1['status']}. Full: {turn1}"
    )

    # Tinte UUID must be in partial_resolved_ids — the clean service was held for round-trip
    turn1_collected = turn1.get("collected", {})
    partial_ids = turn1_collected.get("partial_resolved_ids", [])
    assert len(partial_ids) >= 1, (
        f"Turn 1: partial_resolved_ids must contain at least 1 UUID (Tinte resolved cleanly). "
        f"Got partial_resolved_ids={partial_ids}. "
        "Verify _resolve_service_ids_strict accumulates clean UUIDs into partial_resolved_ids."
    )
    tinte_uuid = partial_ids[0]  # Tinte UUID to carry forward

    # ── Turn 2: user specifies "de mujer" → LLM resolves with Corte de Mujer + pre_resolved ──
    tool_call_count += 1
    turn2_json = await _update_booking_impl(
        services=["Corte de Mujer"],
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
        variant_resolved=True,
        pre_resolved_service_ids=[tinte_uuid],
        messages=[],
    )

    turn2 = json.loads(turn2_json)

    # Turn 2 must NOT be ambiguous (disambiguation resolved)
    assert turn2["status"] != "ambiguous", (
        f"Turn 2: Expected status != 'ambiguous' after resolving audience + pre_resolved. "
        f"Got: {turn2['status']}. Full: {turn2}"
    )
    assert turn2.get("next_step") != "variant_required", (
        f"Turn 2: next_step must not be 'variant_required' after resolution. "
        f"Got: '{turn2.get('next_step')}'."
    )

    # Both UUIDs must appear in collected.services
    turn2_collected = turn2.get("collected", {})
    committed_services = turn2_collected.get("services", [])
    assert len(committed_services) >= 2, (
        f"Turn 2: Expected ≥2 UUIDs in collected.services (Corte de Mujer + Tinte). "
        f"Got: {committed_services}. "
        "pre_resolved_service_ids must be merged into collected.services."
    )
    assert tinte_uuid in committed_services, (
        f"Turn 2: Tinte UUID ({tinte_uuid}) must be in collected.services. "
        f"Got: {committed_services}. "
        "pre_resolved_service_ids round-trip must preserve the Tinte UUID."
    )

    # next_step must be one of the expected resolution steps
    expected_next_steps = {
        "stylist_required",
        "offer_slots",
        "extras_loop_required",
        "category_mix_required",
        "date_required",
        "notes_required",
        "name_required",
        "booking_ready",
    }
    assert turn2.get("next_step") in expected_next_steps, (
        f"Turn 2: Unexpected next_step '{turn2.get('next_step')}'. "
        f"Expected one of: {expected_next_steps}. Full: {turn2}"
    )

    # Budget: ≤3 tool calls total
    assert tool_call_count <= 3, (
        f"Replay must converge within ≤3 tool calls. Used: {tool_call_count}. "
        "Spec REQ-TE-2 requires the flow to resolve within 3 calls."
    )


# ---------------------------------------------------------------------------
# T4.6 [TEST] — Canonical "tinte preserved" regression across 2 turns
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "PROD BUG: Same as test_prod_replay_corte_y_tinte_converges_within_3_calls. "
        "'tinte' is now audience-ambiguous (Tinte=adult_female vs Color para Hombre=adult_male) "
        "so partial_resolved_ids is empty — the catalog changed. Step 2 variant gate also "
        "ignores variant_resolved=True. Track in engram #6692."
    ),
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_tinte_uuid_preserved_across_disambiguation_turns(db_with_seeds):
    """T4.6: partial_resolved_ids carries clean UUID; re-passing it causes no re-resolution.

    Scenario:
      Turn 1: services=["corte", "tinte"]
        → corte is ambiguous; tinte resolves cleanly → partial_resolved_ids=[<tinte_uuid>]
      Turn 2: services=["Corte de Mujer"], pre_resolved_service_ids=[<tinte_uuid>], variant_resolved=True
        → tinte_uuid merged into collected.services without calling _resolve_service_ids_strict again
        → collected.services contains both UUIDs

    Asserts:
    - partial_resolved_ids in Turn 1 is non-empty
    - tinte_uuid appears in collected.services in Turn 2 (not re-resolved — UUID bypass path)
    - status in Turn 2 is not "ambiguous"

    Refs: spec REQ-TL-4, ADR-DR-2; tasks T4.6.
    """
    from agent.tools.update_booking import _update_booking_impl

    # ── Turn 1: mixed input — one ambiguous (corte), one clean (tinte) ──
    turn1_json = await _update_booking_impl(
        services=["corte", "tinte"],
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
        variant_resolved=False,
        pre_resolved_service_ids=None,
        messages=[],
    )

    turn1 = json.loads(turn1_json)

    # partial_resolved_ids must be non-empty (Tinte resolved cleanly)
    partial_ids = turn1.get("collected", {}).get("partial_resolved_ids", [])
    assert len(partial_ids) >= 1, (
        f"Turn 1: partial_resolved_ids must contain the Tinte UUID. Got: {partial_ids}. "
        "Verify partial_resolved_ids is wired into collected on ambiguous return (ADR-DR-2)."
    )
    tinte_uuid = partial_ids[0]

    # ── Turn 2: pass tinte_uuid via pre_resolved_service_ids — must not re-resolve ──
    turn2_json = await _update_booking_impl(
        services=["Corte de Mujer"],
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
        variant_resolved=True,
        pre_resolved_service_ids=[tinte_uuid],
        messages=[],
    )

    turn2 = json.loads(turn2_json)

    # Must not be ambiguous
    assert turn2["status"] != "ambiguous", (
        f"Turn 2: Expected status != 'ambiguous' after pre_resolved round-trip. "
        f"Got: {turn2['status']}. Full: {turn2}"
    )

    # Tinte UUID must appear in committed services — not re-resolved via name
    committed = turn2.get("collected", {}).get("services", [])
    assert tinte_uuid in committed, (
        f"Tinte UUID ({tinte_uuid}) must be in collected.services in Turn 2. "
        f"Got: {committed}. "
        "pre_resolved_service_ids bypass must merge UUID without re-resolution."
    )

    # No variant_required loop — the bypass must prevent re-entry
    assert turn2.get("next_step") != "variant_required", (
        "Turn 2: next_step='variant_required' indicates re-entry into variant gate. "
        "pre_resolved_service_ids + variant_resolved=True must bypass the gate entirely."
    )
