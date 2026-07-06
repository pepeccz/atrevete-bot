"""
Tests for manage_appointments_tool module.

Verifies the consolidated tool function signature:
- manage_appointments has action as Literal["list", "cancel", "reschedule", ...]
- customer_phone is injected from state (InjectedState), NOT a tool argument
"""

import inspect
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.tools.manage_appointments_tool import manage_appointments


def _get_sig():
    fn = (
        manage_appointments.coroutine
        if hasattr(manage_appointments, "coroutine")
        else manage_appointments
    )
    return inspect.signature(fn)


def test_tool_has_action_param():
    """manage_appointments function has an 'action' parameter."""
    sig = _get_sig()
    assert "action" in sig.parameters, "action parameter is missing from manage_appointments"


def test_action_param_has_literal_annotation():
    """action parameter annotation includes expected action values."""
    sig = _get_sig()
    annotation = sig.parameters["action"].annotation
    ann_str = str(annotation)
    assert "list" in ann_str, f"'list' not in annotation: {ann_str}"
    assert "cancel" in ann_str, f"'cancel' not in annotation: {ann_str}"
    assert "reschedule" in ann_str, f"'reschedule' not in annotation: {ann_str}"


def test_customer_phone_not_in_tool_params():
    """customer_phone must NOT be an explicit tool parameter (it is InjectedState)."""
    sig = _get_sig()
    # state parameter carries customer_phone via InjectedState; no raw customer_phone param
    assert (
        "customer_phone" not in sig.parameters
    ), "customer_phone should be removed from tool params and injected via InjectedState"


def test_action_accepts_confirm():
    """confirm is a valid Literal value in the action annotation."""
    sig = _get_sig()
    ann_str = str(sig.parameters["action"].annotation)
    assert "confirm" in ann_str


def test_action_accepts_decline():
    """decline is a valid Literal value in the action annotation."""
    sig = _get_sig()
    ann_str = str(sig.parameters["action"].annotation)
    assert "decline" in ann_str


# ─────────────────────────────────────────────────────────────────────────────
# Tool dispatch tests for confirm/decline actions
# ─────────────────────────────────────────────────────────────────────────────


_STATE_WITH_PHONE = {"customer_phone": "+34612345678"}


@pytest.mark.asyncio
async def test_confirm_action_happy():
    """confirm action delegates to handle_tool_action with CONFIRM_APPOINTMENT."""
    from agent.routing.intent_types import IntentType
    from agent.services.confirmation_service import ConfirmationResult

    appt_id = uuid4()
    fake_result = ConfirmationResult(
        success=True,
        appointment_id=appt_id,
        response_text="¡Perfecto! Tu cita queda confirmada.",
    )
    mock_handler = AsyncMock(return_value=fake_result)
    with (
        patch(
            "agent.tools.manage_appointments_tool.get_async_session",
            return_value=_make_async_session_ctx(),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
            new=AsyncMock(return_value=_make_idor_ok()),
        ),
        patch(
            "agent.services.confirmation_service.get_future_pending_appointments",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "agent.services.confirmation_service.handle_tool_action",
            new=mock_handler,
        ),
    ):
        out = await manage_appointments.coroutine(
            action="confirm",
            appointment_id=str(appt_id),
            state={**_STATE_WITH_PHONE, "customer_id": str(uuid4())},
        )
    assert "confirmada" in out.lower()
    mock_handler.assert_awaited_once()
    args, kwargs = mock_handler.call_args
    # Accept either positional or keyword form
    passed = list(args) + list(kwargs.values())
    assert IntentType.CONFIRM_APPOINTMENT in passed


@pytest.mark.asyncio
async def test_decline_action_happy():
    """decline action delegates to handle_tool_action with DECLINE_APPOINTMENT."""
    from agent.routing.intent_types import IntentType
    from agent.services.confirmation_service import ConfirmationResult

    appt_id = uuid4()
    fake_result = ConfirmationResult(
        success=True,
        appointment_id=appt_id,
        response_text="Entendido. Tu cita ha sido cancelada.",
    )
    mock_handler = AsyncMock(return_value=fake_result)
    with (
        patch(
            "agent.tools.manage_appointments_tool.get_async_session",
            return_value=_make_async_session_ctx(),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
            new=AsyncMock(return_value=_make_idor_ok()),
        ),
        patch(
            "agent.services.confirmation_service.get_future_pending_appointments",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "agent.services.confirmation_service.handle_tool_action",
            new=mock_handler,
        ),
    ):
        out = await manage_appointments.coroutine(
            action="decline",
            appointment_id=str(appt_id),
            state={**_STATE_WITH_PHONE, "customer_id": str(uuid4())},
        )
    assert "cancelada" in out.lower()
    mock_handler.assert_awaited_once()
    passed = list(mock_handler.call_args.args) + list(mock_handler.call_args.kwargs.values())
    assert IntentType.DECLINE_APPOINTMENT in passed


