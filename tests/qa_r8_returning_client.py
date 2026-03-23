"""
QA Round 8 — returning_client flow, persona: carlos_returning_client
Harness script: injects messages into INCOMING_STREAM, captures responses via outgoing_messages Pub/Sub.

CRITICAL PAYLOAD SHAPE (from agent/main.py):
  - conversation_id: str
  - customer_phone: str  (NOT 'phone')
  - message_text: str    (NOT 'message')
  - sender_name: str     (optional, preferred over customer_name)
"""

import asyncio
import json
import time
import uuid
import sys
import re

import redis.asyncio as aioredis

# ── Config ──────────────────────────────────────────────────────────────────
REDIS_URL = "redis://localhost:6379/0"
REDIS_PASSWORD = "9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda"
INCOMING_STREAM = "incoming_messages_stream"
PUBSUB_CHANNEL = "outgoing_messages"
RESPONSE_TIMEOUT = 35.0   # 30s + some margin for 3s batching window
BATCH_WINDOW_SECS = 3.5   # extra wait after injecting for batch flush

DB_URL = "postgresql://atrevete:a3f7c2e9d1b8f4a6c5e2d9b3f8a1c4e7@localhost:5432/atrevete_db"


def build_payload(conversation_id: str, phone: str, message_text: str, sender_name: str = "Carlos López") -> dict:
    """Build the message payload exactly as agent/main.py expects it."""
    return {
        "conversation_id": conversation_id,
        "customer_phone": phone,           # key: customer_phone
        "message_text": message_text,      # key: message_text
        "sender_name": sender_name,        # key: sender_name
        "timestamp": time.time(),
    }


def extract_first_slot(text: str) -> str:
    """Extract the first slot option from the bot's response."""
    patterns = [
        # "El martes a las 10:00" or "El lunes 10:00"
        r'(?:El |el )?([Ll]unes|[Mm]artes|[Mm]iércoles|[Jj]ueves|[Vv]iernes|[Ss]ábado)[,\s]+(?:a las?\s+)?(\d{1,2}:\d{2})',
        # "1. martes a las 10:00"
        r'(?:\d+[.)]\s*)([Ll]unes|[Mm]artes|[Mm]iércoles|[Jj]ueves|[Vv]iernes|[Ss]ábado)[,\s]+(?:a las?\s+)?(\d{1,2}:\d{2})',
        # bare "martes 10:00"
        r'([Ll]unes|[Mm]artes|[Mm]iércoles|[Jj]ueves|[Vv]iernes|[Ss]ábado)\s+(\d{1,2}:\d{2})',
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            day = match.group(1).capitalize()
            time_str = match.group(2)
            return f"El {day} a las {time_str}"

    # Fallback: numbered list → send "1"
    for line in text.split('\n'):
        line = line.strip()
        if re.match(r'^[1-9][.)]\s+', line):
            return "1"

    return "1"  # ultimate fallback


DYNAMIC_RESPONSES = {
    "variant_question": {
        "keywords": ["para caballero", "para dama", "tipo de corte", "qué tipo de corte", "dama o caballero"],
        "response": "Caballero",
    },
    "slot_question": {
        "keywords": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado",
                     "disponible", "horario", "10:00", "11:00", "09:00", "08:00",
                     "qué día", "qué hora", "te viene bien", "te queda bien", "podría ser",
                     "opción", "elegí", "elegir", "elige"],
        "response": None,  # dynamically extracted
    },
    "addon_question": {
        "keywords": ["add-on", "adicional", "shampoo", "acondicionador", "tratamiento",
                     "¿querés", "también te ofrezco", "incluir algo más"],
        "response": "No gracias",
    },
    "name_question": {
        "keywords": ["nombre", "cómo te llamás", "tu nombre", "nombre completo", "me podés dar"],
        "response": "Carlos López",
    },
    "notes_question": {
        "keywords": ["nota", "notas", "aclaración", "comentario", "observación", "algo más que"],
        "response": "Sin notas",
    },
    "confirmation_question": {
        "keywords": ["confirmá", "confirmar", "¿confirmás", "estás de acuerdo",
                     "¿todo bien", "para confirmar", "confirmamos"],
        "response": "Sí, confirmo",
    },
}

