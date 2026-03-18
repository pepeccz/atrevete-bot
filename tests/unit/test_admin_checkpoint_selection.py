from unittest.mock import AsyncMock, MagicMock

import pytest

from api.routes.admin import _get_latest_checkpoint_state


def _async_iter(items):
    async def _generator():
        for item in items:
            yield item

    return _generator()


def _make_checkpoint(message_count: int) -> dict:
    return {
        "checkpoint": {
            "channel_values": {
                "messages": [{"content": f"msg-{idx}"} for idx in range(message_count)],
                "customer_name": "Ana",
            }
        }
    }


def _make_redis(checkpoints: dict[str, dict]) -> MagicMock:
    redis_client = MagicMock()
    redis_client.scan_iter = MagicMock(return_value=_async_iter(list(checkpoints.keys())))
    json_client = MagicMock()
    json_client.get = AsyncMock(side_effect=lambda key: checkpoints[key])
    redis_client.json = MagicMock(return_value=json_client)
    return redis_client


@pytest.mark.asyncio
async def test_latest_checkpoint_state_picks_highest_message_count() -> None:
    checkpoints = {
        "checkpoint:thread-123:001": _make_checkpoint(3),
        "checkpoint:thread-123:002": _make_checkpoint(7),
        "checkpoint:thread-123:003": _make_checkpoint(5),
    }
    redis_client = _make_redis(checkpoints)

    state = await _get_latest_checkpoint_state(redis_client, "thread-123")

    assert state is not None
    assert len(state["messages"]) == 7


@pytest.mark.asyncio
async def test_latest_checkpoint_state_returns_single_entry() -> None:
    checkpoints = {
        "checkpoint:thread-999:001": _make_checkpoint(4),
    }
    redis_client = _make_redis(checkpoints)

    state = await _get_latest_checkpoint_state(redis_client, "thread-999")

    assert state is not None
    assert len(state["messages"]) == 4