@pytest.mark.asyncio
async def test_confirm_invalid_uuid():
    # customer_id present so the flow passes the CUSTOMER_ID_REQUIRED (J2) gate
    # and reaches UUID validation, which is what this test asserts.
    # get_future_pending_appointments mocked to [] so the F2 disambiguation gate
    # is bypassed (len<=1 path) and the LLM-supplied appointment_id is used.
    with patch(
        "agent.services.confirmation_service.get_future_pending_appointments",
        new=AsyncMock(return_value=[]),
    ):
        out = await manage_appointments.coroutine(
            action="confirm",
            appointment_id="not-a-uuid",
            state={**_STATE_WITH_PHONE, "customer_id": str(uuid4())},
        )
    assert "no es válido" in out.lower() or "inválido" in out.lower()


@pytest.mark.asyncio
async def test_confirm_missing_appointment_id():
    out = await manage_appointments.coroutine(
        action="confirm",
        state=_STATE_WITH_PHONE,
    )
    assert "id" in out.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Reschedule validator guard tests (T3 RED → T4 GREEN)
#
# These tests verify that _reschedule_appointment calls validate_booking_date
# BEFORE any DB write when new_date is provided.
# ─────────────────────────────────────────────────────────────────────────────

FAKE_APPT_ID = str(uuid4())
CUSTOMER_PHONE = "+34612345678"
OPEN_DATE = "2026-05-05"
SUNDAY_DATE = "2026-05-03"
REF_DATE_STR = "2026-04-28"


def _make_eligibility_ok():
    """Return a mock eligibility result that allows rescheduling."""
    eligible = MagicMock()
    eligible.eligible = True
    return eligible


def _make_idor_ok():
    """Return a mock IDOR validation result that passes ownership check."""
    from agent.tools._booking_validators import FKValidationResult

    return FKValidationResult(ok=True, error_code=None, error_message=None)


def _make_async_session_ctx():
    """Return an async context manager mock for get_async_session."""
    mock_session = AsyncMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


