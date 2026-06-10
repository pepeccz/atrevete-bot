"""agent_factory — build_conversation_agent() entry point.

Public API
----------
build_conversation_agent(llm_factory, checkpointer) -> CompiledStateGraph
    Returns a create_agent graph wired with 6 tools and 7–8 middleware layers.

Middleware stack (7 base layers + 1 optional trace layer):
  When LLM_TRACE_ENABLED=True:
    [LLMTraceMiddleware, Disclosure, CustomerResolve, AppointmentContext,
     DynamicPrompt, AvailabilityContext, PromptAssembly, Summarize]
  When LLM_TRACE_ENABLED=False (default):
    [Disclosure, CustomerResolve, AppointmentContext, DynamicPrompt,
     AvailabilityContext, PromptAssembly, Summarize]

LLMTraceMiddleware is FIRST (outermost) so its ContextVar scope covers all
middleware including SummarizeMiddleware's internal LLM call. See Design ADR-3.
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
from agent.middleware.llm_trace import LLMTraceMiddleware
from agent.middleware.prompt_assembly import PromptAssemblyMiddleware
from agent.middleware.response_groundedness import ResponseGroundednessMiddleware
from agent.middleware.summarize import SummarizeMiddleware
from agent.prompts.loader import load_system_prompt
from agent.state import AgentState
from agent.tools import AGENT_TOOLS
from shared.config import get_settings


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
    settings = get_settings()

    # Base 7-layer middleware stack (always present)
    base_middleware = [
        DisclosureMiddleware(),
        CustomerResolveMiddleware(),
        AppointmentContextMiddleware(),  # runs after CustomerResolve (reads customer_id)
        DynamicPromptMiddleware(),
        AvailabilityContextMiddleware(),  # injects _slot_availability after DynamicPrompt
        PromptAssemblyMiddleware(),  # assembles _slot_* keys into system_message
        SummarizeMiddleware(window=20, keep_tail=10),
        # J5: post-hoc groundedness scan (LOG-ONLY at initial deploy)
        ResponseGroundednessMiddleware(),
    ]

    # Prepend LLMTraceMiddleware as outermost layer (index 0) when tracing is enabled.
    # ADR-3: outermost position ensures ContextVar covers SummarizeMiddleware's LLM call.
    if settings.LLM_TRACE_ENABLED:
        middleware = [LLMTraceMiddleware(), *base_middleware]
    else:
        middleware = base_middleware

    return create_agent(
        model=model,
        tools=AGENT_TOOLS,
        system_prompt=load_system_prompt(),
        middleware=middleware,
        checkpointer=checkpointer,
        state_schema=AgentState,
    )
