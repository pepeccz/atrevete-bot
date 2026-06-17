"""Unit tests for tests/e2e/harness/seed_customer.py.

All tests are fully mocked — no live DB or Redis required.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_customer(phone: str = "+34999000020") -> MagicMock:
    customer = MagicMock()
    customer.id = uuid4()
    customer.phone = phone
    customer.first_name = "Ana"
    customer.last_name = "Torres"
    customer.metadata_ = {}
    return customer


def _make_fake_service(name: str = "Corte de Mujer") -> MagicMock:
    service = MagicMock()
    service.id = uuid4()
    service.name = name
    service.duration_minutes = 60
    return service


def _make_fake_stylist(name: str = "Marta") -> MagicMock:
    stylist = MagicMock()
    stylist.id = uuid4()
    stylist.name = name
    return stylist


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phone_guard_rejects_non_test_prefix() -> None:
    """seed_returning_customer raises ValueError for non-+349 phones."""
    from tests.e2e.harness.seed_customer import seed_returning_customer

    with pytest.raises(ValueError, match=r"\+349"):
        await seed_returning_customer(
            phone="+34600000001",
            customer_name="Real Customer",
            memories={"visit_count": 1},
        )


@pytest.mark.asyncio
async def test_phone_guard_accepts_test_prefix() -> None:
    """seed_returning_customer does not raise ValueError for +34999... phones."""
    from tests.e2e.harness.seed_customer import seed_returning_customer

    fake_customer = _make_fake_customer(phone="+34999000020")

    # Mock the DB session to return the fake customer on select
    fake_session = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    fake_result = MagicMock()
    fake_result.scalar_one_or_none.return_value = fake_customer
    fake_session.execute = AsyncMock(return_value=fake_result)
    fake_session.flush = AsyncMock()
    fake_session.commit = AsyncMock()

    fake_session_factory = MagicMock(return_value=fake_session)

    with (
        patch("tests.e2e.harness.seed_customer.AsyncSessionLocal", fake_session_factory),
        patch("tests.e2e.harness.seed_customer._get_store_safe", return_value=None),
    ):
        # Should not raise ValueError
        result = await seed_returning_customer(
            phone="+34999000020",
            customer_name="Ana Torres",
            memories={"visit_count": 2},
        )

    assert result["customer_id"] == str(fake_customer.id)


@pytest.mark.asyncio
async def test_memories_written_keys_in_result() -> None:
    """Result dict contains memories_written_keys matching the input memories keys."""
    from tests.e2e.harness.seed_customer import seed_returning_customer

    input_memories = {
        "visit_count": 4,
        "preferred_stylist_name": "Marta",
        "typical_services": ["Corte de Mujer"],
        "agent_notes": "Prefiere media melena.",
    }

    fake_customer = _make_fake_customer()
    fake_session = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    fake_result = MagicMock()
    fake_result.scalar_one_or_none.return_value = fake_customer
    fake_session.execute = AsyncMock(return_value=fake_result)
    fake_session.flush = AsyncMock()
    fake_session.commit = AsyncMock()

    fake_store = AsyncMock()
    fake_store.aput = AsyncMock()

    with (
        patch("tests.e2e.harness.seed_customer.AsyncSessionLocal", MagicMock(return_value=fake_session)),
        patch("tests.e2e.harness.seed_customer._get_store_safe", return_value=fake_store),
    ):
        result = await seed_returning_customer(
            phone="+34999000020",
            customer_name="Ana Torres",
            memories=input_memories,
        )

    assert set(result["memories_written_keys"]) == set(input_memories.keys())
    assert result["past_appointment_id"] is None

    # Verify store.aput was called with the exact memories dict
    fake_store.aput.assert_called_once()
    call_kwargs = fake_store.aput.call_args.kwargs
    assert call_kwargs["value"] == input_memories


@pytest.mark.asyncio
async def test_past_appointment_date_is_in_the_past() -> None:
    """When past_appointment.days_ago=30, the appointment start_time is before now."""
    from tests.e2e.harness.seed_customer import seed_returning_customer

    fake_customer = _make_fake_customer()
    fake_service = _make_fake_service("Corte de Mujer")
    fake_stylist = _make_fake_stylist("Marta")

    # DB session that returns customer, then service, then stylist
    call_count = 0

    async def _execute_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # First call: select Customer
            result.scalar_one_or_none.return_value = fake_customer
        elif call_count == 2:
            # Second call: select Service
            result.scalar_one_or_none.return_value = fake_service
        elif call_count == 3:
            # Third call: select Stylist
            result.scalar_one_or_none.return_value = fake_stylist
        else:
            result.scalar_one_or_none.return_value = None
        return result

    # Track the Appointment that gets created
    created_appts: list = []

    fake_session = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    fake_session.execute = AsyncMock(side_effect=_execute_side_effect)
    fake_session.flush = AsyncMock()
    fake_session.commit = AsyncMock()

    original_add = MagicMock()

    def _capture_add(obj):
        # Capture Appointment objects
        from database.models import Appointment

        if isinstance(obj, Appointment):
            created_appts.append(obj)

    fake_session.add = MagicMock(side_effect=_capture_add)

    before_call = datetime.now(UTC)

    with (
        patch("tests.e2e.harness.seed_customer.AsyncSessionLocal", MagicMock(return_value=fake_session)),
        patch("tests.e2e.harness.seed_customer._get_store_safe", return_value=None),
    ):
        result = await seed_returning_customer(
            phone="+34999000020",
            customer_name="Ana Torres",
            memories={"visit_count": 4},
            past_appointment={
                "days_ago": 30,
                "service_name": "Corte de Mujer",
                "stylist_name": "Marta",
                "status": "completed",
            },
        )

    # An appointment must have been created
    assert len(created_appts) == 1, "Expected exactly one Appointment to be added to the session"
    appt = created_appts[0]

    # start_time must be strictly in the past relative to when the call was made
    assert appt.start_time < before_call, (
        f"Expected start_time {appt.start_time} to be before {before_call}"
    )

    # gcal_sync_status must be 'not_applicable' for test appointments
    assert appt.gcal_sync_status == "not_applicable"

    # past_appointment_id must be present in the result
    assert result["past_appointment_id"] is not None


def test_malformed_memories_json_cmd_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    """_cmd_seed exits with code 1 when --memories-json is not valid JSON."""
    import argparse
    import io

    from tests.e2e.harness import qa_turn_helper

    # Build a fake args namespace that mimics what argparse would produce
    args = argparse.Namespace(
        phone="+34999000020",
        customer_name="Ana Torres",
        memories_json="not valid json",
        past_appointment_json=None,
    )

    stderr_capture = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_capture)

    with pytest.raises(SystemExit) as exc_info:
        import asyncio

        asyncio.run(qa_turn_helper._cmd_seed(args))

    assert exc_info.value.code == 1

    stderr_output = stderr_capture.getvalue()
    import json

    error_payload = json.loads(stderr_output)
    assert error_payload["ok"] is False
    assert error_payload["error"] == "invalid memories_json"
