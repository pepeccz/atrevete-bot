"""
QA Run R6 — Flow: indecision — Persona: luis_indecisive_client
Harness script for Atrévete Bot end-to-end test via Redis Streams + Pub/Sub.
"""

import asyncio
import json
import time
import uuid

import redis.asyncio as aioredis

# ── Config ─────────────────────────────────────────────────────────────────────
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = "9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda"

INCOMING_STREAM = "incoming_messages_stream"
OUTGOING_PUBSUB = "outgoing_messages"

CONVERSATION_ID = str(uuid.uuid4())
CONTACT_ID = 99901   # Fake test contact
ACCOUNT_ID = 1
INBOX_ID = 1

RESPONSE_TIMEOUT = 30.0   # seconds per turn

# ── Turn script per harness ─────────────────────────────────────────────────────
# Each entry is (description, message_text)
SCRIPT = [
    ("T1", "Hola, soy hombre y quiero verme más prolijo, ¿qué me recomendás?"),
]

# ── Payload builder ─────────────────────────────────────────────────────────────

def build_payload(text: str) -> dict:
    return {
        "event": "message_created",
        "message_type": "incoming",
        "content": text,
        "conversation": {
            "id": CONVERSATION_ID,
            "contact_id": CONTACT_ID,
            "account_id": ACCOUNT_ID,
            "inbox_id": INBOX_ID,
        },
        "contact": {
            "id": CONTACT_ID,
            "name": "Luis Martínez",
            "phone_number": "+34600000099",
        },
        "account": {"id": ACCOUNT_ID},
    }


