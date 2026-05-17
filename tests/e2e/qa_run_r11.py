#!/usr/bin/env python3
"""
QA Run R11 — returning_client flow, persona: carlos_returning_client
Commit: 55ab710 (holistic booking FSM contract fix)
"""
import json
import threading
import time
import uuid

import redis

REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_PASSWORD = "9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda"
INCOMING_STREAM = "incoming_messages_stream"
OUTGOING_CHANNEL = "outgoing_messages"
RESPONSE_TIMEOUT = 30.0
PHONE_NUMBER = "+34600111222"

conversation_id = str(uuid.uuid4())
print(f"conversation_id: {conversation_id}")

r = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASSWORD,
    decode_responses=True,
)

# --- Pub/Sub capture ---
received_messages = []
capture_lock = threading.Lock()
stop_event = threading.Event()


def pubsub_listener():
    ps = r.pubsub()
    ps.subscribe(OUTGOING_CHANNEL)
    ps.get_message(timeout=1)  # flush subscribe ack
    while not stop_event.is_set():
        msg = ps.get_message(timeout=0.1)
        if msg and msg["type"] == "message":
            try:
                data = json.loads(msg["data"])
                with capture_lock:
                    received_messages.append(data)
            except Exception as e:
                print(f"[pubsub parse error] {e} — raw: {msg['data']}")


listener_thread = threading.Thread(target=pubsub_listener, daemon=True)
listener_thread.start()
time.sleep(0.5)  # give subscriber time to register
print("[pubsub] Subscribed to outgoing_messages — ready.")


def inject(text: str) -> dict:
    """Inject a user message and wait for agent response matching our conversation_id."""
    payload = {
        "conversation_id": conversation_id,
        "message": text,
        "phone_number": PHONE_NUMBER,
        "contact_name": "Carlos López",
        "timestamp": time.time(),
    }
    data_field = json.dumps(payload)
    msg_id = r.xadd(INCOMING_STREAM, {"data": data_field})
    print(f"  → injected [{msg_id}]: {text!r}")

    t0 = time.time()
    while time.time() - t0 < RESPONSE_TIMEOUT:
        with capture_lock:
            for item in received_messages:
                if str(item.get("conversation_id")) == conversation_id:
                    received_messages.remove(item)
                    elapsed = int((time.time() - t0) * 1000)
                    return {"response": item, "latency_ms": elapsed}
        time.sleep(0.2)

    return {"response": None, "latency_ms": int((time.time() - t0) * 1000)}


def extract_message(response_envelope: dict) -> str:
    if response_envelope.get("response") is None:
        return "[TIMEOUT — no response]"
    resp = response_envelope["response"]
    return resp.get("message") or resp.get("message_text") or str(resp)


# ──────────────────────────────────────────────
# HARNESS SCRIPT
# ──────────────────────────────────────────────
turns = []

# Decision helpers: classify bot text to pick next utterance
def decide_next(bot_text: str, turn_num: int) -> str:
    """
    Map bot response to the next user utterance per harness spec.
    """
    lower = bot_text.lower()

    # Variant question (caballero / dama)
    if any(k in lower for k in ["tipo de corte", "caballero o dama", "caballero o señora", "¿es un corte de caballero", "tipo de servicio", "qué tipo"]):
        return "Caballero"

    # Stylist list shown (numbered list with names)
    if any(k in lower for k in ["1.", "luciana", "selecciona", "elegir estilista", "elige una estilista", "peluquera"]):
        return "1"

    # Numbered slot list
    if any(k in lower for k in ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "1.", "2.", "3.", "slot", "horario", "disponible"]):
        # Could also be a stylist list — disambiguate
        if "luciana" in lower and "1." in lower:
            return "1"  # stylist selection
        return "1"  # slot selection

    # Add-ons / additional services
    if any(k in lower for k in ["¿desea", "¿quiere agregar", "¿te gustaría", "servicio adicional", "algo más", "algún otro"]):
        return "No gracias"

    # Name request
    if any(k in lower for k in ["tu nombre", "cómo te llamas", "¿cuál es tu nombre", "nombre completo"]):
        return "Carlos López"

    # Notes request
    if any(k in lower for k in ["nota", "algún comentario", "indicación", "observación"]):
        return "Sin notas"

    # Confirmation
    if any(k in lower for k in ["confirmas", "¿confirmas", "confirmar", "¿deseas confirmar", "reserva confirmada", "¿todo correcto"]):
        return "Sí, confirmo"

    # Error recovery
    if any(k in lower for k in ["error", "problema", "no pude", "falló", "intenta de nuevo"]):
        return "Intenta de nuevo"

    # Default: send T1 text on first turn, else wait
    if turn_num == 1:
        return "Hola, quiero un corte caballero con Luciana esta semana a la mañana"
    return None  # no match — will be flagged


print(f"\n{'='*60}")
print("QA R11 — returning_client | carlos_returning_client")
print(f"conversation_id: {conversation_id}")
print(f"{'='*60}\n")

