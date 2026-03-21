from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from tests.e2e.conftest import qa_run_identity as qa_run_identity_fixture
from tests.e2e.harness.redis_harness import RedisTestHarness
from shared.redis_client import INCOMING_STREAM
from tests.e2e.harness.run_models import QARunIdentity
from tests.e2e.harness.state_reset import ProtectedDataError, safe_delete_customer


class FakePubSub:
    def __init__(self, messages: list[dict | None]):
        self._messages = list(messages)

    async def get_message(self, ignore_subscribe_messages: bool = True, timeout: float | None = None):
        await asyncio.sleep(0)
        if self._messages:
            return self._messages.pop(0)
        if timeout:
            await asyncio.sleep(min(timeout, 0.01))
        return None

    async def subscribe(self, *_args, **_kwargs) -> None:
        return None

    async def unsubscribe(self, *_args, **_kwargs) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeDeleteResult:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount


class FakeDeleteSession:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount
        self.executed = 0

    async def execute(self, _statement):
        self.executed += 1
        return FakeDeleteResult(self.rowcount)


class _DummyNode:
    def __init__(self, name: str):
        self.name = name


class _DummyRequest:
    def __init__(self, name: str):
        self.node = _DummyNode(name)


def _pubsub_message(conversation_id: str, message: str) -> dict[str, str]:
    return {
        "data": (
            f'{{"conversation_id": "{conversation_id}", "customer_phone": "+34999123456", '
            f'"message": "{message}"}}'
        )
    }


@pytest.mark.asyncio
async def test_capture_response_batches_matching_messages() -> None:
    redis_client = AsyncMock()
    harness = RedisTestHarness(redis_client=redis_client, binary_redis_client=AsyncMock())
    harness._pubsub = FakePubSub(
        [
            _pubsub_message("other-conversation", "ignorada"),
            _pubsub_message("target-conversation", "Primera respuesta"),
            _pubsub_message("target-conversation", "Segunda respuesta"),
            None,
        ]
    )

    response = await harness.capture_response(
        conversation_id="target-conversation",
        timeout=0.1,
        batch_window_seconds=0.01,
    )

    assert response["conversation_id"] == "target-conversation"
    assert response["message"] == "Primera respuesta\n\nSegunda respuesta"
    assert len(response["raw_payloads"]) == 2
    assert all(payload["conversation_id"] == "target-conversation" for payload in response["raw_payloads"])


@pytest.mark.asyncio
async def test_execute_turn_records_session_evidence() -> None:
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock(return_value="1-0")
    harness = RedisTestHarness(redis_client=redis_client, binary_redis_client=AsyncMock())
    harness._pubsub = FakePubSub([])
    identity = QARunIdentity(
        conversation_id="qa-conversation",
        customer_phone="+34999123456",
        sender_name="QA-booking-1234abcd",
        run_started_at=datetime.now(UTC),
    )
    session = harness.create_session(identity=identity, batch_window_seconds=0.01)

    async def fake_capture_response(
        conversation_id: str,
        timeout: float = 60.0,
        batch_window_seconds: float = 3.0,
    ) -> dict[str, object]:
        assert conversation_id == identity.conversation_id
        assert timeout == 60.0
        assert batch_window_seconds == 0.01
        return {
            "conversation_id": identity.conversation_id,
            "customer_phone": identity.customer_phone,
            "message": "Hola, decime qué servicio queres.",
            "messages": ["Hola, decime qué servicio queres."],
            "timestamp_first_captured": datetime.now(UTC),
            "timestamp_captured": datetime.now(UTC),
            "raw_payloads": [{"conversation_id": identity.conversation_id, "message": "Hola"}],
            "raw_payload": {"conversation_id": identity.conversation_id, "message": "Hola"},
        }

    harness.capture_response = fake_capture_response  # type: ignore[method-assign]

    result = await harness.execute_turn(user_message="Hola", session=session)

    assert result["turn_number"] == 1
    assert result["agent_response"] == "Hola, decime qué servicio queres."
    assert result["timed_out"] is False
    assert len(session.evidence) == 1
    assert session.turn_count == 1
    assert session.raw_payloads == [{"conversation_id": identity.conversation_id, "message": "Hola"}]
    assert redis_client.xadd.await_args_list[0].args == (
        INCOMING_STREAM,
        {
            "data": (
                '{"conversation_id": "qa-conversation", "customer_phone": "+34999123456", '
                '"message_text": "Hola", "sender_name": "QA-booking-1234abcd", '
                '"customer_name": "QA-booking-1234abcd", "is_audio_transcription": false, '
                '"audio_url": null}'
            ),
        },
    )
    assert redis_client.xadd.await_args_list[1].args[0] == "qa_outgoing:qa-conversation"
    assert redis_client.xadd.await_args_list[1].args[1]["bot_reply"] == "Hola, decime qué servicio queres."
    assert redis_client.xadd.await_args_list[1].args[1]["turn_index"] == "1"


