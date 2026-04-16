"""
General Mode — v6.0 Mode-Based Architecture (M4 create_agent migration).

Handles informational queries: FAQs, service information, salon hours, policies.
Routes to BOOKING for service requests. Has NO tools — the agent is a
single-shot LLM call with a layered system prompt.

This is the default mode after GREETING completes and whenever the user asks
an informational question during an active BOOKING flow.

M4 changes: no longer inherits from BaseModeNode. Public surface is
``build_general_node(llm_factory)`` returning an async LangGraph node that
invokes ``create_agent`` with zero tools plus TokenTrackingMiddleware.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.middleware.token_tracking import TokenTrackingMiddleware
from agent.modes._intro import maybe_prepend_intro, use_optimized_prompts
from agent.prompts.loader import build_layered_messages
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)


# Legacy fallback prompt used when USE_OPTIMIZED_PROMPTS is off.
_LEGACY_SYSTEM_PROMPT = (
    "Eres Maite, asistenta virtual de Atrévete Peluquería en Alcobendas. "
    "Respondé dudas sobre servicios, horarios, precios y políticas del salón "
    "de forma breve, cálida y útil."
)


def _extract_final_text(result: Any) -> str:
    """Return the last AIMessage content from a ``create_agent`` result dict."""
    if not isinstance(result, dict):
        return ""
    messages = result.get("messages") or []
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                return "\n".join(parts).strip()
    return ""


def _build_legacy_transcript(state: ConversationState) -> tuple[str, list]:
    """Build (system_prompt, transcript) for the legacy non-layered path."""
    conversation_summary = state.get("conversation_summary")
    system_content = _LEGACY_SYSTEM_PROMPT
    if conversation_summary:
        system_content += f"\n\nContexto previo de la conversación:\n{conversation_summary}"

    transcript: list = []
    for msg in state.get("messages", [])[-8:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            transcript.append(HumanMessage(content=content))
        elif role == "assistant":
            transcript.append(AIMessage(content=content))

    return system_content, transcript


async def _build_layered_transcript(
    state: ConversationState,
    mode_context: dict,
) -> tuple[str, list]:
    """Build (system_prompt, transcript) from the layered-prompt loader.

    Collapses every SystemMessage into a single string because ``create_agent``
    accepts ``system_prompt`` + user/tool messages separately.
    """
    messages, _ = await build_layered_messages(
        state,
        mode_context,
        include_history=True,
        history_limit=8,
        mode_name="GENERAL",
        include_catalog=True,
    )
    system_parts: list[str] = []
    transcript: list = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if content:
                system_parts.append(content)
        else:
            transcript.append(msg)
    return "\n\n".join(system_parts), transcript


async def _generate_general_response(
    llm: Any,
    state: ConversationState,
    mode_context: dict,
) -> str:
    """Invoke the GENERAL ``create_agent`` and return the final assistant text.

    Falls back to an empty string on any infrastructure failure — the caller
    is responsible for supplying a sensible fallback response.
    """
    if llm is None:
        return ""

    try:
        if use_optimized_prompts():
            system_prompt, transcript = await _build_layered_transcript(state, mode_context)
        else:
            system_prompt, transcript = _build_legacy_transcript(state)
    except Exception as exc:
        logger.warning("GeneralMode: prompt assembly failed: %s — returning empty text", exc)
        return ""

    try:
        agent = create_agent(
            model=llm,
            tools=[],
            system_prompt=system_prompt,
            middleware=[TokenTrackingMiddleware(mode_name="GENERAL")],
        )
        result = await agent.ainvoke({"messages": transcript})
    except Exception as exc:
        logger.warning("GeneralMode: create_agent invocation failed: %s", exc)
        return ""

    return _extract_final_text(result)


async def _handle_general(state: ConversationState, llm: Any) -> dict:
    """Compute the state update for one general-mode turn."""
    mode_context = state.get("mode_context") or {}

    response_text = await _generate_general_response(llm, state, mode_context)
    if not response_text:
        response_text = (
            "Perdona, tuve un problema procesando tu mensaje. "
            "¿Podés repetirlo o darme más detalles?"
        )

    final_response, disclosure_sent = maybe_prepend_intro(response_text, state)

    logger.info(
        "GeneralMode.handle | conversation=%s | response_len=%s",
        state.get("conversation_id", "unknown"),
        len(final_response),
    )

    updates: dict = {
        **add_message(state, "assistant", final_response),
        "mode_context": mode_context,
        "last_node": "general",
        "user_message": None,
    }
    if disclosure_sent:
        updates["ai_disclosure_sent"] = True
    return updates


def build_general_node(
    llm_factory: Callable[[], Any] | None = None,
) -> Callable[[ConversationState], Any]:
    """Return an async LangGraph node function for the GENERAL mode.

    Args:
        llm_factory: Zero-arg callable that returns a ``BaseChatModel``. Invoked
            lazily on every turn. When ``None``, the node returns a canned
            fallback response without invoking the LLM.
    """

    async def general_node(state: ConversationState) -> dict:
        llm = llm_factory() if llm_factory is not None else None
        return await _handle_general(state, llm)

    return general_node


__all__ = ["build_general_node"]
