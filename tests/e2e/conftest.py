"""pytest fixtures for conversational QA end-to-end tests."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
import redis.asyncio as redis

from shared.config import get_settings
from tests.e2e.harness.context_manager import QATestingContext, TestingContextManager
from tests.e2e.harness.redis_harness import RedisTestHarness
from tests.e2e.harness.run_models import QARunIdentity
from tests.e2e.harness.state_reset import StateResetHarness


@pytest.fixture(autouse=True)
def qa_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MESSAGE_BATCH_WINDOW_SECONDS", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator[redis.Redis, None]:
    settings = get_settings()
    conn_kwargs: dict[str, object] = {"decode_responses": True}
    if settings.REDIS_PASSWORD:
        conn_kwargs["password"] = settings.REDIS_PASSWORD
    client = redis.from_url(settings.REDIS_URL, **conn_kwargs)
    await client.ping()
    yield client
    await client.close()


@pytest_asyncio.fixture
async def binary_redis_client() -> AsyncGenerator[redis.Redis, None]:
    settings = get_settings()
    conn_kwargs: dict[str, object] = {"decode_responses": False}
    if settings.REDIS_PASSWORD:
        conn_kwargs["password"] = settings.REDIS_PASSWORD
    client = redis.from_url(settings.REDIS_URL, **conn_kwargs)
    await client.ping()
    yield client
    await client.close()


@pytest_asyncio.fixture
async def redis_harness(
    redis_client: redis.Redis,
    binary_redis_client: redis.Redis,
) -> AsyncGenerator[RedisTestHarness, None]:
    harness = RedisTestHarness(redis_client=redis_client, binary_redis_client=binary_redis_client)
    yield harness
    await harness.close()


@pytest_asyncio.fixture
async def state_reset(redis_client: redis.Redis) -> AsyncGenerator[StateResetHarness, None]:
    yield StateResetHarness(redis_client=redis_client)


@pytest.fixture
def testing_context() -> QATestingContext:
    manager = TestingContextManager(root_path=Path.cwd())
    try:
        return manager.load_context()
    except FileNotFoundError as exc:
        pytest.skip(f"QA context file not available in this environment: {exc}")


def _make_run_identity(request: pytest.FixtureRequest) -> QARunIdentity:
    """Generate a unique QARunIdentity from a pytest request (or duck-typed request).

    The conversation_id and customer_phone are derived from the test node name
    so each test gets a stable, isolated identity. Phone numbers always start
    with '+34999' (the QA test prefix).
    """
    test_name = request.node.name
    # Create a short deterministic suffix from the test name
    suffix = hashlib.md5(test_name.encode()).hexdigest()[:8]
    # Map suffix to digits for the phone (need 7 digits after '+34999')
    phone_digits = str(int(suffix, 16) % 10_000_000).zfill(7)
    customer_phone = f"+34999{phone_digits}"
    conversation_id = f"qa-{test_name[:32].replace(' ', '-').lower()}"
    sender_name = f"QA-{suffix}"
    return QARunIdentity(
        conversation_id=conversation_id,
        customer_phone=customer_phone,
        sender_name=sender_name,
        run_started_at=datetime.now(UTC),
    )


@pytest.fixture
def qa_run_identity(request: pytest.FixtureRequest) -> QARunIdentity:
    """Pytest fixture that generates a unique QARunIdentity per test node."""
    return _make_run_identity(request)


# Expose the underlying factory so tests can call it directly without pytest:
#   identity_factory = getattr(qa_run_identity, "__wrapped__")
#   identity = identity_factory(_DummyRequest("my-test"))
qa_run_identity.__wrapped__ = _make_run_identity  # type: ignore[attr-defined]


@pytest_asyncio.fixture(autouse=True)
async def cleanup_after_test(
    request: pytest.FixtureRequest, state_reset: StateResetHarness
) -> AsyncGenerator[None, None]:
    yield
    conversation_ids = getattr(request.node, "qa_conversation_ids", [])
    for conversation_id in conversation_ids:
        await state_reset.reset_conversation_state(conversation_id)
