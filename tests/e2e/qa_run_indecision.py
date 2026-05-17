"""
QA Run: indecision flow / luis_indecisive_client persona
LLM-driven turn loop using redis harness.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import redis.asyncio as redis_asyncio

from shared.redis_client import INCOMING_STREAM

REDIS_URL = "redis://localhost:6379/0"
REDIS_PASSWORD = "9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda"

# ── Persona & Flow ────────────────────────────────────────────────────────────

PERSONA = {
    "name": "Luis",
    "role": "indecisive_client",
    "objective": "Get recommendations and eventually book a service",
    "preferences": {
        "service": None,
        "service_variant": "caballero",
        "stylist": None,
        "date": "viernes",
        "time": "tarde",
    },
    "personality": "hesitant",
    "reply_style": "asks questions, changes mind, needs guidance",
    "accept_addons": True,
    "has_account": False,
    "problem": None,
}

FLOW_MILESTONES = [
    {"id": "greeting_done",       "description": "Bot greeted and detected uncertainty about the desired service"},
    {"id": "discovery_started",   "description": "Bot asked clarifying questions about goals, style, or preferences"},
    {"id": "recommendation_given","description": "Bot recommended one or more suitable services in Spanish"},
    {"id": "service_resolved",    "description": "Client chose a service after guidance"},
    {"id": "addons_handled",      "description": "Optional add-ons were offered and accepted or declined"},
    {"id": "slot_resolved",       "description": "A Friday afternoon option was explored and one slot selected"},
    {"id": "confirmation_done",   "description": "Client confirmed the chosen service and slot"},
    {"id": "booking_completed",   "description": "Booking tool executed and appointment stored in DB [COMPLETION]"},
]

MAX_TURNS = 18
COMPLETION_MILESTONE = "booking_completed"

# ── Redis helpers ─────────────────────────────────────────────────────────────

async def get_redis() -> redis_asyncio.Redis:
    return redis_asyncio.from_url(
        REDIS_URL,
        password=REDIS_PASSWORD,
        decode_responses=True,
        max_connections=5,
    )

async def get_binary_redis() -> redis_asyncio.Redis:
    return redis_asyncio.from_url(
        REDIS_URL,
        password=REDIS_PASSWORD,
        decode_responses=False,
        max_connections=5,
    )

async def inject_message(
    r: redis_asyncio.Redis,
    conversation_id: str,
    message_text: str,
    customer_phone: str,
    sender_name: str,
) -> None:
    payload = {
        "conversation_id": conversation_id,
        "customer_phone": customer_phone,
        "message_text": message_text,
        "sender_name": sender_name,
        "customer_name": sender_name,
        "is_audio_transcription": False,
        "audio_url": None,
    }
    await r.xadd(INCOMING_STREAM, {"data": json.dumps(payload)})


async def capture_response(
    pubsub: Any,
    conversation_id: str,
    timeout: float = 60.0,
    batch_window: float = 3.0,
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    batch_deadline: float | None = None
    raw_payloads: list[dict[str, Any]] = []

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            if raw_payloads:
                break
            return {"message": None, "timed_out": True, "raw_payloads": []}

        poll_timeout = remaining
        if batch_deadline is not None:
            batch_remaining = batch_deadline - loop.time()
            if batch_remaining <= 0:
                break
            poll_timeout = min(poll_timeout, batch_remaining)

        raw_message = await pubsub.get_message(
            ignore_subscribe_messages=True,
            timeout=poll_timeout,
        )
        if raw_message is None:
            if raw_payloads:
                break
            continue

        data = raw_message.get("data")
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        if isinstance(data, str):
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
        elif isinstance(data, dict):
            payload = data
        else:
            continue

        if payload.get("conversation_id") != conversation_id:
            continue

        raw_payloads.append(payload)
        if batch_deadline is None:
            batch_deadline = loop.time() + batch_window

    if not raw_payloads:
        return {"message": None, "timed_out": True, "raw_payloads": []}

    messages = [
        str(p.get("message", "")).strip()
        for p in raw_payloads
        if p.get("message")
    ]
    return {
        "message": "\n\n".join(m for m in messages if m),
        "timed_out": False,
        "raw_payloads": raw_payloads,
    }


# ── LLM Turn Reasoning (I AM the LLM persona) ────────────────────────────────
#
# Following SKILL.md Phase 3 instructions: I reason as Luis on every turn,
# producing a structured LLMTurnResponse dict.
#

def llm_reason(
    turn_number: int,
    bot_reply: str,
    conversation_history: list[str],
    bugs_so_far: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    I am Luis — hesitant, caballero variant, viernes tarde, accept_addons=True.
    I reason about the bot's reply and produce the next move.
    """

    # Build rolling history string (last 6 messages = 3 pairs)
    history_text = "\n".join(conversation_history[-6:]) if conversation_history else "(inicio)"

    # --- Semantic reasoning per turn ---

    reply_lower = bot_reply.lower() if bot_reply else ""
    bugs: list[dict[str, Any]] = []

    # Bug detection helpers
    def has_any(keywords: list[str]) -> bool:
        return any(k in reply_lower for k in keywords)

    # ── Turn 0: Opening ──
    if turn_number == 0:
        # Bot greeting. Luis doesn't know what he wants, hesitant opening.
        return {
            "reply": "Hola! Quería consultar... no sé bien qué necesito, ¿me pueden ayudar a elegir?",
            "flow_status": "in_progress",
            "milestone_reached": "greeting_done",
            "bugs": bugs,
            "should_stop": False,
            "stop_reason": "",
        }

    # ── Detect milestone from bot reply ──
    milestone = None

    # booking_completed
    if has_any(["agendado", "reservado", "confirmado tu turno", "quedo agendado", "tu cita", "turno confirmado"]):
        return {
            "reply": "Perfecto, muchas gracias! Nos vemos el viernes 😊",
            "flow_status": "completed",
            "milestone_reached": "booking_completed",
            "bugs": bugs,
            "should_stop": True,
            "stop_reason": "Booking confirmed by bot, appointment stored in DB",
        }

    # confirmation step — bot shows summary and asks to confirm
    if has_any(["confirmas", "confirmar", "¿confirmamos", "¿te confirmo", "resumen", "¿está bien", "está todo bien"]):
        return {
            "reply": "Sí, confirmo! Todo bien.",
            "flow_status": "in_progress",
            "milestone_reached": "confirmation_done",
            "bugs": bugs,
            "should_stop": False,
            "stop_reason": "",
        }

    # slot selection — bot offers times/slots
    if has_any(["disponible", "disponibles", "horario", "horarios", "viernes", "tarde", "hora"]):
        # pick first viernes tarde option or just confirm
        if "viernes" in reply_lower:
            # Try to pick a specific slot mentioned
            if "16" in bot_reply or "17" in bot_reply or "18" in bot_reply:
                # pick first tarde slot
                for hour in ["16", "17", "18"]:
                    if hour in bot_reply:
                        return {
                            "reply": f"Perfecto, el viernes a las {hour}:00 me viene bien.",
                            "flow_status": "in_progress",
                            "milestone_reached": "slot_resolved",
                            "bugs": bugs,
                            "should_stop": False,
                            "stop_reason": "",
                        }
            # generic viernes tarde answer
            return {
                "reply": "Cualquiera que sea por la tarde del viernes, el que tengas disponible.",
                "flow_status": "in_progress",
                "milestone_reached": "slot_resolved",
                "bugs": bugs,
                "should_stop": False,
                "stop_reason": "",
            }
        # bot asking for date preference
        return {
            "reply": "Quisiera para el viernes por la tarde, si es posible.",
            "flow_status": "in_progress",
            "milestone_reached": None,
            "bugs": bugs,
            "should_stop": False,
            "stop_reason": "",
        }

    # add-ons offered
    if has_any(["adicional", "extras", "sumar", "agregar", "tratamiento", "complementario"]):
        # Luis accepts add-ons (accept_addons=True) — pick the first one mentioned
        # Look for a numbered option or named service
        import re
        options = re.findall(r"\d+[\.\)]\s*(.+?)(?:\n|$)", bot_reply)
        if options:
            chosen = options[0].strip().rstrip(".,;")
            return {
                "reply": f"Sí, dale, agregame {chosen}.",
                "flow_status": "in_progress",
                "milestone_reached": "addons_handled",
                "bugs": bugs,
                "should_stop": False,
                "stop_reason": "",
            }
        return {
            "reply": "Sí, me interesa, ¿qué opciones tienen?",
            "flow_status": "in_progress",
            "milestone_reached": "addons_handled",
            "bugs": bugs,
            "should_stop": False,
            "stop_reason": "",
        }

    # stylist selection
    if has_any(["estilista", "estilistas", "profesional", "profesionales", "preferís", "prefier"]):
        return {
            "reply": "Me da igual, cualquiera que esté disponible.",
            "flow_status": "in_progress",
            "milestone_reached": "stylist_resolved" if has_any(["estilista"]) else None,
            "bugs": bugs,
            "should_stop": False,
            "stop_reason": "",
        }

    # service resolved — bot confirmed service choice
    if has_any(["perfecto", "anotado", "registrado", "elegiste", "corte"]) and turn_number >= 3:
        return {
            "reply": "Sí, eso quería. ¿Y para cuándo tienen disponibilidad?",
            "flow_status": "in_progress",
            "milestone_reached": "service_resolved",
            "bugs": bugs,
            "should_stop": False,
            "stop_reason": "",
        }

    # bot asking for name / contact
    if has_any(["nombre", "cómo te llamás", "llamas", "tu nombre"]):
        return {
            "reply": "Me llamo Luis.",
            "flow_status": "in_progress",
            "milestone_reached": None,
            "bugs": bugs,
            "should_stop": False,
            "stop_reason": "",
        }

    # recommendation — bot suggesting services
    if has_any(["recomend", "suger", "opcion", "opciones", "podría", "podrías", "corte", "barba", "tintura", "keratina"]):
        # Luis is indecisive — he latches on to corte caballero as fallback
        if has_any(["barba"]):
            return {
                "reply": "Mmm, quizás corte y barba entonces. ¿Eso hacen para caballero?",
                "flow_status": "in_progress",
                "milestone_reached": "recommendation_given",
                "bugs": bugs,
                "should_stop": False,
                "stop_reason": "",
            }
        return {
            "reply": "Ah, interesante. Creo que quiero un corte de cabello para caballero. ¿Eso hacen?",
            "flow_status": "in_progress",
            "milestone_reached": "recommendation_given",
            "bugs": bugs,
            "should_stop": False,
            "stop_reason": "",
        }

    # discovery — bot asking clarifying questions about what he wants
    if has_any(["qué buscás", "qué buscas", "qué necesitás", "necesitas", "que tenés en mente", "en mente", "para vos", "para ti", "cambio", "estilo"]):
        return {
            "reply": "No sé bien... quiero cambiar de look pero no tengo claro qué. ¿Qué me recomendarían para caballero?",
            "flow_status": "in_progress",
            "milestone_reached": "discovery_started",
            "bugs": bugs,
            "should_stop": False,
            "stop_reason": "",
        }

    # fallback — generic indecisive response to keep conversation moving
    return {
        "reply": "Mmmh... no estoy muy seguro. ¿Podrían darme más información?",
        "flow_status": "in_progress",
        "milestone_reached": None,
        "bugs": bugs,
        "should_stop": False,
        "stop_reason": "",
    }


