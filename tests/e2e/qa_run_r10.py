#!/usr/bin/env python3
"""
QA Run R10 - returning_client / carlos_returning_client
Follows atrevete-qa-tester SKILL exactly:
  1. Subscribe to outgoing_messages Pub/Sub BEFORE injecting
  2. Inject turns via XADD to incoming_messages_stream
  3. Capture agent `message` field per turn
  4. Timeout 30s per turn
"""

import asyncio
import json
import time
import uuid
import sys
import os

import redis.asyncio as redis

# Redis config (from .env)
REDIS_URL = "redis://localhost:6379/0"
REDIS_PASSWORD = "9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda"

INCOMING_STREAM = "incoming_messages_stream"
PUBSUB_CHANNEL = "outgoing_messages"

CONVERSATION_ID = str(uuid.uuid4())
PHONE_NUMBER = f"+34999{CONVERSATION_ID[:8].replace('-', '')[:6]}"
CHATWOOT_CONTACT_ID = 9901  # synthetic test contact
CHATWOOT_CONVERSATION_ID = 9901

TURN_TIMEOUT = 30.0  # seconds

print(f"[QA-R10] conversation_id = {CONVERSATION_ID}")
print(f"[QA-R10] phone = {PHONE_NUMBER}")


def make_payload(text: str) -> dict:
    return {
        "conversation_id": CONVERSATION_ID,
        "message": text,
        "message_type": "incoming",
        "phone_number": PHONE_NUMBER,
        "chatwoot_contact_id": CHATWOOT_CONTACT_ID,
        "chatwoot_conversation_id": CHATWOOT_CONVERSATION_ID,
        "contact_name": "Carlos López",
        "account_id": 1,
        "inbox_id": 1,
    }


async def run_qa():
    client = redis.from_url(
        REDIS_URL,
        password=REDIS_PASSWORD,
        decode_responses=True,
    )

    # ── Pub/Sub subscriber (subscribe BEFORE first inject) ──────────────────
    pubsub = client.pubsub()
    await pubsub.subscribe(PUBSUB_CHANNEL)
    print(f"[QA-R10] Subscribed to '{PUBSUB_CHANNEL}'")

    # Drain any stale messages sitting in the channel buffer
    await asyncio.sleep(0.3)
    async for msg in pubsub.listen():
        if msg["type"] == "subscribe":
            break

    turns = []

    async def wait_for_response(turn_num: int) -> str | None:
        """Wait up to TURN_TIMEOUT seconds for a response matching our conversation_id."""
        deadline = time.monotonic() + TURN_TIMEOUT
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                msg = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True), timeout=min(1.0, remaining)
                )
            except asyncio.TimeoutError:
                continue
            if msg is None:
                await asyncio.sleep(0.05)
                continue
            if msg["type"] != "message":
                continue
            try:
                data = json.loads(msg["data"])
            except Exception:
                continue
            # Match on conversation_id
            if data.get("conversation_id") == CONVERSATION_ID:
                return data.get("message") or data.get("message_text") or str(data)
        return None

    async def send_and_capture(turn_num: int, user_text: str) -> dict:
        payload = make_payload(user_text)
        t0 = time.monotonic()
        # XADD with wrapped shape {"data": json.dumps(payload)}
        await client.xadd(
            INCOMING_STREAM,
            {"data": json.dumps(payload)},
            maxlen=10000,
            approximate=True,
        )
        print(f"\n[T{turn_num}] USER → {user_text!r}")
        response = await wait_for_response(turn_num)
        latency_ms = int((time.monotonic() - t0) * 1000)
        if response:
            print(f"[T{turn_num}] BOT  ← {response[:200]!r}  ({latency_ms}ms)")
        else:
            print(f"[T{turn_num}] BOT  ← TIMEOUT after {latency_ms}ms")
        return {
            "turn_number": turn_num,
            "user_message": user_text,
            "agent_response": response,
            "response_latency_ms": latency_ms,
            "timed_out": response is None,
        }

    # ══════════════════════════════════════════════════════════════
    # HARNESS SCRIPT (per task instructions)
    # T1: opening
    # ══════════════════════════════════════════════════════════════

    # T1 — opening
    t1 = await send_and_capture(
        1, "Hola, quiero un corte caballero con Luciana esta semana a la mañana"
    )
    turns.append(t1)
    if t1["timed_out"]:
        print("[QA-R10] TIMEOUT on T1 — aborting")
        await pubsub.unsubscribe()
        await client.aclose()
        return turns, False

    bot1 = t1["agent_response"].lower()

    # Detect what the bot wants:
    # - If asking service variant (caballero/dama) → answer "Caballero"
    # - If showing stylist numbered list → answer "1"
    # - If showing slot list → answer "1"
    # - If asking name → answer "Carlos López"
    # - If asking notes/additional info → answer "Sin notas"
    # - If asking add-ons → answer "No gracias"
    # - If showing confirmation → answer "Sí, confirmo"

    turn_num = 2

    def classify_bot_response(text: str) -> str:
        t = text.lower()
        # confirmation screen
        if any(
            w in t
            for w in [
                "confirmar",
                "confirmás",
                "confirmas",
                "confirmación",
                "¿confirmás",
                "todo listo",
                "¿está bien",
            ]
        ):
            return "CONFIRM"
        # asking name
        if any(w in t for w in ["nombre", "cómo te llamás", "como te llamas", "tu nombre"]):
            return "ASK_NAME"
        # asking notes
        if any(w in t for w in ["nota", "adicional", "comentario", "algún detalle", "alguna nota"]):
            return "ASK_NOTES"
        # add-ons
        if any(
            w in t
            for w in [
                "barbería",
                "barba",
                "producto",
                "tratamiento",
                "hidratación",
                "mechas",
                "tintura",
                "adicional",
                "add-on",
                "además",
                "¿querés agregar",
                "querés sumar",
            ]
        ):
            return "ADDON"
        # numbered list of slots (contains hour patterns)
        if any(
            w in t
            for w in [
                "1️⃣",
                "2️⃣",
                "3️⃣",
                "lunes",
                "martes",
                "miércoles",
                "jueves",
                "viernes",
                "09:",
                "10:",
                "11:",
                "8:",
                "hs",
            ]
        ):
            return "SLOT_LIST"
        # numbered stylist list
        if any(
            w in t
            for w in [
                "luciana",
                "estilista",
                "estilis",
                "¿con quién",
                "con quien",
                "con cuál",
                "con cual",
            ]
        ):
            return "STYLIST_LIST"
        # service variant
        if any(
            w in t
            for w in ["caballero", "dama", "tipo de corte", "¿para caballero", "para caballero"]
        ):
            return "SERVICE_VARIANT"
        # error
        if any(w in t for w in ["error", "problema", "disculpá", "disculpa", "inconveniente"]):
            return "ERROR"
        return "UNKNOWN"

    # We run a loop-based harness for up to 12 turns total
    completed = False
    while turn_num <= 12:
        last_bot = turns[-1]["agent_response"]
        if last_bot is None:
            print(f"[QA-R10] TIMEOUT at turn {turn_num - 1} — aborting")
            break

        category = classify_bot_response(last_bot)
        print(f"[QA-R10] category={category}")

        # Terminal success conditions
        if any(
            w in last_bot.lower()
            for w in [
                "turno confirmado",
                "cita confirmada",
                "reserva confirmada",
                "ya está agendado",
                "quedó agendado",
                "registrado",
                "¡listo!",
                "¡perfecto",
                "nos vemos",
                "te esperamos",
            ]
        ):
            print("[QA-R10] BOOKING COMPLETED detected in bot response")
            completed = True
            break

        # Decide reply based on category
        if category == "CONFIRM":
            reply = "Sí, confirmo"
        elif category == "ASK_NAME":
            reply = "Carlos López"
        elif category == "ASK_NOTES":
            reply = "Sin notas"
        elif category == "ADDON":
            reply = "No gracias"
        elif category == "SLOT_LIST":
            reply = "1"
        elif category == "STYLIST_LIST":
            reply = "1"
        elif category == "SERVICE_VARIANT":
            reply = "Caballero"
        elif category == "ERROR":
            reply = "Intenta de nuevo"
        else:
            # unknown — if last bot said something about booking being done, stop
            if any(w in last_bot.lower() for w in ["confirmado", "agendado", "reservado", "listo"]):
                print("[QA-R10] BOOKING COMPLETED (fallback detection)")
                completed = True
                break
            # Otherwise try "1" as a generic numbered-list answer
            reply = "1"

        turn = await send_and_capture(turn_num, reply)
        turns.append(turn)
        turn_num += 1

        if turn["timed_out"]:
            break

    await pubsub.unsubscribe()
    await client.aclose()
    return turns, completed


