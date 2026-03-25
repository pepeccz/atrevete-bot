"""
QA Round 6 — booking_complete / maria_new_client
Validates BUG-001 fix: FSM must advance through all booking steps.

Key insight: Agent uses Redis Streams and expects flat payload:
  {"conversation_id": "...", "customer_phone": "...", "message_text": "...", "sender_name": "..."}
NOT the Chatwoot webhook payload.

Responses are published to "outgoing_messages" Pub/Sub channel with:
  {"conversation_id": "...", "customer_phone": "...", "message": "..."}
"""

import asyncio
import json
import time
import uuid
from datetime import datetime, UTC

import redis.asyncio as aioredis

REDIS_URL = "redis://localhost:6379/0"
REDIS_PASSWORD = "9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda"
INCOMING_STREAM = "incoming_messages_stream"
OUTGOING_PUBSUB = "outgoing_messages"
RESPONSE_TIMEOUT = 45.0  # seconds per turn

# ---------- conversation setup ----------
CONVERSATION_ID = str(uuid.uuid4())
CUSTOMER_PHONE = "+34999000099"
SENDER_NAME = "María García"

print(f"\n{'=' * 60}")
print(f"QA-R6 booking_complete | persona: maria_new_client")
print(f"conversation_id: {CONVERSATION_ID}")
print(f"timestamp: {datetime.now(UTC).isoformat()}")
print(f"{'=' * 60}\n")


def build_payload(text: str) -> dict:
    """
    Build the CORRECT payload format that the agent expects.
    This mirrors ChatwootMessageEvent.model_dump() from api/routes/chatwoot.py.
    """
    return {
        "conversation_id": CONVERSATION_ID,
        "customer_phone": CUSTOMER_PHONE,
        "message_text": text,
        "sender_name": SENDER_NAME,
        "customer_name": SENDER_NAME,  # deprecated but kept for compatibility
        "is_audio_transcription": False,
        "audio_url": None,
    }


async def run_qa():
    r = aioredis.from_url(
        REDIS_URL,
        password=REDIS_PASSWORD,
        decode_responses=True,
        max_connections=10,
    )

    # ---------- subscribe BEFORE injecting ----------
    pubsub = r.pubsub()
    await pubsub.subscribe(OUTGOING_PUBSUB)
    # Drain the subscription confirmation message
    await asyncio.sleep(0.2)
    msg = await pubsub.get_message(timeout=1.0)
    print(f"[SETUP] Subscribed to {OUTGOING_PUBSUB} | confirm: {msg}")

    turns = []

    # ----- T1: Initial booking request -----
    # Give all info upfront to minimize clarification
    current_user_msg = "Hola, quiero un turno para corte de cabello dama el jueves que viene, sin preferencia de estilista"

    for turn_num in range(1, 16):  # max 15 turns
        t_send = time.monotonic()
        ts_utc = datetime.now(UTC).isoformat()

        # Inject into INCOMING_STREAM (correct flat payload format)
        payload = build_payload(current_user_msg)
        msg_id = await r.xadd(
            INCOMING_STREAM,
            {"data": json.dumps(payload)},
            maxlen=10000,
            approximate=True,
        )
        print(f"\n[T{turn_num}] USER → '{current_user_msg[:100]}'")
        print(f"         stream_id={msg_id}")

        # Wait for agent response on pubsub (matching our conversation_id)
        agent_response = None
        deadline = time.monotonic() + RESPONSE_TIMEOUT

        while time.monotonic() < deadline:
            msg = await pubsub.get_message(timeout=1.0)
            if msg and msg["type"] == "message":
                try:
                    data = json.loads(msg["data"])
                    if str(data.get("conversation_id")) == str(CONVERSATION_ID):
                        agent_response = data.get("message") or data.get("message_text", "")
                        break
                    else:
                        # Log other conversation IDs to confirm channel is working
                        other_id = data.get("conversation_id", "?")
                        print(f"         [pubsub] other conv: {other_id}")
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"         [pubsub] parse error: {e}")

        t_recv = time.monotonic()
        latency_ms = int((t_recv - t_send) * 1000)

        if agent_response is None:
            print(f"[T{turn_num}] ⚠️  TIMEOUT — no response in {RESPONSE_TIMEOUT}s")
            turns.append(
                {
                    "turn_number": turn_num,
                    "user_message": current_user_msg,
                    "agent_response": None,
                    "response_latency_ms": None,
                    "timeout": True,
                    "ts_utc": ts_utc,
                }
            )
            break

        agent_preview = agent_response[:200] if agent_response else ""
        print(f"[T{turn_num}] BOT  ← ({latency_ms}ms)")
        print(f"         '{agent_preview}'")

        turns.append(
            {
                "turn_number": turn_num,
                "user_message": current_user_msg,
                "agent_response": agent_response,
                "response_latency_ms": latency_ms,
                "timeout": False,
                "ts_utc": ts_utc,
            }
        )

        # ---- Check for completion ----
        resp_lower = agent_response.lower()

        completion_signals = [
            "turno confirmado",
            "cita confirmada",
            "reserva confirmada",
            "tu turno quedó",
            "¡listo",
            "quedó registrado",
            "¡reservado",
            "✅",
            "turno para el",
            "tu cita para",
            "confirmado el turno",
        ]
        if any(kw in resp_lower for kw in completion_signals):
            print(f"\n✅ [BOOKING COMPLETED] Signal detected at T{turn_num}")
            break

        if turn_num >= 15:
            print(f"\n⚠️  [MAX TURNS REACHED]")
            break

        # ---- Adaptive next user message ----
        next_msg = _decide_next_message(resp_lower, turn_num)
        current_user_msg = next_msg

    await pubsub.unsubscribe(OUTGOING_PUBSUB)
    await r.aclose()
    return turns


