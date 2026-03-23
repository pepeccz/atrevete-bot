"""
QA Round 9 — Flow: indecision | Persona: luis_indecisive_client
Harness: R1-R8 lessons incorporated
"""

import asyncio
import json
import time
import uuid
import sys
import os

import redis.asyncio as redis

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
REDIS_PASSWORD = "9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda"
REDIS_URL = f"redis://:{REDIS_PASSWORD}@localhost:6379/0"
INCOMING_STREAM = "incoming_messages_stream"
OUTGOING_PUBSUB_CHANNEL = "outgoing_messages"
RESPONSE_TIMEOUT = 30.0  # seconds per turn

# ─────────────────────────────────────────
# PAYLOAD BUILDER
# ─────────────────────────────────────────
def build_payload(conversation_id: str, message: str, contact_id: str) -> dict:
    """Build the exact shape the agent expects.

    Critical fields (from agent/main.py lines 414-417):
      - message_text  ← what the agent reads (NOT 'message')
      - customer_phone ← used for Chatwoot delivery
      - sender_name   ← stored as pending_whatsapp_name
    """
    return {
        "conversation_id": conversation_id,
        "message_text": message,           # CRITICAL: agent reads message_text
        "customer_phone": "+34600000099",  # CRITICAL: must not be None
        "sender_name": "Luis",             # pending_whatsapp_name
        "source": "whatsapp",
        "message_type": "incoming",
        "channel": "Channel::Whatsapp",
        "account_id": "12345",
        "inbox_id": "67890",
    }


# ─────────────────────────────────────────
# HARNESS SCRIPT — R1-R8 lessons
# ─────────────────────────────────────────
SCRIPT = [
    # T1 — greeting + recommendation request
    {
        "turn": 1,
        "message": "Hola, soy hombre y quiero verme más prolijo, ¿qué me recomendás?",
        "condition": "always",
        "milestone": "greeting_done + discovery_started",
    },
    # T2 — choose service by name (not number)
    {
        "turn": 2,
        "message_if_list": "corte caballero",        # if numbered list shown
        "message_default": "Quiero el corte caballero",
        "condition": "service_list_or_default",
        "milestone": "service_resolved",
    },
    # T3 — confirm service if asked
    {
        "turn": 3,
        "message": "Sí, quiero ese servicio",
        "condition": "confirm_service",
        "milestone": "service_confirmed",
    },
    # T4 — decline add-ons
    {
        "turn": 4,
        "message": "No, solo el corte",
        "condition": "addons_offered",
        "milestone": "addons_handled",
    },
    # T5 — pick any stylist
    {
        "turn": 5,
        "message": "Cualquiera que esté disponible",
        "condition": "stylist_asked",
        "milestone": "stylist_resolved",
    },
    # T6 — pick slot (first available OR "1" if numbered list)
    {
        "turn": 6,
        "message_if_numbered": "1",
        "message_default": "El primer horario disponible que tengan",
        "condition": "slot_asked",
        "milestone": "slot_resolved",
    },
    # T7 — provide name
    {
        "turn": 7,
        "message": "Luis Martínez",
        "condition": "name_asked",
        "milestone": "customer_name",
    },
    # T8 — no notes
    {
        "turn": 8,
        "message": "Sin notas",
        "condition": "notes_asked",
        "milestone": "notes_handled",
    },
    # T9 — confirm booking
    {
        "turn": 9,
        "message": "Sí, confirmo",
        "condition": "confirmation_shown",
        "milestone": "confirmation_done",
    },
]