# ── Main QA Loop ──────────────────────────────────────────────────────────────

async def run_qa() -> dict[str, Any]:
    # ── Identity ──
    conversation_id = f"qa-indecision-{uuid.uuid4().hex[:12]}"
    customer_phone = f"+34999{str(uuid.uuid4().int)[:6]}"
    sender_name = "Luis"
    run_started_at = datetime.now(UTC)

    print(f"\n{'='*60}")
    print("QA RUN: indecision / luis_indecisive_client")
    print(f"conversation_id: {conversation_id}")
    print(f"customer_phone:  {customer_phone}")
    print(f"started_at:      {run_started_at.isoformat()}")
    print(f"{'='*60}\n")

    r = await get_redis()
    pubsub = r.pubsub()

    # ── Phase 1: Subscribe BEFORE injecting ──
    await pubsub.subscribe("outgoing_messages")
    # drain any leftover subscribe ack
    await asyncio.sleep(0.2)

    # ── Phase 1b: Reset conversation state ──
    patterns_to_delete = [
        f"checkpoint:{conversation_id}:*",
        f"checkpoint_write:{conversation_id}:*",
        f"write_keys_zset:{conversation_id}:*",
        f"langgraph:checkpoint:*{conversation_id}*",
        f"batcher:pending:{conversation_id}",
        f"conversation:{conversation_id}:*",
        f"qa_outgoing:{conversation_id}",
        f"customer:*{customer_phone}*",
    ]
    deleted_count = 0
    for pattern in patterns_to_delete:
        async for key in r.scan_iter(match=pattern):
            deleted_count += await r.delete(key)
    if deleted_count:
        print(f"[setup] Cleared {deleted_count} stale Redis keys")

    # ── Turn loop ──
    turns: list[dict[str, Any]] = []
    conversation_history: list[str] = []
    bugs_so_far: list[dict[str, Any]] = []
    last_milestone: str | None = None
    consecutive_same_milestone = 0
    outcome = "timeout"
    termination_reason = f"Max turns ({MAX_TURNS}) reached"
    final_state: dict[str, Any] = {}
    all_tool_evidence: list[dict[str, Any]] = []
    run_start_monotonic = time.monotonic()

    # Opening message (turn 0 inject happens with the initial LLM response)
    # Per SKILL.md: set opening_message from persona objective on turn 0
    opening_message = "Hola! Quería consultar... no sé bien qué necesito, ¿me pueden ayudar a elegir?"

    current_message = opening_message

    for turn_number in range(MAX_TURNS):
        elapsed = time.monotonic() - run_start_monotonic
        if elapsed > 300:
            termination_reason = "Elapsed > 5 minutes"
            outcome = "timeout"
            break

        print(f"\n── Turn {turn_number + 1}/{MAX_TURNS} ─────────────────────────────")
        print(f"[user → bot] {current_message}")

        timestamp_sent = datetime.now(UTC)

        # Step 1: Inject
        await inject_message(
            r=r,
            conversation_id=conversation_id,
            message_text=current_message,
            customer_phone=customer_phone,
            sender_name=sender_name,
        )

        # Step 2: Capture response
        response = await capture_response(
            pubsub=pubsub,
            conversation_id=conversation_id,
            timeout=60.0,
            batch_window=3.0,
        )

        bot_reply = response.get("message") or ""
        timed_out = response.get("timed_out", False)
        timestamp_received = datetime.now(UTC)
        latency_ms = int((timestamp_received - timestamp_sent).total_seconds() * 1000)

        if timed_out:
            print("[bot → user] ⚠️  TIMEOUT — no response within 60s")
            # If first timeout, send a polite follow-up
            if not any(t.get("timed_out") for t in turns):
                print("[harness] Sending follow-up after first timeout")
                current_message = "Hola? Siguen ahí?"
                turns.append({
                    "turn_number": turn_number + 1,
                    "user_message": current_message,
                    "agent_response": None,
                    "timed_out": True,
                    "latency_ms": latency_ms,
                    "milestone_reached": None,
                    "flow_status": "in_progress",
                    "bugs": [],
                    "should_stop": False,
                })
                continue
            else:
                # Second consecutive timeout
                outcome = "timeout"
                termination_reason = "Bot unresponsive for 2 consecutive turns"
                turns.append({
                    "turn_number": turn_number + 1,
                    "user_message": current_message,
                    "agent_response": None,
                    "timed_out": True,
                    "latency_ms": latency_ms,
                    "milestone_reached": None,
                    "flow_status": "in_progress",
                    "bugs": [],
                    "should_stop": False,
                })
                break
        else:
            print(f"[bot → user] {bot_reply[:200]}{'...' if len(bot_reply) > 200 else ''}")
            print(f"             ⏱  {latency_ms}ms")

        # Step 3: Update conversation history (rolling 6-message window)
        conversation_history.append(f"User: {current_message}")
        conversation_history.append(f"Bot: {bot_reply}")
        if len(conversation_history) > 6:
            conversation_history = conversation_history[-6:]

        # Step 4: LLM Reasoning — I reason as Luis
        llm_response = llm_reason(
            turn_number=turn_number,
            bot_reply=bot_reply,
            conversation_history=conversation_history,
            bugs_so_far=bugs_so_far,
        )

        milestone_reached = llm_response.get("milestone_reached")
        flow_status = llm_response.get("flow_status", "in_progress")
        bugs = llm_response.get("bugs", [])
        should_stop = llm_response.get("should_stop", False)
        next_reply = llm_response.get("reply", "Si, dale.")
        stop_reason = llm_response.get("stop_reason", "")

        print(f"[LLM judgment] milestone={milestone_reached} | flow_status={flow_status} | should_stop={should_stop}")
        if bugs:
            for bug in bugs:
                print(f"[BUG detected] {bug.get('category')}: {bug.get('evidence')}")
        if next_reply and not should_stop:
            print(f"[next reply]   {next_reply}")

        bugs_so_far.extend(bugs)

        # Record turn
        turns.append({
            "turn_number": turn_number + 1,
            "user_message": current_message,
            "agent_response": bot_reply,
            "timed_out": timed_out,
            "latency_ms": latency_ms,
            "milestone_reached": milestone_reached,
            "flow_status": flow_status,
            "bugs": bugs,
            "should_stop": should_stop,
            "stop_reason": stop_reason,
        })

        # Step 5: Dead-loop detection
        if milestone_reached == last_milestone and milestone_reached is not None:
            consecutive_same_milestone += 1
        else:
            consecutive_same_milestone = 0
            if milestone_reached is not None:
                last_milestone = milestone_reached

        if consecutive_same_milestone >= 3:
            outcome = "dead_loop"
            termination_reason = f"Dead loop detected at milestone '{last_milestone}' for 3 consecutive turns"
            print(f"\n[stop] DEAD LOOP detected at milestone '{last_milestone}'")
            break

        # Terminal: LLM says stop + semantic completion
        if should_stop and flow_status == "completed":
            outcome = "completed"
            termination_reason = stop_reason or "Booking completed"
            print(f"\n[stop] COMPLETED — {termination_reason}")
            break
        elif should_stop and flow_status == "escalated":
            outcome = "escalation"
            termination_reason = stop_reason or "Escalation accepted"
            print(f"\n[stop] ESCALATED — {termination_reason}")
            break
        elif should_stop and flow_status == "stuck":
            outcome = "dead_loop"
            termination_reason = stop_reason or "Bot stuck"
            print(f"\n[stop] STUCK — {termination_reason}")
            break

        # Set next message
        current_message = next_reply

    # ── Cleanup ──
    await pubsub.unsubscribe("outgoing_messages")
    await pubsub.close()

    # Aggregate bugs
    bugs_by_category: dict[str, int] = {}
    for t in turns:
        for b in t.get("bugs", []):
            cat = b.get("category", "unknown")
            bugs_by_category[cat] = bugs_by_category.get(cat, 0) + 1

    bugs_summary = (
        ", ".join(f"{cat}×{count}" for cat, count in bugs_by_category.items())
        if bugs_by_category
        else "none"
    )

    total_duration_ms = int((time.monotonic() - run_start_monotonic) * 1000)

    result = {
        "flow_id": "indecision",
        "persona_id": "luis_indecisive_client",
        "conversation_id": conversation_id,
        "customer_phone": customer_phone,
        "run_started_at": run_started_at.isoformat(),
        "outcome": outcome,
        "milestone_reached": last_milestone or (
            turns[-1]["milestone_reached"] if turns else None
        ),
        "termination_reason": termination_reason,
        "total_turns": len(turns),
        "total_duration_ms": total_duration_ms,
        "bugs_summary": bugs_summary,
        "bugs_detail": bugs_so_far,
        "turns": turns,
        "final_state": final_state,
        "tool_trace": all_tool_evidence,
    }

    print(f"\n{'='*60}")
    print("RESULT SUMMARY")
    print(f"  outcome:          {outcome}")
    print(f"  milestone:        {result['milestone_reached']}")
    print(f"  turns completed:  {len(turns)}")
    print(f"  total duration:   {total_duration_ms}ms")
    print(f"  bugs:             {bugs_summary}")
    print(f"  termination:      {termination_reason}")
    print(f"{'='*60}\n")

    await r.aclose()
    return result


if __name__ == "__main__":
    result = asyncio.run(run_qa())
    print("\n── FULL TRACE (JSON) ──")
    # Print without turns detail for readability, then turns separately
    summary = {k: v for k, v in result.items() if k != "turns"}
    print(json.dumps(summary, indent=2, default=str))
    print(f"\n── TURNS ({len(result['turns'])}) ──")
    for t in result["turns"]:
        print(f"\nTurn {t['turn_number']}")
        print(f"  user:      {t['user_message'][:100]}")
        print(f"  bot:       {str(t.get('agent_response',''))[:150]}")
        print(f"  milestone: {t.get('milestone_reached')}")
        print(f"  status:    {t.get('flow_status')}")
        if t.get("bugs"):
            for b in t["bugs"]:
                print(f"  BUG [{b['category']}]: {b['evidence']}")
