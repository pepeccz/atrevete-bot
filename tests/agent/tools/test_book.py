"""
Tests for agent/tools/book.py — Task 3.5 (RED→GREEN).

book() is an atomic tool: customer get-or-create + appointment insert + GCal push.
DB-dependent tests use real Postgres; they skip gracefully if DB is unreachable.
GCal push is always mocked.
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_response(raw: str):
    return json.loads(raw)


def future_start_iso(days_ahead: int = 5) -> str:
    """Return a timezone-aware ISO start time."""
    dt = datetime.now(UTC) + timedelta(days=days_ahead, hours=2)
    return dt.isoformat()


# ---------------------------------------------------------------------------
# DB connectivity guard
# ---------------------------------------------------------------------------


async def _db_available() -> bool:
    """Returns True if the test Postgres instance is reachable."""
    try:
        from sqlalchemy import text

        from database.connection import get_async_session

        async with get_async_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session():
    from database.connection import get_async_session

    async with get_async_session() as session:
        yield session


@pytest.fixture
async def test_stylist():
    """Insert a minimal active stylist. Clean up after test."""
    from sqlalchemy import select

    from database.connection import get_async_session
    from database.models import ServiceCategory, Stylist

    if not await _db_available():
        pytest.skip("Postgres not reachable")

    sid = uuid4()
    async with get_async_session() as session:
        stylist = Stylist(
            id=sid,
            name="TestMarta",
            slug=f"testmarta-{sid.hex[:6]}",
            category=ServiceCategory.HAIRDRESSING,
            is_active=True,
        )
        session.add(stylist)
        await session.commit()

    yield sid  # yield the ID, not the ORM object (session closed)

    # cleanup
    from database.models import Appointment

    async with get_async_session() as sess:
        appts = (
            (await sess.execute(select(Appointment).where(Appointment.stylist_id == sid)))
            .scalars()
            .all()
        )
        for a in appts:
            await sess.delete(a)
        await sess.commit()
        s = await sess.get(Stylist, sid)
        if s:
            await sess.delete(s)
        await sess.commit()


@pytest.fixture
async def test_service():
    """Insert a minimal service for testing. Clean up after test."""
    from database.connection import get_async_session
    from database.models import Service, ServiceCategory

    if not await _db_available():
        pytest.skip("Postgres not reachable")

    svc_id = uuid4()
    async with get_async_session() as session:
        svc = Service(
            id=svc_id,
            name=f"TestCorte-{svc_id.hex[:6]}",
            category=ServiceCategory.HAIRDRESSING,
            duration_minutes=40,
            is_active=True,
        )
        session.add(svc)
        await session.commit()

    yield svc_id

    async with get_async_session() as sess:
        s = await sess.get(Service, svc_id)
        if s:
            await sess.delete(s)
        await sess.commit()


# ---------------------------------------------------------------------------
# Import smoke — always run (no DB needed)
# ---------------------------------------------------------------------------


def test_book_importable():
    from agent.tools.book import book  # noqa: F401

    assert hasattr(book, "invoke")


def test_book_has_tool_name():
    from agent.tools.book import book

    assert hasattr(book, "name")
    assert "book" in book.name


# ---------------------------------------------------------------------------
# Name validation — no DB needed (validation happens before DB call)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_book_rejects_empty_name():
    from agent.tools.book import book

    raw = await book.coroutine(
        service_ids=[str(uuid4())],
        stylist_id=str(uuid4()),
        start_iso=future_start_iso(),
        customer_full_name="",
        notes=None,
        confirmed=True,
        pre_book_validated=True,
        state={"customer_phone": "+34600000001"},
    )

    data = parse_response(raw)
    assert data["status"] == "rejected"
    assert len(data["errors"]) > 0


@pytest.mark.asyncio
async def test_book_rejects_single_token_name():
    """Single-word name (no surname) must be rejected before DB call."""
    from agent.tools.book import book

    raw = await book.coroutine(
        service_ids=[str(uuid4())],
        stylist_id=str(uuid4()),
        start_iso=future_start_iso(),
        customer_full_name="María",
        notes=None,
        confirmed=True,
        pre_book_validated=True,
        state={"customer_phone": "+34600000002"},
    )

    data = parse_response(raw)
    assert data["status"] == "rejected"
    assert len(data["errors"]) > 0


@pytest.mark.asyncio
async def test_book_error_messages_non_imperative():
    """Error strings must not start with imperative verbs."""
    from agent.tools.book import book

    raw = await book.coroutine(
        service_ids=[str(uuid4())],
        stylist_id=str(uuid4()),
        start_iso=future_start_iso(),
        customer_full_name="Solo",
        notes=None,
        confirmed=True,
        pre_book_validated=True,
        state={"customer_phone": "+34600000003"},
    )

    data = parse_response(raw)
    for err in data.get("errors", []):
        low = err.lower()
        assert not any(
            low.startswith(v) for v in ("use ", "choose ", "select ", "enter ", "provide ", "add ")
        ), f"Imperative error string: {err!r}"


def test_book_split_full_name_two_tokens():
    """_split_full_name: 'María García' → ('María', 'García')."""
    from agent.tools.book import _split_full_name

    first, last = _split_full_name("María García")
    assert first == "María"
    assert last == "García"


def test_book_split_full_name_multiple_tokens():
    """_split_full_name: 'Juan de la Cruz' → ('Juan', 'de la Cruz')."""
    from agent.tools.book import _split_full_name

    first, last = _split_full_name("Juan de la Cruz")
    assert first == "Juan"
    assert last == "de la Cruz"


def test_book_split_full_name_single_raises():
    from agent.tools.book import _split_full_name

    with pytest.raises(ValueError):
        _split_full_name("María")


def test_book_split_full_name_empty_raises():
    from agent.tools.book import _split_full_name

    with pytest.raises(ValueError):
        _split_full_name("")


def test_book_split_full_name_whitespace_only_raises():
    from agent.tools.book import _split_full_name

    with pytest.raises(ValueError):
        _split_full_name("   ")


# ---------------------------------------------------------------------------
# DB-dependent tests — skip if Postgres not available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_book_creates_new_customer_and_appointment(test_stylist, test_service):
    """Happy path: new phone → creates customer + appointment. Returns ok."""

    from agent.tools.book import book
    from database.connection import get_async_session
    from database.models import Appointment, AppointmentStatus, Customer

    phone = f"+34600{uuid4().hex[:6]}"

    _start = future_start_iso()
    _expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    _offered = [{"start_iso": _start, "stylist_id": str(test_stylist), "expires_at": _expires, "turn_index": 0}]

    with patch(
        "agent.services.gcal_push_service.fire_and_forget_push_appointment",
        new_callable=AsyncMock,
    ) as mock_push, patch(
        "agent.tools.book.check_slot_availability",
        new=AsyncMock(return_value={"available": True}),
    ):
        raw = await book.coroutine(
            service_ids=[str(test_service)],
            stylist_id=str(test_stylist),
            start_iso=_start,
            customer_full_name="María García",
            notes=None,
            confirmed=True,
            pre_book_validated=True,
            policy_accepted=True,
            state={"customer_phone": phone, "recently_offered_slots": _offered},
        )

    data = parse_response(raw)
    assert data["status"] == "ok"
    assert "appointment_id" in data["payload"]
    assert "customer_id" in data["payload"]
    assert "start_iso" in data["payload"]
    assert "end_iso" in data["payload"]
    assert "stylist_id" in data["payload"]
    mock_push.assert_called_once()

    # Verify DB rows
    async with get_async_session() as sess:
        appt = await sess.get(Appointment, data["payload"]["appointment_id"])
        assert appt is not None
        # future_start_iso(days_ahead=5) is >48h out, so the lead-time gate
        # (agent/tools/book.py:474) creates the appointment PENDING, not CONFIRMED.
        assert appt.status == AppointmentStatus.PENDING

        cust = await sess.get(Customer, data["payload"]["customer_id"])
        assert cust is not None
        assert cust.phone == phone
        assert cust.first_name == "María"
        assert cust.last_name == "García"

    # Cleanup
    from sqlalchemy import delete as sa_delete

    from database.models import CustomerConsent

    async with get_async_session() as sess:
        appt = await sess.get(Appointment, data["payload"]["appointment_id"])
        if appt:
            await sess.delete(appt)
        await sess.commit()
        cust_id = data["payload"]["customer_id"]
        await sess.execute(sa_delete(CustomerConsent).where(CustomerConsent.customer_id == cust_id))
        await sess.commit()
        cust = await sess.get(Customer, cust_id)
        if cust:
            await sess.delete(cust)
        await sess.commit()


@pytest.mark.asyncio
async def test_book_reuses_existing_customer(test_stylist, test_service):
    """If phone already exists in customers, reuse that customer_id."""
    from sqlalchemy import select

    from agent.tools.book import book
    from database.connection import get_async_session
    from database.models import Appointment, Customer

    phone = f"+34611{uuid4().hex[:6]}"

    # Pre-create customer
    async with get_async_session() as sess:
        existing = Customer(
            id=uuid4(),
            phone=phone,
            first_name="Existing",
            last_name="User",
        )
        sess.add(existing)
        await sess.commit()
        existing_id = existing.id

    _start2 = future_start_iso(days_ahead=6)
    _expires2 = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    _offered2 = [{"start_iso": _start2, "stylist_id": str(test_stylist), "expires_at": _expires2, "turn_index": 0}]

    with patch("agent.services.gcal_push_service.fire_and_forget_push_appointment", new_callable=AsyncMock), \
         patch("agent.tools.book.check_slot_availability", new=AsyncMock(return_value={"available": True})):
        raw = await book.coroutine(
            service_ids=[str(test_service)],
            stylist_id=str(test_stylist),
            start_iso=_start2,
            customer_full_name="Different Name",
            notes=None,
            confirmed=True,
            pre_book_validated=True,
            policy_accepted=True,
            state={"customer_phone": phone, "recently_offered_slots": _offered2},
        )

    data = parse_response(raw)
    assert data["status"] == "ok"
    assert str(data["payload"]["customer_id"]) == str(existing_id)

    # Cleanup
    from sqlalchemy import delete as sa_delete

    from database.models import CustomerConsent

    async with get_async_session() as sess:
        appts = (
            (await sess.execute(select(Appointment).where(Appointment.customer_id == existing_id)))
            .scalars()
            .all()
        )
        for a in appts:
            await sess.delete(a)
        await sess.commit()
        await sess.execute(sa_delete(CustomerConsent).where(CustomerConsent.customer_id == existing_id))
        await sess.commit()
        c = await sess.get(Customer, existing_id)
        if c:
            await sess.delete(c)
        await sess.commit()


@pytest.mark.asyncio
async def test_book_calls_gcal_push_after_db_commit(test_stylist, test_service):
    """GCal push (fire_and_forget) is called once on happy path."""
    from sqlalchemy import select

    from agent.tools.book import book
    from database.connection import get_async_session
    from database.models import Appointment, Customer

    phone = f"+34622{uuid4().hex[:6]}"

    _start3 = future_start_iso(days_ahead=7)
    _expires3 = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    _offered3 = [{"start_iso": _start3, "stylist_id": str(test_stylist), "expires_at": _expires3, "turn_index": 0}]

    with patch(
        "agent.services.gcal_push_service.fire_and_forget_push_appointment",
        new_callable=AsyncMock,
    ) as mock_push, patch(
        "agent.tools.book.check_slot_availability",
        new=AsyncMock(return_value={"available": True}),
    ):
        raw = await book.coroutine(
            service_ids=[str(test_service)],
            stylist_id=str(test_stylist),
            start_iso=_start3,
            customer_full_name="Ana López",
            notes="test note",
            confirmed=True,
            pre_book_validated=True,
            policy_accepted=True,
            state={"customer_phone": phone, "recently_offered_slots": _offered3},
        )

    data = parse_response(raw)
    assert data["status"] == "ok"
    mock_push.assert_called_once()

    # Cleanup
    from sqlalchemy import delete as sa_delete

    from database.models import CustomerConsent

    async with get_async_session() as sess:
        cust = (
            await sess.execute(select(Customer).where(Customer.phone == phone))
        ).scalar_one_or_none()
        if cust:
            appts = (
                (await sess.execute(select(Appointment).where(Appointment.customer_id == cust.id)))
                .scalars()
                .all()
            )
            for a in appts:
                await sess.delete(a)
            await sess.commit()
            await sess.execute(sa_delete(CustomerConsent).where(CustomerConsent.customer_id == cust.id))
            await sess.commit()
            await sess.delete(cust)
            await sess.commit()


# ---------------------------------------------------------------------------
# T5 — book inviolable preconditions (R7, R8)
# ---------------------------------------------------------------------------

FAKE_SERVICE_ID = uuid4()
FAKE_STYLIST_ID = uuid4()


STATE_WITH_PHONE = {"customer_phone": "+34600000001"}


def _book_args(**overrides):
    """Return a minimal valid book call dict.

    customer_phone is NOT included — it is injected via state (InjectedState).
    Pass state=STATE_WITH_PHONE separately when calling book.coroutine().
    """
    base = {
        "service_ids": [str(FAKE_SERVICE_ID)],
        "stylist_id": str(FAKE_STYLIST_ID),
        "start_iso": future_start_iso(5),
        "customer_full_name": "Ana López",
        "confirmed": True,
        "pre_book_validated": True,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_confirmation_gate_false():
    """R7: confirmed=False → rejected, next_step=confirmation_required, no DB write."""
    from agent.tools.book import book

    raw = await book.coroutine(**_book_args(confirmed=False), state=STATE_WITH_PHONE)
    data = parse_response(raw)
    assert data["status"] == "rejected"
    assert data.get("next_step") == "confirmation_required"


@pytest.mark.asyncio
async def test_confirmation_gate_omitted():
    """R7: confirmed not passed (defaults to False) → same rejection."""
    from agent.tools.book import book

    args = _book_args()
    del args["confirmed"]  # omit — should default to False
    raw = await book.coroutine(**args, state=STATE_WITH_PHONE)
    data = parse_response(raw)
    assert data["status"] == "rejected"
    assert data.get("next_step") == "confirmation_required"


@pytest.mark.asyncio
async def test_incomplete_missing_customer_name():
    """R8: confirmed=True but customer_full_name absent → incomplete_booking,
    payload.missing contains customer_full_name."""
    from agent.tools.book import book

    raw = await book.coroutine(**_book_args(customer_full_name=""), state=STATE_WITH_PHONE)
    data = parse_response(raw)
    assert data["status"] == "rejected"
    assert data.get("next_step") == "incomplete_booking"
    assert "customer_full_name" in data.get("payload", {}).get("missing", [])


@pytest.mark.asyncio
async def test_incomplete_missing_phone():
    """R8: confirmed=True but customer_phone absent from state → rejected.

    customer_phone is now read from state (InjectedState), not from tool args.
    Passing an empty state simulates a missing phone.
    """
    from agent.tools.book import book

    raw = await book.coroutine(**_book_args(), state={"customer_phone": ""})
    data = parse_response(raw)
    assert data["status"] == "rejected"
    # Missing state phone is caught before the completeness guard
    assert data.get("next_step") in (None, "incomplete_booking", "confirmation_required") or data.get(
        "errors"
    )


@pytest.mark.asyncio
async def test_incomplete_missing_service_ids():
    """R8: confirmed=True but service_ids empty → incomplete_booking."""
    from agent.tools.book import book

    raw = await book.coroutine(**_book_args(service_ids=[]), state=STATE_WITH_PHONE)
    data = parse_response(raw)
    assert data["status"] == "rejected"
    assert data.get("next_step") == "incomplete_booking"
    assert "service_ids" in data.get("payload", {}).get("missing", [])


@pytest.mark.asyncio
async def test_incomplete_missing_stylist():
    """R8: confirmed=True but stylist_id empty → incomplete_booking."""
    from agent.tools.book import book

    raw = await book.coroutine(**_book_args(stylist_id=""), state=STATE_WITH_PHONE)
    data = parse_response(raw)
    assert data["status"] == "rejected"
    assert data.get("next_step") == "incomplete_booking"
    assert "stylist_id" in data.get("payload", {}).get("missing", [])


@pytest.mark.asyncio
async def test_incomplete_missing_start_iso():
    """R8: confirmed=True but start_iso empty → incomplete_booking."""
    from agent.tools.book import book

    raw = await book.coroutine(**_book_args(start_iso=""), state=STATE_WITH_PHONE)
    data = parse_response(raw)
    assert data["status"] == "rejected"
    assert data.get("next_step") == "incomplete_booking"
    assert "start_iso" in data.get("payload", {}).get("missing", [])
