"""pytest fixtures for conversational QA end-to-end tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
import redis.asyncio as redis

from shared.config import get_settings
from tests.e2e.harness.context_manager import QATestingContext, TestingContextManager
from tests.e2e.harness.redis_harness import RedisTestHarness
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
    return manager.load_context()


@pytest_asyncio.fixture(autouse=True)
async def cleanup_after_test(
    request: pytest.FixtureRequest, state_reset: StateResetHarness
) -> AsyncGenerator[None, None]:
    yield
    conversation_ids = getattr(request.node, "qa_conversation_ids", [])
    for conversation_id in conversation_ids:
        await state_reset.reset_conversation_state(conversation_id)