def detect_context(response: str) -> str:
    """Detect what the bot is asking/showing to decide next turn."""
    r = response.lower()

    # Numbered slot list (e.g., "1.", "1)", "1 -")
    has_numbered = any(f"{i}." in r or f"{i})" in r or f"{i} -" in r for i in range(1, 8))

    # Booking complete — highest priority
    if "reserva" in r and ("exitosa" in r or "confirmada" in r or "agendada" in r or "confirmado" in r):
        return "booking_complete"
    if "cita ha sido confirmada" in r or "cita confirmada" in r:
        return "booking_complete"

    # Booking tool error — stuck state
    if "problema al intentar reservar" in r or "herramienta para agendar no está funcionando" in r:
        return "booking_error"

    # Confirmation request
    if "¿confirmamos" in r or "¿confirmo" in r or "¿está todo bien" in r or "¿confirmás" in r:
        return "confirmation"
    if "confirmar" in r and ("la reserva" in r or "tu cita" in r or "¿sí" in r or "¿no" in r):
        return "confirmation"
    # Cancel confirmation guard
    if "¿seguro que quieres cancelar" in r:
        return "cancel_guard"
    # Notes (must be before name since notes ask can follow slot)
    if "nota" in r or "aclaración" in r or "comentario" in r or "algo más que deba saber" in r:
        return "notes"
    # Name collection
    if "nombre" in r or "cómo te llamas" in r or "cómo te llamás" in r or "tu nombre" in r:
        return "name"
    # Numbered slots
    if has_numbered and ("horario" in r or "disponible" in r or "lunes" in r or "martes" in r
                          or "miércoles" in r or "jueves" in r or "viernes" in r):
        return "numbered_slots"
    # Slot confirmation (bot showed a single slot and asks "¿Te viene bien?")
    if ("te viene bien" in r or "te parece bien" in r or "¿quieres que te agende" in r) and "horario" in r:
        return "confirmation"
    # General slot ask
    if "horario" in r or "qué día" in r or "cuándo" in r or "fecha" in r or "disponib" in r:
        return "slot"
    # Stylist
    if "estilista" in r or "con quién" in r or "peluquero" in r or "peluquera" in r:
        return "stylist"
    # Add-ons — check BEFORE confirm_service to avoid false positives
    if "barba" in r and ("combinar" in r or "add" in r or "complemento" in r or "añadir" in r or "look completo" in r):
        return "addons"
    if "añadir" in r and ("servicio" in r or "complemento" in r):
        return "addons"
    # Service confirm
    if ("corte" in r or "servicio" in r) and ("¿quieres que te agende" in r or "¿lo agenda" in r or "elegid" in r):
        return "confirm_service"
    # Service list
    if "servicio" in r and ("1." in r or "2." in r or "elegí" in r or "cuál" in r):
        return "service_list"
    return "other"


