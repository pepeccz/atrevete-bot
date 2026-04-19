"""
Base module for v6.0 mode nodes.

Provides shared types and the BaseModeNode abstract class used by modes that
still rely on inheritance (BookingModeNode, AppointmentManagementMode). Those
modes run via ``create_agent`` + middleware (see ``_invoke_create_agent`` in
each subclass); the legacy ``_run_agentic_loop`` was removed once no production
code path called it.

Surviving hooks (``_pre_tool_call``, ``_post_tool_result``) remain because the
``NodeBridgeMiddleware`` calls them on the node instance to preserve mode-level
gating and post-processing.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langchain_openai import ChatOpenAI

from agent.state.schemas import ConversationState

# ============================================================================
# ToolCallRejection — Returned by _pre_tool_call to reject a tool invocation
# ============================================================================


@dataclass
class ToolCallRejection:
    """Structured rejection from _pre_tool_call — skips tool execution cleanly.

    When _pre_tool_call returns this instead of a dict, NodeBridgeMiddleware:
    1. Skips tool.ainvoke()
    2. Builds a rejection dict with {"rejected": True, ...}
    3. Appends it as a ToolMessage so the LLM sees the rejection reason
    """

    name: str  # Tool name that was rejected (e.g. "book")
    error_code: str  # Machine code: NO_OFFERED_SLOTS, NO_CUSTOMER_NAME, etc.
    error_message: str  # Prescriptive instruction for LLM ("RECHAZADO. SIGUIENTE ACCIÓN: ...")
    recovery_response: str | None = None  # Human-facing forced text on 2nd failure


# ============================================================================
# AgenticLoopResult — Return type for _invoke_create_agent()
# ============================================================================


@dataclass
class AgenticLoopResult:
    """Result from running an agent turn (via create_agent + middleware)."""

    response_text: str
    tool_results: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    tool_events: list[Any] = field(default_factory=list)


# ============================================================================
# ModeResult — TypedDict for mode node return values
# ============================================================================


class ModeResult(TypedDict, total=False):
    """Type hints for dicts returned by mode node handle() methods."""

    messages: list
    current_mode: str
    customer_name: str | None
    customer_id: str | None
    mode_context: dict
    mode_history: list[str]
    is_first_interaction: bool
    ai_disclosure_sent: bool
    escalation_triggered: bool
    error_count: int
    last_node: str
    conversation_summary: str
    user_message: str | None


# ============================================================================
# BaseModeNode — Abstract base class for modes on the legacy inheritance path
# ============================================================================


class BaseModeNode(ABC):
    """
    Abstract base class for v6.0 mode nodes still on class-based surface.

    BookingModeNode and AppointmentManagementMode inherit from this class.
    GreetingMode, GeneralMode, and EscalationMode are factory functions and
    do NOT inherit.

    Responsibilities left on this class:
    - ``mode_name`` / ``handle`` contract (abstract)
    - ``_pre_tool_call`` / ``_post_tool_result`` hooks consumed by
      ``NodeBridgeMiddleware`` to preserve mode-level tool gating and
      post-processing inside ``create_agent``.

    Everything else (prompt assembly, token tracking, agentic looping, response
    dedup) now lives in per-mode helpers or composable middleware.
    """

    def __init__(self, tools: list, llm_client: ChatOpenAI | None = None):
        self.tools = tools
        self.llm = llm_client
        self.logger = logging.getLogger(self.__class__.__name__)

    @property
    @abstractmethod
    def mode_name(self) -> str:
        """Return the mode name string (BOOKING / APPOINTMENT_MANAGEMENT)."""
        ...

    @abstractmethod
    async def handle(self, state: ConversationState, intent: Any) -> dict:
        """
        Process the user message and return a partial state update dict.

        Args:
            state: Current conversation state (read-only; return updates, don't mutate)
            intent: IntentResult from the router node

        Returns:
            Partial state dict with only the fields that changed.
            MUST always include "user_message": None to clear transient field.
        """
        ...

    async def _pre_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> dict[str, Any] | ToolCallRejection:
        """Hook called by NodeBridgeMiddleware before each tool invocation.

        Subclasses can override to intercept and transform tool arguments
        before the tool executes, or return a ToolCallRejection to prevent
        execution entirely.

        The hook receives the raw LLM dict BEFORE Pydantic validation, so it can
        resolve placeholder values (e.g. slot_index → stylist_id).

        Args:
            tool_name: Name of the tool about to be called.
            tool_args: Arguments the LLM provided for the tool (raw dict).

        Returns:
            Modified tool_args dict (or original if no changes needed),
            or ToolCallRejection to skip tool execution.
        """
        return tool_args

    async def _post_tool_result(
        self,
        tool_name: str,
        tool_args: dict,
        result: Any,
    ) -> Any:
        """Hook called by NodeBridgeMiddleware after each tool execution.

        Subclasses can override to process results mid-loop, allowing context
        updates to take effect before the LLM generates its final response.

        The base implementation is a no-op pass-through.

        Args:
            tool_name: Name of the tool that just executed.
            tool_args: Arguments that were passed to the tool.
            result: Raw result returned by the tool (str or dict).

        Returns:
            The (optionally modified) result to be used as the ToolMessage content.
        """
        return result
