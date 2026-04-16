"""
Escalation Mode — v6.0 Mode-Based Architecture (M4 create_agent migration).

Handles human handoff when:
- Customer explicitly requests a human agent
- Error count exceeds threshold (auto-escalation)
- AI cannot handle the request

v6.1: Replaced one-shot handoff with a deterministic 3-step intake FSM that
collects issue summary and contact preference before calling the escalation tool.

v6.2: Added explicit-human-request fast-path (WS-4).
When the user explicitly asks for a human ("pasame con una persona", "quiero un humano",
etc.) on fresh ESCALATION entry, the FSM is skipped entirely and escalation is
performed immediately without running ACKNOWLEDGE or DESCRIBE steps.

FSM steps (stored in mode_context["escalation_step"]):
  ACKNOWLEDGE → DESCRIBE → CONTACT → DONE

Sets escalation_triggered=True in state once the tool is called.
Once triggered, stays in ESCALATION for remaining messages.

M4 changes: no longer inherits from BaseModeNode. Public surface is
``build_escalation_node()`` which returns an async LangGraph node function.
This mode is a pure FSM — no LLM involvement, no tools, no middleware.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

from agent.modes._intro import maybe_prepend_intro
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)

# ── FSM step constants ──────────────────────────────────────────────────────────
_STEP_ACKNOWLEDGE = "ACKNOWLEDGE"
_STEP_DESCRIBE = "DESCRIBE"
_STEP_CONTACT = "CONTACT"
_STEP_DONE = "DONE"

# ── WS-4: Explicit human-request patterns ───────────────────────────────────────
_EXPLICIT_HUMAN_PATTERN = re.compile(
    r"(?:"
    r"pas[aá]me?\s+con\s+(?:una?\s+)?(?:persona|humano|alguien|operador|agente)"
    r"|quiero\s+(?:hablar\s+con\s+)?(?:una?\s+)?(?:persona|humano|alguien|operador|agente\s+real)"
    r"|hablar\s+con\s+(?:una?\s+)?(?:persona|humano|alguien|operador|agente\s+real)"
    r"|(?:una?\s+)?persona\s+real"
    r"|(?:una?\s+)?humano\s+(?:real|de\s+verdad|por\s+favor)?"
    r"|atenci[oó]n\s+humana"
    r"|pon[eé]me?\s+con\s+(?:una?\s+)?(?:persona|humano|alguien)"
    r"|comun[ií]c[aá]me?\s+con\s+(?:una?\s+)?(?:persona|humano|alguien)"
    r")",
    re.IGNORECASE | re.UNICODE,
)


def _is_explicit_human_request(text: str) -> bool:
    """Return True if the user is explicitly requesting to speak with a human."""
    return bool(_EXPLICIT_HUMAN_PATTERN.search(text.strip()))


# ── Urgency signals — UP-1 ──────────────────────────────────────────────────────
_URGENCY_SIGNALS: frozenset[str] = frozenset(
    {
        "urgente",
        "emergencia",
        "ahora mismo",
        "lo antes posible",
        "inmediato",
        "inmediatamente",
        "necesito hablar ya",
        "urgente necesito",
    }
)

# ── Response templates ──────────────────────────────────────────────────────────
_ALREADY_ESCALATED = (
    "Ya he contactado con nuestro equipo. Te atenderán en breve. 🙏 "
    "¿Hay algo más en lo que pueda ayudarte mientras esperas?"
)
_ESCALATION_SUCCESS = (
    "Entendido. He avisado a nuestro equipo y te atenderán personalmente en breve. 🙏"
)
_ESCALATION_FALLBACK = "He notificado a nuestro equipo. Te contactarán en breve. 🙏"
_ACKNOWLEDGE_REPLY = (
    "Lamento lo que estás pasando. Quiero que esto se resuelva bien. "
    "Cuéntame brevemente qué pasó para derivarlo al equipo con toda la información."
)
_CONTACT_PROMPT = "¿Prefieres que te contacten por WhatsApp o por llamada?"
_DONE_WAITING = (
    "Ya avisé al equipo. Te van a contactar en breve. 🙏 "
    "¿Hay algo más que pueda hacer por ti mientras esperas?"
)


def _normalize_contact_preference(text: str) -> str:
    """Normalise the user's contact preference text into a canonical value."""
    lower = text.lower()
    if any(k in lower for k in ("whatsapp", "wsp", "whats")):
        return "WhatsApp"
    if any(k in lower for k in ("llamada", "telefono", "teléfono", "llamen", "llamar", "llama")):
        return "llamada"
    return text.strip()


