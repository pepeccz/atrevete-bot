"""
BaseModeNode — Abstract base class for all mode nodes (v6.0 mode-based architecture).

This module defines the shared contract and utilities that every mode node
(GreetingMode, BookingMode, GeneralMode, EscalationMode) must implement.

Architecture:
    BaseModeNode
        ├─ GreetingMode   (GREETING mode — first contact)
        ├─ BookingMode    (BOOKING mode — appointment flow)
        ├─ GeneralMode    (GENERAL mode — FAQs, info queries)
        └─ EscalationMode (ESCALATION mode — human handoff)

Each mode:
1. Receives the current ConversationState + IntentResult
2. Calls LLM (optionally with tools) via _call_llm()
3. Returns a partial state update dict for LangGraph reducers

Resilience:
    If ``resilience_chain`` is provided (a FallbackChain instance), all LLM
    calls go through ``call_with_fallback()`` for automatic provider rotation.
    Otherwise, LLM calls are made directly via ``llm_client.ainvoke()``.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent.state.helpers import increment_error_count
from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)


# ============================================================================
# ModeResult
# ============================================================================


@dataclass
class ModeResult:
    """
    Result returned by a mode node's handle() method.

    Encapsulates the response, any requested mode transition, context updates,
    and additional metadata for debugging or downstream logic.

    Attributes:
        response: The assistant response text to send to the customer.
        next_mode: If not None, signals a mode transition. The orchestrator
                   node should call ``transition_mode(state, next_mode)`` and
                   update the state accordingly.
        mode_context_update: Dict of changes to merge into state.mode_context
                             for the current (or incoming) mode.
        metadata: Arbitrary key-value pairs for debugging, metrics, or
                  downstream enrichment (not persisted to state).
    """

    response: str
    next_mode: str | None = None
    mode_context_update: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


# ============================================================================
# BaseModeNode
# ============================================================================


class BaseModeNode(ABC):
    """
    Abstract base class for all mode nodes in the v6.0 architecture.

    Subclasses MUST implement:
    - ``mode_name`` property (str) — unique identifier for the mode
    - ``handle(state, intent)`` method — core mode logic

    Shared utilities (available to all subclasses):
    - ``_call_llm(messages, tools)`` — resilience-aware LLM invocation
    - ``_build_messages(state, system_prompt)`` — constructs LangChain message list
    - ``_format_tool_response(tool_result)`` — formats tool output for LLM context

    Usage:
        class GreetingMode(BaseModeNode):
            @property
            def mode_name(self) -> str:
                return "GREETING"

            async def handle(self, state, intent) -> dict:
                messages = self._build_messages(state, "You are a greeter...")
                result = await self._call_llm(messages)
                response_text = result.content
                return add_message(state, "assistant", response_text)
    """

    def __init__(
        self,
        tools: list,
        llm_client: Any,
        resilience_chain: Any | None = None,
    ) -> None:
        """
        Initialise the mode node.

        Args:
            tools: List of LangChain tools available to this mode.
                   Pass an empty list for modes that don't use tools.
            llm_client: Primary LLM client (ChatOpenAI or compatible).
                        Must support ``ainvoke(messages)``.
            resilience_chain: Optional FallbackChain instance. If provided,
                              all LLM calls go through ``call_with_fallback()``.
                              If None, calls are made directly on ``llm_client``.
        """
        self._tools: list = tools
        self._llm: Any = llm_client
        self._resilience_chain: Any | None = resilience_chain

    # -------------------------------------------------------------------------
    # Abstract interface — subclasses MUST implement
    # -------------------------------------------------------------------------

    @property
    @abstractmethod
    def mode_name(self) -> str:
        """
        Unique name for this mode (matches ConversationMode literal).

        Must be one of: "GREETING", "BOOKING", "GENERAL", "ESCALATION".
        Used for logging, mode_history tracking, and draft_contexts keys.
        """
        ...

    @abstractmethod
    async def handle(
        self,
        state: ConversationState,
        intent: Any,  # IntentResult from agent.routing.intent_router
    ) -> dict:
        """
        Process the current turn and return a partial state update dict.

        Subclasses implement the core logic here:
        1. Build LLM messages using _build_messages()
        2. Call _call_llm() with messages (and tools if needed)
        3. Extract response from LLM output
        4. Return a partial state update dict using add_message() + mode updates

        The returned dict is merged by LangGraph reducers — return only the
        fields that changed. Do NOT return the full state.

        Args:
            state: Current ConversationState (read-only; use helpers to build updates)
            intent: IntentResult with classified intent and confidence

        Returns:
            Partial state update dict compatible with LangGraph reducers.
            Typically includes at minimum: {"messages": [...]}

        Example:
            async def handle(self, state, intent) -> dict:
                messages = self._build_messages(state, SYSTEM_PROMPT)
                llm_result = await self._call_llm(messages)
                return add_message(state, "assistant", llm_result.content)
        """
        ...

    # -------------------------------------------------------------------------
    # Shared utilities — available to all subclasses
    # -------------------------------------------------------------------------

    async def _call_llm(
        self,
        messages: list,
        tools: list | None = None,
    ) -> Any:
        """
        Resilience-aware LLM invocation.

        If ``self._resilience_chain`` is set, uses FallbackChain.call_with_fallback()
        for automatic provider rotation. Otherwise, calls ``self._llm.ainvoke()``
        directly (with optional tool binding).

        On any exception:
        - Logs the error
        - Returns None (caller should handle None gracefully)

        Args:
            messages: List of LangChain message objects (SystemMessage, HumanMessage, etc.)
            tools: Optional list of LangChain tools to bind. If None, no tools are bound.

        Returns:
            LLM response object (typically AIMessage with .content), or None on failure.
        """
        try:
            if self._resilience_chain is not None:
                # Resilience path: FallbackChain manages provider rotation
                # The chain injects ``llm`` as a kwarg per-provider attempt
                async def _invoke_with_provider(
                    *, llm: Any, **_kwargs: Any
                ) -> Any:
                    if tools:
                        bound = llm.bind_tools(tools)
                        return await bound.ainvoke(messages)
                    return await llm.ainvoke(messages)

                conversation_id = "mode-node"  # Default; subclasses can override
                return await self._resilience_chain.call_with_fallback(
                    _invoke_with_provider,
                    conversation_id=conversation_id,
                )
            else:
                # Direct path: use primary LLM client
                if tools:
                    bound = self._llm.bind_tools(tools)
                    return await bound.ainvoke(messages)
                return await self._llm.ainvoke(messages)

        except Exception as exc:
            logger.error(
                "BaseModeNode._call_llm: LLM call failed | mode=%s | error=%s",
                self.mode_name,
                exc,
                exc_info=True,
            )
            return None

    def _build_messages(
        self,
        state: ConversationState,
        system_prompt: str,
    ) -> list:
        """
        Build a LangChain message list from conversation state + system prompt.

        The resulting list has this structure:
        1. SystemMessage (system_prompt) — role instructions for this mode
        2. Optional HumanMessage with conversation_summary (if present)
        3. Recent conversation messages converted to LangChain types

        Message role mapping:
        - state message role "user"      → HumanMessage
        - state message role "assistant" → AIMessage
        - state message role "tool"      → ToolMessage (with tool_call_id)

        Args:
            state: Current ConversationState (read-only).
            system_prompt: System instructions for this mode's LLM call.

        Returns:
            List of LangChain message objects ready for LLM invocation.
        """
        lc_messages: list = [SystemMessage(content=system_prompt)]

        # Include conversation summary if present (for long conversations)
        summary = state.get("conversation_summary")
        if summary:
            lc_messages.append(
                HumanMessage(
                    content=f"[Resumen de la conversación previa]\n{summary}"
                )
            )

        # Convert state messages to LangChain message objects
        state_messages = state.get("messages", [])
        for msg in state_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))
            elif role == "tool":
                # ToolMessage requires tool_call_id
                tool_call_id = msg.get("tool_call_id", "tool_call_0")
                lc_messages.append(
                    ToolMessage(content=content, tool_call_id=tool_call_id)
                )
            else:
                # Fallback for unknown roles — treat as HumanMessage
                logger.debug(
                    "BaseModeNode._build_messages: unknown role '%s' — treating as HumanMessage",
                    role,
                )
                lc_messages.append(HumanMessage(content=content))

        return lc_messages

    def _format_tool_response(self, tool_result: Any) -> str:
        """
        Format tool output for injection into LLM context.

        Converts various tool result types to a clean string representation
        suitable for inclusion in a ToolMessage or as additional context.

        Handles:
        - str: returned as-is
        - dict: formatted as key=value pairs (newline-separated)
        - list: each item on its own line (dicts formatted as key=value)
        - None: returns "(sin resultado)"
        - Other: str() conversion

        Args:
            tool_result: Raw output from a tool call.

        Returns:
            Formatted string representation of the tool result.
        """
        if tool_result is None:
            return "(sin resultado)"

        if isinstance(tool_result, str):
            return tool_result

        if isinstance(tool_result, dict):
            lines = []
            for key, value in tool_result.items():
                lines.append(f"{key}: {value}")
            return "\n".join(lines)

        if isinstance(tool_result, list):
            lines = []
            for item in tool_result:
                if isinstance(item, dict):
                    item_parts = [f"{k}: {v}" for k, v in item.items()]
                    lines.append(" | ".join(item_parts))
                else:
                    lines.append(str(item))
            return "\n".join(lines)

        return str(tool_result)