def _decide_next_message(resp_lower: str, turn_num: int) -> str:
    """Adaptive harness — decide next user message based on bot response."""

    # Service confirmation
    if any(
        kw in resp_lower
        for kw in [
            "¿cuál servicio",
            "qué servicio",
            "que servicio",
            "primer servicio",
            "segundo servicio",
            "confirmar servicio",
            "corte de cabello dama",
            "corte dama",
            "¿es correcto",
            "es correcto",
            "¿confirmamos el servicio",
        ]
    ):
        return "Sí, el primer servicio"

    # Add-ons
    if any(
        kw in resp_lower
        for kw in [
            "complemento",
            "add-on",
            "addon",
            "tratamiento",
            "hidratación",
            "hidratacion",
            "color adicional",
            "agregar algo",
            "¿querés agregar",
            "queres agregar",
            "servicio adicional",
            "¿algún adicional",
            "algun adicional",
            "¿querés algún",
            "queres algun",
        ]
    ):
        return "No gracias"

    # Stylist selection
    if any(
        kw in resp_lower
        for kw in [
            "estilista",
            "con quién",
            "con quien",
            "preferís",
            "preferis",
            "alguna estilista",
        ]
    ):
        return "Sin preferencia, cualquiera está bien"

    # Slot / time selection
    if any(
        kw in resp_lower
        for kw in [
            "seleccioná",
            "selecciona",
            "elegí",
            "elegi",
            "horario",
            "opción",
            "opcion",
            "1.",
            "2.",
            "3.",
            "disponible",
            "slot",
            "turno disponible",
            "podría ser",
            "podria ser",
            "cuál te",
            "cual te",
        ]
    ):
        return "1"

    # Name
    if any(
        kw in resp_lower
        for kw in [
            "nombre",
            "cómo te llamas",
            "como te llamas",
            "tu nombre",
            "¿me das tu nombre",
            "me das tu nombre",
        ]
    ):
        return "María García"

    # Notes
    if any(
        kw in resp_lower
        for kw in [
            "nota",
            "notas",
            "algún comentario",
            "comentario",
            "¿alguna nota",
            "alguna nota",
        ]
    ):
        return "Sin notas"

    # Confirmation
    if any(
        kw in resp_lower
        for kw in [
            "confirmar",
            "confirmás",
            "confirmas",
            "¿confirmamos",
            "¿todo bien",
            "todo bien",
            "¿procedo",
            "procedo",
            "¿está bien",
            "esta bien",
            "¿lo confirmamos",
            "lo confirmamos",
        ]
    ):
        return "Sí, confirmo"

    # Greeting without action
    if (
        any(
            kw in resp_lower
            for kw in [
                "¡hola",
                "hola,",
                "bienvenid",
                "puedo ayudarte",
                "¿en qué te puedo",
                "en que te puedo",
            ]
        )
        and turn_num == 1
    ):
        return "Quiero sacar un turno para corte de cabello dama el jueves que viene"

    # Generic affirmative for anything else
    return "Sí"


async def check_db():
    """Check PostgreSQL for recent appointments."""
    import subprocess

    result = subprocess.run(
        [
            "docker",
            "exec",
            "atrevete-postgres",
            "psql",
            "-U",
            "atrevete",
            "-d",
            "atrevete_db",
            "-t",
            "-c",
            "SELECT count(*) FROM appointments WHERE created_at > now() - interval '1 hour';",
        ],
        capture_output=True,
        text=True,
    )
    count_str = result.stdout.strip()
    try:
        count = int(count_str)
    except ValueError:
        count = -1
    return count, result.stdout, result.stderr


async def check_logs_for_steps():
    """Grep agent logs for booking_step progression."""
    import subprocess

    result = subprocess.run(
        ["docker", "logs", "atrevete-agent", "--tail", "500"],
        capture_output=True,
        text=True,
    )
    logs = result.stdout + result.stderr

    steps_seen = []
    step_keywords = [
        "service_selection",
        "add_ons",
        "stylist_selection",
        "slot_selection",
        "confirmation",
        "COMPLETED",
        "booking_step",
        "_advance_step",
        "book()",
        "appointment_created",
        "FSMResult",
        "AgenticLoopResult",
        "synthetic",
    ]

    for kw in step_keywords:
        if kw in logs:
            matching_lines = [l for l in logs.split("\n") if kw in l]
            steps_seen.append(
                {
                    "keyword": kw,
                    "count": len(matching_lines),
                    "sample": matching_lines[-1][:200] if matching_lines else "",
                }
            )

    # Extract the relevant section of logs for our conversation
    conv_lines = [l for l in logs.split("\n") if CONVERSATION_ID in l]

    return steps_seen, logs[-4000:], conv_lines