BOOKING_DONE_KEYWORDS = [
    "reserva confirmada", "turno confirmado", "reservado", "agendado",
    "¡listo", "todo listo", "nos vemos", "te esperamos", "quedó reservado",
    "quedó agendado", "se registró", "appointment confirmed",
]


def decide_response(bot_text: str, turn_number: int) -> str | None:
    """Based on bot response text, decide what to reply next."""
    text_lower = bot_text.lower()

    # Booking done — no more replies needed
    if any(kw in text_lower for kw in BOOKING_DONE_KEYWORDS):
        return None

    # Check slot options first (more specific, avoids false positives)
    slot_entry = DYNAMIC_RESPONSES["slot_question"]
    if turn_number >= 2 and any(kw in text_lower for kw in slot_entry["keywords"]):
        slot = extract_first_slot(bot_text)
        print(f"  [SLOT] Extracted: '{slot}'")
        return slot

    # Check remaining patterns in priority order
    for key in ["variant_question", "addon_question", "name_question", "notes_question", "confirmation_question"]:
        entry = DYNAMIC_RESPONSES[key]
        if any(kw in text_lower for kw in entry["keywords"]):
            return entry["response"]

    return None  # No known pattern → stop


async def run_qa(conversation_id: str, phone: str) -> list[dict]:
    """Execute the returning_client QA flow via Redis."""

    client = aioredis.from_url(
        REDIS_URL,
        password=REDIS_PASSWORD,
        decode_responses=True,
    )

    await client.ping()
    print(f"✅ Redis connected")
    print(f"   conversation_id: {conversation_id}")
    print(f"   phone: {phone}")
    print()

    # ── Subscribe BEFORE injecting to avoid race condition ──────────────────
    pubsub = client.pubsub()
    await pubsub.subscribe(PUBSUB_CHANNEL)
    # Drain the subscribe confirmation message
    await asyncio.sleep(0.2)
    msg = await pubsub.get_message(timeout=0.5)
    while msg and msg.get("type") == "subscribe":
        msg = await pubsub.get_message(timeout=0.5)

    print(f"✅ Subscribed to '{PUBSUB_CHANNEL}'")
    print()

    turns = []
    max_turns = 12
    turn_number = 0

    # T1: Initial message
    current_message = "Hola, quiero un corte caballero con Luciana esta semana a la mañana"

    while turn_number < max_turns:
        turn_number += 1
        print(f"─── Turn {turn_number} ───────────────────────────────────────")
        print(f"  USER → {current_message}")

        t_inject = time.time()

        # Build payload with CORRECT field names
        payload = build_payload(conversation_id, phone, current_message)
        msg_json = json.dumps(payload)

        # XADD to incoming stream (wrapped shape: {"data": json_str})
        stream_id = await client.xadd(
            INCOMING_STREAM,
            {"data": msg_json},
        )
        print(f"  [STREAM] Injected: {stream_id}")

        # ── Wait for response on Pub/Sub ────────────────────────────────────
        agent_response = None
        deadline = time.time() + RESPONSE_TIMEOUT

        while time.time() < deadline:
            pub_msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if pub_msg and pub_msg.get("type") == "message":
                try:
                    data = json.loads(pub_msg["data"])
                    if data.get("conversation_id") == conversation_id:
                        agent_response = data.get("message") or data.get("message_text", "")
                        break
                except (json.JSONDecodeError, KeyError):
                    pass

        t_response = time.time()
        latency_ms = int((t_response - t_inject) * 1000)

        if agent_response is None:
            print(f"  ⚠️  TIMEOUT — no response for conversation_id={conversation_id}")
            turns.append({
                "turn_number": turn_number,
                "user_message": current_message,
                "agent_response": None,
                "response_latency_ms": int(RESPONSE_TIMEOUT * 1000),
                "timed_out": True,
            })
            break

        print(f"  BOT  → {agent_response[:300]}{'...' if len(agent_response) > 300 else ''}")
        print(f"  ⏱  {latency_ms}ms")

        turns.append({
            "turn_number": turn_number,
            "user_message": current_message,
            "agent_response": agent_response,
            "response_latency_ms": latency_ms,
        })

        # Check if booking is completed
        response_lower = agent_response.lower()
        if any(kw in response_lower for kw in BOOKING_DONE_KEYWORDS):
            print(f"\n  ✅ BOOKING COMPLETE detected at turn {turn_number}")
            break

        # Decide next response
        next_msg = decide_response(agent_response, turn_number)
        if next_msg is None:
            print(f"  [INFO] No next response needed — flow ended or unexpected state")
            break

        current_message = next_msg
        print()

    # ── Cleanup ────────────────────────────────────────────────────────────
    await pubsub.unsubscribe(PUBSUB_CHANNEL)
    await client.aclose()

    return turns