async def run_flow():
    redis = aioredis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        decode_responses=True,
    )

    pubsub = redis.pubsub()

    print(f"[QA-R6] conversation_id = {CONVERSATION_ID}")
    print(f"[QA-R6] Subscribing to '{OUTGOING_PUBSUB}' BEFORE injecting...")

    # Subscribe BEFORE injecting — critical to avoid race condition
    await pubsub.subscribe(OUTGOING_PUBSUB)
    # drain the subscribe confirmation message
    await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)

    turns = []
    current_script_idx = 0
    turn_number = 0

    # Adaptive turn logic — we send T1 first, then decide based on bot replies
    harness_replies = {
        "list_shown": "1",              # Bot shows numbered service list
        "confirm_service": "Sí, quiero ese servicio para el viernes a la tarde",
        "add_ons": "Empecemos solo con el corte",
        "slot_options": "1",
        "stylist": "Cualquiera",
        "name": "Luis Martínez",
        "notes": "Sin notas",
        "confirm_appointment": "Sí, confirmo",
    }

    # Turn queue — initial turn
    pending_turns = [
        ("T1", "Hola, soy hombre y quiero verme más prolijo, ¿qué me recomendás?"),
    ]

    # States to track
    milestones = {
        "recommendation_provided": False,
        "service_selected": False,
        "date_requested": False,
        "slots_shown": False,
        "stylist_asked": False,
        "name_asked": False,
        "appointment_confirmed": False,
    }

    # Track what the last bot message was to decide next turn
    last_bot_message = ""
    max_turns = 18

    while turn_number < max_turns and pending_turns:
        label, user_msg = pending_turns.pop(0)
        turn_number += 1

        print(f"\n{'='*60}")
        print(f"[T{turn_number}] USER → {user_msg!r}")

        payload = build_payload(user_msg)
        injected_at = time.time()

        # Inject into Redis Stream
        await redis.xadd(
            INCOMING_STREAM,
            {"data": json.dumps(payload)},
        )

        # Wait for response on Pub/Sub
        agent_response = None
        deadline = time.time() + RESPONSE_TIMEOUT

        while time.time() < deadline:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg["type"] == "message":
                try:
                    data = json.loads(msg["data"])
                    # Check this message belongs to our conversation
                    conv_id = data.get("conversation_id") or data.get("conversation", {}).get("id", "")
                    if str(conv_id) == str(CONVERSATION_ID):
                        agent_response = data.get("message") or data.get("message_text") or data.get("content", "")
                        break
                    else:
                        # Not our conversation — keep waiting
                        pass
                except (json.JSONDecodeError, AttributeError):
                    pass

        elapsed_ms = int((time.time() - injected_at) * 1000)

        if agent_response is None:
            print(f"[T{turn_number}] TIMEOUT after {RESPONSE_TIMEOUT}s — no response received")
            turns.append({
                "turn_number": turn_number,
                "label": label,
                "user_message": user_msg,
                "agent_response": None,
                "response_latency_ms": int(RESPONSE_TIMEOUT * 1000),
                "status": "TIMEOUT",
            })
            # Stop — no point continuing
            break

        last_bot_message = agent_response
        print(f"[T{turn_number}] BOT  ({elapsed_ms}ms) → {agent_response[:200]!r}")

        turns.append({
            "turn_number": turn_number,
            "label": label,
            "user_message": user_msg,
            "agent_response": agent_response,
            "response_latency_ms": elapsed_ms,
            "status": "OK",
        })

        # ── Milestone detection ───────────────────────────────────────────────
        lower = agent_response.lower()

        if any(x in lower for x in ["corte caballero", "recomend", "listado", "servicio", "opcion", "opción", "1."]):
            milestones["recommendation_provided"] = True

        if any(x in lower for x in ["confirmar", "¿deseas", "quieres este servicio", "servicio seleccionado"]):
            milestones["service_selected"] = True

        if any(x in lower for x in ["fecha", "día", "cuándo", "cuando", "horario"]):
            milestones["date_requested"] = True

        if any(x in lower for x in ["disponible", "turno", "slot", "elegir", "hora", "viernes", "lunes"]):
            milestones["slots_shown"] = True

        if any(x in lower for x in ["estilista", "especialista", "profesional", "quién", "quien"]):
            milestones["stylist_asked"] = True

        if any(x in lower for x in ["nombre", "name", "cómo te llamas", "como te llamas"]):
            milestones["name_asked"] = True

        if any(x in lower for x in ["confirmado", "reservado", "cita creada", "turno confirmado", "cita confirmada"]):
            milestones["appointment_confirmed"] = True

        # ── Adaptive next turn logic ──────────────────────────────────────────
        # Decide next user message based on bot reply

        if turn_number == 1:
            # T1 sent. If bot shows numbered list → send "1"
            # If bot gives recommendation and asks to confirm → send T3 directly
            if any(x in lower for x in ["1.", "1)", "corte caballero"]):
                pending_turns.append(("T2", "1"))
            elif any(x in lower for x in ["recomend", "sugier"]):
                # Bot recommended directly, skip to T3
                pending_turns.append(("T3", "Sí, quiero ese servicio para el viernes a la tarde"))

        elif turn_number == 2:
            # T2 was "1" selecting service. Bot may ask confirmation or proceed
            if any(x in lower for x in ["confirmar", "¿deseas", "seleccionado", "escogiste"]):
                pending_turns.append(("T3", "Sí, quiero ese servicio para el viernes a la tarde"))
            elif any(x in lower for x in ["fecha", "día", "cuándo", "cuando", "horario", "add-on", "addon", "extra", "servicio adicional"]):
                # Bot skipped confirmation and asked for date, or asked for add-ons
                if any(x in lower for x in ["add-on", "addon", "extra", "servicio adicional", "algo más", "algo mas", "agregar"]):
                    pending_turns.append(("T4", "Empecemos solo con el corte"))
                else:
                    pending_turns.append(("T3", "Sí, quiero ese servicio para el viernes a la tarde"))
            else:
                # Unclear — try confirming
                pending_turns.append(("T3", "Sí, quiero ese servicio para el viernes a la tarde"))

        elif turn_number == 3:
            # T3 was "Sí, quiero ese servicio para el viernes a la tarde"
            # Bot may ask add-ons, show slots, or ask for more info
            if any(x in lower for x in ["add-on", "addon", "extra", "servicio adicional", "algo más", "algo mas", "agregar", "complemento"]):
                pending_turns.append(("T4", "Empecemos solo con el corte"))
            elif any(x in lower for x in ["1.", "1)", "disponible", "turno", "slot", "hora"]):
                pending_turns.append(("T5", "1"))
            elif any(x in lower for x in ["estilista", "especialista"]):
                pending_turns.append(("T6", "Cualquiera"))
            elif any(x in lower for x in ["nombre", "name"]):
                pending_turns.append(("T7", "Luis Martínez"))

        elif turn_number == 4:
            # T4 was "Empecemos solo con el corte" (add-on decline)
            if any(x in lower for x in ["1.", "1)", "disponible", "turno", "slot", "hora"]):
                pending_turns.append(("T5", "1"))
            elif any(x in lower for x in ["estilista", "especialista"]):
                pending_turns.append(("T6", "Cualquiera"))
            elif any(x in lower for x in ["nombre", "name"]):
                pending_turns.append(("T7", "Luis Martínez"))
            else:
                # Try slot selection
                pending_turns.append(("T5", "1"))

        elif turn_number == 5:
            # T5 was "1" for slot selection
            if any(x in lower for x in ["estilista", "especialista", "profesional"]):
                pending_turns.append(("T6", "Cualquiera"))
            elif any(x in lower for x in ["nombre", "name"]):
                pending_turns.append(("T7", "Luis Martínez"))
            elif any(x in lower for x in ["nota", "comment", "observación", "adicional"]):
                pending_turns.append(("T8", "Sin notas"))
            elif any(x in lower for x in ["confirmado", "reservado", "cita"]):
                # Already confirmed
                milestones["appointment_confirmed"] = True
            else:
                pending_turns.append(("T6", "Cualquiera"))

        elif turn_number == 6:
            # T6 was "Cualquiera" for stylist
            if any(x in lower for x in ["nombre", "name", "cómo te llamas"]):
                pending_turns.append(("T7", "Luis Martínez"))
            elif any(x in lower for x in ["nota", "comment", "observación"]):
                pending_turns.append(("T8", "Sin notas"))
            elif any(x in lower for x in ["confirmad", "reservad", "cita"]):
                milestones["appointment_confirmed"] = True
            else:
                pending_turns.append(("T7", "Luis Martínez"))

        elif turn_number == 7:
            # T7 was "Luis Martínez"
            if any(x in lower for x in ["nota", "comment", "observación", "algo más", "info adicional"]):
                pending_turns.append(("T8", "Sin notas"))
            elif any(x in lower for x in ["confirm", "reserva", "cita", "¿confirmas"]):
                pending_turns.append(("T9", "Sí, confirmo"))
            else:
                pending_turns.append(("T8", "Sin notas"))

        elif turn_number == 8:
            # T8 was "Sin notas"
            if any(x in lower for x in ["confirm", "reserva", "cita", "¿confirmas", "¿deseas confirmar"]):
                pending_turns.append(("T9", "Sí, confirmo"))
            else:
                pending_turns.append(("T9", "Sí, confirmo"))

        elif turn_number == 9:
            # T9 was "Sí, confirmo"
            if any(x in lower for x in ["confirmado", "reservado", "cita", "turno"]):
                milestones["appointment_confirmed"] = True
            # Done — no more pending turns

        else:
            # Unexpected extra turns — bot might be stuck in a loop
            print(f"[WARN] Unexpected state at turn {turn_number}, bot might be looping")

    # ── Unsubscribe and close ─────────────────────────────────────────────────
    await pubsub.unsubscribe(OUTGOING_PUBSUB)
    await pubsub.close()
    await redis.aclose()

    return {
        "scenario_id": "indecision",
        "persona_id": "luis_indecisive_client",
        "conversation_id": CONVERSATION_ID,
        "turn_count": turn_number,
        "milestones": milestones,
        "turns": turns,
    }


