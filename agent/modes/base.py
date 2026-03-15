"""
Base module for v6.0 mode nodes.

Provides shared types and the BaseModeNode abstract class used by all 4 modes.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from agent.prompts.loader import build_layered_messages, build_step_context, get_system_prompt
from agent.state.schemas import ConversationState
from shared.config import get_settings


# ============================================================================
# AgenticLoopResult — Return type for _run_agentic_loop()
# ============================================================================


@dataclass
class AgenticLoopResult:
    """Result from running an agentic loop with optional tool calls."""

    response_text: str
    tool_results: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


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
    escalation_triggered: bool
    error_count: int
    last_node: str
    conversation_summary: str
    user_message: str | None


# ============================================================================
# BaseModeNode — Abstract base class for all 4 mode nodes
# ============================================================================


class BaseModeNode(ABC):
    """
    Abstract base class for v6.0 mode nodes.

    Each mode node (Greeting, General, Booking, Escalation) inherits from
    this class and implements handle() to process the user message and
    return a partial state update dict.

    The _run_agentic_loop() method provides a reusable agentic loop with
    optional tool calling support.
    """

    def __init__(self, tools: list, llm_client: ChatOpenAI | None = None):
        self.tools = tools
        self.llm = llm_client
        self.logger = logging.getLogger(self.__class__.__name__)

    @property
    @abstractmethod
    def mode_name(self) -> str:
        """Return the mode name string (GREETING/BOOKING/GENERAL/ESCALATION)."""
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

    async def _load_cached_system_prompt(self) -> str:
        """
        Load the cached system prompt (shared content).

        Loads and concatenates:
        - shared/identity.md
        - shared/critical_rules.md
        - shared/glossary.md

        Cached for 10 minutes with thread safety via asyncio.Lock.

        Returns:
            str: Concatenated system prompt (~2,200 tokens)
        """
        return await get_system_prompt()

    def _build_step_context(
        self,
        state: ConversationState,
        mode_context: dict,
        step_name: str | None = None,
    ) -> str:
        """
        Build dynamic context with step info, collected data, and user message.

        Creates context string with:
        - Current step information
        - Collected data so far (service, stylist, slot, name, notes)
        - User message
        - Conversation summary (if available)

        Args:
            state: Current conversation state
            mode_context: Mode-specific context data
            step_name: Optional step name for context

        Returns:
            str: Dynamic context string (~300 tokens)
        """
        step_info = {"step_name": step_name} if step_name else None
        return build_step_context(state, mode_context, step_info)

    async def _build_layered_messages(
        self,
        state: ConversationState,
        mode_context: dict,
        step_name: str | None = None,
        include_history: bool = True,
        history_limit: int = 6,
    ) -> list:
        """
        Build messages using the optimized layered prompt approach.

        Uses cached system prompt + dynamic step context for ~25% token reduction.

        Args:
            state: Current conversation state
            mode_context: Mode-specific context data
            step_name: Optional step name for context
            include_history: Whether to include conversation history
            history_limit: Max number of history messages to include

        Returns:
            list: List of LangChain message objects
        """
        step_info = {"step_name": step_name} if step_name else None
        return await build_layered_messages(
            state,
            mode_context,
            step_info,
            include_history,
            history_limit,
            mode_name=self.mode_name,
            substep=step_name,
        )

    def _use_optimized_prompts(self) -> bool:
        """
        Check if optimized prompts should be used.

        Returns True if USE_OPTIMIZED_PROMPTS is enabled (default: True).
        When False, modes should fall back to legacy inline prompts.

        Returns:
            bool: Whether to use the optimized prompt system
        """
        try:
            settings = get_settings()
            return settings.USE_OPTIMIZED_PROMPTS
        except Exception:
            # Default to True if settings can't be loaded
            return True

    async def _call_llm(self, messages: list) -> Any | None:
        """
        Call the LLM with a list of messages. Returns the response or None on failure.

        Args:
            messages: List of LangChain message objects

        Returns:
            LLM response object or None if LLM not configured / call failed
        """
        if self.llm is None:
            return None
        try:
            return await self.llm.ainvoke(messages)
        except Exception as exc:
            self.logger.error("LLM call failed: %s", exc)
            return None

    async def _run_agentic_loop(
        self,
        messages: list,
        tools: list | None = None,
    ) -> AgenticLoopResult:
        """
        Run an agentic loop with optional tool calls.

        Flow:
        1. Call LLM (with tools bound if any)
        2. If LLM returns tool_calls, invoke each tool and collect results
        3. If tools were called, make a second LLM call with tool results for final response
        4. Return AgenticLoopResult with response_text and tool_results

        Args:
            messages: List of LangChain message objects (SystemMessage, HumanMessage, etc.)
            tools: Tool list to bind. Defaults to self.tools if None.

        Returns:
            AgenticLoopResult with response_text, tool_results, and optional error
        """
        active_tools = tools if tools is not None else self.tools
        tool_results: dict[str, Any] = {}

        if self.llm is None:
            return AgenticLoopResult(
                response_text="Error: no LLM configurado.",
                error="No LLM configured",
            )

        try:
            # Bind tools if any are provided
            llm_with_tools = self.llm.bind_tools(active_tools) if active_tools else self.llm
            response = await llm_with_tools.ainvoke(messages)

            # Process tool calls if any
            if hasattr(response, "tool_calls") and response.tool_calls:
                tool_map = {t.name: t for t in active_tools}

                for tool_call in response.tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool_args = tool_call.get("args", {})
                    if tool_name in tool_map:
                        try:
                            result = await tool_map[tool_name].ainvoke(tool_args)
                            tool_results[tool_name] = result
                        except Exception as exc:
                            self.logger.error(
                                "Tool %s failed: %s", tool_name, exc
                            )
                            tool_results[tool_name] = {"error": str(exc)}

                # Second LLM call with tool results appended
                tool_messages = list(messages)
                tool_messages.append(response)  # Append AIMessage with tool_calls

                for tool_call in response.tool_calls:
                    tool_name = tool_call.get("name", "")
                    result = tool_results.get(tool_name, {})
                    tool_messages.append(
                        ToolMessage(
                            content=str(result),
                            tool_call_id=tool_call.get("id", tool_name),
                        )
                    )

                final_response = await self.llm.ainvoke(tool_messages)
                response_text = (
                    final_response.content
                    if hasattr(final_response, "content")
                    else str(final_response)
                )
            else:
                response_text = (
                    response.content
                    if hasattr(response, "content")
                    else str(response)
                )

            return AgenticLoopResult(
                response_text=response_text,
                tool_results=tool_results,
            )

        except Exception as exc:
            self.logger.error("Agentic loop failed: %s", exc)
            return AgenticLoopResult(
                response_text="Lo siento, ha ocurrido un error. ¿Puedes repetir tu mensaje?",
                error=str(exc),
            )
