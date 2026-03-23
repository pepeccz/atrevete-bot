"""
Base module for v6.0 mode nodes.

Provides shared types and the BaseModeNode abstract class used by all 4 modes.
"""

import logging
import re
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


MAX_TOOL_ROUNDS = 3
_TOOL_CALL_PATTERN = re.compile(r"\[[\w_]+(?:\([^\)]*\))?\](?!\()")

# EU AI Act first-turn disclosure enforced in code.
FIRST_TURN_INTRO = "¡Hola! 🌸 Soy Maite, la asistenta virtual con IA de Atrévete Peluquería."


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

    @staticmethod
    def _sanitize_response(text: str) -> str:
        """
        Strip pseudo-tool-call text and action narration from LLM output before user delivery.

        Removes patterns like:
        - "Voy a..." (upcoming actions)
        - "Déjame..." (let me/me deixa)
        - "Ahora voy a..." (now I'm going to)
        - "Un momento..." (one moment)
        - "Permíteme..." (allow me)
        """
        cleaned = _TOOL_CALL_PATTERN.sub("", text)

        # Strip action narration sentences (only if at sentence start)
        # These indicate the LLM is narrating upcoming tool calls instead of executing silently
        narration_patterns = [
            r"^Voy a\s+.*?\.\s*",  # Voy a buscar... / Voy a confirmar...
            r"^Déjame\s+.*?\.\s*",  # Déjame buscar... / Déjame ayudarte...
            r"^Ahora voy a\s+.*?\.\s*",  # Ahora voy a...
            r"^Un momento.*?\.\s*",  # Un momento, déjame...
            r"^Permíteme\s+.*?\.\s*",  # Permíteme...
            r"^Claro,? voy a\s+.*?\.\s*",  # Claro, voy a...
        ]
        for pattern in narration_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)

        # Clean up excess whitespace
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = cleaned.strip()
        return cleaned

    def _maybe_prepend_intro(
        self,
        response_text: str,
        state: ConversationState,
    ) -> tuple[str, bool]:
        """Prepend the first-turn disclosure unless it was already handled.

        Uses TWO independent checks to avoid duplication:
        1. The `ai_disclosure_sent` state flag (set after first delivery)
        2. A scan of prior assistant messages for the intro text

        Check #2 is the fallback safety net — it catches cases where the
        state flag didn't persist correctly across checkpoint boundaries.
        """
        # Check 1: Explicit state flag
        if state.get("ai_disclosure_sent", False):
            return response_text, False

        # Check 2: Scan existing messages for prior disclosure
        for msg in state.get("messages", []):
            if msg.get("role") == "assistant" and "soy maite" in (msg.get("content") or "").lower():
                return response_text, False

        # No prior disclosure found — strip any LLM-generated greeting/self-intro
        # before prepending our canonical disclosure (prevents double greetings).
        # BUG-006 FIX: use a two-pass strip:
        # Pass 1 — remove leading "¡Hola!/Hola/Buenas..." opener (with or without emoji)
        # Pass 2 — remove full self-intro "Soy Maite, la asistenta..." sentence if present
        # Both passes are anchored to the start of the string so only leading text is removed.
        _GREETING_OPENER_PATTERN = re.compile(
            r"^[¡!]?"
            r"(?:hola|buenas?(?:\s+(?:d[ií]as?|tardes?|noches?))?)"
            r"[^.!?]*"  # anything up to the first sentence boundary
            r"[.!?]?\s*"  # optional punctuation + whitespace
            r"(?:\S+\s*)?",  # optional single emoji/word immediately after punctuation
            re.IGNORECASE,
        )
        _SELF_INTRO_PATTERN = re.compile(
            r"^(?:soy\s+maite|maite[,.]?\s+(?:tu|la|su)\s+asistent)[^.!?]*[.!?]?\s*",
            re.IGNORECASE,
        )
        stripped = _GREETING_OPENER_PATTERN.sub("", response_text).lstrip()
        stripped = _SELF_INTRO_PATTERN.sub("", stripped).lstrip()
        if stripped != response_text:
            self.logger.debug(
                "_maybe_prepend_intro: stripped LLM self-intro from first-turn response"
            )
            response_text = stripped

        # Also check if LLM still introduced itself (partial match not caught by regex)
        if response_text.startswith(FIRST_TURN_INTRO[:20]):
            return response_text, True
        if "soy maite" in response_text.lower():
            return response_text, True

        # Prepend the mandatory EU AI Act disclosure
        return f"{FIRST_TURN_INTRO} {response_text}", True

    async def _pre_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> dict[str, Any]:
        """Hook called before each tool invocation in the agentic loop.

        Subclasses can override to intercept and transform tool arguments
        before the tool executes. Default: pass-through (returns tool_args unchanged).

        The hook receives the raw LLM dict BEFORE Pydantic validation, so it can
        resolve placeholder values (e.g. slot_index → stylist_id).

        Args:
            tool_name: Name of the tool about to be called.
            tool_args: Arguments the LLM provided for the tool (raw dict).

        Returns:
            Modified tool_args dict (or original if no changes needed).
        """
        return tool_args

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
            tool_map = {t.name: t for t in active_tools}
            working_messages = list(messages)
            iterations = 0
            response: Any | None = None

            while iterations < MAX_TOOL_ROUNDS:
                llm_with_tools = self.llm.bind_tools(active_tools) if active_tools else self.llm
                response = await llm_with_tools.ainvoke(working_messages)

                if not (hasattr(response, "tool_calls") and response.tool_calls):
                    break

                working_messages.append(response)

                for tool_call in response.tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool_args = tool_call.get("args", {})

                    # Pre-tool-call hook: allows subclasses to transform args
                    try:
                        tool_args = await self._pre_tool_call(tool_name, tool_args)
                    except Exception as exc:
                        self.logger.warning(
                            "_pre_tool_call failed for %s: %s — using original args",
                            tool_name,
                            exc,
                        )

                    if tool_name in tool_map:
                        try:
                            result = await tool_map[tool_name].ainvoke(tool_args)
                        except Exception as exc:
                            self.logger.error("Tool %s failed: %s", tool_name, exc)
                            result = {"error": str(exc)}
                    else:
                        result = {"error": f"Unknown tool: {tool_name}"}

                    # Accumulate results in a list per tool name (BUG-1 fix:
                    # multiple calls to the same tool no longer overwrite)
                    tool_results.setdefault(tool_name, []).append(result)

                    working_messages.append(
                        ToolMessage(
                            content=str(result),
                            tool_call_id=tool_call.get("id", tool_name),
                        )
                    )

                iterations += 1

            if response is None:
                return AgenticLoopResult(
                    response_text="Lo siento, no pude procesar tu mensaje.",
                    error="No response from LLM",
                )

            content = response.content if hasattr(response, "content") else response
            response_text: str = content if isinstance(content, str) else str(content)
            response_text = self._sanitize_response(response_text)

            if (
                iterations >= MAX_TOOL_ROUNDS
                and hasattr(response, "tool_calls")
                and response.tool_calls
            ):
                self.logger.warning(
                    "Agentic loop hit MAX_TOOL_ROUNDS (%d)",
                    MAX_TOOL_ROUNDS,
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