@pytest.mark.asyncio
async def test_execute_turn_can_return_timeout_evidence_without_raising() -> None:
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock(return_value="1-0")
    harness = RedisTestHarness(redis_client=redis_client, binary_redis_client=AsyncMock())
    harness._pubsub = FakePubSub([])
    identity = QARunIdentity(
        conversation_id="qa-timeout",
        customer_phone="+34999000001",
        sender_name="QA-timeout-1234abcd",
        run_started_at=datetime.now(UTC),
    )
    session = harness.create_session(identity=identity)

    async def always_timeout(
        conversation_id: str,
        timeout: float = 60.0,
        batch_window_seconds: float = 3.0,
    ) -> dict[str, object]:
        raise TimeoutError(f"timeout for {conversation_id} after {timeout}s / {batch_window_seconds}s")

    harness.capture_response = always_timeout  # type: ignore[method-assign]

    result = await harness.execute_turn(
        user_message="Necesito turno",
        session=session,
        raise_on_timeout=False,
    )

    assert result["turn_number"] == 1
    assert result["timed_out"] is True
    assert result["agent_response"] is None
    assert session.turn_count == 1
    assert len(session.evidence) == 1
    assert session.evidence[0].timed_out is True


def test_two_runs_different_phones() -> None:
    identity_factory = getattr(qa_run_identity_fixture, "__wrapped__")

    identity_one = identity_factory(_DummyRequest("qa-first-run"))
    identity_two = identity_factory(_DummyRequest("qa-second-run"))

    assert identity_one.customer_phone != identity_two.customer_phone
    assert identity_one.customer_phone.startswith("+34999")
    assert identity_two.customer_phone.startswith("+34999")


@pytest.mark.asyncio
async def test_session_evidence_not_shared() -> None:
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock(return_value="1-0")
    harness = RedisTestHarness(redis_client=redis_client, binary_redis_client=AsyncMock())
    harness._pubsub = FakePubSub([])
    identity_one = QARunIdentity(
        conversation_id="qa-session-one",
        customer_phone="+34999123456",
        sender_name="QA-one",
        run_started_at=datetime.now(UTC),
    )
    identity_two = QARunIdentity(
        conversation_id="qa-session-two",
        customer_phone="+34999123457",
        sender_name="QA-two",
        run_started_at=datetime.now(UTC),
    )
    session_one = harness.create_session(identity=identity_one, batch_window_seconds=0.01)
    session_two = harness.create_session(identity=identity_two, batch_window_seconds=0.01)

    async def fake_capture_response(
        conversation_id: str,
        timeout: float = 60.0,
        batch_window_seconds: float = 3.0,
    ) -> dict[str, object]:
        return {
            "conversation_id": conversation_id,
            "customer_phone": identity_one.customer_phone
            if conversation_id == identity_one.conversation_id
            else identity_two.customer_phone,
            "message": f"respuesta para {conversation_id}",
            "messages": [f"respuesta para {conversation_id}"],
            "timestamp_first_captured": datetime.now(UTC),
            "timestamp_captured": datetime.now(UTC),
            "raw_payloads": [{"conversation_id": conversation_id, "message": "ok"}],
            "raw_payload": {"conversation_id": conversation_id, "message": "ok"},
        }

    harness.capture_response = fake_capture_response  # type: ignore[method-assign]

    await harness.execute_turn(user_message="hola", session=session_one)
    await harness.execute_turn(user_message="buenas", session=session_two)

    assert len(session_one.evidence) == 1
    assert len(session_two.evidence) == 1
    assert session_one.evidence[0].agent_response == "respuesta para qa-session-one"
    assert session_two.evidence[0].agent_response == "respuesta para qa-session-two"
    assert session_one.raw_payloads == [{"conversation_id": "qa-session-one", "message": "ok"}]
    assert session_two.raw_payloads == [{"conversation_id": "qa-session-two", "message": "ok"}]


