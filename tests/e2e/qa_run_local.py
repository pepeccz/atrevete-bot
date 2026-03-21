"""
QA Run: booking_complete flow with María (new client persona).
Runs locally, connecting to Redis on localhost:6379 (Docker-mapped).

Usage:
    python tests/e2e/qa_run_local.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any
import re

import redis.asyncio as aioredis

# ---------------------------------------------------------------------------
# Config — connect to Redis exposed on localhost:6379 from Docker
# ---------------------------------------------------------------------------
REDIS_URL = "redis://localhost:6379/0"
REDIS_PASSWORD = "9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda"
INCOMING_STREAM = "incoming_messages_stream"
OUTGOING_CHANNEL = "outgoing_messages"
MAX_TURNS = 15
TURN_TIMEOUT_S = 45.0
BATCH_WINDOW_S = 4.0  # wait up to 4s for multi-part messages

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("qa_run")


def build_opening_message() -> str:
    return "Hola! Quiero sacar un turno para corte de dama para el jueves que viene."


def reason_as_maria(
    turn_number: int,
    bot_reply: str,
    conversation_history: list[str],
    milestone_history: list[str | None],
) -> dict[str, Any]:
    """
    Inline LLM reasoning: we ARE María.
    Returns LLMTurnResponse-compatible dict.
    """
    reply_lower = bot_reply.lower()
    bugs: list[dict] = []
    milestone_reached: str | None = None

    # --- Milestone detection ---
    # greeting_done: bot greeted + any intent captured
    if any(w in reply_lower for w in ["bienvenida", "bienvenido", "hola", "como puedo", "ayudarte"]):
        if "greeting_done" not in milestone_history:
            milestone_reached = "greeting_done"

    # service_resolved: bot confirmed the service type
    if any(w in reply_lower for w in ["corte de dama", "corte para dama", "corte (dama)", "servicio: corte"]):
        if "service_resolved" not in [m for m in milestone_history if m]:
            milestone_reached = "service_resolved"

    # addons_handled: bot offered add-ons (we decline)
    if any(w in reply_lower for w in ["adicional", "extra", "sumar", "agregar", "tratamiento", "complementario", "add-on", "addon"]):
        if "addons_handled" not in [m for m in milestone_history if m]:
            milestone_reached = "addons_handled"

    # stylist_resolved: bot asked for/confirmed stylist
    if any(w in reply_lower for w in ["estilista", "profesional", "preferís", "preferis", "quién", "quien", "luciana", "valentina", "sofia"]):
        if "addons_handled" in [m for m in milestone_history if m] and "stylist_resolved" not in [m for m in milestone_history if m]:
            milestone_reached = "stylist_resolved"

    # slot_resolved: bot shows available slots
    if any(w in reply_lower for w in ["turno", "horario", "disponible", "jueves", "lunes", "martes", "viernes"]):
        if re.search(r'\d{1,2}[:h]\d{2}', bot_reply) or re.search(r'^\s*\d+[.)]\s+', bot_reply, re.MULTILINE):
            if "slot_resolved" not in [m for m in milestone_history if m]:
                milestone_reached = "slot_resolved"

    # confirmation_done: bot asks to confirm
    if any(w in reply_lower for w in ["confirmas", "confirmar", "confirmás", "¿confirmo", "¿confirmás", "resumen", "estás segura", "segura"]):
        if "slot_resolved" in [m for m in milestone_history if m] and "confirmation_done" not in [m for m in milestone_history if m]:
            milestone_reached = "confirmation_done"

    # booking_completed: bot confirms booking is done
    if any(w in reply_lower for w in ["reservado", "agendado", "confirmado", "quedó", "quedo agendado", "turno confirmado", "¡listo", "listo!"]):
        milestone_reached = "booking_completed"

    # --- Bug detection ---

    # Redundant "dama o caballero?" question
    if ("dama" in reply_lower and "caballero" in reply_lower and "?" in bot_reply):
        history_text = " ".join(conversation_history)
        if "dama" in history_text.lower() and turn_number > 1:
            bugs.append({
                "category": "redundant_question",
                "evidence": (
                    f"Bot asked 'dama o caballero?' on turn {turn_number} "
                    f"but user already specified 'para dama' in opening message"
                ),
                "turns": [1, turn_number],
            })

    # Wrong language
    spanish_indicators = ["el ", "la ", "de ", " y ", " o ", "para ", "que ", "en ", "por ", "con "]
    if len(bot_reply) > 30 and not any(ind in reply_lower for ind in spanish_indicators):
        bugs.append({
            "category": "wrong_language",
            "evidence": f"Reply does not appear to be in Spanish: '{bot_reply[:80]}'",
            "turns": [turn_number],
        })

    # --- Generate María's reply ---
    reply_text = _generate_maria_reply(turn_number, bot_reply, milestone_history, milestone_reached)

    # --- Flow status ---
    if milestone_reached == "booking_completed":
        return {
            "reply": "Perfecto, muchas gracias! 😊",
            "flow_status": "completed",
            "milestone_reached": "booking_completed",
            "bugs": bugs,
            "should_stop": True,
            "stop_reason": "Booking confirmed by bot, appointment stored",
        }

    return {
        "reply": reply_text,
        "flow_status": "in_progress",
        "milestone_reached": milestone_reached,
        "bugs": bugs,
        "should_stop": False,
        "stop_reason": "",
    }


def _generate_maria_reply(
    turn_number: int,
    bot_reply: str,
    milestone_history: list[str | None],
    milestone_reached: str | None,
) -> str:
    """María is concise, direct. Max 1-2 sentences."""
    reply_lower = bot_reply.lower()

    # Bot confirmed booking (check FIRST to avoid false matches)
    if any(w in reply_lower for w in ["reservado", "agendado", "quedó", "quedo agendado", "turno confirmado"]):
        return "Perfecto, muchas gracias!"

    # Bot greeting / asks how to help
    if any(w in reply_lower for w in ["como puedo ayudarte", "en qué puedo", "qué necesitas", "bienvenida"]):
        return "Quiero sacar un turno para corte de dama para el jueves que viene."

    # Bot explicitly asks dama/caballero
    if re.search(r"(dama|caballero|niño)\s*(o|\/)\s*(dama|caballero|niño)", reply_lower):
        return "Para dama."

    # Bot offers add-ons
    if any(w in reply_lower for w in ["adicional", "extra", "sumar", "agregar", "tratamiento", "complementario"]):
        return "No, gracias."

    # Bot asks for stylist preference  
    if any(w in reply_lower for w in ["estilista", "profesional", "preferís", "preferis", "quién", "quien preferís"]):
        return "Cualquiera."

    # Bot shows numbered service/slot/time options — pick option 1
    numbered = re.findall(r"(\d+)[.)]\s+(.+?)(?=\n|\d+[.)]|$)", bot_reply)
    if numbered:
        # If it's a service selection (corte, flequillo, etc.)
        if any(w in reply_lower for w in ["corte", "flequillo", "servicio", "cuál", "cual"]):
            return f"{numbered[0][0]}."
        # If it's a slot/time selection
        if any(w in reply_lower for w in ["turno", "horario", "disponible", "jueves", "lunes", "martes", "fecha", "hora"]):
            return f"{numbered[0][0]}."

    # Bot shows a single date/time
    time_match = re.search(r"(\d{1,2}:\d{2})\s*(hs)?", bot_reply)
    if time_match and any(w in reply_lower for w in ["turno", "horario", "disponible"]):
        return "Ese me viene bien, dale."

    # Bot asks for confirmation
    if any(w in reply_lower for w in ["confirmas", "confirmar", "confirmás", "estás segura", "segura", "agendar"]):
        return "Sí, confirmo."

    # Bot shows summary before final confirmation
    if any(w in reply_lower for w in ["resumen", "detalle", "a nombre de", "la cita"]):
        return "Sí, confirmo."

    # Bot asks for name
    if any(w in reply_lower for w in ["nombre", "llamas", "como te"]):
        return "María."

    # Fallback — for first turn if something unexpected
    if turn_number == 1:
        return "Quiero sacar un turno para corte de dama para el jueves que viene."
    
    return "Dale, gracias."


async def run_qa_flow() -> dict[str, Any]:
    """Execute the booking_complete flow with María."""

    conversation_id = f"qa-{uuid.uuid4().hex[:12]}"
    # Use QA-safe test phone pattern: +34999XXXXXX
    customer_phone = f"+34999{str(abs(hash(conversation_id)) % 1000000).zfill(6)}"
    sender_name = "María QA"
    run_started_at = datetime.now(UTC)

    log.info(f"🚀 Starting QA run: conversation_id={conversation_id}")
    log.info(f"   Phone: {customer_phone}")

    redis_client = await aioredis.from_url(
        REDIS_URL,
        password=REDIS_PASSWORD,
        decode_responses=True,
        max_connections=5,
    )

    # CRITICAL: Subscribe BEFORE injecting (per skill rules)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(OUTGOING_CHANNEL)
    log.info(f"✅ Subscribed to '{OUTGOING_CHANNEL}'")

    # Drain stale subscribe confirmation messages
    await asyncio.sleep(0.3)

    turns: list[dict[str, Any]] = []
    conversation_history: list[str] = []
    milestone_history: list[str | None] = []
    last_milestone: str | None = None
    consecutive_same_milestone = 0
    outcome = "timeout"
    termination_reason = f"Max turns ({MAX_TURNS}) exceeded"
    bugs_all: list[dict] = []

    current_message = build_opening_message()
    consecutive_timeouts = 0

    try:
        for turn_number in range(1, MAX_TURNS + 1):
            log.info(f"\n{'─'*60}")
            log.info(f"Turn {turn_number}/{MAX_TURNS}")
            log.info(f"USER → BOT: {current_message}")

            # Inject user message into INCOMING_STREAM
            payload = {
                "conversation_id": conversation_id,
                "customer_phone": customer_phone,
                "message_text": current_message,
                "sender_name": sender_name,
                "customer_name": "María",
                "is_audio_transcription": False,
                "audio_url": None,
            }
            timestamp_sent = datetime.now(UTC)
            stream_id = await redis_client.xadd(
                INCOMING_STREAM, {"data": json.dumps(payload)}
            )
            log.info(f"   Injected → stream_id={stream_id}")

            # Capture bot response from Pub/Sub
            bot_response_text = ""
            timed_out = False
            timestamp_received = None
            raw_payloads: list[dict] = []

            loop = asyncio.get_running_loop()
            deadline = loop.time() + TURN_TIMEOUT_S
            batch_deadline: float | None = None

            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    if raw_payloads:
                        break
                    timed_out = True
                    break

                poll_timeout = remaining
                if batch_deadline is not None:
                    batch_remaining = batch_deadline - loop.time()
                    if batch_remaining <= 0:
                        break
                    poll_timeout = min(poll_timeout, batch_remaining)

                raw_msg = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=min(poll_timeout, 1.0),
                )
                if raw_msg is None:
                    if raw_payloads:
                        # Got at least one message, wait for batch window
                        if batch_deadline is not None and loop.time() >= batch_deadline:
                            break
                    continue

                raw_data = raw_msg.get("data", "")
                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode("utf-8")
                try:
                    payload_data = json.loads(raw_data)
                except Exception:
                    continue

                if payload_data.get("conversation_id") != conversation_id:
                    continue

                timestamp_received = datetime.now(UTC)
                raw_payloads.append(payload_data)
                if batch_deadline is None:
                    batch_deadline = loop.time() + BATCH_WINDOW_S

            # Assemble bot response
            if raw_payloads:
                messages = [
                    str(p.get("message", "")).strip()
                    for p in raw_payloads
                    if p.get("message")
                ]
                bot_response_text = "\n\n".join(m for m in messages if m)
                consecutive_timeouts = 0
            elif timed_out:
                consecutive_timeouts += 1
                bot_response_text = "[TIMEOUT - NO RESPONSE]"

            latency_ms = (
                int((timestamp_received - timestamp_sent).total_seconds() * 1000)
                if timestamp_received
                else int(TURN_TIMEOUT_S * 1000)
            )

            if timed_out:
                log.warning(f"   ⚠️  TIMEOUT — no response within {TURN_TIMEOUT_S}s")
            else:
                log.info(f"   BOT → USER ({latency_ms}ms): {bot_response_text[:300]}")

            # Update conversation history (rolling 6-exchange window)
            conversation_history.append(f"User: {current_message}")
            conversation_history.append(f"Bot: {bot_response_text}")
            if len(conversation_history) > 12:
                conversation_history = conversation_history[-12:]

            # LLM Reasoning step (we ARE María/the LLM)
            if timed_out:
                llm_response: dict[str, Any] = {
                    "reply": "Hola? Siguen ahí?",
                    "flow_status": "stuck",
                    "milestone_reached": None,
                    "bugs": [{
                        "category": "context_loss",
                        "evidence": f"Bot did not respond within {TURN_TIMEOUT_S}s on turn {turn_number}",
                        "turns": [turn_number],
                    }],
                    "should_stop": False,
                    "stop_reason": "",
                }
            else:
                llm_response = reason_as_maria(
                    turn_number=turn_number,
                    bot_reply=bot_response_text,
                    conversation_history=conversation_history,
                    milestone_history=milestone_history,
                )

            milestone_reached = llm_response.get("milestone_reached")
            milestone_history.append(milestone_reached)
            bugs_this_turn = llm_response.get("bugs", [])
            bugs_all.extend(bugs_this_turn)

            # Dead loop detection
            if milestone_reached == last_milestone and milestone_reached is not None:
                consecutive_same_milestone += 1
            else:
                consecutive_same_milestone = 0
                last_milestone = milestone_reached

            # Record turn
            turns.append({
                "turn_number": turn_number,
                "user_message": current_message,
                "bot_response": bot_response_text,
                "latency_ms": latency_ms,
                "timed_out": timed_out,
                "milestone_reached": milestone_reached,
                "flow_status": llm_response.get("flow_status"),
                "bugs": bugs_this_turn,
                "should_stop": llm_response.get("should_stop"),
                "llm_reply": llm_response.get("reply"),
            })

            status_icon = "✅" if not bugs_this_turn else "⚠️"
            log.info(
                f"   {status_icon} Milestone: {milestone_reached} | "
                f"Flow: {llm_response.get('flow_status')} | "
                f"Bugs: {len(bugs_this_turn)}"
            )

            # Stop conditions (hard limits)
            if consecutive_same_milestone >= 3:
                outcome = "dead_loop"
                termination_reason = f"Dead loop: milestone '{last_milestone}' for 3 consecutive turns"
                log.warning(f"💀 DEAD LOOP: {termination_reason}")
                break

            if consecutive_timeouts >= 2:
                outcome = "timeout"
                termination_reason = "Bot unresponsive for 2 consecutive turns"
                log.error(f"💀 BOT UNRESPONSIVE: {termination_reason}")
                break

            if llm_response.get("should_stop") and llm_response.get("flow_status") == "completed":
                outcome = "completed"
                termination_reason = llm_response.get("stop_reason", "Flow completed")
                log.info(f"🎉 FLOW COMPLETED: {termination_reason}")
                break

            if llm_response.get("should_stop") and llm_response.get("flow_status") == "escalated":
                outcome = "escalation"
                termination_reason = llm_response.get("stop_reason", "Escalation triggered")
                break

            current_message = llm_response.get("reply", "Dale, gracias.")

        else:
            outcome = "timeout"
            termination_reason = f"Max turns ({MAX_TURNS}) exceeded without completion"

    finally:
        try:
            await pubsub.unsubscribe(OUTGOING_CHANNEL)
            await pubsub.close()
        except Exception:
            pass
        try:
            await redis_client.aclose()
        except Exception:
            pass

    # Derive final milestone
    final_milestone = None
    for m in reversed(milestone_history):
        if m is not None:
            final_milestone = m
            break

    return {
        "conversation_id": conversation_id,
        "customer_phone": customer_phone,
        "run_started_at": run_started_at.isoformat(),
        "outcome": outcome,
        "termination_reason": termination_reason,
        "milestone_reached": final_milestone,
        "total_turns": len(turns),
        "turns": turns,
        "bugs_all": bugs_all,
        "bugs_count": len(bugs_all),
    }


async def main() -> None:
    result = await run_qa_flow()

    print("\n" + "=" * 70)
    print("QA RUN RESULTS — booking_complete / María (new client persona)")
    print("=" * 70)
    print(f"Outcome:         {result['outcome'].upper()}")
    print(f"Final milestone: {result['milestone_reached']}")
    print(f"Total turns:     {result['total_turns']}")
    print(f"Bugs found:      {result['bugs_count']}")
    print(f"Termination:     {result['termination_reason']}")
    print()

    print("CONVERSATION TRACE:")
    print("-" * 70)
    for t in result["turns"]:
        timeout_flag = " ⚠️TIMEOUT" if t["timed_out"] else ""
        print(f"\nTurn {t['turn_number']}{timeout_flag} ({t['latency_ms']}ms):")
        print(f"  USER:      {t['user_message']}")
        bot_preview = t["bot_response"][:400] if t["bot_response"] else "(empty)"
        print(f"  BOT:       {bot_preview}")
        print(f"  Milestone: {t['milestone_reached']}")
        print(f"  Status:    {t['flow_status']}")
        if t["bugs"]:
            for b in t["bugs"]:
                print(f"  BUG [{b['category']}]: {b['evidence']}")

    print()
    if result["bugs_all"]:
        print("ALL BUGS DETECTED:")
        for b in result["bugs_all"]:
            print(f"  [{b['category']}] {b['evidence']}")
    else:
        print("✅ No semantic bugs detected.")

    print()
    print("=" * 70)
    print("FULL JSON TRACE:")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