async def check_db() -> int:
    """Check appointment count created in last hour."""
    import asyncpg

    conn = await asyncpg.connect(
        "postgresql://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db"
    )
    row = await conn.fetchrow(
        "SELECT count(*) as cnt FROM appointments WHERE created_at > now() - interval '1 hour'"
    )
    await conn.close()
    return row["cnt"]


async def main():
    turns, completed = await run_qa()

    print("\n" + "=" * 70)
    print("QA RUN R10 — CONVERSATION TRACE")
    print("=" * 70)
    for t in turns:
        print(f"\nTurn {t['turn_number']}:")
        print(f"  USER: {t['user_message']}")
        print(f"  BOT:  {t['agent_response']}")
        print(f"  Latency: {t['response_latency_ms']}ms  Timeout: {t['timed_out']}")
    print("\n" + "=" * 70)
    print(f"Total turns: {len(turns)}")
    print(f"Booking completed flag: {completed}")

    # DB check
    try:
        db_count = await check_db()
        print(f"DB appointments (last 1h): {db_count}")
        appointment_in_db = db_count > 0
    except Exception as e:
        print(f"DB check error: {e}")
        appointment_in_db = False

    # Milestones
    all_responses = " ".join((t["agent_response"] or "") for t in turns).lower()
    milestones = {
        "greeting_done": any("hola" in (t["agent_response"] or "").lower() for t in turns[:2]),
        "service_resolved": "corte" in all_responses or "caballero" in all_responses,
        "stylist_locked": "luciana" in all_responses,
        "slot_resolved": any(
            x in all_responses
            for x in ["lunes", "martes", "miércoles", "jueves", "viernes", "turno"]
        ),
        "confirmation_done": any(
            x in all_responses for x in ["confirma", "confirmado", "listo", "agendado"]
        ),
        "booking_completed": completed or appointment_in_db,
    }

    print(f"\nMilestones: {milestones}")
    status = "PASS" if (completed or appointment_in_db) else "FAIL"
    print(f"\nSTATUS: {status}")

    return {
        "status": status,
        "turn_count": len(turns),
        "milestones_hit": milestones,
        "appointment_in_db": appointment_in_db,
        "conversation_trace": turns,
    }


if __name__ == "__main__":
    result = asyncio.run(main())
    print(f"\nFINAL RESULT: {json.dumps(result, ensure_ascii=False, indent=2)}")