@pytest.mark.asyncio
async def test_capture_filters_by_conversation_id() -> None:
    redis_client = AsyncMock()
    harness = RedisTestHarness(redis_client=redis_client, binary_redis_client=AsyncMock())
    harness._pubsub = FakePubSub(
        [
            _pubsub_message("other-conversation", "ignorada"),
            _pubsub_message("target-conversation", "capturada"),
            None,
        ]
    )

    response = await harness.capture_response(
        conversation_id="target-conversation",
        timeout=0.1,
        batch_window_seconds=0.01,
    )

    assert response["message"] == "capturada"
    assert response["raw_payloads"] == [
        {
            "conversation_id": "target-conversation",
            "customer_phone": "+34999123456",
            "message": "capturada",
        }
    ]


@pytest.mark.asyncio
async def test_capture_ignores_other_conversations() -> None:
    redis_client = AsyncMock()
    harness = RedisTestHarness(redis_client=redis_client, binary_redis_client=AsyncMock())
    harness._pubsub = FakePubSub(
        [
            _pubsub_message("other-conversation", "ignorada"),
            None,
        ]
    )

    with pytest.raises(TimeoutError, match="target-conversation"):
        await harness.capture_response(
            conversation_id="target-conversation",
            timeout=0.02,
            batch_window_seconds=0.01,
        )


@pytest.mark.asyncio
async def test_timeout_returns_evidence_with_timeout_flag() -> None:
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock(return_value="1-0")
    harness = RedisTestHarness(redis_client=redis_client, binary_redis_client=AsyncMock())
    harness._pubsub = FakePubSub([])
    session = harness.create_session(
        identity=QARunIdentity(
            conversation_id="qa-timeout-flag",
            customer_phone="+34999000002",
            sender_name="QA-timeout-flag",
            run_started_at=datetime.now(UTC),
        )
    )

    async def always_timeout(
        conversation_id: str,
        timeout: float = 60.0,
        batch_window_seconds: float = 3.0,
    ) -> dict[str, object]:
        raise TimeoutError(f"timeout for {conversation_id} after {timeout}s / {batch_window_seconds}s")

    harness.capture_response = always_timeout  # type: ignore[method-assign]

    result = await harness.execute_turn(
        user_message="Necesito turno",
        session=session,
        raise_on_timeout=False,
    )

    assert result["timed_out"] is True
    assert session.evidence[0].timed_out is True


@pytest.mark.asyncio
async def test_timeout_does_not_crash() -> None:
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock(return_value="1-0")
    harness = RedisTestHarness(redis_client=redis_client, binary_redis_client=AsyncMock())
    harness._pubsub = FakePubSub([])
    session = harness.create_session(
        identity=QARunIdentity(
            conversation_id="qa-timeout-safe",
            customer_phone="+34999000003",
            sender_name="QA-timeout-safe",
            run_started_at=datetime.now(UTC),
        )
    )
    harness.capture_response = AsyncMock(side_effect=TimeoutError("boom"))

    result = await harness.execute_turn(
        user_message="Necesito turno",
        session=session,
        raise_on_timeout=False,
    )

    assert result["agent_response"] is None
    assert result["timed_out"] is True
    assert len(session.evidence) == 1


@pytest.mark.asyncio
async def test_cleanup_only_deletes_test_phone() -> None:
    session = FakeDeleteSession(rowcount=1)

    deleted = await safe_delete_customer(cast(Any, session), "+34999123456")

    assert deleted == 1
    assert session.executed == 1


@pytest.mark.asyncio
async def test_cleanup_refuses_real_phone() -> None:
    with pytest.raises(ProtectedDataError, match="Refusing to delete non-test data"):
        await safe_delete_customer(cast(Any, SimpleNamespace()), "+34612345678")