def _make_execute_reschedule_result():
    """Return a mock reschedule result for the happy path."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    result = MagicMock()
    result.success = True
    result.new_start_time = datetime(2026, 5, 5, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    result.error = None
    result.slot_taken = False
    return result


@pytest.mark.asyncio
async def test_reschedule_g1_unresolvable_relative_text_no_db_write():
    """T3 G1: new_date='mañana' (unresolvable non-ISO) → error_code=invalid_relative_date, no DB write."""
    from agent.tools._booking_validators import DateValidationResult
    from agent.tools.manage_appointments_tool import _reschedule_appointment

    invalid_result = DateValidationResult(
        date_iso=None,
        error_code="invalid_relative_date",
        error_message="No pude entender la fecha. ¿Podés decirme el día y mes?",
        payload={"raw_text": "mañana"},
    )

    execute_reschedule_mock = AsyncMock()

    with (
        patch(
            "agent.tools.manage_appointments_tool.get_async_session",
            return_value=_make_async_session_ctx(),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
            new=AsyncMock(return_value=_make_idor_ok()),
        ),
        patch(
            "agent.services.reschedule_service.validate_reschedule_eligibility",
            new=AsyncMock(return_value=_make_eligibility_ok()),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_booking_date",
            new=AsyncMock(return_value=invalid_result),
        ),
        patch(
            "agent.services.reschedule_service.execute_reschedule",
            new=execute_reschedule_mock,
        ),
    ):
        result = await _reschedule_appointment(
            customer_phone=CUSTOMER_PHONE,
            appointment_id=FAKE_APPT_ID,
            new_date="mañana",
            new_time="10:00",
            reason=None,
            customer_id=uuid4(),  # satisfy J2 IDOR guard — tests date validation, not the guard
        )

    assert result["success"] is False
    assert result["error_code"] == "invalid_relative_date"
    assert result["message"]  # Spanish message present
    execute_reschedule_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_reschedule_g2_sunday_closed_no_db_write():
    """T3 G2: new_date=Sunday ISO → error_code=closed_day, no DB write."""
    from agent.tools._booking_validators import DateValidationResult
    from agent.tools.manage_appointments_tool import _reschedule_appointment

    closed_result = DateValidationResult(
        date_iso=None,
        error_code="closed_day",
        error_message="El salón está cerrado el domingo.",
        payload={"closed_date": SUNDAY_DATE, "reason": "domingo"},
    )

    execute_reschedule_mock = AsyncMock()

    with (
        patch(
            "agent.tools.manage_appointments_tool.get_async_session",
            return_value=_make_async_session_ctx(),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
            new=AsyncMock(return_value=_make_idor_ok()),
        ),
        patch(
            "agent.services.reschedule_service.validate_reschedule_eligibility",
            new=AsyncMock(return_value=_make_eligibility_ok()),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_booking_date",
            new=AsyncMock(return_value=closed_result),
        ),
        patch(
            "agent.services.reschedule_service.execute_reschedule",
            new=execute_reschedule_mock,
        ),
    ):
        result = await _reschedule_appointment(
            customer_phone=CUSTOMER_PHONE,
            appointment_id=FAKE_APPT_ID,
            new_date=SUNDAY_DATE,
            new_time="10:00",
            reason=None,
            customer_id=uuid4(),  # satisfy J2 IDOR guard — tests closed_day validation
        )

    assert result["success"] is False
    assert result["error_code"] == "closed_day"
    execute_reschedule_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_reschedule_g3_advance_policy_violated_no_db_write():
    """T3 G3: new_date=tomorrow (within lead-time) → error_code=advance_policy_violated, no DB write."""
    from agent.tools._booking_validators import DateValidationResult
    from agent.tools.manage_appointments_tool import _reschedule_appointment

    violation_result = DateValidationResult(
        date_iso=None,
        error_code="advance_policy_violated",
        error_message="La fecha viola la política de antelación mínima.",
        payload={"min_date": "2026-05-01", "min_days": 3},
    )

    execute_reschedule_mock = AsyncMock()

    with (
        patch(
            "agent.tools.manage_appointments_tool.get_async_session",
            return_value=_make_async_session_ctx(),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
            new=AsyncMock(return_value=_make_idor_ok()),
        ),
        patch(
            "agent.services.reschedule_service.validate_reschedule_eligibility",
            new=AsyncMock(return_value=_make_eligibility_ok()),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_booking_date",
            new=AsyncMock(return_value=violation_result),
        ),
        patch(
            "agent.services.reschedule_service.execute_reschedule",
            new=execute_reschedule_mock,
        ),
    ):
        result = await _reschedule_appointment(
            customer_phone=CUSTOMER_PHONE,
            appointment_id=FAKE_APPT_ID,
            new_date="2026-04-29",  # tomorrow — within lead-time
            new_time="10:00",
            reason=None,
            customer_id=uuid4(),  # satisfy J2 IDOR guard — tests advance_policy validation
        )

    assert result["success"] is False
    assert result["error_code"] == "advance_policy_violated"
    assert "min_date" in result  # payload spread into result
    execute_reschedule_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_reschedule_happy_path_valid_date_calls_db():
    """T3 happy path: valid future ISO → validator returns ok → execute_reschedule is called."""
    from agent.tools._booking_validators import DateValidationResult
    from agent.tools.manage_appointments_tool import _reschedule_appointment

    ok_result = DateValidationResult(
        date_iso=OPEN_DATE,
        error_code=None,
        error_message=None,
        payload={},
    )

    execute_reschedule_mock = AsyncMock(return_value=_make_execute_reschedule_result())

    with (
        patch(
            "agent.tools.manage_appointments_tool.get_async_session",
            return_value=_make_async_session_ctx(),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
            new=AsyncMock(return_value=_make_idor_ok()),
        ),
        patch(
            "agent.services.reschedule_service.validate_reschedule_eligibility",
            new=AsyncMock(return_value=_make_eligibility_ok()),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_booking_date",
            new=AsyncMock(return_value=ok_result),
        ),
        patch(
            "agent.services.reschedule_service.execute_reschedule",
            new=execute_reschedule_mock,
        ),
    ):
        result = await _reschedule_appointment(
            customer_phone=CUSTOMER_PHONE,
            appointment_id=FAKE_APPT_ID,
            new_date=OPEN_DATE,
            new_time="10:00",
            reason=None,
            customer_id=uuid4(),  # satisfy J2 IDOR guard — tests happy path reschedule
        )

    assert result["success"] is True
    execute_reschedule_mock.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# F2 — confirm/decline disambiguation precondition (multiple pending targets)
#
# manage_appointments(action="confirm"|"decline") must resolve the target
# EXCLUSIVELY from the customer's own message (ordinal/keyword selectors) when
# there is more than 1 PENDING appointment — the LLM-supplied appointment_id
# is ignored in that case. A free-text disambiguator that a human would
# recognize (naming date/time/stylist) but that is NOT a recognized selector
# pattern is treated as "no selector found" (guided list, no mutation) — this
# is intentional security design (REQ-F2-6), not a bug.
# ─────────────────────────────────────────────────────────────────────────────


def _make_pending_appointment(appt_id, stylist_name: str = "Ana", confirmation_sent_at=None):
    """Fake Appointment for confirmation_service._build_appointment_list.

    confirmation_sent_at defaults to None — the fixture matches the ORIGINAL
    bug scenario (engram #7518): freshly-booked PENDING appointments where
    the 48h confirmation WhatsApp template has NOT been sent yet.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    appt = MagicMock()
    appt.id = appt_id
    appt.start_time = datetime(2026, 7, 9, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    appt.confirmation_sent_at = confirmation_sent_at
    stylist = MagicMock()
    stylist.name = stylist_name
    appt.stylist = stylist
    return appt


def _extract_uuid_args(mock_calls):
    """Collect every UUID-typed positional/keyword arg across all calls to a mock."""
    from uuid import UUID as _UUID

    ids = set()
    for call in mock_calls:
        for arg in list(call.args) + list(call.kwargs.values()):
            if isinstance(arg, _UUID):
                ids.add(arg)
    return ids


def _make_confirmation_result(message: str):
    fake_result = MagicMock()
    fake_result.success = True
    fake_result.state_updates = None
    fake_result.response_text = message
    fake_result.error_message = None
    return fake_result


@pytest.mark.asyncio
async def test_confirm_with_multiple_pending_and_no_selector_returns_guided_list():
    """REQ-F2-2: >1 pending + no recognized selector -> guided list, no mutation."""
    appt_a = _make_pending_appointment(uuid4(), "Ana")
    appt_b = _make_pending_appointment(uuid4(), "Marta")
    mock_handler = AsyncMock()

    with (
        patch(
            "agent.services.confirmation_service.get_future_pending_appointments",
            new=AsyncMock(return_value=[appt_a, appt_b]),
        ),
        patch(
            "agent.services.confirmation_service.handle_tool_action",
            new=mock_handler,
        ),
    ):
        out = await manage_appointments.coroutine(
            action="confirm",
            appointment_id=str(appt_a.id),
            state={
                **_STATE_WITH_PHONE,
                "customer_id": str(uuid4()),
                "user_message": "quiero confirmar mi cita",
            },
        )

    assert isinstance(out, str)
    assert "1." in out and "2." in out
    assert "TODAS" in out
    mock_handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_reproduces_original_bug_fresh_pending_no_confirmation_sent():
    """CRITICAL regression test (engram #7518 — live re-run of PR-2's fix FAILED).

    Reproduces the EXACT original bug scenario: 2 freshly-booked PENDING
    appointments, both >48h out, BOTH with confirmation_sent_at=None (the
    notifications worker has not sent the 48h confirmation template yet).
    The customer sends the bare, ambiguous message "quiero confirmar mi
    cita" and the LLM supplies appointment_id=appt_b (the LATER-booked
    appointment — the wrong one, mirroring the live reproduction).

    The disambiguation gate MUST still fire and return the guided list
    without mutating ANY appointment, even though confirmation_sent_at is
    NULL on both rows. This is precisely the case PR-2's original
    get_pending_confirmations()-based gate missed, because that query
    filters WHERE confirmation_sent_at IS NOT NULL and returned 0 rows for
    this fixture — the gate's len(pending) > 1 precondition never fired and
    the code fell through to trusting the LLM's (wrong) appointment_id.
    """
    appt_a = _make_pending_appointment(uuid4(), "Ana", confirmation_sent_at=None)
    appt_b = _make_pending_appointment(uuid4(), "Marta", confirmation_sent_at=None)
    assert appt_a.confirmation_sent_at is None
    assert appt_b.confirmation_sent_at is None
    mock_handler = AsyncMock()

    with (
        patch(
            "agent.services.confirmation_service.get_future_pending_appointments",
            new=AsyncMock(return_value=[appt_a, appt_b]),
        ),
        patch(
            "agent.services.confirmation_service.handle_tool_action",
            new=mock_handler,
        ),
    ):
        out = await manage_appointments.coroutine(
            action="confirm",
            appointment_id=str(appt_b.id),  # LLM-supplied — wrong, mirrors live repro
            state={
                **_STATE_WITH_PHONE,
                "customer_id": str(uuid4()),
                "user_message": "quiero confirmar mi cita",
            },
        )

    assert isinstance(out, str)
    assert "1." in out and "2." in out
    mock_handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_with_freetext_disambiguator_not_recognized_returns_guided_list():
    """REQ-F2-2/F2-6: a free-text disambiguator naming a specific appointment
    (date/time/stylist) is NOT a recognized selector -> guided list, no
    mutation, even though the LLM correctly resolved appointment_id."""
    appt_a = _make_pending_appointment(uuid4(), "Ana")
    appt_b = _make_pending_appointment(uuid4(), "Marta")
    mock_handler = AsyncMock()

    with (
        patch(
            "agent.services.confirmation_service.get_future_pending_appointments",
            new=AsyncMock(return_value=[appt_a, appt_b]),
        ),
        patch(
            "agent.services.confirmation_service.handle_tool_action",
            new=mock_handler,
        ),
    ):
        out = await manage_appointments.coroutine(
            action="confirm",
            appointment_id=str(appt_b.id),  # LLM correctly resolved B — must be ignored
            state={
                **_STATE_WITH_PHONE,
                "customer_id": str(uuid4()),
                "user_message": "la del jueves a las 16 con Marta",
            },
        )

    assert isinstance(out, str)
    assert "1." in out and "2." in out
    mock_handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_with_numeric_selector_resolves_from_customer_text():
    """REQ-F2-2b: numeric/ordinal selector resolves the target from
    pending[n-1], ignoring the LLM-supplied (wrong) appointment_id."""
    appt_a = _make_pending_appointment(uuid4(), "Ana")
    appt_b = _make_pending_appointment(uuid4(), "Marta")
    mock_handler = AsyncMock(
        return_value=_make_confirmation_result("¡Perfecto! Tu cita queda confirmada.")
    )

    with (
        patch(
            "agent.tools.manage_appointments_tool.get_async_session",
            return_value=_make_async_session_ctx(),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
            new=AsyncMock(return_value=_make_idor_ok()),
        ),
        patch(
            "agent.services.confirmation_service.get_future_pending_appointments",
            new=AsyncMock(return_value=[appt_a, appt_b]),
        ),
        patch(
            "agent.services.confirmation_service.handle_tool_action",
            new=mock_handler,
        ),
    ):
        out = await manage_appointments.coroutine(
            action="confirm",
            appointment_id=str(appt_a.id),  # wrong id supplied by the LLM — must be ignored
            state={
                **_STATE_WITH_PHONE,
                "customer_id": str(uuid4()),
                "user_message": "la 2",
            },
        )

    assert "confirmada" in out.lower()
    mock_handler.assert_awaited_once()
    processed = _extract_uuid_args(mock_handler.call_args_list)
    assert appt_b.id in processed
    assert appt_a.id not in processed


@pytest.mark.asyncio
async def test_confirm_all_applies_to_fetched_pending_set_only():
    """REQ-F2-2c: 'todas' applies confirm to every appointment in the fetched
    pending set only, via the existing per-appointment path (one call/row)."""
    pending = [
        _make_pending_appointment(uuid4(), "Ana"),
        _make_pending_appointment(uuid4(), "Marta"),
        _make_pending_appointment(uuid4(), "Laura"),
    ]
    mock_handler = AsyncMock(
        return_value=_make_confirmation_result("¡Perfecto! Tu cita queda confirmada.")
    )

    with (
        patch(
            "agent.tools.manage_appointments_tool.get_async_session",
            return_value=_make_async_session_ctx(),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
            new=AsyncMock(return_value=_make_idor_ok()),
        ),
        patch(
            "agent.services.confirmation_service.get_future_pending_appointments",
            new=AsyncMock(return_value=pending),
        ),
        patch(
            "agent.services.confirmation_service.handle_tool_action",
            new=mock_handler,
        ),
    ):
        out = await manage_appointments.coroutine(
            action="confirm",
            appointment_id=str(pending[0].id),
            state={
                **_STATE_WITH_PHONE,
                "customer_id": str(uuid4()),
                "user_message": "todas",
            },
        )

    assert "3" in out
    assert mock_handler.await_count == len(pending)
    assert _extract_uuid_args(mock_handler.call_args_list) == {a.id for a in pending}


@pytest.mark.asyncio
async def test_confirm_with_cancel_all_keyword_returns_clarification_no_mutation():
    """Polarity guard: action=confirm but the customer's ALL-type keyword is
    from the CANCEL family ("cancelar todas") — this contradicts the tool's
    chosen action. MUST NOT mutate anything; MUST return a clarification
    asking the customer what they actually want."""
    pending = [
        _make_pending_appointment(uuid4(), "Ana"),
        _make_pending_appointment(uuid4(), "Marta"),
    ]
    mock_handler = AsyncMock()

    with (
        patch(
            "agent.services.confirmation_service.get_future_pending_appointments",
            new=AsyncMock(return_value=pending),
        ),
        patch(
            "agent.services.confirmation_service.handle_tool_action",
            new=mock_handler,
        ),
    ):
        out = await manage_appointments.coroutine(
            action="confirm",
            appointment_id=str(pending[0].id),
            state={
                **_STATE_WITH_PHONE,
                "customer_id": str(uuid4()),
                "user_message": "cancelar todas",
            },
        )

    assert isinstance(out, str)
    mock_handler.assert_not_awaited()
    # Clarification must surface both directions so the customer can pick.
    assert "TODAS" in out
    assert "CANCELAR TODAS" in out


@pytest.mark.asyncio
async def test_decline_with_confirm_all_keyword_returns_clarification_no_mutation():
    """Polarity guard mirror: action=decline but the customer's ALL-type
    keyword is from the CONFIRM family ("confirmar todas") — contradicts the
    tool's chosen action. MUST NOT mutate; MUST return a clarification."""
    pending = [
        _make_pending_appointment(uuid4(), "Ana"),
        _make_pending_appointment(uuid4(), "Marta"),
    ]
    mock_handler = AsyncMock()

    with (
        patch(
            "agent.services.confirmation_service.get_future_pending_appointments",
            new=AsyncMock(return_value=pending),
        ),
        patch(
            "agent.services.confirmation_service.handle_tool_action",
            new=mock_handler,
        ),
    ):
        out = await manage_appointments.coroutine(
            action="decline",
            appointment_id=str(pending[0].id),
            state={
                **_STATE_WITH_PHONE,
                "customer_id": str(uuid4()),
                "user_message": "confirmar todas",
            },
        )

    assert isinstance(out, str)
    mock_handler.assert_not_awaited()
    assert "TODAS" in out
    assert "CANCELAR TODAS" in out


@pytest.mark.asyncio
async def test_confirm_with_ordinal_selector_unaffected_by_polarity_guard():
    """Polarity guard scope: ordinal/number selections carry NO polarity —
    the action param is trusted as before, unaffected by the new guard."""
    appt_a = _make_pending_appointment(uuid4(), "Ana")
    appt_b = _make_pending_appointment(uuid4(), "Marta")
    mock_handler = AsyncMock(
        return_value=_make_confirmation_result("¡Perfecto! Tu cita queda confirmada.")
    )

    with (
        patch(
            "agent.tools.manage_appointments_tool.get_async_session",
            return_value=_make_async_session_ctx(),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
            new=AsyncMock(return_value=_make_idor_ok()),
        ),
        patch(
            "agent.services.confirmation_service.get_future_pending_appointments",
            new=AsyncMock(return_value=[appt_a, appt_b]),
        ),
        patch(
            "agent.services.confirmation_service.handle_tool_action",
            new=mock_handler,
        ),
    ):
        out = await manage_appointments.coroutine(
            action="confirm",
            appointment_id=str(appt_a.id),
            state={
                **_STATE_WITH_PHONE,
                "customer_id": str(uuid4()),
                "user_message": "la 2",
            },
        )

    assert "confirmada" in out.lower()
    mock_handler.assert_awaited_once()
    processed = _extract_uuid_args(mock_handler.call_args_list)
    assert appt_b.id in processed


@pytest.mark.asyncio
async def test_confirm_with_single_pending_confirms_directly():
    """REQ-F2-3: exactly 1 pending -> direct confirm, no disambiguation list."""
    appt = _make_pending_appointment(uuid4(), "Ana")
    mock_handler = AsyncMock(
        return_value=_make_confirmation_result("¡Perfecto! Tu cita queda confirmada.")
    )

    with (
        patch(
            "agent.tools.manage_appointments_tool.get_async_session",
            return_value=_make_async_session_ctx(),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
            new=AsyncMock(return_value=_make_idor_ok()),
        ),
        patch(
            "agent.services.confirmation_service.get_future_pending_appointments",
            new=AsyncMock(return_value=[appt]),
        ),
        patch(
            "agent.services.confirmation_service.handle_tool_action",
            new=mock_handler,
        ),
    ):
        out = await manage_appointments.coroutine(
            action="confirm",
            appointment_id=str(appt.id),
            state={
                **_STATE_WITH_PHONE,
                "customer_id": str(uuid4()),
                "user_message": "confirmo",
            },
        )

    assert "confirmada" in out.lower()
    mock_handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_decline_with_multiple_pending_and_no_selector_returns_guided_list():
    """Decline mirror of REQ-F2-2."""
    appt_a = _make_pending_appointment(uuid4(), "Ana")
    appt_b = _make_pending_appointment(uuid4(), "Marta")
    mock_handler = AsyncMock()

    with (
        patch(
            "agent.services.confirmation_service.get_future_pending_appointments",
            new=AsyncMock(return_value=[appt_a, appt_b]),
        ),
        patch(
            "agent.services.confirmation_service.handle_tool_action",
            new=mock_handler,
        ),
    ):
        out = await manage_appointments.coroutine(
            action="decline",
            appointment_id=str(appt_a.id),
            state={
                **_STATE_WITH_PHONE,
                "customer_id": str(uuid4()),
                "user_message": "quiero cancelar mi cita",
            },
        )

    assert isinstance(out, str)
    assert "1." in out and "2." in out
    assert "CANCELAR TODAS" in out
    mock_handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_decline_with_numeric_selector_resolves_from_customer_text():
    """Decline mirror of REQ-F2-2b."""
    appt_a = _make_pending_appointment(uuid4(), "Ana")
    appt_b = _make_pending_appointment(uuid4(), "Marta")
    mock_handler = AsyncMock(
        return_value=_make_confirmation_result("Entendido. Tu cita ha sido cancelada.")
    )

    with (
        patch(
            "agent.tools.manage_appointments_tool.get_async_session",
            return_value=_make_async_session_ctx(),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
            new=AsyncMock(return_value=_make_idor_ok()),
        ),
        patch(
            "agent.services.confirmation_service.get_future_pending_appointments",
            new=AsyncMock(return_value=[appt_a, appt_b]),
        ),
        patch(
            "agent.services.confirmation_service.handle_tool_action",
            new=mock_handler,
        ),
    ):
        out = await manage_appointments.coroutine(
            action="decline",
            appointment_id=str(appt_a.id),  # wrong id supplied by the LLM — must be ignored
            state={
                **_STATE_WITH_PHONE,
                "customer_id": str(uuid4()),
                "user_message": "la 2",
            },
        )

    assert "cancelada" in out.lower()
    mock_handler.assert_awaited_once()
    processed = _extract_uuid_args(mock_handler.call_args_list)
    assert appt_b.id in processed
    assert appt_a.id not in processed


@pytest.mark.asyncio
async def test_cancel_all_applies_to_fetched_pending_set_only():
    """Decline mirror of REQ-F2-2c ('cancelar todas')."""
    pending = [
        _make_pending_appointment(uuid4(), "Ana"),
        _make_pending_appointment(uuid4(), "Marta"),
        _make_pending_appointment(uuid4(), "Laura"),
    ]
    mock_handler = AsyncMock(
        return_value=_make_confirmation_result("Entendido. Tu cita ha sido cancelada.")
    )

    with (
        patch(
            "agent.tools.manage_appointments_tool.get_async_session",
            return_value=_make_async_session_ctx(),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
            new=AsyncMock(return_value=_make_idor_ok()),
        ),
        patch(
            "agent.services.confirmation_service.get_future_pending_appointments",
            new=AsyncMock(return_value=pending),
        ),
        patch(
            "agent.services.confirmation_service.handle_tool_action",
            new=mock_handler,
        ),
    ):
        out = await manage_appointments.coroutine(
            action="decline",
            appointment_id=str(pending[0].id),
            state={
                **_STATE_WITH_PHONE,
                "customer_id": str(uuid4()),
                "user_message": "cancelar todas",
            },
        )

    assert "3" in out
    assert mock_handler.await_count == len(pending)
    assert _extract_uuid_args(mock_handler.call_args_list) == {a.id for a in pending}


@pytest.mark.asyncio
async def test_decline_with_single_pending_declines_directly():
    """Decline mirror of REQ-F2-3."""
    appt = _make_pending_appointment(uuid4(), "Ana")
    mock_handler = AsyncMock(
        return_value=_make_confirmation_result("Entendido. Tu cita ha sido cancelada.")
    )

    with (
        patch(
            "agent.tools.manage_appointments_tool.get_async_session",
            return_value=_make_async_session_ctx(),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
            new=AsyncMock(return_value=_make_idor_ok()),
        ),
        patch(
            "agent.services.confirmation_service.get_future_pending_appointments",
            new=AsyncMock(return_value=[appt]),
        ),
        patch(
            "agent.services.confirmation_service.handle_tool_action",
            new=mock_handler,
        ),
    ):
        out = await manage_appointments.coroutine(
            action="decline",
            appointment_id=str(appt.id),
            state={
                **_STATE_WITH_PHONE,
                "customer_id": str(uuid4()),
                "user_message": "cancelo",
            },
        )

    assert "cancelada" in out.lower()
    mock_handler.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# F5 — cancellation_reason taxonomy on tool-driven cancel (REQ-F5-1..3)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_action_stamps_customer_declined_reason():
    """REQ-F5-1: manage_appointments(action="cancel") must stamp
    cancellation_reason="customer_declined" on the cancelled appointment,
    replacing the previous hardcoded reason=None.
    """
    appt_id = uuid4()
    mock_cancellation_result = MagicMock()
    mock_cancellation_result.success = True
    mock_cancellation_result.response_text = "Tu cita ha sido cancelada."
    execute_cancellation_mock = AsyncMock(return_value=mock_cancellation_result)

    with (
        patch(
            "agent.tools.manage_appointments_tool.get_async_session",
            return_value=_make_async_session_ctx(),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
            new=AsyncMock(return_value=_make_idor_ok()),
        ),
        patch(
            "agent.services.cancellation_service.execute_cancellation",
            new=execute_cancellation_mock,
        ),
    ):
        out = await manage_appointments.coroutine(
            action="cancel",
            appointment_id=str(appt_id),
            state={**_STATE_WITH_PHONE, "customer_id": str(uuid4())},
        )

    assert "cancelada" in out.lower()
    execute_cancellation_mock.assert_awaited_once()
    _, kwargs = execute_cancellation_mock.call_args
    assert kwargs["reason"] == "customer_declined"


@pytest.mark.asyncio
async def test_reschedule_action_leaves_cancellation_reason_untouched():
    """REQ-F5-3 (regression, resolved as a no-op): the reschedule action must
    NOT participate in cancellation_reason at all — execute_reschedule only
    ever receives appointment_id/new_start_time, no reason forwarding of any
    kind. This pins the design's "line 637 is a no-op" resolution; it is
    expected to already pass (no production code change needed for this case).
    """
    from agent.tools._booking_validators import DateValidationResult

    ok_result = DateValidationResult(
        date_iso=OPEN_DATE,
        error_code=None,
        error_message=None,
        payload={},
    )
    execute_reschedule_mock = AsyncMock(return_value=_make_execute_reschedule_result())

    with (
        patch(
            "agent.tools.manage_appointments_tool.get_async_session",
            return_value=_make_async_session_ctx(),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
            new=AsyncMock(return_value=_make_idor_ok()),
        ),
        patch(
            "agent.services.reschedule_service.validate_reschedule_eligibility",
            new=AsyncMock(return_value=_make_eligibility_ok()),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_booking_date",
            new=AsyncMock(return_value=ok_result),
        ),
        patch(
            "agent.services.reschedule_service.execute_reschedule",
            new=execute_reschedule_mock,
        ),
    ):
        out = await manage_appointments.coroutine(
            action="reschedule",
            appointment_id=FAKE_APPT_ID,
            new_date=OPEN_DATE,
            new_time="10:00",
            state={**_STATE_WITH_PHONE, "customer_id": str(uuid4())},
        )

    assert "reprogramada" in out.lower()
    execute_reschedule_mock.assert_awaited_once()
    _, kwargs = execute_reschedule_mock.call_args
    assert "reason" not in kwargs
    assert set(kwargs.keys()) == {"appointment_id", "new_start_time"}