# T1: always send opening message
t1_message = "Hola, quiero un corte caballero con Luciana esta semana a la mañana"
print(f"[T1] User: {t1_message!r}")
result = inject(t1_message)
bot_msg = extract_message(result)
print(f"[T1] Bot ({result['latency_ms']}ms): {bot_msg!r}\n")
turns.append({
    "turn_number": 1,
    "user_message": t1_message,
    "agent_response": bot_msg,
    "response_latency_ms": result["latency_ms"],
})

# T2 onwards: respond based on bot content
completed = False
for turn_num in range(2, 13):
    last_bot = turns[-1]["agent_response"]

    # Check for terminal states
    if any(k in last_bot.lower() for k in ["cita confirmada", "cita creada", "reserva confirmada", "hemos confirmado", "confirmación de tu cita", "¡tu cita"]):
        print(f"[T{turn_num}] → BOOKING COMPLETED (terminal state detected)")
        completed = True
        break

    if "[TIMEOUT" in last_bot:
        print(f"[T{turn_num}] → TIMEOUT — aborting")
        break

    next_msg = decide_next(last_bot, turn_num)
    if next_msg is None:
        print(f"[T{turn_num}] → Could not determine next message. Last bot: {last_bot[:200]!r}")
        # Try "1" as a safe default for unknown numbered lists
        next_msg = "1"

    print(f"[T{turn_num}] User: {next_msg!r}")
    result = inject(next_msg)
    bot_msg = extract_message(result)
    print(f"[T{turn_num}] Bot ({result['latency_ms']}ms): {bot_msg!r}\n")
    turns.append({
        "turn_number": turn_num,
        "user_message": next_msg,
        "agent_response": bot_msg,
        "response_latency_ms": result["latency_ms"],
    })

stop_event.set()

# ──────────────────────────────────────────────
# DB VERIFICATION
# ──────────────────────────────────────────────
print("\n" + "="*60)
print("DB VERIFICATION")
print("="*60)

import subprocess

db_result = subprocess.run(
    [
        "docker", "exec", "atrevete-postgres",
        "psql", "-U", "atrevete", "-d", "atrevete_db",
        "-t", "-c",
        "SELECT count(*) FROM appointments WHERE created_at > now() - interval '1 hour';"
    ],
    capture_output=True, text=True
)
db_count_str = db_result.stdout.strip()
print(f"appointments in last 1h: {db_count_str}")
appointment_count = int(db_count_str) if db_count_str.isdigit() else 0
appointment_in_db = appointment_count > 0

# ──────────────────────────────────────────────
# MILESTONE ANALYSIS
# ──────────────────────────────────────────────
print("\n" + "="*60)
print("MILESTONE ANALYSIS")
print("="*60)

all_bot_text = " ".join(t["agent_response"].lower() for t in turns)
all_user_text = " ".join(t["user_message"].lower() for t in turns)

milestones = {
    "greeting_done": any(k in all_bot_text for k in ["hola", "bienvenid", "maite", "soy"]),
    "booking_intent_detected": any(k in all_bot_text for k in ["corte", "servicio", "tipo de"]),
    "stylist_locked": any(k in all_bot_text for k in ["luciana", "estilista"]),
    "slot_offered": any(k in all_bot_text for k in ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "disponible", "horario"]),
    "customer_name_step": "carlos" in all_bot_text or "nombre" in all_bot_text,
    "confirmation_done": any(k in all_bot_text for k in ["confirm", "cita creada", "cita confirmada", "¡tu cita"]),
    "booking_completed": completed,
}

for milestone, hit in milestones.items():
    status = "✅" if hit else "❌"
    print(f"  {status} {milestone}")

milestones_hit = [m for m, v in milestones.items() if v]

# ──────────────────────────────────────────────
# FINAL SUMMARY
# ──────────────────────────────────────────────
status = "PASS" if (completed and appointment_in_db) else "FAIL"

print("\n" + "="*60)
print("FINAL SUMMARY")
print("="*60)
print(f"STATUS: {status}")
print(f"turn_count: {len(turns)}")
print(f"appointment_in_db: {appointment_in_db} (count={appointment_count})")
print(f"milestones_hit: {milestones_hit}")
print(f"booking_completed: {completed}")

print("\n--- FULL CONVERSATION TRACE ---")
for t in turns:
    print(f"\n[T{t['turn_number']}] User: {t['user_message']!r}")
    print(f"[T{t['turn_number']}] Bot  ({t['response_latency_ms']}ms): {t['agent_response']!r}")

result_data = {
    "status": status,
    "turn_count": len(turns),
    "conversation_id": conversation_id,
    "milestones_hit": milestones_hit,
    "appointment_in_db": appointment_in_db,
    "appointment_count": appointment_count,
    "booking_completed": completed,
    "turns": turns,
}

print("\n--- JSON RESULT ---")
print(json.dumps(result_data, ensure_ascii=False, indent=2))
