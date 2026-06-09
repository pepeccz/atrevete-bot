"""Thin CLI wrapper for QA turn operations.

Provides 4 subcommands (health, turn, reset, state) that a Claude Code
sub-agent can call via Bash to drive live conversational QA flows.

Usage:
    python tests/e2e/harness/qa_turn_helper.py health
    python tests/e2e/harness/qa_turn_helper.py turn --conversation-id <uuid> --message "Hola"
    python tests/e2e/harness/qa_turn_helper.py reset --conversation-id <uuid>
    python tests/e2e/harness/qa_turn_helper.py state --conversation-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

from shared.config import get_settings
from tests.e2e.harness.redis_harness import RedisTestHarness


def _json_out(data: dict[str, Any]) -> None:
    """Write JSON to stdout and exit 0."""
    print(json.dumps(data, ensure_ascii=False, default=str))


def _json_err(error: str, details: str | None = None) -> None:
    """Write error JSON to stderr and exit 1."""
    payload: dict[str, Any] = {"ok": False, "error": error}
    if details:
        payload["details"] = details
    print(json.dumps(payload, ensure_ascii=False, default=str), file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------


async def _cmd_health() -> None:
    """Check Redis connectivity and INCOMING_STREAM existence."""
    import redis.asyncio as redis

    from shared.config import get_settings
    from shared.redis_client import INCOMING_STREAM

    settings = get_settings()
    redis_kwargs: dict[str, Any] = {"decode_responses": True}
    if settings.REDIS_PASSWORD:
        redis_kwargs["password"] = settings.REDIS_PASSWORD
    client = redis.from_url(settings.REDIS_URL, **redis_kwargs)
    try:
        await client.ping()
        stream_exists = await client.exists(INCOMING_STREAM)
        _json_out(
            {
                "ok": True,
                "redis": "connected",
                "stream": "exists" if stream_exists else "missing",
            }
        )
    except Exception as exc:
        _json_err("redis_connection_failed", str(exc))
    finally:
        await client.aclose()


async def _cmd_turn(args: Any) -> int:
    """Execute an atomic subscribe-before-inject turn.

    Builds QARunIdentity and QARunSession from CLI args, then delegates
    to RedisTestHarness.execute_turn(). Returns 0 on success, 2 on timeout.
    """
    import redis.asyncio as redis

    from tests.e2e.harness.run_models import QARunIdentity, QARunSession

    settings = get_settings()
    redis_kwargs: dict[str, Any] = {"decode_responses": True}
    if settings.REDIS_PASSWORD:
        redis_kwargs["password"] = settings.REDIS_PASSWORD
    client = redis.from_url(settings.REDIS_URL, **redis_kwargs)
    harness = RedisTestHarness(redis_client=client)
    try:
        identity = QARunIdentity(
            conversation_id=args.conversation_id,
            customer_phone=args.customer_phone,
            sender_name=args.persona_name,
            run_started_at=datetime.now(timezone.utc),
        )
        session = QARunSession(
            identity=identity,
            started_monotonic=time.monotonic(),
        )
        result = await harness.execute_turn(
            user_message=args.user_message,
            session=session,
            timeout=args.timeout,
            raise_on_timeout=False,
        )
        _json_out(
            {
                "agent_response": result["agent_response"],
                "timed_out": result["timed_out"],
                "response_latency_ms": result["response_latency_ms"],
                "tool_evidence": result["tool_evidence"],
            }
        )
        return 2 if result["timed_out"] else 0
    except Exception as exc:
        _json_err("turn_failed", str(exc))
        return 1
    finally:
        await harness.close()
        await client.aclose()


async def _cmd_reset(conversation_id: str, phone: str) -> None:
    """Clean up Redis state for a conversation."""
    import redis.asyncio as redis

    from shared.config import get_settings
    from tests.e2e.harness.state_reset import StateResetHarness

    settings = get_settings()
    redis_kwargs_bin: dict[str, Any] = {"decode_responses": False}
    if settings.REDIS_PASSWORD:
        redis_kwargs_bin["password"] = settings.REDIS_PASSWORD
    client = redis.from_url(settings.REDIS_URL, **redis_kwargs_bin)
    harness = StateResetHarness(redis_client=client)
    try:
        result = await harness.reset_conversation_state(
            conversation_id=conversation_id,
            customer_phone=phone,
        )
        _json_out(result)
    except Exception as exc:
        _json_err("reset_failed", str(exc))
    finally:
        await client.aclose()


async def _cmd_state(args: Any) -> None:
    """Fetch current checkpoint state for a conversation.

    Outputs only fields present in the current AgentState schema
    (post create_agent rewrite). Does NOT output deleted fields:
    current_mode, mode_context, mode_history, is_first_interaction,
    error_count, booking_step.
    """
    import redis.asyncio as redis
    from langchain_core.messages import ToolMessage

    settings = get_settings()
    redis_kwargs_txt: dict[str, Any] = {"decode_responses": True}
    redis_kwargs_bin2: dict[str, Any] = {"decode_responses": False}
    if settings.REDIS_PASSWORD:
        redis_kwargs_txt["password"] = settings.REDIS_PASSWORD
        redis_kwargs_bin2["password"] = settings.REDIS_PASSWORD
    client = redis.from_url(settings.REDIS_URL, **redis_kwargs_txt)
    binary_client = redis.from_url(settings.REDIS_URL, **redis_kwargs_bin2)
    harness = RedisTestHarness(redis_client=client, binary_redis_client=binary_client)
    try:
        state = await harness.capture_final_state(args.conversation_id)
        if state is None:
            _json_out({"has_checkpoint": False})
            return

        messages = state.get("messages", [])

        # Find the name of the last ToolMessage in the messages list
        latest_tool_call_name: str | None = None
        for msg in reversed(messages):
            if isinstance(msg, ToolMessage):
                latest_tool_call_name = getattr(msg, "name", None)
                break

        _json_out(
            {
                "has_checkpoint": True,
                "conversation_id": state.get("conversation_id"),
                "customer_phone": state.get("customer_phone"),
                "customer_id": state.get("customer_id"),
                "customer_name": state.get("customer_name"),
                "messages_count": len(messages),
                "latest_tool_call_name": latest_tool_call_name,
                "customer_consents_count": len(state.get("customer_consents", []) or []),
                "policy_accepted_at": state.get("policy_accepted_at"),
                "summary_present": bool(state.get("conversation_summary") or state.get("summary")),
            }
        )
    except Exception as exc:
        _json_err("state_fetch_failed", str(exc))
    finally:
        await harness.close()
        await client.aclose()
        await binary_client.aclose()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qa_turn_helper",
        description="CLI helper for QA conversational turn operations.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # health
    sub.add_parser("health", help="Check Redis connectivity")

    # turn
    p_turn = sub.add_parser("turn", help="Execute an atomic conversation turn")
    p_turn.add_argument("--conversation-id", required=True, dest="conversation_id", help="Conversation UUID")
    p_turn.add_argument("--user-message", required=True, dest="user_message", help="User message text")
    p_turn.add_argument("--customer-phone", default="+34999000000", dest="customer_phone", help="Customer phone (must start with TEST_PHONE_PREFIX)")
    p_turn.add_argument("--persona-name", default="QA Test Client", dest="persona_name", help="Customer display name")
    p_turn.add_argument("--timeout", type=float, default=60.0, help="Response timeout (seconds)")

    # reset
    p_reset = sub.add_parser("reset", help="Reset Redis state for a conversation")
    p_reset.add_argument("--conversation-id", required=True, dest="conversation_id", help="Conversation UUID")
    p_reset.add_argument("--phone", default="+34999000000", help="Customer phone")

    # state
    p_state = sub.add_parser("state", help="Fetch checkpoint state")
    p_state.add_argument("--conversation-id", required=True, dest="conversation_id", help="Conversation UUID")

    return parser


def main() -> None:
    # Force batch window to 0 so messages are processed immediately
    os.environ["MESSAGE_BATCH_WINDOW_SECONDS"] = "0"

    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "health":
        asyncio.run(_cmd_health())
    elif args.command == "turn":
        asyncio.run(_cmd_turn(args))
    elif args.command == "reset":
        asyncio.run(
            _cmd_reset(
                conversation_id=args.conversation_id,
                phone=args.phone,
            )
        )
    elif args.command == "state":
        asyncio.run(_cmd_state(args))


if __name__ == "__main__":
    main()
