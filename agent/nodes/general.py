"""General node — Task 6.3.

Wraps `langchain.agents.create_agent` with:
  - query_info tool
  - DynamicPromptMiddleware (injects catalog + hours per turn)
  - Short Spanish system prompt

Factory pattern: `build_general_node(llm_factory)` → async node callable.
The node returns a plain dict `{"messages": [<new messages only>]}` so the
top-level graph's `add_messages` reducer accumulates them correctly.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AnyMessage

from agent.middleware.dynamic_prompt import DynamicPromptMiddleware
from agent.tools.query_info import query_info

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Eres Maite, la asistente virtual de Atrévete Peluquería. "
    "Responde consultas sobre servicios, horarios y políticas usando la herramienta "
    "query_info cuando sea útil. Responde siempre en español."
)


def build_general_node(
    llm_factory: Callable[[], Any],
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    """Build and return the async general node function.

    Args:
        llm_factory: Zero-arg callable that returns a `BaseChatModel` instance.

    Returns:
        Async node function compatible with LangGraph StateGraph.
    """
    agent = create_agent(
        model=llm_factory(),
        tools=[query_info],
        system_prompt=_SYSTEM_PROMPT,
        middleware=[DynamicPromptMiddleware()],
    )

    async def general_node(state: dict[str, Any]) -> dict[str, Any]:
        existing: list[AnyMessage] = state.get("messages") or []
        result = await agent.ainvoke({"messages": existing})
        all_messages: list[AnyMessage] = result.get("messages", [])
        # Return only delta (newly added messages)
        new_messages = all_messages[len(existing) :]
        return {"messages": new_messages}

    return general_node