async def main():
    start = time.monotonic()

    # Run the conversation
    turns = await run_qa()

    total_time = time.monotonic() - start

    # Check DB
    db_count, db_stdout, db_stderr = await check_db()

    # Check agent logs
    steps_seen, log_tail, conv_lines = await check_logs_for_steps()

    # ---- Evaluate results ----
    completed_turns = [t for t in turns if not t.get("timeout")]
    timed_out = any(t.get("timeout") for t in turns)

    last_response = completed_turns[-1]["agent_response"] if completed_turns else ""
    booking_confirmed = (
        any(
            kw in (last_response or "").lower()
            for kw in ["confirmado", "tu turno", "reserva", "listo", "quedó", "✅"]
        )
        if last_response
        else False
    )

    appointment_in_db = db_count > 0

    # Milestones
    all_responses = " ".join(t.get("agent_response", "") or "" for t in completed_turns).lower()
    milestones_hit = []
    milestone_checks = {
        "greeting_done": ["hola", "bienvenid", "saludos", "cómo puedo"],
        "service_resolved": ["corte de cabello", "corte dama", "servicio confirmado"],
        "addons_handled": [
            "add-on",
            "complemento",
            "tratamiento",
            "no gracias",
            "sin adicionales",
            "ningún adicional",
        ],
        "stylist_resolved": ["estilista", "cualquier", "sin preferencia"],
        "slot_resolved": ["horario", "disponible", "seleccionaste", "1.", "turno para", "jueves"],
        "confirmation_done": ["confirmar", "confirmo", "confirmado", "procedemos"],
        "booking_completed": [
            "turno confirmado",
            "cita confirmada",
            "reserva confirmada",
            "quedó registrado",
            "✅",
        ],
    }
    for milestone, keywords in milestone_checks.items():
        if any(kw in all_responses for kw in keywords):
            milestones_hit.append(milestone)

    # Determine pass/fail
    if timed_out and len(completed_turns) == 0:
        status = "FAIL"
        fail_reason = "TIMEOUT_T1"
    elif timed_out:
        status = "FAIL"
        fail_reason = f"TIMEOUT_T{turns[-1]['turn_number']}"
    elif appointment_in_db:
        status = "PASS"
        fail_reason = None
    elif booking_confirmed:
        status = "PARTIAL"  # Response said confirmed but not in DB yet
        fail_reason = "NOT_IN_DB"
    else:
        status = "FAIL"
        fail_reason = "NO_CONFIRMATION"

    # ---- Print summary ----
    print(f"\n{'=' * 60}")
    print(f"QA-R6 RESULTS — booking_complete / maria_new_client")
    print(f"{'=' * 60}")
    print(f"STATUS          : {status}" + (f" ({fail_reason})" if fail_reason else ""))
    print(f"Turn count      : {len(completed_turns)}/{len(turns)} (timeout={timed_out})")
    print(f"Total time      : {total_time:.1f}s")
    print(f"Booking confirmed (response): {booking_confirmed}")
    print(f"Appointment in DB (last 1h) : {appointment_in_db} (count={db_count})")
    print(f"\nMilestones hit  : {milestones_hit}")

    print(f"\n--- BOOKING STEP PROGRESSION ---")
    for s in steps_seen:
        print(f"  [{s['keyword']}] × {s['count']}  | last: {s['sample'][:150]}")

    print(f"\n--- LOGS FOR THIS CONVERSATION ({len(conv_lines)} lines) ---")
    for line in conv_lines[-30:]:
        print(f"  {line[:250]}")

    print(f"\n--- CONVERSATION TRACE ---")
    for t in turns:
        r_preview = (t.get("agent_response") or "")[:200]
        lat = t.get("response_latency_ms")
        timeout_flag = "⚠️ TIMEOUT" if t.get("timeout") else f"{lat}ms"
        print(f"\n  T{t['turn_number']} USER: '{t['user_message'][:100]}'")
        print(f"  T{t['turn_number']} BOT  ({timeout_flag}): '{r_preview}'")

    print(f"\n--- LAST 4000 CHARS OF AGENT LOGS ---")
    print(log_tail)

    # ---- Return structured result ----
    return {
        "status": status,
        "fail_reason": fail_reason,
        "turn_count": len(completed_turns),
        "timed_out": timed_out,
        "milestones_hit": milestones_hit,
        "appointment_in_db": appointment_in_db,
        "db_appointment_count": db_count,
        "booking_step_progression": [s["keyword"] for s in steps_seen],
        "booking_step_details": steps_seen,
        "conversation_trace": turns,
        "total_time_s": round(total_time, 1),
    }


if __name__ == "__main__":
    result = asyncio.run(main())
    print(f"\n\n=== FINAL JSON RESULT ===")
    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
