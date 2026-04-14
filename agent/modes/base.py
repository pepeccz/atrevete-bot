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

from agent.prompts.loader import build_layered_messages, get_system_prompt
from agent.state.schemas import ConversationState
from shared.config import get_settings

# ============================================================================
# ToolCallRejection — Returned by _pre_tool_call to reject a tool invocation
# ============================================================================


@dataclass
class ToolCallRejection:
    """Structured rejection from _pre_tool_call — skips tool execution cleanly.

    When _pre_tool_call returns this instead of a dict, the agentic loop:
    1. Skips tool.ainvoke()
    2. Builds a rejection dict with {"rejected": True, ...}
    3. Appends it as a ToolMessage so the LLM sees the rejection reason
    4. If the same error_code is hit 2+ times AND recovery_response is set,
       breaks the loop and returns recovery_response as the final text.
    """

    name: str  # Tool name that was rejected (e.g. "book")
    error_code: str  # Machine code: NO_OFFERED_SLOTS, NO_CUSTOMER_NAME, etc.
    error_message: str  # Prescriptive instruction for LLM ("RECHAZADO. SIGUIENTE ACCIÓN: ...")
    recovery_response: str | None = None  # Human-facing forced text on 2nd failure


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


MAX_TOOL_ROUNDS = 6

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

        Note: glossary.md is intentionally excluded (see loader.py line 241).

        Cached for 10 minutes with thread safety via asyncio.Lock.

        Returns:
            str: Concatenated system prompt (~1,500 tokens)
        """
        return await get_system_prompt()

    async def _build_layered_messages(
        self,
        state: ConversationState,
        mode_context: dict,
        step_name: str | None = None,  # kept for call-site compat; no longer used
        include_history: bool = True,
        history_limit: int = 6,
        include_catalog: bool = True,
    ) -> list:
        """
        Build messages using the optimized layered prompt approach.

        Assembly:
        1. SystemMessage: identity + critical_rules (cached)
        2. SystemMessage: catalog (DB-driven, 5-min cache) — skipped when include_catalog=False
        3. SystemMessage: mode overlay (cached)
        4. Conversation history (optional)
        5. SystemMessage: dynamic context (last, for recency attention)

        Args:
            state: Current conversation state
            mode_context: Mode-specific context data
            step_name: Deprecated — accepted for call-site compat, not used
            include_history: Whether to include conversation history
            history_limit: Max number of history messages to include
            include_catalog: Whether to include the service catalog

        Returns:
            list: List of LangChain message objects
        """
        messages, _ = await build_layered_messages(
            state,
            mode_context,
            include_history,
            history_limit,
            mode_name=self.mode_name,
            include_catalog=include_catalog,
        )
        return messages

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
            response = await self.llm.ainvoke(messages)
            await self._track_token_usage(response, message_count=len(messages))
            return response
        except Exception as exc:
            self.logger.error("LLM call failed: %s", exc)
            return None

    async def _track_token_usage(self, response: Any, message_count: int = 0) -> None:
        """
        Extract token usage from LLM response and record it.

        Fire-and-forget: errors are logged at DEBUG, never raised.
        Supports both usage_metadata (LangChain) and response_metadata.token_usage formats.

        Args:
            response: LLM response object
            message_count: Number of messages in the prompt (used as turn_count proxy)
        """
        try:
            # Primary: LangChain usage_metadata (dict with input_tokens, output_tokens)
            usage = getattr(response, "usage_metadata", None)
            if usage and isinstance(usage, dict):
                input_tokens = usage.get("input_tokens", 0) or 0
                output_tokens = usage.get("output_tokens", 0) or 0
            else:
                # Fallback: response_metadata.token_usage (OpenAI format)
                resp_meta = getattr(response, "response_metadata", None)
                if resp_meta and isinstance(resp_meta, dict):
                    token_usage = resp_meta.get("token_usage", {})
                    if token_usage:
                        input_tokens = token_usage.get("prompt_tokens", 0) or 0
                        output_tokens = token_usage.get("completion_tokens", 0) or 0
                    else:
                        return
                else:
                    return

            if input_tokens > 0 or output_tokens > 0:
                from agent.services.token_tracking import record_token_usage

                # Derive approximate turn count from message count (message pairs ≈ turns)
                turn_count = message_count // 2 if message_count > 0 else 0

                await record_token_usage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    mode_name=self.mode_name,
                    turn_count=turn_count,
                )
        except Exception as e:
            self.logger.debug("Token tracking failed: %s", e)

    @staticmethod
    def _dedup_response(text: str) -> str:
        """Collapse adjacent identical numbered-list blocks in LLM output.

        Splits the response at positions where a new numbered list starts
        (a line beginning with "1." after optional whitespace). If two
        consecutive blocks are identical after stripping whitespace, the
        second occurrence is removed.

        This defends against doubled LLM responses caused by duplicate
        webhook messages that slipped through earlier dedup layers.

        Args:
            text: Raw response text from the LLM.

        Returns:
            Text with consecutive duplicate numbered-list blocks removed.
            Single lists and non-list text are returned unchanged.
        """
        # Split at block boundaries: a newline followed by "1." at line start
        # We keep the delimiter with each block by using a lookahead split
        import re as _re

        parts = _re.split(r"(?=(?:^|\n)1\.)", text)
        # Filter empty parts that result from split
        blocks = [p for p in parts if p.strip()]

        if len(blocks) <= 1:
            return text

        # Collapse consecutive identical blocks
        deduped: list[str] = [blocks[0]]
        for block in blocks[1:]:
            if block.strip() != deduped[-1].strip():
                deduped.append(block)

        if len(deduped) == len(blocks):
            # Nothing removed — return original to avoid whitespace mutations
            return text

        return "".join(deduped).strip()

    @staticmethod
    def _dedup_paragraphs(text: str) -> str:
        """Remove consecutive duplicate paragraphs (split on \\n\\n, exact strip-match).

        Algorithm:
        1. Split on ``\\n\\n`` boundaries.
        2. Strip each paragraph before comparison.
        3. Skip a paragraph if its stripped form equals the previous kept paragraph.
        4. Rejoin with ``\\n\\n``.
        5. If nothing was removed, return the original text to avoid whitespace mutations.

        Non-consecutive identical paragraphs (A → B → A) are preserved.
        Comparison is case-sensitive.

        Args:
            text: Raw response text (possibly with repeated paragraphs).

        Returns:
            Text with consecutive duplicate paragraphs collapsed to one occurrence.
        """
        paragraphs = text.split("\n\n")

        if len(paragraphs) <= 1:
            return text

        deduped: list[str] = []
        prev_stripped: str | None = None

        for para in paragraphs:
            stripped = para.strip()
            if stripped == prev_stripped:
                continue  # consecutive duplicate — skip
            deduped.append(para)
            prev_stripped = stripped

        if len(deduped) == len(paragraphs):
            # Nothing was removed — return original to avoid whitespace mutations
            return text

        return "\n\n".join(deduped)

    @staticmethod
    def _sanitize_response(text: str) -> str:
        """
        Strip action narration from LLM output before user delivery.

        Removes patterns like:
        - "Voy a..." (upcoming actions)
        - "Déjame..." (let me/me deixa)
        - "Ahora voy a..." (now I'm going to)
        - "Un momento..." (one moment)
        - "Permíteme..." (allow me)
        """
        cleaned = text

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
                return response_text, True  # Repair: mark as sent so state flag persists

        # No prior disclosure found — strip any LLM-generated greeting/self-intro
        # before prepending our canonical disclosure (prevents double greetings).
        # BUG-006 FIX (v2): use an iterative loop (max 5 passes) so patterns are
        # stripped in ANY order — handles "Soy Maite... ¡Hola!..." as well as the
        # more common "¡Hola! Soy Maite...". All patterns are ^-anchored so only
        # the LEADING portion of the response is ever removed.
        _GREETING_OPENER_PATTERN = re.compile(
            r"^[\s\U0001F300-\U0001FAFF]*"  # optional leading emoji/whitespace
            r"[¡!]?"
            r"(?:hola|buenas?(?:\s+(?:d[ií]as?|tardes?|noches?))?)"
            r"[^.!?]*"  # anything up to the first sentence boundary
            r"[.!?]?\s*"  # optional punctuation + whitespace
            r"[\U0001F300-\U0001FAFF\s]*",  # optional trailing emoji/whitespace
            re.IGNORECASE,
        )
        _SELF_INTRO_PATTERN = re.compile(
            r"^(?:soy\s+maite|maite[,.]?\s+(?:tu|la|su)\s+asistent)[^.!?]*[.!?]?\s*",
            re.IGNORECASE,
        )
        _MAX_STRIP_ITERATIONS = 5
        any_stripped = False
        for _ in range(_MAX_STRIP_ITERATIONS):
            prev = response_text
            response_text = _GREETING_OPENER_PATTERN.sub("", response_text).lstrip()
            response_text = _SELF_INTRO_PATTERN.sub("", response_text).lstrip()
            if response_text == prev:
                break  # stable — nothing more to strip
            any_stripped = True
        if any_stripped:
            self.logger.debug(
                "_maybe_prepend_intro: stripped LLM self-intro from first-turn response"
            )

        # Also check if LLM still introduced itself using the canonical intro text
        if response_text.startswith(FIRST_TURN_INTRO[:20]):
            return response_text, True
        if FIRST_TURN_INTRO in response_text:
            return response_text, True

        # Prepend the mandatory EU AI Act disclosure
        return f"{FIRST_TURN_INTRO} {response_text}", True

    async def _pre_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> dict[str, Any] | ToolCallRejection:
        """Hook called before each tool invocation in the agentic loop.

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
        """Hook called after each tool execution, before appending ToolMessage.

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

    def _refresh_dynamic_context(
        self,
        working_messages: list,
    ) -> None:
        """Hook called after each tool round to refresh stale SystemMessages.

        Subclasses (e.g. BookingMode) can override to rebuild the dynamic
        context SystemMessage so the LLM sees up-to-date "Datos recogidos"
        after tools like manage_customer update the context mid-loop.

        The base implementation is a no-op.
        """
        pass

    async def _run_agentic_loop(
        self,
        messages: list,
        tools: list | None = None,
        tool_choice: str | None = None,
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
            # Gate recovery: track rejection counts per error_code.
            # On 2nd hit with recovery_response set, break and return forced text.
            rejection_counts: dict[str, int] = {}
            # R3: Tool-call dedup guard — cache keyed by (tool_name, sorted_args)
            # On cache hit, return cached result without re-invoking the tool.
            seen_tool_calls: dict[str, Any] = {}

            while iterations < MAX_TOOL_ROUNDS:
                if active_tools:
                    bind_kwargs: dict[str, Any] = {}
                    # Only force tool_choice on first iteration; after tool results
                    # the LLM needs freedom to respond with text
                    if tool_choice is not None and iterations == 0:
                        bind_kwargs["tool_choice"] = tool_choice
                    llm_with_tools = self.llm.bind_tools(active_tools, **bind_kwargs)
                else:
                    llm_with_tools = self.llm
                response = await llm_with_tools.ainvoke(working_messages)
                await self._track_token_usage(response, message_count=len(working_messages))

                if not (hasattr(response, "tool_calls") and response.tool_calls):
                    break

                working_messages.append(response)

                for tool_call in response.tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool_args = tool_call.get("args", {})
                    # Preserve original args before the hook can overwrite them.
                    # _post_tool_result always receives the original dict so it can
                    # safely call .get() regardless of what _pre_tool_call returned.
                    original_tool_args = dict(tool_args)

                    # Pre-tool-call hook: allows subclasses to transform args
                    # or reject the call entirely via ToolCallRejection
                    effective_args = original_tool_args
                    try:
                        effective_args = await self._pre_tool_call(tool_name, tool_args)
                    except Exception as exc:
                        self.logger.warning(
                            "_pre_tool_call failed for %s: %s — using original args",
                            tool_name,
                            exc,
                        )
                        effective_args = original_tool_args

                    # Check if _pre_tool_call rejected the call.
                    # post_args: the args dict to pass to _post_tool_result.
                    #   - Rejection path: original_tool_args (ToolCallRejection is not a dict)
                    #   - Success path: effective_args (enriched/transformed by hook)
                    #   - Exception path: original_tool_args (set above in except block)
                    if isinstance(effective_args, ToolCallRejection):
                        rejection = effective_args
                        code = rejection.error_code
                        rejection_counts[code] = rejection_counts.get(code, 0) + 1

                        # Gate recovery: if same gate hit 2+ times with a forced response,
                        # break the loop and return the recovery text directly.
                        if rejection_counts[code] >= 2 and rejection.recovery_response:
                            self.logger.warning(
                                "gate_recovery: %s hit %d times — forcing response",
                                code,
                                rejection_counts[code],
                            )
                            return AgenticLoopResult(
                                response_text=rejection.recovery_response,
                                tool_results=tool_results,
                            )

                        post_args = original_tool_args
                        result = {
                            "rejected": True,
                            "error_code": rejection.error_code,
                            "error_message": rejection.error_message,
                            "tool_name": rejection.name,
                        }
                        self.logger.info(
                            "Tool %s rejected by _pre_tool_call: %s — %s",
                            rejection.name,
                            rejection.error_code,
                            rejection.error_message,
                        )
                    else:
                        post_args = effective_args
                        tool_args = effective_args
                        # R3: Dedup guard — skip execution if identical call was
                        # already made in this agentic loop invocation.
                        dedup_args = (
                            sorted(tool_args.items()) if isinstance(tool_args, dict) else tool_args
                        )
                        dedup_key = f"{tool_name}:{dedup_args}"

                        if dedup_key in seen_tool_calls:
                            result = seen_tool_calls[dedup_key]
                            self.logger.warning(
                                "dedup: skipping duplicate %s call — returning cached result",
                                tool_name,
                            )
                        elif tool_name in tool_map:
                            try:
                                result = await tool_map[tool_name].ainvoke(tool_args)
                            except Exception as exc:
                                self.logger.error("Tool %s failed: %s", tool_name, exc)
                                result = {"error": str(exc)}
                            # Cache successful result for dedup
                            seen_tool_calls[dedup_key] = result
                        else:
                            result = {"error": f"Unknown tool: {tool_name}"}

                    # Post-tool-call hook: receives post_args (see above for logic).
                    # In the rejection path, post_args = original_tool_args to prevent
                    # AttributeError when _post_tool_result calls .get() on the object.
                    try:
                        result = await self._post_tool_result(tool_name, post_args, result)
                    except Exception as exc:
                        self.logger.warning(
                            "_post_tool_result failed for %s: %s — using original result",
                            tool_name,
                            exc,
                        )

                    # Accumulate results in a list per tool name (BUG-1 fix:
                    # multiple calls to the same tool no longer overwrite)
                    tool_results.setdefault(tool_name, []).append(result)

                    working_messages.append(
                        ToolMessage(
                            content=str(result),
                            tool_call_id=tool_call.get("id", tool_name),
                        )
                    )

                # Refresh dynamic context SystemMessage so the LLM sees
                # up-to-date state on its next invocation (e.g. after
                # manage_customer sets customer_name, the prompt should
                # show "✅ Nombre: María" instead of stale "❌ pendiente").
                try:
                    self._refresh_dynamic_context(working_messages)
                except Exception as exc:
                    self.logger.warning(
                        "_refresh_dynamic_context failed: %s — continuing with stale context",
                        exc,
                    )

                iterations += 1

            if response is None:
                return AgenticLoopResult(
                    response_text="Lo siento, no pude procesar tu mensaje.",
                    error="No response from LLM",
                )

            content = response.content if hasattr(response, "content") else response
            if isinstance(content, str):
                response_text: str = content
            elif isinstance(content, list):
                # LangChain Responses API: content is a list of typed blocks
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        text_parts.append(block)
                response_text = "\n".join(text_parts)
            else:
                response_text = str(content)
            response_text = self._sanitize_response(response_text)
            response_text = self._dedup_response(response_text)
            response_text = self._dedup_paragraphs(response_text)

            # R3: Tool-skip telemetry — warn if loop exited without any tool calls
            # but tools were available (indicates LLM skipped available tools)
            if not tool_results and active_tools:
                self.logger.warning(
                    "tool_skip",
                    extra={
                        "event": "tool_skip",
                        "mode": self.__class__.__name__,
                        "tools_available": len(active_tools),
                        "iterations": iterations,
                    },
                )

            if (
                iterations >= MAX_TOOL_ROUNDS
                and hasattr(response, "tool_calls")
                and response.tool_calls
            ):
                self.logger.warning(
                    "Agentic loop hit MAX_TOOL_ROUNDS (%d)",
                    MAX_TOOL_ROUNDS,
                )

            # Final text recovery: if loop ended with tool_calls and empty text,
            # do one more LLM call WITHOUT tools to generate a user-facing response.
            if not response_text.strip() and tool_results:
                self.logger.info("Final text recovery: calling LLM without tools")
                recovery_response = await self.llm.ainvoke(working_messages)
                await self._track_token_usage(
                    recovery_response, message_count=len(working_messages)
                )
                recovery_content = (
                    recovery_response.content
                    if hasattr(recovery_response, "content")
                    else recovery_response
                )
                if isinstance(recovery_content, str):
                    recovery_text = recovery_content
                elif isinstance(recovery_content, list):
                    recovery_parts = []
                    for block in recovery_content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            recovery_parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            recovery_parts.append(block)
                    recovery_text = "\n".join(recovery_parts)
                else:
                    recovery_text = str(recovery_content)
                response_text = self._sanitize_response(recovery_text)
                response_text = self._dedup_response(response_text)
                response_text = self._dedup_paragraphs(response_text)

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
