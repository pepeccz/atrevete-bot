"""
QA Runner: returning_client flow, carlos_returning_client persona.
Executes the conversation via Redis Streams/PubSub and uses an LLM
to drive the persona turn-by-turn.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

import redis.asyncio as aioredis
from openai import OpenAI

# ── Redis config ───────────────────────────────────────────────────────────────
REDIS_URL = "redis://:9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda@localhost:6379/0"
INCOMING_STREAM = "incoming_messages_stream"
OUTGOING_CHANNEL = "outgoing_messages"
RESPONSE_TIMEOUT = 30.0

# ── Run config ─────────────────────────────────────────────────────────────────
CONVERSATION_ID = f"qa-{uuid.uuid4()}"
PERSONA_NAME = "Carlos"
CUSTOMER_PHONE = "+34600000001"
MAX_TURNS = 12

# ── LLM config ─────────────────────────────────────────────────────────────────
# Read from env (same OpenRouter key used by the bot)
from shared.config import get_settings

settings = get_settings()
OPENROUTER_API_KEY = settings.OPENROUTER_API_KEY
LLM_MODEL = "openai/gpt-4.1-mini"  # same model as bot

# ── Persona & flow data ────────────────────────────────────────────────────────
PERSONA_YAML = """
name: Carlos
role: returning_client
objective: Book a haircut (corte caballero) with Luciana this week
preferences:
  service: corte caballero
  service_variant: caballero
  stylist: Luciana
  date: esta semana
  time: mañana
personality: familiar
reply_style: knows the salon, casual
accept_addons: false
has_account: true
"""

FLOW_MILESTONES = """
1. greeting_done - Bot greeted and recognized a booking request from a returning client
2. returning_context_captured - Prior salon familiarity or existing account context acknowledged
3. service_resolved - Requested haircut confirmed without unnecessary explanation
4. stylist_locked - Luciana confirmed or an explicit fallback discussed
5. slot_resolved - A concrete slot this week is chosen
6. confirmation_done - Client confirmed the selected appointment
7. booking_completed - Appointment persisted in DB for the requested stylist [COMPLETION]
"""


def build_system_prompt(conversation_history: list[dict], bot_reply: str) -> str:
    history_lines = []
    for msg in conversation_history[-6:]:  # last 6 messages
        role = "User" if msg["role"] == "user" else "Bot"
        history_lines.append(f"{role}: {msg['content']}")
    history_text = "\n".join(history_lines) if history_lines else "(inicio de conversación)"

    return f"""You are {PERSONA_NAME}, a WhatsApp customer of Atrevete beauty salon in Buenos Aires.

PERSONA:
{PERSONA_YAML.strip()}

FLOW MILESTONES (in order):
{FLOW_MILESTONES.strip()}

RULES:
1. Reply ONLY in Spanish, matching the persona personality and reply_style.
2. Keep replies to 1-2 sentences max, like a real WhatsApp message.
3. Stay in character: pursue the persona objective naturally. Do not reveal you are a test agent.
4. If the bot offers numbered options, pick one that matches persona preferences. If no preference, pick the first reasonable option.
5. If the bot asks for info the persona already provided in a previous turn, still answer but flag it as a bug (redundant_question).
6. If the bot ignores a stated preference (e.g. preferred stylist), flag it as ignored_preference.
7. If the bot mentions services, stylists, or prices not in the salon's known catalog, flag it as hallucination.
8. If the bot loses context from earlier turns (forgets name, service, etc.), flag it as context_loss.
9. If the bot replies in a language other than Spanish, flag it as wrong_language.
10. Judge which milestone from the flow was reached this turn. Set milestone_reached to the milestone id or null if no new milestone was reached.
11. Set flow_status to: "in_progress" (still going), "completed" (final milestone reached), "escalated" (human handoff occurred), or "stuck" (bot is looping or confused).
12. Set should_stop=true ONLY when the flow reached its completion_condition or an unrecoverable situation (escalation accepted, bot completely stuck for 3+ turns).
13. Respond ONLY with a valid JSON object. No text outside the JSON.

CONVERSATION SO FAR:
{history_text}

BOT'S LATEST REPLY:
{bot_reply}