def _is_urgent(text: str) -> bool:
    """Detect high-confidence urgency signals in user text."""
    lower = text.lower().strip()
    return any(signal in lower for signal in _URGENCY_SIGNALS)


def _with_intro(response_text: str, state: ConversationState, updates: dict) -> dict:
    """Prepend the EU-AI-Act intro if needed and record the disclosure flag."""
    final_response, disclosure_sent = maybe_prepend_intro(response_text, state)
    updates = {**add_message(state, "assistant", final_response), **updates}
    if disclosure_sent:
        updates["ai_disclosure_sent"] = True
    return updates


async def _handle_escalation(state: ConversationState) -> dict:
    """Compute the state update for one escalation turn.

    Implements the full 3-step intake FSM with fast-paths for technical
    auto-escalation, explicit human requests, and urgency signals. Mirrors
    the behaviour of the original ``EscalationMode.handle`` contract.
    """
    from agent.services.escalation_service import perform_escalation

    conversation_id = state.get("conversation_id", "unknown")
    ctx = dict(state.get("mode_context") or {})

    # T9 — Fast path for technical auto-escalation (error_count >= 3)
    is_technical = (
        state.get("error_count", 0) >= 3 or state.get("escalation_reason") == "technical_error"
    )
    if is_technical and not ctx.get("escalation_step"):
        logger.info(
            "EscalationMode: fast-path technical escalation | conversation=%s | error_count=%s",
            conversation_id,
            state.get("error_count", 0),
        )
        result = await perform_escalation(
            conversation_id=str(state.get("conversation_id", "")),
            customer_phone=state.get("customer_phone") or "",
            reason="technical_error",
            source="auto_error",
            is_technical_error=True,
        )
        ctx["escalation_step"] = _STEP_DONE
        return _with_intro(
            result.user_message or _ESCALATION_FALLBACK,
            state,
            {
                "escalation_triggered": True,
                "mode_context": ctx,
                "last_node": "escalation",
                "user_message": None,
            },
        )

    # ── Recover last user message ──────────────────────────────────────────
    messages = state.get("messages", [])
    user_text = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_text = msg.get("content", "").strip()
            break

    # WS-4 — Fast path for explicit human-contact requests on fresh ESCALATION entry.
    if (
        not ctx.get("escalation_step")
        and not state.get("escalation_triggered")
        and _is_explicit_human_request(user_text)
    ):
        logger.info(
            "EscalationMode: explicit-human fast-path | conversation=%s | text=%r",
            conversation_id,
            user_text[:60],
        )
        response_text = _ESCALATION_FALLBACK
        try:
            esc_result = await perform_escalation(
                conversation_id=str(state.get("conversation_id", "")),
                customer_phone=state.get("customer_phone") or "",
                reason="manual_request",
                source="manual",
                is_technical_error=False,
                issue_summary=user_text,
                contact_preference=None,
                conversation_context=state.get("messages", [])[-5:],
                customer_id=str(state.get("customer_id", ""))
                if state.get("customer_id")
                else None,
            )
            response_text = _ESCALATION_SUCCESS
            logger.info(
                "EscalationMode: explicit-human escalation completed | conversation=%s | "
                "steps_completed=%s",
                conversation_id,
                esc_result.steps_completed,
            )
        except Exception as exc:
            logger.error(
                "EscalationMode: explicit-human perform_escalation failed | "
                "conversation=%s | error=%s",
                conversation_id,
                exc,
            )
        ctx["escalation_step"] = _STEP_DONE
        ctx["issue_summary"] = user_text
        return _with_intro(
            response_text,
            state,
            {
                "escalation_triggered": True,
                "mode_context": ctx,
                "last_node": "escalation",
                "user_message": None,
            },
        )

    # UP-1 — Fast path for urgency signals on fresh ESCALATION entry.
    if (
        not ctx.get("escalation_step")
        and not state.get("escalation_triggered")
        and _is_urgent(user_text)
    ):
        logger.info(
            "EscalationMode: urgency fast-path | conversation=%s | text=%r",
            conversation_id,
            user_text[:60],
        )
        ctx["escalation_step"] = _STEP_CONTACT
        ctx["issue_summary"] = user_text
        return _with_intro(
            _CONTACT_PROMPT,
            state,
            {
                "mode_context": ctx,
                "last_node": "escalation",
                "user_message": None,
            },
        )

    # ── Guard: fresh ESCALATION entry — reset FSM step to ACKNOWLEDGE ──────
    escalation_already_done = state.get("escalation_triggered", False)
    previous_mode = state.get("current_mode", "")

    if not escalation_already_done and previous_mode != "ESCALATION":
        step = _STEP_ACKNOWLEDGE
    else:
        step = ctx.get("escalation_step") or _STEP_ACKNOWLEDGE

    # ── Guard: already triggered → waiting message ─────────────────────────
    if state.get("escalation_triggered") or step == _STEP_DONE:
        logger.info(
            "EscalationMode: already escalated/DONE | conversation=%s | step=%s",
            conversation_id,
            step,
        )
        return _with_intro(
            _ALREADY_ESCALATED,
            state,
            {"last_node": "escalation", "user_message": None},
        )

    # ── T3.1: ACKNOWLEDGE step ─────────────────────────────────────────────
    if step == _STEP_ACKNOWLEDGE:
        logger.info("EscalationMode: ACKNOWLEDGE step | conversation=%s", conversation_id)
        ctx["escalation_step"] = _STEP_DESCRIBE
        return _with_intro(
            _ACKNOWLEDGE_REPLY,
            state,
            {
                "mode_context": ctx,
                "last_node": "escalation",
                "user_message": None,
            },
        )

    # ── T3.2: DESCRIBE step ────────────────────────────────────────────────
    if step == _STEP_DESCRIBE:
        logger.info(
            "EscalationMode: DESCRIBE step | conversation=%s | user_text=%r",
            conversation_id,
            user_text[:60],
        )
        if "solo quiero hablar" in user_text.lower() or len(user_text) < 10:
            issue_summary = ""
        else:
            issue_summary = user_text

        ctx["issue_summary"] = issue_summary
        ctx["escalation_step"] = _STEP_CONTACT

        return _with_intro(
            _CONTACT_PROMPT,
            state,
            {
                "mode_context": ctx,
                "last_node": "escalation",
                "user_message": None,
            },
        )

    # ── T3.3: CONTACT step ─────────────────────────────────────────────────
    if step == _STEP_CONTACT:
        logger.info(
            "EscalationMode: CONTACT step | conversation=%s | user_text=%r",
            conversation_id,
            user_text[:60],
        )
        contact_preference = _normalize_contact_preference(user_text)
        issue_summary = ctx.get("issue_summary", "")
        customer_phone = state.get("customer_phone", "")

        response_text = _ESCALATION_FALLBACK

        try:
            esc_result = await perform_escalation(
                conversation_id=str(state.get("conversation_id", "")),
                customer_phone=customer_phone,
                reason="manual_request",
                source="manual",
                is_technical_error=False,
                issue_summary=issue_summary,
                contact_preference=contact_preference,
                conversation_context=state.get("messages", [])[-5:],
                customer_id=str(state.get("customer_id", "")) if state.get("customer_id") else None,
            )
            response_text = _ESCALATION_SUCCESS
            logger.info(
                "EscalationMode: escalation completed | conversation=%s | "
                "issue=%r | contact=%s | steps_completed=%s",
                conversation_id,
                issue_summary[:60],
                contact_preference,
                esc_result.steps_completed,
            )

        except Exception as exc:
            logger.error(
                "EscalationMode: perform_escalation failed | conversation=%s | error=%s",
                conversation_id,
                exc,
            )

        ctx["contact_preference"] = contact_preference
        ctx["escalation_step"] = _STEP_DONE

        return _with_intro(
            response_text,
            state,
            {
                "escalation_triggered": True,
                "mode_context": ctx,
                "last_node": "escalation",
                "user_message": None,
            },
        )

    # ── Fallback: unknown step → treat as DONE ─────────────────────────────
    logger.warning(
        "EscalationMode: unknown step=%r | conversation=%s — returning waiting message",
        step,
        conversation_id,
    )
    return _with_intro(
        _DONE_WAITING,
        state,
        {"last_node": "escalation", "user_message": None},
    )


def build_escalation_node() -> Callable[[ConversationState], dict]:
    """Return an async LangGraph node function for the ESCALATION mode.

    The node is a pure FSM: no LLM calls, no tools, no middleware. It reads
    ``mode_context["escalation_step"]`` to advance through the intake FSM.
    """

    async def escalation_node(state: ConversationState) -> dict:
        return await _handle_escalation(state)

    return escalation_node


__all__ = [
    "_is_explicit_human_request",
    "_is_urgent",
    "_normalize_contact_preference",
    "build_escalation_node",
]
