"""Change N (N3) — consecutive-rejection strikes → deterministic escalation.

V6 audit C3: after book/update_booking validator rejections the bot loops
(fabricate UUID → reject → re-offer → fabricate again) and never exits.
The strike layer turns the 2nd consecutive identical rejection of the SAME
tool into an explicit escalation directive so the LLM has a deterministic
exit instead of relying on self-correction.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.tools._rejection_strikes import (
    REJECTION_ESCALATION_THRESHOLD,
    apply_rejection_strike,
    count_consecutive_rejections,
)
from agent.tools.schemas import ToolResponse


def _tool_msg(tool_name: str, status: str, next_step: str | None) -> ToolMessage:
    return ToolMessage(
        content=json.dumps({"status": status, "next_step": next_step}),
        tool_call_id="tc",
        name=tool_name,
    )


# ---------------------------------------------------------------------------
# count_consecutive_rejections
# ---------------------------------------------------------------------------


def test_counter_zero_without_prior_rejections():
    assert count_consecutive_rejections([], "book", "reoffer_slots") == 0
    msgs = [HumanMessage(content="hola"), AIMessage(content="ok")]
    assert count_consecutive_rejections(msgs, "book", "reoffer_slots") == 0


def test_counter_increments_on_consecutive_same_rejection():
    msgs = [
        _tool_msg("book", "rejected", "reoffer_slots"),
        AIMessage(content="lo intento de nuevo"),
        _tool_msg("book", "rejected", "reoffer_slots"),
    ]
    assert count_consecutive_rejections(msgs, "book", "reoffer_slots") == 2


def test_counter_resets_on_success_of_same_tool():
    msgs = [
        _tool_msg("book", "rejected", "reoffer_slots"),
        _tool_msg("book", "ok", None),
        _tool_msg("book", "rejected", "reoffer_slots"),
    ]
    assert count_consecutive_rejections(msgs, "book", "reoffer_slots") == 1


def test_counter_ignores_other_tools():
    """A check_availability call between two book rejections does not reset."""
    msgs = [
        _tool_msg("book", "rejected", "reoffer_slots"),
        _tool_msg("check_availability", "ok", None),
        _tool_msg("book", "rejected", "reoffer_slots"),
    ]
    assert count_consecutive_rejections(msgs, "book", "reoffer_slots") == 2


def test_counter_keyed_by_next_step():
    """Different rejection reasons do not accumulate into the same strike count."""
    msgs = [
        _tool_msg("book", "rejected", "confirmation_required"),
        _tool_msg("book", "rejected", "reoffer_slots"),
    ]
    assert count_consecutive_rejections(msgs, "book", "reoffer_slots") == 1


# ---------------------------------------------------------------------------
# apply_rejection_strike
# ---------------------------------------------------------------------------


def test_first_rejection_passes_through_unchanged():
    response = ToolResponse(
        status="rejected", next_step="reoffer_slots", errors=["El hueco ya no está disponible."]
    )
    out = apply_rejection_strike(response, [], "book")
    assert out.next_step == "reoffer_slots"
    assert out is response


def test_second_consecutive_rejection_becomes_escalation_directive():
    """O4: reoffer_slots is now exempt from the strike counter — must pass through unchanged."""
    prior = [_tool_msg("book", "rejected", "reoffer_slots")]
    response = ToolResponse(
        status="rejected", next_step="reoffer_slots", errors=["El hueco ya no está disponible."]
    )
    out = apply_rejection_strike(response, prior, "book")

    # O4 fix: reoffer_slots is a recoverable gate — must NOT escalate
    assert (
        out.next_step == "reoffer_slots"
    ), "reoffer_slots is exempt from escalation strikes (O4) — must pass through unchanged"
    assert out is response, "Exempt next_steps must return the original response unchanged"


def test_true_validator_rejection_escalates_at_threshold():
    """Non-exempt validator rejections (e.g. invalid_service_ids) still escalate at threshold."""
    prior = [_tool_msg("book", "rejected", "invalid_service_ids")]
    response = ToolResponse(
        status="rejected",
        next_step="invalid_service_ids",
        errors=["service_id inválido: abc. Vuelve a leer el catálogo."],
    )
    out = apply_rejection_strike(response, prior, "book")

    assert (
        out.next_step == "escalation_required"
    ), "Non-exempt rejections (invalid_service_ids) must still escalate at threshold"
    assert out.payload["original_next_step"] == "invalid_service_ids"
    assert out.payload["consecutive_rejections"] == REJECTION_ESCALATION_THRESHOLD
    joined = " ".join(out.errors)
    assert "escalate" in joined
    # P5 — errors must not start with an imperative verb
    ToolResponse.validate_errors_non_imperative(out.errors)


def test_ok_responses_never_transformed():
    prior = [_tool_msg("book", "rejected", "reoffer_slots")] * 3
    response = ToolResponse(status="ok", payload={"appointment_id": "x"})
    out = apply_rejection_strike(response, prior, "book")
    assert out.status == "ok"
    assert out.next_step is None


def test_policy_acceptance_required_is_exempt():
    """The policy gate has its own deterministic escalation (R36) — exempt."""
    prior = [_tool_msg("book", "rejected", "policy_acceptance_required")] * 2
    response = ToolResponse(status="rejected", next_step="policy_acceptance_required")
    out = apply_rejection_strike(response, prior, "book")
    assert out.next_step == "policy_acceptance_required"


def test_reoffer_slots_is_exempt_from_escalation():
    """O4: reoffer_slots is a recoverable gate — must NOT trigger escalation at threshold."""
    prior = [_tool_msg("book", "rejected", "reoffer_slots")] * 3
    response = ToolResponse(
        status="rejected",
        next_step="reoffer_slots",
        errors=["El hueco no está entre los ofrecidos."],
    )
    out = apply_rejection_strike(response, prior, "book")
    assert (
        out.next_step == "reoffer_slots"
    ), "reoffer_slots must be exempt from escalation (O4 fix for V7 laconica failure)"
    assert out is response


def test_pre_book_validation_required_is_exempt_from_escalation():
    """O4: pre_book_validation_required is a normal-flow gate — must be exempt."""
    prior = [_tool_msg("book", "rejected", "pre_book_validation_required")] * 2
    response = ToolResponse(status="rejected", next_step="pre_book_validation_required")
    out = apply_rejection_strike(response, prior, "book")
    assert (
        out.next_step == "pre_book_validation_required"
    ), "pre_book_validation_required is an exempt normal-flow gate (O4)"
    assert out is response


# ---------------------------------------------------------------------------
# book tool integration — 2nd identical rejection escalates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_book_second_consecutive_rejection_confirmation_required_stays_exempt():
    """O4: confirmation_required is now exempt — repeated calls must NOT escalate.

    confirmation_required is a normal-flow gate (client hasn't confirmed yet). It is
    expected in every happy-path booking and must never trigger forced escalation.
    """
    from agent.tools.book import book

    prior = [_tool_msg("book", "rejected", "confirmation_required")]
    state = {
        "customer_phone": "+34999000023",
        "conversation_id": "conv-1",
        "messages": prior,
    }
    raw = await book.ainvoke(
        {
            "service_ids": ["x"],
            "stylist_id": "y",
            "start_iso": "2026-07-01T10:00:00+02:00",
            "customer_full_name": "Ana López",
            "confirmed": False,
            "state": state,
        }
    )
    data = json.loads(raw)
    assert data["status"] == "rejected"
    # O4: confirmation_required is exempt — must NOT escalate to escalation_required
    assert (
        data["next_step"] == "confirmation_required"
    ), "confirmation_required is an exempt normal-flow gate and must never escalate (O4)"


@pytest.mark.asyncio
async def test_book_first_rejection_keeps_original_next_step():
    from agent.tools.book import book

    state = {
        "customer_phone": "+34999000023",
        "conversation_id": "conv-1",
        "messages": [],
    }
    raw = await book.ainvoke(
        {
            "service_ids": ["x"],
            "stylist_id": "y",
            "start_iso": "2026-07-01T10:00:00+02:00",
            "customer_full_name": "Ana López",
            "confirmed": False,
            "state": state,
        }
    )
    data = json.loads(raw)
    assert data["next_step"] == "confirmation_required"


# ---------------------------------------------------------------------------
# FK rejection payload — valid candidates (ground truth for recovery)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_service_ids_failure_includes_valid_candidates():
    """When some IDs are valid, the rejection payload lists the active services
    of the same dimension(s) so the LLM can recover with ground truth."""
    from uuid import uuid4

    from agent.tools._booking_validators import validate_service_ids_exist

    valid_id = uuid4()
    fabricated_id = uuid4()
    cand_a, cand_b = uuid4(), uuid4()

    existence_result = MagicMock()
    existence_result.fetchall.return_value = [(str(valid_id),)]

    dimension_result = MagicMock()
    dimension_result.fetchall.return_value = [("hairdressing",)]

    candidates_result = MagicMock()
    candidates_result.fetchall.return_value = [
        (str(cand_a), "Corte Dama"),
        (str(cand_b), "Corte Caballero"),
    ]

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[existence_result, dimension_result, candidates_result])

    result = await validate_service_ids_exist(session, [valid_id, fabricated_id])

    assert result.ok is False
    assert fabricated_id in result.missing_ids
    candidates = result.payload.get("valid_candidates")
    assert candidates, "FK rejection must include valid candidate services"
    names = {c["name"] for c in candidates}
    assert names == {"Corte Dama", "Corte Caballero"}
    assert all("id" in c for c in candidates)


@pytest.mark.asyncio
async def test_validate_service_ids_candidates_omitted_when_too_many():
    """Candidate list is omitted when larger than the cap (avoid catalog dumps)."""
    from uuid import uuid4

    from agent.tools._booking_validators import (
        _VALID_CANDIDATES_MAX,
        validate_service_ids_exist,
    )

    valid_id = uuid4()
    fabricated_id = uuid4()

    existence_result = MagicMock()
    existence_result.fetchall.return_value = [(str(valid_id),)]

    dimension_result = MagicMock()
    dimension_result.fetchall.return_value = [("hairdressing",)]

    candidates_result = MagicMock()
    candidates_result.fetchall.return_value = [
        (str(uuid4()), f"Servicio {i}") for i in range(_VALID_CANDIDATES_MAX + 1)
    ]

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[existence_result, dimension_result, candidates_result])

    result = await validate_service_ids_exist(session, [valid_id, fabricated_id])

    assert result.ok is False
    assert "valid_candidates" not in result.payload


# ---------------------------------------------------------------------------
# O5 — invalid_service_ids error message must not be confused with availability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_service_ids_message_distinct_from_slot_availability():
    """O5: invalid_service_ids error message must clearly signal a service-resolution problem,
    NOT a slot availability issue (V7 cliente-leal turn 8 wrong message)."""
    from uuid import uuid4

    from agent.tools._booking_validators import validate_service_ids_exist

    fabricated_id = uuid4()

    existence_result = MagicMock()
    existence_result.fetchall.return_value = []  # no valid IDs found

    dimension_result = MagicMock()
    dimension_result.fetchall.return_value = []

    candidates_result = MagicMock()
    candidates_result.fetchall.return_value = []

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[existence_result, dimension_result, candidates_result])

    result = await validate_service_ids_exist(session, [fabricated_id])

    assert result.ok is False
    msg = result.error_message or ""
    # Must mention service resolution problem, not availability
    assert (
        "servicio" in msg.lower()
        or "service" in msg.lower()
        or "catalog" in msg.lower()
        or "catálogo" in msg.lower()
    ), "invalid_service_ids error must reference the service/catalog problem"
    # Must NOT tell LLM to report slot unavailability
    assert (
        "disponib" not in msg.lower() or "NO" in msg
    ), "invalid_service_ids error must not be confused with slot availability messages"
    # Must explicitly forbid the LLM from saying slot is unavailable
    assert (
        "NO digas" in msg or "NO" in msg or "no digas" in msg.lower()
    ), "invalid_service_ids error must explicitly instruct LLM not to confuse with availability"