Respond with a JSON object matching this exact schema:
{{
  "reply": "your next WhatsApp message in Spanish",
  "flow_status": "in_progress|completed|escalated|stuck",
  "milestone_reached": "milestone_id or null",
  "bugs": [{{"category": "...", "evidence": "...", "turns": [N, M]}}],
  "should_stop": false,
  "stop_reason": ""
}}"""


def call_llm_for_turn(
    openai_client: OpenAI,
    conversation_history: list[dict],
    bot_reply: str,
) -> dict[str, Any]:
    """Call the LLM to get the next persona reply + analysis."""
    system_prompt = build_system_prompt(conversation_history, bot_reply)

    for attempt in range(2):
        try:
            response = openai_client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Generate the next reply and analysis."},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=400,
            )
            raw = response.choices[0].message.content
            return json.loads(raw)
        except json.JSONDecodeError:
            if attempt == 0:
                continue
            # Fallback
            return {
                "reply": "Dale, seguimos.",
                "flow_status": "in_progress",
                "milestone_reached": None,
                "bugs": [{"category": "json_parse_error", "evidence": "LLM returned non-JSON", "turns": []}],
                "should_stop": False,
                "stop_reason": "",
            }


async def inject_message(
    r: aioredis.Redis,
    conversation_id: str,
    message_text: str,
) -> None:
    payload = {
        "conversation_id": conversation_id,
        "customer_phone": CUSTOMER_PHONE,
        "message_text": message_text,
        "sender_name": PERSONA_NAME,
        "customer_name": PERSONA_NAME,
        "is_audio_transcription": False,
        "audio_url": None,
    }
    await r.xadd(INCOMING_STREAM, {"data": json.dumps(payload)})


async def capture_response(
    pubsub: aioredis.client.PubSub,
    conversation_id: str,
    timeout: float = RESPONSE_TIMEOUT,
) -> str:
    """Wait for the bot to publish a response for conversation_id."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return "__TIMEOUT__"

        raw = await pubsub.get_message(ignore_subscribe_messages=True, timeout=min(remaining, 1.0))
        if raw is None:
            continue

        data = raw.get("data")
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        try:
            payload = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            continue

        if payload.get("conversation_id") != conversation_id:
            continue

        return payload.get("message") or payload.get("message_text") or ""


