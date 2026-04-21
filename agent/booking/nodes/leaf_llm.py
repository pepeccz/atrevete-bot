"""
LLM leaf nodes — Phase 5 implementation.

Each node:
  1. Loads its per-node prompt from agent/prompts/modes/booking/<node>.md
  2. Calls llm.ainvoke([SystemMessage(prompt)] + last_6_turns) — zero tools bound
  3. Returns {'messages': [AIMessage(...)]} — does NOT mutate booking_context

Design ref: design §D4 — no create_agent, no tools, single LLM call per turn.
Spec invariant #2: LLM MUST NOT write to booking_context.

await_confirmation is a silent no-op:
  - User already saw show_confirmation.
  - This node simply waits for next user input (no LLM call, no state change).
  - Decision rationale: resolved per orchestrator instruction, 2026-04-21.

error_recovery clears booking_context (state fence):
  - Resets to {} to ensure schema-incompatible stale state cannot crash subsequent nodes.
  - Spec: error_recovery §Mid-session state schema migration.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from shared.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level LLM instance — no tools bound (design D4).
# Tests patch this via: patch("agent.booking.nodes.leaf_llm.llm", mock_llm)
# ---------------------------------------------------------------------------

_settings = get_settings()
llm = ChatOpenAI(
    model=_settings.LLM_MODEL,
    base_url="https://openrouter.ai/api/v1",
    api_key=_settings.OPENROUTER_API_KEY,
)

# ---------------------------------------------------------------------------
# Prompt loader — reads .md files from agent/prompts/modes/booking/
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts" / "modes" / "booking"
_prompt_cache: dict[str, str] = {}


def _load_prompt(node_name: str) -> str:
    """Load and cache the per-node prompt from <node_name>.md."""
    if node_name not in _prompt_cache:
        prompt_path = _PROMPTS_DIR / f"{node_name}.md"
        _prompt_cache[node_name] = prompt_path.read_text(encoding="utf-8")
    return _prompt_cache[node_name]


def _last_turns(state: dict[str, Any], n: int = 6) -> list:
    """Return the last n messages from state, as LangChain message objects."""
    raw = state.get("messages", [])
    tail = raw[-n:] if len(raw) > n else raw
    result = []
    for msg in tail:
        if isinstance(msg, (HumanMessage, AIMessage, SystemMessage)):
            result.append(msg)
        elif isinstance(msg, dict):
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "human":
                result.append(HumanMessage(content=content))
            elif role == "assistant":
                result.append(AIMessage(content=content))
    return result


# ---------------------------------------------------------------------------
# Leaf purity guard (design D5, INV-2)
# ---------------------------------------------------------------------------

_ALLOWED_LEAF_KEYS = frozenset({"messages", "total_message_count", "booking_context"})


def _assert_leaf_pure(ret: dict) -> None:
    """Assert that a leaf return dict contains only allowed keys.

    booking_context is allowed ONLY for the _last_leaf sentinel write.
    Any other unexpected key is a spec violation (INV-2).

    Args:
        ret: The dict returned by a leaf node before _last_leaf injection.

    Raises:
        AssertionError if ret contains keys outside _ALLOWED_LEAF_KEYS.
    """
    extras = set(ret.keys()) - _ALLOWED_LEAF_KEYS
    assert not extras, f"leaf must not mutate state: {extras}"


async def _invoke(node_name: str, state: dict[str, Any]) -> dict[str, Any]:
    """Shared helper: load prompt, call llm.ainvoke, return messages patch.

    Returns messages as dicts ({'role': 'assistant', 'content': ..., 'timestamp': ...})
    to match ConversationState schema (messages: list[dict]) and satisfy the
    publish freshness guard in agent/main.py which checks last_message['role'] == 'assistant'.

    Each invocation writes _last_leaf sentinel to booking_context (design D8)
    so context-gated resolvers know which leaf ran last.
    """
    prompt = _load_prompt(node_name)
    messages = [SystemMessage(content=prompt)] + _last_turns(state)
    response: AIMessage = await llm.ainvoke(messages)
    content = response.content if isinstance(response.content, str) else str(response.content)
    msg = {
        "role": "assistant",
        "content": content,
        "timestamp": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(),
    }
    ret = {
        "messages": [msg],
        "total_message_count": state.get("total_message_count", 0) + 1,
    }
    # INV-2 guard: assert no unexpected state mutations in ret (before _last_leaf injection)
    _assert_leaf_pure(ret)
    # D8: write _last_leaf sentinel into booking_context
    bc = dict(state.get("booking_context") or {})
    bc["_last_leaf"] = node_name
    ret["booking_context"] = bc
    return ret


# ---------------------------------------------------------------------------
# ask_service
# ---------------------------------------------------------------------------


async def ask_service(state: dict[str, Any]) -> dict[str, Any]:
    """Ask the user what service they want. No tool calls, no booking_context mutation."""
    return await _invoke("ask_service", state)


# ---------------------------------------------------------------------------
# ask_audience
# ---------------------------------------------------------------------------


async def ask_audience(state: dict[str, Any]) -> dict[str, Any]:
    """Ask the user for audience qualifier (Señora/Caballero/Infantil). No tools."""
    return await _invoke("ask_audience", state)


# ---------------------------------------------------------------------------
# ask_more_services
# ---------------------------------------------------------------------------


async def ask_more_services(state: dict[str, Any]) -> dict[str, Any]:
    """Ask if the user wants to add more services. No tools."""
    return await _invoke("ask_more_services", state)


# ---------------------------------------------------------------------------
# ask_stylist
# ---------------------------------------------------------------------------


async def ask_stylist(state: dict[str, Any]) -> dict[str, Any]:
    """Ask the user which stylist they prefer. No tools."""
    return await _invoke("ask_stylist", state)


# ---------------------------------------------------------------------------
# ask_slot
# ---------------------------------------------------------------------------


async def ask_slot(state: dict[str, Any]) -> dict[str, Any]:
    """Present available slots from booking_context.offered_slots. No tools."""
    return await _invoke("ask_slot", state)


# ---------------------------------------------------------------------------
# ask_name
# ---------------------------------------------------------------------------


async def ask_name(state: dict[str, Any]) -> dict[str, Any]:
    """Ask for the customer name to register the appointment. No tools."""
    return await _invoke("ask_name", state)


# ---------------------------------------------------------------------------
# ask_notes
# ---------------------------------------------------------------------------


async def ask_notes(state: dict[str, Any]) -> dict[str, Any]:
    """Ask for optional notes or special requests. No tools."""
    return await _invoke("ask_notes", state)


# ---------------------------------------------------------------------------
# show_confirmation
# ---------------------------------------------------------------------------


async def show_confirmation(state: dict[str, Any]) -> dict[str, Any]:
    """
    Render a human-readable booking summary for confirmation.
    Uses booking_context data for context but MUST NOT modify it (spec invariant #2).
    """
    return await _invoke("show_confirmation", state)


# ---------------------------------------------------------------------------
# await_confirmation — silent no-op
# ---------------------------------------------------------------------------


async def await_confirmation(state: dict[str, Any]) -> dict[str, Any]:
    """
    Silent no-op. User already saw show_confirmation.
    This node waits for the next user input without generating a message.
    Control returns to escape_gate on next turn (via new entry pipeline).

    Design decision: silent no-op (orchestrator instruction, 2026-04-21).
    """
    return {}


# ---------------------------------------------------------------------------
# booking_complete
# ---------------------------------------------------------------------------


async def booking_complete(state: dict[str, Any]) -> dict[str, Any]:
    """
    Emit a closing confirmation message referencing the appointment_id.
    No tool calls, no booking_context modification.
    """
    return await _invoke("booking_complete", state)


# ---------------------------------------------------------------------------
# error_recovery
# ---------------------------------------------------------------------------


async def error_recovery(state: dict[str, Any]) -> dict[str, Any]:
    """
    Emit a recovery message and reset booking_context to a clean state.
    Handles mid-session schema migration: clears stale fields so subsequent
    nodes don't crash on unexpected keys.

    Spec: error_recovery §State Fence — booking_context reset to {}.
    """
    llm_result = await _invoke("error_recovery", state)
    # State fence: clear stale booking_context
    return {**llm_result, "booking_context": {}}