async def check_db() -> int:
    """Count appointments created in the last hour."""
    try:
        import asyncpg
        conn = await asyncpg.connect(DB_URL)
        count = await conn.fetchval(
            "SELECT count(*)::int FROM appointments WHERE created_at > now() - interval '1 hour'"
        )
        await conn.close()
        return int(count)
    except Exception as e:
        print(f"  [DB ERROR] {e}")
        return -1


async def main():
    conversation_id = str(uuid.uuid4())
    phone = "+5491199887766"

    print("=" * 60)
    print("QA ROUND 8 — returning_client / carlos_returning_client")
    print("=" * 60)
    print(f"conversation_id: {conversation_id}")
    print(f"phone: {phone}")
    print()

    turns = await run_qa(conversation_id, phone)

    # ── Conversation trace summary ─────────────────────────────────────────
    print()
    print("=" * 60)
    print("CONVERSATION TRACE")
    print("=" * 60)
    for t in turns:
        print(f"\nTurn {t['turn_number']} ({t.get('response_latency_ms', '?')}ms):")
        print(f"  User : {t['user_message']}")
        resp = t.get('agent_response')
        if resp:
            print(f"  Agent: {resp[:400]}{'...' if len(resp) > 400 else ''}")
        else:
            print(f"  Agent: [TIMEOUT]")

    # ── DB check ──────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("DB CHECK")
    print("=" * 60)
    await asyncio.sleep(2)  # brief wait for DB write
    db_count = await check_db()
    print(f"  SELECT count(*) FROM appointments WHERE created_at > now() - interval '1 hour'")
    print(f"  Result: {db_count}")

    # ── Milestone analysis ────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("MILESTONE ANALYSIS")
    print("=" * 60)

    all_text = " ".join(
        (t.get("agent_response") or "").lower() for t in turns
    )

    milestones = {
        "greeting_done": any(kw in all_text for kw in ["hola", "bienvenid", "cómo te puedo", "puedo ayudarte"]),
        "service_resolved": any(kw in all_text for kw in ["corte caballero", "caballero"]),
        "stylist_locked": "luciana" in all_text,
        "slot_resolved": any(kw in all_text for kw in ["lunes", "martes", "miércoles", "jueves", "viernes", "reservad", "agendad"]),
        "confirmation_done": any(kw in all_text for kw in ["confirmad", "confirmamos", "agendad", "reservad"]),
        "booking_completed": any(kw in all_text for kw in BOOKING_DONE_KEYWORDS),
    }

    for milestone, hit in milestones.items():
        status = "✅" if hit else "❌"
        print(f"  {status} {milestone}")

    milestones_hit = [k for k, v in milestones.items() if v]

    # ── Final verdict ─────────────────────────────────────────────────────
    appointment_in_db = db_count > 0
    booking_completed = milestones["booking_completed"]
    no_timeout = all(not t.get("timed_out") for t in turns)

    passed = booking_completed and appointment_in_db and no_timeout

    print()
    print("=" * 60)
    print(f"RESULT: {'PASS ✅' if passed else 'FAIL ❌'}")
    print(f"  turn_count:        {len(turns)}")
    print(f"  milestones_hit:    {milestones_hit}")
    print(f"  appointment_in_db: {appointment_in_db} (count={db_count})")
    print(f"  booking_completed: {booking_completed}")
    print(f"  no_timeout:        {no_timeout}")
    print("=" * 60)

    return {
        "status": "PASS" if passed else "FAIL",
        "turn_count": len(turns),
        "milestones_hit": milestones_hit,
        "appointment_in_db": appointment_in_db,
        "appointment_count_last_hour": db_count,
        "conversation_id": conversation_id,
        "turns": turns,
    }


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result["status"] == "PASS" else 1)