async def run_qa_flow() -> dict[str, Any]:
    print(f"\n{'='*60}")
    print("QA Flow: returning_client | Persona: carlos_returning_client")
    print(f"Conversation ID: {CONVERSATION_ID}")
    print(f"{'='*60}\n")

    # Setup OpenAI client pointing to OpenRouter
    openai_client = OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
    )

    # Connect to Redis
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = r.pubsub()

    # CRITICAL: Subscribe BEFORE injecting any messages
    await pubsub.subscribe(OUTGOING_CHANNEL)
    print(f"✅ Subscribed to {OUTGOING_CHANNEL}")
    await asyncio.sleep(0.2)  # small grace period for subscription to settle

    turns: list[dict[str, Any]] = []
    conversation_history: list[dict] = []
    all_bugs: list[dict] = []
    milestones_reached: list[str] = []
    flow_status = "in_progress"
    termination_reason = ""

    # ── Initial user message (Carlos greets the bot) ──────────────────────────
    initial_message = "Hola! Soy Carlos, quiero sacar turno para un corte de caballero con Luciana para esta semana"

    for turn_number in range(1, MAX_TURNS + 1):
        print(f"\n--- TURN {turn_number} ---")

        # On turn 1, use the initial message; subsequent turns come from LLM
        if turn_number == 1:
            user_message = initial_message
        else:
            # LLM decides next reply based on last bot response
            last_bot_reply = turns[-1]["agent_response"] if turns else ""
            llm_out = call_llm_for_turn(openai_client, conversation_history, last_bot_reply)
            user_message = llm_out.get("reply", "Dale.")
            flow_status = llm_out.get("flow_status", "in_progress")
            milestone = llm_out.get("milestone_reached")
            bugs = llm_out.get("bugs", [])
            should_stop = llm_out.get("should_stop", False)
            stop_reason = llm_out.get("stop_reason", "")

            print(f"  LLM analysis → flow_status={flow_status}, milestone={milestone}, bugs={len(bugs)}, should_stop={should_stop}")

            if milestone and milestone not in milestones_reached:
                milestones_reached.append(milestone)
            all_bugs.extend(bugs)

            if should_stop:
                termination_reason = stop_reason
                print(f"  🛑 LLM says STOP: {stop_reason}")
                # We still send this final message and record the response
                # Then break after recording

        print(f"  👤 Carlos: {user_message}")

        # Inject the user message
        t_sent = datetime.now(UTC)
        await inject_message(r, CONVERSATION_ID, user_message)

        # Capture bot response
        bot_reply = await capture_response(pubsub, CONVERSATION_ID)
        t_received = datetime.now(UTC)
        latency_ms = int((t_received - t_sent).total_seconds() * 1000)

        if bot_reply == "__TIMEOUT__":
            print(f"  ❌ TIMEOUT after {RESPONSE_TIMEOUT}s")
            turns.append({
                "turn_number": turn_number,
                "user_message": user_message,
                "agent_response": None,
                "timestamp_sent": t_sent.isoformat(),
                "timestamp_received": None,
                "response_latency_ms": -1,
                "timed_out": True,
                "milestone_reached": None,
                "flow_status": "timeout",
                "bugs": [],
            })
            termination_reason = f"agent_timeout on turn {turn_number}"
            flow_status = "timeout"
            break

        print(f"  🤖 Bot ({latency_ms}ms): {bot_reply[:200]}{'...' if len(bot_reply) > 200 else ''}")

        # Record this turn
        turn_record = {
            "turn_number": turn_number,
            "user_message": user_message,
            "agent_response": bot_reply,
            "timestamp_sent": t_sent.isoformat(),
            "timestamp_received": t_received.isoformat(),
            "response_latency_ms": latency_ms,
            "timed_out": False,
            "milestone_reached": None,
            "flow_status": "in_progress",
            "bugs": [],
        }

        # Update conversation history for LLM
        conversation_history.append({"role": "user", "content": user_message})
        conversation_history.append({"role": "assistant", "content": bot_reply})

        # For turn 1, get LLM analysis of the first bot response before deciding turn 2
        if turn_number == 1:
            llm_out = call_llm_for_turn(openai_client, conversation_history[:-1], bot_reply)
            milestone = llm_out.get("milestone_reached")
            bugs = llm_out.get("bugs", [])
            flow_status = llm_out.get("flow_status", "in_progress")
            should_stop = llm_out.get("should_stop", False)
            stop_reason = llm_out.get("stop_reason", "")

            print(f"  LLM analysis → flow_status={flow_status}, milestone={milestone}, bugs={len(bugs)}, should_stop={should_stop}")

            if milestone and milestone not in milestones_reached:
                milestones_reached.append(milestone)
            all_bugs.extend(bugs)

            turn_record["milestone_reached"] = milestone
            turn_record["flow_status"] = flow_status
            turn_record["bugs"] = bugs

            if should_stop:
                termination_reason = stop_reason
                turns.append(turn_record)
                break
        else:
            turn_record["milestone_reached"] = milestone if 'milestone' in dir() else None
            turn_record["flow_status"] = flow_status
            turn_record["bugs"] = bugs if 'bugs' in dir() else []

        turns.append(turn_record)

        # Check termination
        if turn_number > 1 and should_stop:
            break

        if flow_status in ("completed", "escalated", "stuck", "timeout"):
            break

    # ── Cleanup ────────────────────────────────────────────────────────────────
    await pubsub.unsubscribe(OUTGOING_CHANNEL)
    await pubsub.close()

    # Try to capture final checkpoint state
    final_state: dict[str, Any] = {}
    try:
        from tests.e2e.harness.redis_harness import RedisTestHarness
        binary_r = aioredis.from_url(REDIS_URL, decode_responses=False)
        harness = RedisTestHarness(r, binary_redis_client=binary_r)
        final_state = await harness.capture_final_state(CONVERSATION_ID) or {}
        await harness.close()
    except Exception as e:
        final_state = {"checkpoint_error": str(e)}

    await r.aclose()

    # ── Build result ───────────────────────────────────────────────────────────
    last_milestone = milestones_reached[-1] if milestones_reached else "none"
    outcome = flow_status if flow_status != "in_progress" else "max_turns_exceeded"
    if not termination_reason:
        termination_reason = f"max_turns ({MAX_TURNS}) reached" if len(turns) >= MAX_TURNS else "flow_ended"

    result = {
        "scenario_id": "returning_client",
        "persona_id": "carlos_returning_client",
        "conversation_id": CONVERSATION_ID,
        "flow_status": flow_status,
        "outcome": outcome,
        "milestones_reached": milestones_reached,
        "last_milestone": last_milestone,
        "termination_reason": termination_reason,
        "total_turns": len(turns),
        "bugs_detected": all_bugs,
        "bugs_summary": f"{len(all_bugs)} bugs detected" if all_bugs else "No bugs detected",
        "turns": turns,
        "final_state": final_state,
        "total_duration_ms": sum(t["response_latency_ms"] for t in turns if t["response_latency_ms"] > 0),
    }

    return result


if __name__ == "__main__":
    result = asyncio.run(run_qa_flow())

    print(f"\n{'='*60}")
    print("QA RESULT SUMMARY")
    print(f"{'='*60}")
    print(f"Scenario:          {result['scenario_id']}")
    print(f"Conversation ID:   {result['conversation_id']}")
    print(f"Flow Status:       {result['flow_status']}")
    print(f"Outcome:           {result['outcome']}")
    print(f"Milestones:        {result['milestones_reached']}")
    print(f"Total Turns:       {result['total_turns']}")
    print(f"Total Duration:    {result['total_duration_ms']}ms")
    print(f"Bugs:              {result['bugs_summary']}")
    print(f"Termination:       {result['termination_reason']}")
    print("\nFull JSON result written to stdout:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
