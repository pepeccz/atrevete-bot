"""agent_factory — build_conversation_agent() entry point.

Public API
----------
build_conversation_agent(llm_factory, checkpointer) -> CompiledStateGraph
    Returns a create_agent graph wired with 6 tools and 7 middleware layers.
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent

from agent.llm import get_llm
from agent.middleware.appointment_context import AppointmentContextMiddleware
from agent.middleware.availability_context import AvailabilityContextMiddleware
from agent.middleware.customer_resolve import CustomerResolveMiddleware
from agent.middleware.disclosure import DisclosureMiddleware
from agent.middleware.dynamic_prompt import DynamicPromptMiddleware
from agent.middleware.prompt_assembly import PromptAssemblyMiddleware
from agent.middleware.summarize import SummarizeMiddleware
from agent.prompts.loader import load_system_prompt
from agent.state import AgentState
from agent.tools import AGENT_TOOLS


def build_conversation_agent(
    llm_factory: Any = None,
    checkpointer: Any = None,
) -> Any:
    """Build and compile the create_agent conversation graph.

    Args:
        llm_factory: Zero-arg callable → BaseChatModel. Defaults to get_llm().
        checkpointer: Optional LangGraph checkpointer (AsyncRedisSaver / MemorySaver).

    Returns:
        CompiledStateGraph — same interface as old create_graph() output.
    """
    model = (llm_factory or get_llm)()

    return create_agent(
        model=model,
        tools=AGENT_TOOLS,
        system_prompt=load_system_prompt(),
        middleware=[
            DisclosureMiddleware(),
            CustomerResolveMiddleware(),
            AppointmentContextMiddleware(),  # runs after CustomerResolve (reads customer_id)
            DynamicPromptMiddleware(),
            AvailabilityContextMiddleware(),  # injects _slot_availability after DynamicPrompt
            PromptAssemblyMiddleware(),  # assembles _slot_* keys into system_message
            SummarizeMiddleware(window=20, keep_tail=10),
        ],
        checkpointer=checkpointer,
        state_schema=AgentState,
    )
