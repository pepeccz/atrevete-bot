from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from database.models import AppointmentStatus
from tests.e2e.harness import state_reset
from tests.e2e.harness.run_models import QARunIdentity
from tests.e2e.harness.state_reset import (
    AsyncDatabaseCleaner,
    ProtectedDataError,
    is_test_conversation,
    is_test_phone,
    safe_delete_appointments,
    safe_delete_conversation,
    safe_delete_customer,
)


class FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        if isinstance(self._value, list):
            return self._value
        return []

    def first(self):
        return self._value

    def __iter__(self):
        if isinstance(self._value, list):
            return iter(self._value)
        return iter([])


class FakeSession:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, _statement):
        if not self._results:
            raise AssertionError("Unexpected extra execute() call")
        return self._results.pop(0)


@pytest.fixture
def run_identity() -> QARunIdentity:
    return QARunIdentity(
        conversation_id="qa-conv-123",
        customer_phone="+34999123456",
        sender_name="QA Test",
        run_started_at=datetime.now(UTC),
    )


def test_is_test_phone_accepts_only_qa_marker() -> None:
    assert is_test_phone("+34999123456") is True
    assert is_test_phone("+34612345678") is False
    assert is_test_phone("34999123456") is False


def test_is_test_conversation_matches_run_identity(run_identity: QARunIdentity) -> None:
    assert is_test_conversation("qa-conv-123", run_identity) is True
    assert is_test_conversation("other-conv", run_identity) is False


@pytest.mark.asyncio
async def test_safe_delete_customer_rejects_real_phone() -> None:
    with pytest.raises(ProtectedDataError, match="Refusing to delete non-test data"):
        await safe_delete_customer(cast(Any, SimpleNamespace()), "+34612345678")


@pytest.mark.asyncio
async def test_safe_delete_appointments_rejects_real_phone() -> None:
    with pytest.raises(ProtectedDataError, match="Refusing to delete non-test data"):
        await safe_delete_appointments(cast(Any, SimpleNamespace()), "+34612345678")


@pytest.mark.asyncio
async def test_safe_delete_conversation_rejects_foreign_conversation(
    run_identity: QARunIdentity,
) -> None:
    with pytest.raises(ProtectedDataError, match="Refusing to delete non-test data"):
        await safe_delete_conversation(cast(Any, SimpleNamespace()), "foreign-conv", run_identity)


@pytest.mark.asyncio
async def test_verify_appointment_returns_none_when_customer_missing(
    run_identity: QARunIdentity,
) -> None:
    cleaner = AsyncDatabaseCleaner("postgresql+asyncpg://irrelevant/test", run_identity)
    fake_session = FakeSession([FakeScalarResult(None)])

    @asynccontextmanager
    async def fake_session_context():
        yield fake_session

    cleaner._session_context = fake_session_context  # type: ignore[method-assign]

    result = await cleaner.verify_appointment(
        phone=run_identity.customer_phone,
        service_name="Corte caballero",
        stylist_name="Luciana",
        start_datetime=datetime.now(UTC),
    )

    assert result is None


@pytest.mark.asyncio
async def test_verify_appointment_returns_normalized_row(run_identity: QARunIdentity) -> None:
    appointment_id = uuid4()
    customer_id = uuid4()
    stylist_id = uuid4()
    service_id = uuid4()
    start_datetime = datetime.now(UTC)
    created_at = datetime.now(UTC)

    appointment = SimpleNamespace(
        id=appointment_id,
        customer_id=customer_id,
        stylist_id=stylist_id,
        service_ids=[service_id],
        start_time=start_datetime,
        created_at=created_at,
        status=AppointmentStatus.PENDING,
    )
    customer = SimpleNamespace(id=customer_id, phone=run_identity.customer_phone)
    service = SimpleNamespace(id=service_id, name="Corte caballero")
    stylist = SimpleNamespace(id=stylist_id, name="Luciana")

    cleaner = AsyncDatabaseCleaner("postgresql+asyncpg://irrelevant/test", run_identity)
    fake_session = FakeSession(
        [
            FakeScalarResult((appointment, customer, service, stylist)),
        ]
    )

    @asynccontextmanager
    async def fake_session_context():
        yield fake_session

    cleaner._session_context = fake_session_context  # type: ignore[method-assign]

    result = await cleaner.verify_appointment(
        phone=run_identity.customer_phone,
        service_name=service.name,
        stylist_name=stylist.name,
        start_datetime=start_datetime,
    )

    assert result == {
        "appointment_id": appointment_id,
        "customer_id": customer_id,
        "customer_phone": run_identity.customer_phone,
        "service_name": service.name,
        "stylist_name": stylist.name,
        "start_datetime": start_datetime,
        "created_at": created_at,
        "status": "pending",
    }


class TestCliEntrypoint:
    """FIX 2 (TASK-23 QA-harness continuity tooling): state_reset.py previously had
    no argparse/__main__ entrypoint, so the command documented in
    skills/atrevete-qa-runner/SKILL.md Steps 2/8
    (``python tests/e2e/harness/state_reset.py reset --conversation-id X --phone Y``)
    silently exited 0 without doing anything."""

    def test_main_reset_invokes_cmd_reset_with_parsed_args(self, monkeypatch) -> None:
        recorded: dict[str, Any] = {}

        async def fake_cmd_reset(conversation_id: str, phone: str) -> None:
            recorded["conversation_id"] = conversation_id
            recorded["phone"] = phone

        monkeypatch.setattr(state_reset, "_cmd_reset", fake_cmd_reset)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "state_reset.py",
                "reset",
                "--conversation-id",
                "qa-conv-123",
                "--phone",
                "+34999123456",
            ],
        )

        state_reset.main()

        assert recorded == {"conversation_id": "qa-conv-123", "phone": "+34999123456"}

    def test_reset_missing_conversation_id_exits_nonzero(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "argv", ["state_reset.py", "reset", "--phone", "+34999123456"])

        with pytest.raises(SystemExit) as exc_info:
            state_reset.main()

        assert exc_info.value.code != 0

    @pytest.mark.asyncio
    async def test_cmd_reset_rejects_non_qa_phone(self, monkeypatch) -> None:
        """The +349 guard must refuse a reset for a non-test phone instead of
        silently touching production-shaped data."""
        harness_reset = AsyncMock()
        monkeypatch.setattr(
            state_reset,
            "StateResetHarness",
            lambda redis_client: SimpleNamespace(reset_conversation_state=harness_reset),
        )

        with pytest.raises(SystemExit) as exc_info:
            await state_reset._cmd_reset(conversation_id="qa-conv-123", phone="+34612345678")

        assert exc_info.value.code == 1
        harness_reset.assert_not_called()

    @pytest.mark.asyncio
    async def test_cmd_reset_calls_harness_for_qa_phone(self, monkeypatch) -> None:
        harness_reset = AsyncMock(return_value={"clean": True})
        fake_client = SimpleNamespace(aclose=AsyncMock())
        monkeypatch.setattr(state_reset.redis, "from_url", lambda *a, **k: fake_client)
        monkeypatch.setattr(
            state_reset,
            "StateResetHarness",
            lambda redis_client: SimpleNamespace(reset_conversation_state=harness_reset),
        )

        await state_reset._cmd_reset(conversation_id="qa-conv-123", phone="+34999123456")

        harness_reset.assert_awaited_once_with(
            conversation_id="qa-conv-123", customer_phone="+34999123456"
        )
        fake_client.aclose.assert_awaited_once()