async def check_db():
    """Check if appointment was created in DB in the last hour."""
    import subprocess
    result = subprocess.run(
        [
            "docker", "exec", "atrevete-postgres",
            "psql", "-U", "atrevete", "-d", "atrevete_db",
            "-t", "-c",
            "SELECT count(*) FROM appointments WHERE created_at > now() - interval '1 hour';"
        ],
        capture_output=True, text=True
    )
    raw = result.stdout.strip()
    try:
        count = int(raw)
    except ValueError:
        count = -1
    return count, result.stdout, result.stderr


if __name__ == "__main__":
    trace = asyncio.run(run_flow())

    print("\n" + "="*70)
    print("QA-R6 CONVERSATION TRACE — indecision / luis_indecisive_client")
    print("="*70)
    print(f"conversation_id : {trace['conversation_id']}")
    print(f"turn_count      : {trace['turn_count']}")
    print(f"milestones      : {json.dumps(trace['milestones'], indent=2)}")
    print("\n--- FULL TRACE ---")
    for t in trace["turns"]:
        print(f"\n[T{t['turn_number']}] {t['label']} ({t.get('response_latency_ms', '?')}ms) status={t.get('status','?')}")
        print(f"  USER: {t['user_message']}")
        print(f"  BOT : {t['agent_response']}")

    # DB check
    count, raw_out, raw_err = asyncio.run(check_db())
    print("\n--- DB CHECK ---")
    print(f"Appointments created in last 1h: {count}")
    if raw_err:
        print(f"DB stderr: {raw_err}")

    # Final verdict
    m = trace["milestones"]
    appointment_in_db = count > 0
    status = "PASS" if (m["recommendation_provided"] and m["appointment_confirmed"] and appointment_in_db) else "FAIL"

    print("\n" + "="*70)
    print(f"STATUS           : {status}")
    print(f"recommendation   : {m['recommendation_provided']}")
    print(f"appointment_confirmed : {m['appointment_confirmed']}")
    print(f"appointment_in_db: {appointment_in_db} (count={count})")
    print("="*70)

    # Write results to file for capture
    with open("/tmp/qa_r6_result.json", "w") as f:
        json.dump({
            "status": status,
            "turn_count": trace["turn_count"],
            "milestones": trace["milestones"],
            "appointment_in_db": appointment_in_db,
            "db_count": count,
            "conversation_id": trace["conversation_id"],
            "turns": trace["turns"],
        }, f, indent=2, ensure_ascii=False)
    print("\nFull results saved to /tmp/qa_r6_result.json")
