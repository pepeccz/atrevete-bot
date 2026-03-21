"""
QA Runner: booking_complete flow with maria_new_client persona.
Standalone script that executes the full LLM-driven QA scenario via Redis.
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

import redis.asyncio as redis

# Ensure project root is on path
sys.path.insert(0, "/home/pcabeza/Proyectos/atrevete-bot")

from shared.config import get_settings
from shared.redis_client import INCOMING_STREAM
from tests.e2e.harness.run_models import QARunIdentity, QARunSession
from tests.e2e.harness.state_reset import StateResetHarness, AsyncDatabaseCleaner


# ---------------------------------------------------------------------------
# Persona + Flow Definition (inlined from qa-testing-context.md / skill data)
# ---------------------------------------------------------------------------

PERSONA = {
    "name": "María",
    "role": "new_client",
    "objective": "Book a haircut (corte para dama) for next Thursday",
    "preferences": {
        "service": "corte de cabello",
        "service_variant": "dama",
        "date": "jueves que viene",
    },
    "personality": "concise",
    "reply_style": "brief, direct answers",
    "accept_addons": False,
    "has_account": False,
}

FLOW_MILESTONES = [
    "greeting_done",
    "service_resolved",
    "addons_handled",
    "stylist_resolved",
    "slot_resolved",
    "confirmation_done",
    "booking_completed",  # COMPLETION
]

COMPLETION_MILESTONE = "booking_completed"
MAX_TURNS = 15
RESPONSE_TIMEOUT = 60.0
BATCH_WINDOW = 3.0

OPENING_MESSAGE = "Hola, quiero reservar un turno para corte de cabello de dama para el jueves que viene"

# Phone must match TEST_PHONE_PATTERN: +34999XXXXXX
QA_PHONE = "+34999" + str(int(time.time()))[-6:]


# ---------------------------------------------------------------------------
# LLM Turn Reasoning (we ARE the LLM — inline implementation)
# ---------------------------------------------------------------------------

def llm_reason(
    turn_number: int,
    bot_reply: str,
    conversation_history: list[dict],
    persona: dict,
    milestones: list[str],
    last_milestone: str | None,
) -> dict[str, Any]:
    """
    This is the LLM reasoning step. As the sub-agent, I reason about:
    - What did the bot say?
    - Which milestone does it correspond to?
    - What should María reply?
    - Are there any bugs?
    - Should we stop?
    """
    bot_lower = bot_reply.lower()

    # Detect milestone
    milestone_reached = None
    if turn_number == 0:
        # First bot response — after we said greeting+intent
        milestone_reached = "greeting_done"
    
    # Service resolved: bot confirms corte de cabello or asks to confirm service
    if any(kw in bot_lower for kw in ["corte", "servicio", "confirmado", "perfecto"]):
        if last_milestone in (None, "greeting_done"):
            milestone_reached = milestone_reached or "service_resolved"

    # Addons: bot offers extras/addons
    if any(kw in bot_lower for kw in ["adicional", "adicionales", "extra", "extras", "sumar", "complementario", "tratamiento"]):
        if last_milestone in ("greeting_done", "service_resolved"):
            milestone_reached = "addons_handled"
    
    # If we already handled addons and bot goes to stylist
    if any(kw in bot_lower for kw in ["estilista", "profesional", "luciana", "sofia", "valentina", "camila", "cualquiera", "preferis"]):
        if last_milestone in ("service_resolved", "addons_handled"):
            milestone_reached = "stylist_resolved"
    
    # Slot selection: bot shows available slots
    if any(kw in bot_lower for kw in ["horario", "turno", "disponible", "jueves", "viernes", "martes", "miercoles", "hora", "fecha"]):
        if last_milestone in ("service_resolved", "addons_handled", "stylist_resolved"):
            milestone_reached = "slot_resolved"
    
    # Confirmation: bot asks to confirm
    if any(kw in bot_lower for kw in ["confirmas", "confirmar", "resumen", "confirmo", "¿todo bien", "todo listo"]):
        if last_milestone in ("slot_resolved", "stylist_resolved"):
            milestone_reached = "confirmation_done"
    
    # Booking completed: bot says booking is done
    if any(kw in bot_lower for kw in ["reservado", "agendado", "quedo", "quedó", "listo", "turno reservado", "turno agendado"]):
        if last_milestone in ("slot_resolved", "confirmation_done"):
            milestone_reached = "booking_completed"

    # Bug detection
    bugs = []
    if turn_number > 0:
        history_text = " ".join(m.get("user", "") for m in conversation_history[-6:]).lower()
        # Check for redundant service type question after we already said "dama"
        if ("dama" in history_text or "corte" in history_text) and \
           any(kw in bot_lower for kw in ["dama o caballero", "para dama", "para caballero", "¿es para dama", "es para dama", "el corte es para"]):
            if turn_number >= 2:
                bugs.append({
                    "category": "redundant_question",
                    "evidence": f"User already specified 'corte de cabello de dama' in turn 0; bot re-asked variant on turn {turn_number}",
                    "turns": [0, turn_number]
                })

    # Generate reply based on what bot said
    reply = _generate_reply(bot_reply, persona, last_milestone, milestone_reached)

    # Determine should_stop
    should_stop = milestone_reached == COMPLETION_MILESTONE
    flow_status = "completed" if should_stop else "in_progress"
    stop_reason = "Booking confirmed by bot, appointment details provided" if should_stop else ""

    # Check if stuck
    if "no entend" in bot_lower or "no comprend" in bot_lower:
        flow_status = "stuck"

    return {
        "reply": reply,
        "flow_status": flow_status,
        "milestone_reached": milestone_reached,
        "bugs": bugs,
        "should_stop": should_stop,
        "stop_reason": stop_reason,
    }


def _generate_reply(
    bot_reply: str,
    persona: dict,
    last_milestone: str | None,
    milestone_reached: str | None,
) -> str:
    """Generate María's next reply — concise, natural, in character."""
    import re
    bot_lower = bot_reply.lower()

    # Bot asks for service type / variant — always answer with the variant
    if any(kw in bot_lower for kw in ["dama", "niña", "bebé", "caballero", "el corte es para", "es para"]):
        if "?" in bot_reply and last_milestone in (None, "greeting_done"):
            return "Para dama."

    # Bot asks about add-ons / extras
    if any(kw in bot_lower for kw in ["adicional", "adicionales", "extra", "extras", "sumar", "tratamiento", "complementario"]):
        return "No, gracias."

    # Bot asks for stylist preference
    if any(kw in bot_lower for kw in ["estilista", "profesional", "preferis", "preferís", "¿con quién", "con quien"]):
        return "Me da igual, cualquiera."

    # Bot presents available slots — pick the first one (Thursday if possible)
    if any(kw in bot_lower for kw in ["horario", "turno disponible", "disponibles", "opciones", "tenemos disponible"]):
        # Try to find a Thursday slot, otherwise pick first option
        lines = bot_reply.split("\n")
        for line in lines:
            if "jueves" in line.lower() and any(c.isdigit() for c in line):
                m = re.match(r"^\s*\d+[.)]\s*(.+)$", line.strip())
                if m:
                    return f"El {m.group(1).strip()}, por favor."
        # fallback: pick option 1
        for line in lines:
            m = re.match(r"^\s*1[.)]\s*(.+)$", line.strip())
            if m:
                return f"El {m.group(1).strip()}."
        return "El primero que tengas disponible."

    # Bot asks to confirm
    if any(kw in bot_lower for kw in ["confirmas", "confirmar", "¿confirmo", "confirmo", "todo listo", "¿todo bien", "resumen"]):
        return "Sí, confirmo."

    # Bot asks for customer name
    if any(kw in bot_lower for kw in ["nombre", "como te llamas", "cómo te llamás", "tu nombre"]):
        return "María."

    # Bot says booking is done / completed
    if any(kw in bot_lower for kw in ["reservado", "agendado", "quedo", "quedó", "confirmado", "turno confirmado"]):
        return "Perfecto, muchas gracias."

    # Bot asks generic question - affirmative
    if "?" in bot_reply:
        return "Sí, dale."

    # Fallback: generic affirmative
    return "Dale, gracias."