async def wait_for_response(pubsub, conversation_id: str, timeout: float) -> tuple[str | None, float]:
    """Wait for a matching outgoing_messages response for this conversation."""
    start = time.monotonic()
    while (time.monotonic() - start) < timeout:
        try:
            msg = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=1.0)
        except asyncio.TimeoutError:
            continue

        if msg is None:
            await asyncio.sleep(0.05)
            continue

        if msg["type"] != "message":
            continue

        try:
            data = json.loads(msg["data"])
        except (json.JSONDecodeError, TypeError):
            continue

        # Match by conversation_id
        if str(data.get("conversation_id", "")) == str(conversation_id):
            latency_ms = (time.monotonic() - start) * 1000
            # Agent uses "message" key (not "message_text")
            agent_text = data.get("message") or data.get("message_text") or str(data)
            return agent_text, latency_ms

    return None, (time.monotonic() - start) * 1000


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
async def run_qa() -> dict:
    conversation_id = str(uuid.uuid4())
    contact_id = str(uuid.uuid4())
    print(f"\n{'='*60}")
    print(f"QA Round 9 — indecision / luis_indecisive_client")
    print(f"conversation_id: {conversation_id}")
    print(f"{'='*60}\n")

    client = redis.from_url(REDIS_URL, decode_responses=True)

    # ── Subscribe BEFORE sending anything ──
    pubsub = client.pubsub()
    await pubsub.subscribe(OUTGOING_PUBSUB_CHANNEL)
    # Drain the subscribe confirmation message
    await asyncio.sleep(0.3)

    turns = []
    milestones_hit = []
    booking_complete = False
    turn_count = 0

    # ── Dynamic harness: up to 18 turns ──
    # We run a decision loop: decide message based on last bot response,
    # inject it, wait, record.

    last_context = "start"
    last_response = ""

    # Determine next message using the pre-defined script + context detection
    script_idx = 0  # pointer into SCRIPT

    for turn_num in range(1, 19):
        # Decide what to send
        if turn_num == 1:
            user_msg = SCRIPT[0]["message"]
        else:
            ctx = detect_context(last_response)

            if ctx == "booking_complete":
                print(f"  >> Bot confirmed booking — stopping at turn {turn_num - 1}")
                booking_complete = True
                break

            # Map context to message
            if ctx == "service_list":
                user_msg = "corte caballero"
            elif ctx == "confirm_service":
                user_msg = "Sí, quiero ese servicio"
            elif ctx == "addons":
                user_msg = "No, solo el corte"
            elif ctx == "stylist":
                user_msg = "Cualquiera que esté disponible"
            elif ctx == "numbered_slots":
                user_msg = "1"
            elif ctx == "slot":
                user_msg = "El primer horario disponible que tengan"
            elif ctx == "name":
                user_msg = "Luis Martínez"
            elif ctx == "notes":
                user_msg = "Sin notas, gracias"
            elif ctx == "confirmation":
                user_msg = "Sí, confirmo"
            elif ctx == "cancel_guard":
                # Bot asked "¿Seguro que quieres cancelar?" — say NO to keep booking
                user_msg = "No, quiero continuar con la reserva"
            elif ctx == "booking_error":
                # Bot is stuck with a booking error — try to go back to slot selection
                user_msg = "Por favor, intenta de nuevo con el primer horario disponible"
            else:
                # Fallback — advance script if possible
                script_idx = min(script_idx + 1, len(SCRIPT) - 1)
                entry = SCRIPT[script_idx]
                user_msg = entry.get("message") or entry.get("message_default", "")

        turn_count = turn_num
        payload = build_payload(conversation_id, user_msg, contact_id)

        print(f"[T{turn_num}] USER → {user_msg!r}")

        # Inject into INCOMING_STREAM
        inject_start = time.monotonic()
        await client.xadd(
            INCOMING_STREAM,
            {"data": json.dumps(payload)},
            maxlen=10000,
            approximate=True,
        )

        # Wait for response
        agent_text, latency_ms = await wait_for_response(pubsub, conversation_id, RESPONSE_TIMEOUT)

        if agent_text is None:
            print(f"  TIMEOUT after {RESPONSE_TIMEOUT}s — no response received")
            turns.append({
                "turn_number": turn_num,
                "user_message": user_msg,
                "agent_response": "TIMEOUT",
                "response_latency_ms": RESPONSE_TIMEOUT * 1000,
            })
            break

        print(f"  BOT  ← {agent_text[:200]!r} ({latency_ms:.0f}ms)")
        turns.append({
            "turn_number": turn_num,
            "user_message": user_msg,
            "agent_response": agent_text,
            "response_latency_ms": round(latency_ms),
        })

        last_response = agent_text
        last_context = detect_context(agent_text)

        # Track milestones
        al = agent_text.lower()
        if turn_num == 1 and ("hola" in al or "bienvenid" in al or "recomend" in al or "maite" in al):
            if "greeting_done" not in milestones_hit:
                milestones_hit.append("greeting_done")
        if "recomend" in al and "recommendation_given" not in milestones_hit:
            milestones_hit.append("recommendation_given")
        if last_context in ("addons", "stylist", "slot", "numbered_slots", "name", "notes", "confirmation") and "service_resolved" not in milestones_hit:
            milestones_hit.append("service_resolved")
        if last_context in ("stylist", "slot", "numbered_slots", "name", "notes", "confirmation") and "addons_handled" not in milestones_hit:
            milestones_hit.append("addons_handled")
        if last_context in ("slot", "numbered_slots", "name", "notes", "confirmation") and "stylist_resolved" not in milestones_hit:
            milestones_hit.append("stylist_resolved")
        if last_context in ("name", "notes", "confirmation") and "slot_resolved" not in milestones_hit:
            milestones_hit.append("slot_resolved")
        if last_context in ("notes", "confirmation") and "customer_name" not in milestones_hit:
            milestones_hit.append("customer_name")
        if last_context == "booking_complete":
            if "booking_completed" not in milestones_hit:
                milestones_hit.append("booking_completed")
            booking_complete = True

        if booking_complete:
            print(f"  >> Booking confirmed in bot response — done!")
            break

    await pubsub.unsubscribe(OUTGOING_PUBSUB_CHANNEL)
    await client.aclose()

    # Determine final status
    expected_milestones = {"greeting_done", "service_resolved", "slot_resolved", "booking_completed"}
    hit_set = set(milestones_hit)
    passed = booking_complete or "booking_completed" in hit_set

    result = {
        "scenario_id": "indecision",
        "persona_id": "luis_indecisive_client",
        "conversation_id": conversation_id,
        "turn_count": turn_count,
        "status": "PASS" if passed else "FAIL",
        "booking_complete": booking_complete,
        "milestones_hit": milestones_hit,
        "turns": turns,
    }
    return result


async def check_db_appointments() -> int:
    """Check DB for appointments created in the last hour."""
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
    try:
        return int(result.stdout.strip())
    except ValueError:
        return -1


if __name__ == "__main__":
    result = asyncio.run(run_qa())

    print(f"\n{'='*60}")
    print("RESULT SUMMARY")
    print(f"{'='*60}")
    print(f"Status      : {result['status']}")
    print(f"Turn count  : {result['turn_count']}")
    print(f"Booking done: {result['booking_complete']}")
    print(f"Milestones  : {result['milestones_hit']}")
    print(f"Conv ID     : {result['conversation_id']}")

    # DB check
    count = asyncio.run(check_db_appointments())
    result["appointment_in_db"] = count > 0
    result["appointments_last_hour"] = count
    print(f"\nDB appointments (last 1h): {count}")
    print(f"appointment_in_db: {result['appointment_in_db']}")

    print(f"\n{'='*60}")
    print("FULL TRACE")
    print(f"{'='*60}")
    for t in result["turns"]:
        print(f"\n[T{t['turn_number']}] USER: {t['user_message']}")
        print(f"      BOT : {t['agent_response'][:300]}")
        print(f"      LAT : {t['response_latency_ms']}ms")

    print(f"\n{'='*60}")
    print(json.dumps(result, indent=2, ensure_ascii=False))
