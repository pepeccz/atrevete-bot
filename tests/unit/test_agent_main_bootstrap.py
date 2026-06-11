import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FakeBatcher:
    def __init__(self, window_seconds, redis_client):
        self.window_seconds = window_seconds
        self.redis_client = redis_client
        self._callback = None

    def set_callback(self, callback):
        self._callback = callback

    async def recover_pending_batches(self):
        import agent.main as agent_main

        assert self._callback is not None
        await self._callback(
            "conv-bootstrap-001",
            [
                {
                    "conversation_id": "conv-bootstrap-001",
                    "customer_phone": "+34612345678",
                    "customer_name": "Pepe Garcia",
                    "message_text": "Hola",
                }
            ],
        )
        agent_main.shutdown_event.set()
        return 1


def test_agent_main_uses_authoritative_graph_factory():
    """agent/main.py must import create_graph from agent.graph (create_agent rewrite).

    NOTE: old path was agent.graphs.conversation_flow (pre-create_agent architecture).
    Current path is agent.graph (commit 8bf72b4 — create_agent rewrite).
    """
    repo_root = Path(__file__).parent.parent.parent
    source = (repo_root / "agent" / "main.py").read_text(encoding="utf-8")

    assert "from agent.graph import create_graph" in source


@pytest.mark.asyncio
async def test_subscribe_to_incoming_messages_uses_authoritative_runtime_graph():
    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock(
        return_value={
            "messages": [{"role": "assistant", "content": "Hola, soy Maite"}],
            "current_mode": "GREETING",
            "last_node": "summarize",
        }
    )
    settings = SimpleNamespace(
        MESSAGE_BATCH_WINDOW_SECONDS=0,
        USE_REDIS_STREAMS=True,
        REDIS_URL="redis://localhost:6379/0",  # required by get_checkpointer in main.py
    )
    # Fake module with current agent.checkpointer API (get_checkpointer / setup_checkpointer)
    fake_cm = MagicMock()
    fake_cm.__aenter__ = AsyncMock(return_value="checkpoint")
    fake_cm.__aexit__ = AsyncMock(return_value=False)
    fake_checkpointer_module = SimpleNamespace(
        get_checkpointer=MagicMock(return_value=fake_cm),
        setup_checkpointer=AsyncMock(),
    )
    fake_langfuse_client = MagicMock()
    fake_langfuse_client.flush = MagicMock()
    fake_monitoring_module = SimpleNamespace(
        get_langfuse_handler=MagicMock(return_value=None),
        get_langfuse_client=MagicMock(return_value=fake_langfuse_client),
    )

    with patch.dict(
        sys.modules,
        {
            "agent.checkpointer": fake_checkpointer_module,
            "agent.utils.monitoring": fake_monitoring_module,
        },
    ):
        sys.modules.pop("agent.main", None)
        agent_main = importlib.import_module("agent.main")
        agent_main.shutdown_event = asyncio.Event()

        with (
            patch.object(agent_main, "validate_startup_config", new=AsyncMock()),
            patch.object(agent_main, "get_redis_client", return_value=MagicMock()),
            patch.object(agent_main, "get_settings", return_value=settings),
            patch.object(agent_main, "create_graph", return_value=fake_graph) as mock_create_graph,
            patch.object(agent_main, "MessageBatcher", _FakeBatcher),
            patch.object(agent_main, "publish_to_channel", new=AsyncMock()) as mock_publish,
            patch.object(agent_main, "create_consumer_group", new=AsyncMock()),
        ):
            await agent_main.subscribe_to_incoming_messages()

    # agent/main.py calls create_graph(checkpointer=saver) without store kwarg
    mock_create_graph.assert_called_once_with(checkpointer="checkpoint")

    invoked_state = fake_graph.ainvoke.await_args.args[0]
    invoked_config = fake_graph.ainvoke.await_args.kwargs["config"]

    assert invoked_state["conversation_id"] == "conv-bootstrap-001"
    assert invoked_state["customer_phone"] == "+34612345678"
    assert invoked_state["user_message"] == "Hola"
    assert invoked_state["pending_whatsapp_name"] == "Pepe Garcia"
    assert "customer_name" not in invoked_state
    assert invoked_config["configurable"]["thread_id"] == "conv-bootstrap-001"

    mock_publish.assert_awaited_once_with(
        "outgoing_messages",
        {
            "conversation_id": "conv-bootstrap-001",
            "customer_phone": "+34612345678",
            "message": "Hola, soy Maite",
        },
    )
