"""Canonical agent tool registry.

AGENT_TOOLS is the single source of truth for the 6 tools passed to create_agent.
Order is load-bearing: LangChain bind_tools uses positional indices for prompt-cache
stability. Do NOT reorder without a matching model-evaluation pass.
"""

from langchain_core.tools import BaseTool

from agent.tools.book import book
from agent.tools.check_availability import check_availability
from agent.tools.escalation_tools import escalate
from agent.tools.manage_appointments_tool import manage_appointments
from agent.tools.next_available import get_next_available_options
from agent.tools.update_booking import update_booking

AGENT_TOOLS: list[BaseTool] = [
    check_availability,
    get_next_available_options,
    book,
    manage_appointments,
    escalate,
    update_booking,
]

__all__ = ["AGENT_TOOLS"]
