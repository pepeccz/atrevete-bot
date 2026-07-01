"""
T1 RED — book.py initial-status gate unit tests.

Tests the new status gate (S1-R1 through S1-R5) and payload fields added in T2 (GREEN).

Before T2:
- Tests 1, 4, 5, 6, 7, 8, 9, 10 FAIL definitively (new behavior not yet implemented).
- Tests 2 and 3 also include payload assertions that FAIL before T2.

After T2: all 10 tests pass.

Spec refs: S1-R1, S1-R2, S1-R3, S1-R4, S1-R5, S1-A, S1-B, S1-C, S1-D
Design ref: D-N1
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Time-freezing helpers
# ---------------------------------------------------------------------------

_real_datetime = datetime  # keep reference before any monkeypatching

# Fixed "now" for deterministic lead-time calculations.
_FIXED_NOW = _real_datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)


class _FakeDatetime:
    """Drop-in for `datetime` in agent.tools.book scope.

    .now(tz) always returns _FIXED_NOW.
    .fromisoformat() delegates to the real datetime so ISO parsing keeps working.
    """

    @staticmethod
    def now(tz=None):  # noqa: ARG004
        return _FIXED_NOW

    @staticmethod
    def fromisoformat(s: str):
        return _real_datetime.fromisoformat(s)


# ---------------------------------------------------------------------------
# Convenience start_iso values relative to _FIXED_NOW
# ---------------------------------------------------------------------------

_START_72H = (_FIXED_NOW + timedelta(hours=72)).isoformat()       # lead 72h > 48h → PENDING
_START_3H = (_FIXED_NOW + timedelta(hours=3)).isoformat()         # lead 3h ≤ 48h  → CONFIRMED
_START_48H = (_FIXED_NOW + timedelta(hours=48)).isoformat()       # lead 48h exactly → CONFIRMED (S1-R3)
_START_48H1S = (_FIXED_NOW + timedelta(hours=48, seconds=1)).isoformat()  # lead 48h+1s → PENDING


# ---------------------------------------------------------------------------
# Shared test helper
# ---------------------------------------------------------------------------


def _make_ok_fk() -> MagicMock:
    m = MagicMock()
    m.ok = True
    m.missing_ids = []
    m.payload = {}
    return m


async def _invoke_book(start_iso: str) -> tuple[dict, object, AsyncMock]:
    """Run book() with the given start_iso under full mock isolation.

    Returns (payload_dict, appointment_orm_object, gcal_push_mock).
    """
    from agent.tools.book import book  # noqa: PLC0415

    stylist_uuid = uuid4()
    service_uuid = uuid4()
    customer_uuid = uuid4()
    appointment_uuid = uuid4()

    # Customer with current policy already persisted — avoids the policy-gate branch.
    mock_customer = MagicMock()
    mock_customer.id = customer_uuid
    mock_customer.policy_accepted_at = _real_datetime(2026, 1, 1, tzinfo=UTC)
    mock_customer.policy_version = "1.0"
    mock_customer.phone = "+34666000001"

    mock_stylist = MagicMock()
    mock_stylist.name = "María"

    # --- Session 1: main transaction (service duration + customer lookup) ---
    dur_rows = MagicMock()
    dur_rows.fetchall = MagicMock(return_value=[(60,)])

    cust_rows = MagicMock()
    cust_rows.scalar_one_or_none = MagicMock(return_value=mock_customer)

    _txn_call = [0]

    async def _txn_execute(stmt):  # noqa: ARG001
        _txn_call[0] += 1
        return dur_rows if _txn_call[0] == 1 else cust_rows

    mock_txn_session = MagicMock()
    mock_txn_session.execute = _txn_execute
    mock_txn_session.get = AsyncMock(return_value=mock_customer)
    mock_txn_session.add = MagicMock()
    mock_txn_session.flush = AsyncMock()
    mock_txn_session.commit = AsyncMock()
    mock_txn_session.__aenter__ = AsyncMock(return_value=mock_txn_session)
    mock_txn_session.__aexit__ = AsyncMock(return_value=False)

    # --- Session 2: GCal service-name query ---
    svc_name_rows = MagicMock()
    svc_name_rows.fetchall = MagicMock(return_value=[("Corte de Mujer",)])

    mock_gcal_session = MagicMock()
    mock_gcal_session.execute = AsyncMock(return_value=svc_name_rows)
    mock_gcal_session.__aenter__ = AsyncMock(return_value=mock_gcal_session)
    mock_gcal_session.__aexit__ = AsyncMock(return_value=False)

    # --- Session 3: stylist display-name query ---
    mock_sty_session = MagicMock()
    mock_sty_session.get = AsyncMock(return_value=mock_stylist)
    mock_sty_session.__aenter__ = AsyncMock(return_value=mock_sty_session)
    mock_sty_session.__aexit__ = AsyncMock(return_value=False)

    _session_call = [0]

    def _make_session(*_args, **_kwargs):
        _session_call[0] += 1
        if _session_call[0] == 1:
            return mock_txn_session
        if _session_call[0] == 2:
            return mock_gcal_session
        return mock_sty_session

    settings_mock = MagicMock()
    settings_mock.POLICY_VERSION = "1.0"
    settings_mock.POLICY_URL = "https://example.com/politica"

    ok_fk = _make_ok_fk()

    ok_slot = MagicMock()
    ok_slot.ok = True
    ok_slot.error_message = ""

    gcal_push_mock = AsyncMock()

    with (
        patch("agent.tools.book.datetime", _FakeDatetime),
        patch("database.connection.get_async_session", side_effect=_make_session),
        patch(
            "agent.services.gcal_push_service.fire_and_forget_push_appointment",
            gcal_push_mock,
        ),
        patch("agent.tools.book.uuid4", return_value=appointment_uuid),
        patch(
            "agent.tools.book.check_slot_availability",
            new_callable=AsyncMock,
            return_value={"available": True},
        ),
        patch("agent.tools.book.get_settings", return_value=settings_mock),
        patch("agent.tools.book.validate_service_ids_exist", new=AsyncMock(return_value=ok_fk)),
        patch("agent.tools.book.validate_stylist_id_exists", new=AsyncMock(return_value=ok_fk)),
        patch("agent.tools.book.validate_slot_in_offered", return_value=ok_slot),
        patch("agent.tools.book.accept_policy", new=AsyncMock()),
        patch("agent.tools.book._invalidate_cached_customer", new=AsyncMock()),
        patch("agent.tools.book.clear_conversation_policy_acceptance", new=AsyncMock()),
    ):
        raw = await book.coroutine(
            service_ids=[str(service_uuid)],
            stylist_id=str(stylist_uuid),
            start_iso=start_iso,
            customer_full_name="Ana García",
            confirmed=True,
            pre_book_validated=True,
            policy_accepted=True,
            state={"customer_phone": "+34666000001"},
        )
        # Yield one event-loop tick so any asyncio.create_task inside book() can start
        # (and fail silently in _persist_memories_safe) before the patches are removed.
        await asyncio.sleep(0)

    result = json.loads(raw)
    # Appointment ORM object captured from session.add() call
    appointment = mock_txn_session.add.call_args[0][0]
    return result, appointment, gcal_push_mock


# ---------------------------------------------------------------------------
# T1.1 — Status gate: >48h → PENDING
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_72h_out_creates_pending():
    """72h-out booking must produce Appointment with status=PENDING (S1-R1).

    FAILS before T2: current code hardcodes AppointmentStatus.CONFIRMED.
    """
    from database.models import AppointmentStatus  # noqa: PLC0415

    _, appointment, _ = await _invoke_book(_START_72H)
    assert appointment.status == AppointmentStatus.PENDING


# ---------------------------------------------------------------------------
# T1.2 — Status gate: ≤48h → CONFIRMED (with payload regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_3h_out_creates_confirmed():
    """3h-out booking must produce Appointment with status=CONFIRMED (S1-R1).

    The payload assertion on appointment_status ensures this test also FAILS before T2
    (before T2 the payload field is absent), even though CONFIRMED was always the behavior.
    """
    from database.models import AppointmentStatus  # noqa: PLC0415

    result, appointment, _ = await _invoke_book(_START_3H)
    assert appointment.status == AppointmentStatus.CONFIRMED
    # S1-R4: payload field must exist; this assertion fails before T2
    assert result["payload"]["appointment_status"] == "confirmed"


# ---------------------------------------------------------------------------
# T1.3 — Exact 48h boundary → CONFIRMED (with payload regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_exact_48h_is_confirmed():
    """Exactly 48h lead → CONFIRMED: boundary belongs to the ≤48h side (S1-R3).

    The payload assertion ensures this fails before T2 even though CONFIRMED was
    the default behavior.
    """
    from database.models import AppointmentStatus  # noqa: PLC0415

    result, appointment, _ = await _invoke_book(_START_48H)
    assert appointment.status == AppointmentStatus.CONFIRMED
    assert result["payload"]["appointment_status"] == "confirmed"


# ---------------------------------------------------------------------------
# T1.4 — 48h + 1s boundary → PENDING
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_48h_plus_1s_is_pending():
    """48h+1s lead → PENDING: strictly >48h crosses to the PENDING side (S1-R3).

    FAILS before T2: current code always returns CONFIRMED.
    """
    from database.models import AppointmentStatus  # noqa: PLC0415

    _, appointment, _ = await _invoke_book(_START_48H1S)
    assert appointment.status == AppointmentStatus.PENDING


# ---------------------------------------------------------------------------
# T1.5 — GCal push receives "pending" for a >48h (PENDING) booking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gcal_push_receives_pending_status_when_appointment_is_pending():
    """GCal push must receive status="pending" for a 72h-out PENDING booking (S1-R5).

    Currently consistent with existing hardcoded behavior, but this test locks it in
    explicitly for the PENDING case.
    """
    _, _, gcal_mock = await _invoke_book(_START_72H)
    gcal_mock.assert_awaited_once()
    assert gcal_mock.call_args.kwargs["status"] == "pending"


# ---------------------------------------------------------------------------
# T1.6 — GCal push receives "confirmed" for a ≤48h (CONFIRMED) booking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gcal_push_receives_confirmed_status_when_appointment_is_confirmed():
    """GCal push must receive status="confirmed" for a 3h-out CONFIRMED booking (S1-R5).

    FAILS before T2: current book.py hardcodes status="pending" for ALL bookings
    regardless of the appointment's actual status (pre-existing bug N1b).
    """
    _, _, gcal_mock = await _invoke_book(_START_3H)
    gcal_mock.assert_awaited_once()
    assert gcal_mock.call_args.kwargs["status"] == "confirmed"


# ---------------------------------------------------------------------------
# T1.7 — Payload includes appointment_status="pending" for >48h booking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_payload_includes_appointment_status_pending():
    """book() payload must include appointment_status="pending" for 72h-out booking (S1-R4).

    FAILS before T2: the field does not exist in the current payload.
    """
    result, _, _ = await _invoke_book(_START_72H)
    assert result["status"] == "ok"
    assert result["payload"]["appointment_status"] == "pending"


# ---------------------------------------------------------------------------
# T1.8 — Payload includes appointment_status="confirmed" for ≤48h booking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_payload_includes_appointment_status_confirmed():
    """book() payload must include appointment_status="confirmed" for 3h-out booking (S1-R4).

    FAILS before T2: the field does not exist in the current payload.
    """
    result, _, _ = await _invoke_book(_START_3H)
    assert result["status"] == "ok"
    assert result["payload"]["appointment_status"] == "confirmed"


# ---------------------------------------------------------------------------
# T1.9 — Payload includes requires_confirmation=True for PENDING booking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_payload_includes_requires_confirmation_true():
    """book() payload must include requires_confirmation=True for PENDING booking (S1-R4).

    FAILS before T2: the field does not exist in the current payload.
    """
    result, _, _ = await _invoke_book(_START_72H)
    assert result["payload"]["requires_confirmation"] is True


# ---------------------------------------------------------------------------
# T1.10 — Payload includes requires_confirmation=False for CONFIRMED booking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_payload_includes_requires_confirmation_false():
    """book() payload must include requires_confirmation=False for CONFIRMED booking (S1-R4).

    FAILS before T2: the field does not exist in the current payload.
    """
    result, _, _ = await _invoke_book(_START_3H)
    assert result["payload"]["requires_confirmation"] is False
