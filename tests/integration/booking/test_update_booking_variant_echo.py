"""T4/T5/T6 — end-to-end regression coverage for the variant/audience echo fix.

Reproduces the 2026-08-10 WhatsApp prod bug (customer names "peinado largo",
gets asked "which kind of peinado?" a second time) and locks in the fix at
the `_update_booking_impl` tool boundary:

  T4: prod transcript replay — an explicit child-variant name resolves within
      one turn, without `variant_resolved` ever needing to be True.
  T5: `collected.variant_resolved` / `collected.audience` round-trip echo,
      proven on BOTH a success response and a Step-1.7 `ambiguous` response
      (the ambiguous-path echo is the RED proof for design decision D-A —
      the draft's echo, appended at the end of the function, never reached
      any early-return path).
  T6: Step 2's `variant_required` rejection carries `collected` but MUST NOT
      carry `partial_resolved_ids` (design decision D-B) — leaking it would
      let the model bypass name resolution and silently book the un-confirmed
      principal via `pre_resolved_service_ids`.

Skip gracefully when Postgres is unreachable (via db_with_seeds fixture in
conftest.py).

Refs: spec "End-to-end regression coverage", "variant_resolved / audience
round-trip echo", "Step 2 variant-loop gating"; design D-A, D-B; tasks 1.4.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import delete

from database.models import Service, ServiceCategory


async def _call_update_booking(
    services: list[str] | None,
    *,
    variant_resolved: bool = False,
    audience: str | None = None,
    pre_resolved_service_ids: list[str] | None = None,
) -> dict:
    """Thin wrapper around `_update_booking_impl` with the non-relevant args defaulted."""
    from agent.tools.update_booking import _update_booking_impl

    result_json = await _update_booking_impl(
        services=services,
        stylist_name=None,
        no_preference_stylist=False,
        date_iso=None,
        audience=audience,
        date_text=None,
        customer_full_name=None,
        notes=None,
        no_more_services=False,
        extras_asked=False,
        notes_asked=False,
        customer_known=False,
        slot_iso=None,
        variant_resolved=variant_resolved,
        pre_resolved_service_ids=pre_resolved_service_ids,
        messages=[],
    )
    return json.loads(result_json)


# ---------------------------------------------------------------------------
# T4 — Prod transcript replay: "peinado" → variant_required → "Peinado Largo"
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_prod_replay_peinado_largo_resolves_same_turn(db_with_seeds):
    """Replays the exact 2026-08-10 transcript against `_update_booking_impl`.

    Turn 1: services=["peinado"] (the family) → variant_required, nothing committed.
    Turn 2: services=["Peinado Largo"] (the explicit child), `variant_resolved`
        NEVER set True → must commit the child UUID in the same turn, not
        re-ask. This is the customer-facing contract the prod bug broke.
    """
    turn1 = await _call_update_booking(["peinado"])
    assert turn1["status"] == "ambiguous", (
        f"Turn 1: expected status='ambiguous' for the bare family term 'peinado'. Got: {turn1}"
    )
    assert turn1.get("next_step") == "variant_required", (
        f"Turn 1: expected next_step='variant_required'. Got: {turn1.get('next_step')}"
    )

    # Turn 2 — the customer answers with the explicit child name. `variant_resolved`
    # is intentionally NEVER passed here: this is the exact prod bug reproduction.
    turn2 = await _call_update_booking(["Peinado Largo"])
    assert turn2["status"] != "ambiguous", (
        f"Turn 2: naming the explicit variant must not re-trigger ambiguity. Got: {turn2}"
    )
    assert turn2.get("next_step") != "variant_required", (
        f"Turn 2: must not re-ask 'which kind of peinado?' — this is the prod bug. "
        f"Got next_step={turn2.get('next_step')!r}. Full: {turn2}"
    )
    committed = turn2.get("collected", {}).get("service_ids", [])
    assert len(committed) == 1, (
        f"Turn 2: expected exactly 1 committed UUID (the child variant). Got: {committed}"
    )


# ---------------------------------------------------------------------------
# T5 — variant_resolved / audience round-trip echo
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_echo_present_on_success_response(db_with_seeds):
    """Success path: both flags, when set, are echoed back in `collected`."""
    result = await _call_update_booking(
        ["Peinado Largo"], variant_resolved=True, audience="adult_female"
    )
    assert result["status"] != "ambiguous", f"Expected a non-ambiguous response. Got: {result}"
    collected = result.get("collected", {})
    assert collected.get("variant_resolved") is True, (
        f"Expected collected.variant_resolved == True on the success path. Got: {collected}"
    )
    assert collected.get("audience") == "adult_female", (
        f"Expected collected.audience == 'adult_female' on the success path. Got: {collected}"
    )


@pytest.fixture
async def audience_family_without_female(db_with_seeds):
    """Seed a synthetic audience-ambiguous family whose members are adult_male / child.

    Deliberately does NOT include an 'adult_female' member. Used to prove the
    Step-1.7 `ambiguous` response still echoes `collected.variant_resolved` /
    `collected.audience` even when the passed audience does not resolve the
    ambiguity for THIS family (i.e., the echo is unconditional on the flags
    themselves, not on whether they closed the gate for the current term).
    """
    stem = "zzztestfam"
    names = [f"{stem} de Ellos Test", f"{stem} de Peques Test"]
    audiences = ["adult_male", "child_male"]

    await db_with_seeds.execute(delete(Service).where(Service.name.in_(names)))
    await db_with_seeds.commit()

    for name, aud in zip(names, audiences, strict=True):
        svc = Service(
            id=uuid4(),
            name=name,
            category=ServiceCategory.HAIRDRESSING,
            duration_minutes=30,
            is_active=True,
            audience=aud,
            metadata_={
                "service_type": "principal",
                "dimension": "zzztest_dimension",
                "parent_service_name": None,
            },
        )
        db_with_seeds.add(svc)
    await db_with_seeds.commit()

    yield stem

    await db_with_seeds.execute(delete(Service).where(Service.name.in_(names)))
    await db_with_seeds.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_echo_present_on_ambiguous_response(db_with_seeds, audience_family_without_female):
    """Step-1.7 ambiguous path: the flags must still be echoed (D-A RED proof).

    The bare family stem term is audience-ambiguous, and the passed
    audience='adult_female' does not match either family member — so the gate
    still fires. The `collected` echo of `variant_resolved` / `audience` must
    be present anyway, because the seeding happens once at request start,
    before any early return — not appended only on the success path.
    """
    result = await _call_update_booking(
        [audience_family_without_female], variant_resolved=True, audience="adult_female"
    )
    assert result["status"] == "ambiguous", f"Expected an ambiguous response. Got: {result}"
    assert result.get("next_step") == "audience_required", (
        f"Expected next_step='audience_required'. Got: {result.get('next_step')}"
    )
    collected = result.get("collected", {})
    assert collected.get("variant_resolved") is True, (
        f"Expected collected.variant_resolved == True on the ambiguous path — this is the "
        f"D-A proof (draft's echo never reached this early return). Got: {collected}"
    )
    assert collected.get("audience") == "adult_female", (
        f"Expected collected.audience == 'adult_female' on the ambiguous path. Got: {collected}"
    )


# ---------------------------------------------------------------------------
# T6 — Step 2 rejection must carry collected but NOT partial_resolved_ids
# ---------------------------------------------------------------------------


@pytest.fixture
async def step2_backstop_principal(db_with_seeds):
    """Seed a principal + 1 active child dedicated to forcing the Step 2 backstop.

    Step 2 is a dead-for-children, principal-only backstop post-fix (design D-D):
    it only fires when Step 1.7 (`_resolve_service_ids_strict`) missed a
    principal that DOES have active children. This fixture pairs with a
    monkeypatch of `_resolve_service_ids_strict` (in the test body) to
    simulate exactly that "Step 1.7 missed it" condition without relying on
    a fragile prod-catalog synonym collision.
    """
    principal = "Zzzt6 Principal Test"
    child = "Zzzt6 Principal Test Variante"

    await db_with_seeds.execute(delete(Service).where(Service.name.in_([principal, child])))
    await db_with_seeds.commit()

    principal_svc = Service(
        id=uuid4(),
        name=principal,
        category=ServiceCategory.HAIRDRESSING,
        duration_minutes=30,
        is_active=True,
        metadata_={"service_type": "principal", "dimension": "zzzt6_dim", "parent_service_name": None},
    )
    child_svc = Service(
        id=uuid4(),
        name=child,
        category=ServiceCategory.HAIRDRESSING,
        duration_minutes=30,
        is_active=True,
        metadata_={
            "service_type": "variant",
            "dimension": "zzzt6_dim",
            "parent_service_name": principal,
        },
    )
    db_with_seeds.add_all([principal_svc, child_svc])
    await db_with_seeds.commit()

    yield principal

    await db_with_seeds.execute(delete(Service).where(Service.name.in_([principal, child])))
    await db_with_seeds.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_step2_rejection_carries_collected_without_partial_resolved_ids(
    db_with_seeds, step2_backstop_principal, monkeypatch
):
    """Step 2's `variant_required` rejection: `collected` present, `partial_resolved_ids` absent.

    Step 1.7 is monkeypatched to a clean (non-ambiguous) resolution — simulating
    the "Step 1.7 missed it" backstop condition — so the raw `services` loop in
    Step 2 is what detects the variant ambiguity for real, against the seeded
    principal-with-children. `variant_resolved=False` so Step 2 is not gated off.

    D-B: at this point `resolved_ids` inside the closure would hold the
    principal's UUID if leaked as `partial_resolved_ids` — that would let the
    model re-pass it as `pre_resolved_service_ids` and silently bypass the
    variant gate. Flags only, no partial_resolved_ids.
    """

    async def _fake_resolve_service_ids_strict(session, service_names, audience=None):
        return ([], [], [], [])

    monkeypatch.setattr(
        "agent.tools._booking_helpers._resolve_service_ids_strict",
        _fake_resolve_service_ids_strict,
    )

    result = await _call_update_booking(
        [step2_backstop_principal], variant_resolved=False, audience="adult_female"
    )

    assert result["status"] == "rejected", f"Expected status='rejected' from Step 2. Got: {result}"
    assert result.get("next_step") == "variant_required", (
        f"Expected next_step='variant_required' from Step 2. Got: {result.get('next_step')}"
    )
    assert "collected" in result and result["collected"] is not None, (
        f"Step 2's rejection must carry `collected` (D-A seeding). Got: {result}"
    )
    collected = result["collected"]
    assert collected.get("audience") == "adult_female", (
        f"Expected the seeded audience echo to survive into Step 2's rejection. Got: {collected}"
    )
    assert "partial_resolved_ids" not in collected, (
        f"Step 2's rejection MUST NOT carry partial_resolved_ids (D-B) — resolved_ids here is "
        f"the principal's own UUID, and leaking it lets the model bypass the variant gate via "
        f"pre_resolved_service_ids. Got: {collected}"
    )