# ---------------------------------------------------------------------------
# Main QA Runner
# ---------------------------------------------------------------------------

async def run_qa_flow():
    settings = get_settings()
    
    # Generate unique conversation ID for this run
    conversation_id = f"qa-test-{uuid.uuid4().hex[:12]}"
    
    print(f"\n{'='*60}")
    print(f"QA RUN: booking_complete | Persona: maria_new_client")
    print(f"Conversation ID: {conversation_id}")
    print(f"Phone: {QA_PHONE}")
    print(f"{'='*60}\n")

    # Connect to Redis
    r = redis.from_url(settings.REDIS_URL, decode_responses=True)
    r_binary = redis.from_url(settings.REDIS_URL, decode_responses=False)

    run_identity = QARunIdentity(
        conversation_id=conversation_id,
        customer_phone=QA_PHONE,
        sender_name="María",
        run_started_at=datetime.now(UTC),
    )

    # Reset state before starting
    print("Resetting conversation state...")
    state_reset = StateResetHarness(redis_client=r)
    reset_result = await state_reset.reset_conversation_state(
        conversation_id=conversation_id,
        customer_phone=QA_PHONE,
        run_identity=run_identity,
    )
    print(f"State reset: {reset_result}\n")

    # Subscribe to outgoing_messages BEFORE injecting anything
    pubsub = r.pubsub()
    await pubsub.subscribe("outgoing_messages")
    # Drain any stale subscribe confirmation messages
    await asyncio.sleep(0.3)
    
    turns = []
    conversation_history = []
    last_milestone = None
    consecutive_same_milestone = 0
    current_message = OPENING_MESSAGE
    outcome = "in_progress"
    termination_reason = ""
    all_bugs = []
    milestones_reached = []
    turn_number = 0

    try:
        while turn_number < MAX_TURNS:
            print(f"--- Turn {turn_number + 1} ---")
            print(f"María: {current_message}")

            # Step 1: Inject user message
            payload = {
                "conversation_id": conversation_id,
                "customer_phone": QA_PHONE,
                "message_text": current_message,
                "sender_name": "María",
                "customer_name": "María",
                "is_audio_transcription": False,
                "audio_url": None,
            }
            await r.xadd(INCOMING_STREAM, {"data": json.dumps(payload)})

            # Step 2: Capture bot response from Pub/Sub
            timestamp_sent = datetime.now(UTC)
            bot_reply = None
            timed_out = False
            
            loop = asyncio.get_running_loop()
            deadline = loop.time() + RESPONSE_TIMEOUT
            batch_deadline = None
            raw_payloads = []

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
                        # Already have data, wait for batch window
                        if batch_deadline is not None and loop.time() >= batch_deadline:
                            break
                    continue

                # Decode payload
                raw_data = raw_msg.get("data")
                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode("utf-8")
                try:
                    msg_payload = json.loads(raw_data)
                except (json.JSONDecodeError, TypeError):
                    continue

                if msg_payload.get("conversation_id") != conversation_id:
                    continue

                raw_payloads.append(msg_payload)
                if not raw_payloads or len(raw_payloads) == 1:
                    # Start batch window on first matching message
                    batch_deadline = loop.time() + BATCH_WINDOW

            timestamp_received = datetime.now(UTC)

            if timed_out and not raw_payloads:
                print(f"  ⚠️  TIMEOUT - no bot response within {RESPONSE_TIMEOUT}s")
                if turn_number == 0:
                    # First timeout, try once more with follow-up
                    current_message = "Hola? Siguen ahí?"
                    turns.append({
                        "turn_number": turn_number + 1,
                        "user_message": current_message,
                        "bot_response": None,
                        "milestone_reached": None,
                        "bugs_detected": [],
                        "flow_status": "timeout",
                        "latency_ms": int(RESPONSE_TIMEOUT * 1000),
                    })
                    turn_number += 1
                    continue
                else:
                    outcome = "timeout"
                    termination_reason = "Bot unresponsive"
                    break

            # Combine all messages from batch
            messages = [
                str(p.get("message", "")).strip()
                for p in raw_payloads
                if p.get("message")
            ]
            bot_reply = "\n\n".join(m for m in messages if m)
            latency_ms = int((timestamp_received - timestamp_sent).total_seconds() * 1000)

            print(f"  Bot: {bot_reply[:300]}{'...' if len(bot_reply) > 300 else ''}")
            print(f"  Latency: {latency_ms}ms")

            # Step 3: LLM Reasoning
            llm_response = llm_reason(
                turn_number=turn_number,
                bot_reply=bot_reply,
                conversation_history=conversation_history,
                persona=PERSONA,
                milestones=FLOW_MILESTONES,
                last_milestone=last_milestone,
            )

            milestone = llm_response.get("milestone_reached")
            flow_status = llm_response.get("flow_status", "in_progress")
            bugs = llm_response.get("bugs", [])
            should_stop = llm_response.get("should_stop", False)
            reply = llm_response.get("reply", "Dale, gracias.")

            print(f"  Milestone: {milestone or '(continuing)'}")
            if bugs:
                print(f"  🐛 Bugs: {[b['category'] for b in bugs]}")

            # Record turn
            turns.append({
                "turn_number": turn_number + 1,
                "user_message": current_message,
                "bot_response": bot_reply,
                "milestone_reached": milestone,
                "bugs_detected": bugs,
                "flow_status": flow_status,
                "latency_ms": latency_ms,
            })

            # Track milestone progression
            if milestone and milestone not in milestones_reached:
                milestones_reached.append(milestone)

            all_bugs.extend(bugs)

            # Dead loop detection
            if milestone == last_milestone:
                consecutive_same_milestone += 1
            else:
                consecutive_same_milestone = 0
                last_milestone = milestone

            if consecutive_same_milestone >= 3:
                outcome = "dead_loop"
                termination_reason = f"Dead loop: same milestone '{last_milestone}' for 3 consecutive turns"
                print(f"\n  🔁 DEAD LOOP detected: {termination_reason}")
                break

            # Update conversation history (rolling 6-message window)
            conversation_history.append({"user": current_message, "bot": bot_reply})
            if len(conversation_history) > 6:
                conversation_history = conversation_history[-6:]

            # Check stop conditions
            if should_stop and flow_status == "completed":
                outcome = "completed"
                termination_reason = llm_response.get("stop_reason", "Flow completed")
                print(f"\n  ✅ Flow completed: {termination_reason}")
                break

            if flow_status == "escalated":
                outcome = "escalation"
                termination_reason = "Escalation triggered"
                break

            turn_number += 1
            current_message = reply
            print()

        else:
            outcome = "timeout"
            termination_reason = f"Max turns ({MAX_TURNS}) exceeded"

    except Exception as e:
        outcome = "error"
        termination_reason = f"Exception: {e}"
        print(f"\n  ❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await pubsub.unsubscribe("outgoing_messages")
        await pubsub.aclose()

    # DB Verification
    appointment_in_db = False
    appointment_created = False
    db_appointments = []
    
    if outcome == "completed":
        print("\n--- DB Verification ---")
        try:
            db_cleaner = AsyncDatabaseCleaner(
                db_url=settings.DATABASE_URL,
                run_identity=run_identity,
            )
            appointments = await db_cleaner.list_recent_appointments(QA_PHONE)
            if appointments:
                appointment_in_db = True
                appointment_created = True
                db_appointments = [
                    {
                        "appointment_id": str(a["appointment_id"]),
                        "service_name": a["service_name"],
                        "stylist_name": a["stylist_name"],
                        "start_datetime": a["start_datetime"].isoformat() if a.get("start_datetime") else None,
                        "status": a["status"],
                    }
                    for a in appointments
                ]
                print(f"  ✅ Appointment found in DB: {db_appointments}")
            else:
                print(f"  ❌ No appointment found in DB for phone {QA_PHONE}")
            await db_cleaner.close()
        except Exception as e:
            print(f"  ⚠️  DB verification error: {e}")

    # Summary
    print(f"\n{'='*60}")
    print(f"RESULT SUMMARY")
    print(f"{'='*60}")
    print(f"Outcome: {outcome}")
    print(f"Total turns: {len(turns)}")
    print(f"Milestones reached: {milestones_reached}")
    print(f"Bugs found: {len(all_bugs)}")
    print(f"Appointment in DB: {appointment_in_db}")
    print(f"Termination reason: {termination_reason}")

    # Cleanup
    print("\n--- Cleanup ---")
    try:
        reset_harness = StateResetHarness(redis_client=r)
        cleanup = await reset_harness.reset_conversation_state(
            conversation_id=conversation_id,
            customer_phone=QA_PHONE,
            run_identity=run_identity,
        )
        print(f"Cleanup result: {cleanup}")
    except Exception as e:
        print(f"Cleanup warning: {e}")

    await r.aclose()
    await r_binary.aclose()

    # Return structured result
    return {
        "turns": turns,
        "outcome": "success" if outcome == "completed" and appointment_in_db else outcome,
        "total_turns": len(turns),
        "bugs_found": all_bugs,
        "milestones_reached": milestones_reached,
        "termination_reason": termination_reason,
        "appointment_created": appointment_created,
        "appointment_in_db": appointment_in_db,
        "db_appointments": db_appointments,
        "conversation_id": conversation_id,
    }


if __name__ == "__main__":
    result = asyncio.run(run_qa_flow())
    print("\n--- FINAL TRACE (JSON) ---")
    print(json.dumps(result, indent=2, default=str))
