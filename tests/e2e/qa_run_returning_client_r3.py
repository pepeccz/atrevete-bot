"""QA Round 3 - returning_client flow with carlos_returning_client persona."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import UTC, datetime

import redis.asyncio as aioredis

REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_PASSWORD = "9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda"
INCOMING_STREAM = "incoming_messages_stream"
OUTGOING_CHANNEL = "outgoing_messages"
RESPONSE_TIMEOUT = 35.0

DB_HOST = "localhost"
DB_PORT = 5432
DB_USER = "atrevete"
DB_PASSWORD = "a3f7c2e9d1b8f4a6c5e2d9b3f8a1c4e7"
DB_NAME = "atrevete_db"

# Persona: Carlos — returning client
PERSONA_NAME = "Carlos"
CUSTOMER_PHONE = "+34611223344"


def decide_next_reply(turn_num: int, bot_message: str, history: list) -> tuple[str, bool]:
    """
    Decide Carlos's next reply given bot message.
    Returns (reply, should_stop).
    Carlos is a returning client who wants "corte caballero" with Luciana, "esta semana a la mañana".
    """
    msg_lower = bot_message.lower()

    # Completion signals — booking is DONE
    if any(kw in msg_lower for kw in [
        "turno confirmado", "reserva confirmada", "quedó agendado", "quedó confirmado",
        "te esperamos", "nos vemos", "¡hasta", "hasta pronto", "booking confirmado",
    ]):
        return ("Perfecto, gracias!", True)

    # Bot asks Carlos to confirm the booking details
    if any(kw in msg_lower for kw in [
        "¿confirmás", "¿confirmas", "confirmás?", "confirmas?",
        "¿todo correcto", "¿todo bien", "¿está bien así", "confirmar el turno",
        "¿querés confirmar",
    ]):
        return ("Sí, confirmo", False)

    # Bot offers add-ons
    if any(kw in msg_lower for kw in [
        "barba", "cejas", "masaje", "tratamiento", "¿querés agregar",
        "¿te gustaría agregar", "add-on", "adicional", "también podés",
        "¿sumás", "¿agregás",
    ]):
        return ("No gracias, solo el corte", False)

    # Bot asks about time/day (should already know "esta semana a la mañana")
    if any(kw in msg_lower for kw in ["qué día", "qué horario", "qué hora", "para cuándo", "¿cuándo querés"]):
        return ("Esta semana a la mañana", False)

    # Bot shows available slots — pick morning slot
    if any(kw in msg_lower for kw in [
        "disponibilidad", "tengo estos horarios", "los horarios disponibles",
        "podría ser", "opciones disponibles", "mañana a las", "lunes", "martes",
        "miércoles", "jueves", "viernes", "sábado"
    ]):
        # Extract time from message
        times = re.findall(r'\b([89]|10|11)(?:[:h]\d{0,2})?\s*(?:hs?\.?|horas?)?', bot_message)
        if times:
            return (f"El de las {times[0]}:00 me viene bien", False)
        # Try ordinals or "primero"
        return ("El primer horario disponible", False)

    # Bot asks if we want to search availability
    if any(kw in msg_lower for kw in [
        "¿te gustaría que", "¿buscamos", "¿queres que busque", "buscar disponibilidad",
        "¿busco disponibilidad",
    ]):
        return ("Sí, buscá", False)

    # Bot asks for stylist preference
    if any(kw in msg_lower for kw in ["estilista", "con quién", "¿con quién", "preferís", "¿preferís"]):
        return ("Con Luciana", False)

    # Bot asks if Luciana or any stylist is OK
    if "luciana" in msg_lower and any(kw in msg_lower for kw in ["¿con", "¿te", "disponible"]):
        return ("Sí, con Luciana", False)

    # BUG-003 scenario: bot asks variant (shouldn't happen, but respond anyway)
    if any(kw in msg_lower for kw in ["caballero, dama", "para dama", "para niño", "¿para quién", "tipo de corte"]):
        return ("Caballero", False)

    # Bot asks for name
    if any(kw in msg_lower for kw in ["nombre", "cómo te llamás", "cómo te llamas", "¿tu nombre"]):
        return ("Carlos", False)

    # Luciana unavailable
    if any(kw in msg_lower for kw in ["luciana no", "luciana está", "no tiene disponibilidad", "no está disponible"]):
        return ("Bueno, con quien haya está bien", False)

    # Generic affirmative for unknown questions
    return ("Dale, está bien", False)


async def run_qa():
    print(f"\n{'='*70}")
    print("QA ROUND 3 — returning_client — carlos_returning_client")
    print(f"{'='*70}\n")

    conversation_id = str(uuid.uuid4())
    print(f"conversation_id: {conversation_id}")
    print(f"customer_phone:  {CUSTOMER_PHONE}")
    print(f"timestamp:       {datetime.now(UTC).isoformat()}\n")

    r_str = await aioredis.from_url(
        f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/0",
        decode_responses=True,
    )

    # 1. Subscribe BEFORE injecting (critical per skill)
    pubsub = r_str.pubsub()
    await pubsub.subscribe(OUTGOING_CHANNEL)
    await asyncio.sleep(0.15)  # let subscription propagate
    print("✓ Subscribed to outgoing_messages\n")

    turns = []
    milestones_hit = []
    bugs_observed = []
    max_turns = 12
    turn_num = 0

    # Turn 1: greeting
    pending_message = "Hola! Quería sacar turno"
    # Turn 2 will be: "Un corte caballero con Luciana, esta semana a la mañana"
    turn_2_sent = False
    flow_complete = False

    async def do_turn(user_msg: str) -> dict:
        nonlocal turn_num
        turn_num += 1
        print(f"--- Turn {turn_num} ---")
        print(f"Carlos: {user_msg}")

        payload = {
            "conversation_id": conversation_id,
            "customer_phone": CUSTOMER_PHONE,
            "message_text": user_msg,
            "sender_name": PERSONA_NAME,
            "customer_name": PERSONA_NAME,
            "is_audio_transcription": False,
            "audio_url": None,
        }
        ts_sent = datetime.now(UTC)
        await r_str.xadd(INCOMING_STREAM, {"data": json.dumps(payload)})

        # Capture response
        deadline = asyncio.get_running_loop().time() + RESPONSE_TIMEOUT
        agent_response = None
        timed_out = False

        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                timed_out = True
                break
            raw = await pubsub.get_message(ignore_subscribe_messages=True, timeout=min(remaining, 1.0))
            if raw is None:
                continue
            raw_data = raw.get("data")
            if isinstance(raw_data, bytes):
                raw_data = raw_data.decode("utf-8")
            try:
                pub_payload = json.loads(raw_data)
            except Exception:
                continue
            if pub_payload.get("conversation_id") != conversation_id:
                continue
            agent_response = pub_payload.get("message", "")
            ts_received = datetime.now(UTC)
            break

        if timed_out:
            print(f"Bot: [TIMEOUT after {RESPONSE_TIMEOUT}s]\n")
            return {
                "turn_number": turn_num,
                "user_message": user_msg,
                "agent_response": None,
                "response_latency_ms": -1,
                "timed_out": True,
            }

        latency_ms = int((ts_received - ts_sent).total_seconds() * 1000)
        print(f"Bot:   {agent_response}")
        print(f"       [{latency_ms}ms]\n")

        return {
            "turn_number": turn_num,
            "user_message": user_msg,
            "agent_response": agent_response,
            "response_latency_ms": latency_ms,
            "timed_out": False,
        }

    history = []

    while turn_num < max_turns and not flow_complete:
        turn = await do_turn(pending_message)
        turns.append(turn)

        if turn["timed_out"]:
            bugs_observed.append({"turn": turn_num, "bug": "TIMEOUT", "detail": "No agent response"})
            break

        agent_response = turn["agent_response"] or ""
        history.append({"user": pending_message, "bot": agent_response})
        msg_lower = agent_response.lower()

        # ── Milestone detection ──────────────────────────────────────────────
        if turn_num == 1 and any(kw in msg_lower for kw in ["hola", "bienvenid", "buenas", "¿en qué", "claro", "te ayudo"]):
            if "greeting_done" not in milestones_hit:
                milestones_hit.append("greeting_done")

        if any(kw in msg_lower for kw in ["corte caballero", "corte de caballero"]) and "service_resolved" not in milestones_hit:
            milestones_hit.append("service_resolved")

        if "luciana" in msg_lower and "stylist_locked" not in milestones_hit:
            milestones_hit.append("stylist_locked")

        if any(kw in msg_lower for kw in [
            "lunes", "martes", "miércoles", "jueves", "viernes", "sábado",
            "disponibilidad", "horario disponible",
        ]) and "slot_resolved" not in milestones_hit:
            milestones_hit.append("slot_resolved")

        # Confirmation pending — bot asks to confirm
        if any(kw in msg_lower for kw in ["¿confirmás", "¿confirmas", "confirmar el turno", "¿querés confirmar"]):
            if "confirmation_pending" not in milestones_hit:
                milestones_hit.append("confirmation_pending")

        # booking_completed — only on STRONG completion signals
        booking_done = any(kw in msg_lower for kw in [
            "turno confirmado", "reserva confirmada", "quedó agendado", "quedó confirmado",
            "te esperamos", "nos vemos el", "¡hasta", "booking confirmado",
        ])
        if booking_done and "booking_completed" not in milestones_hit:
            milestones_hit.append("booking_completed")

        # ── Bug detection ────────────────────────────────────────────────────

        # BUG-003: bot asks variant question after "corte caballero" was already stated
        if turn_num >= 2 and any(kw in msg_lower for kw in [
            "caballero, dama", "caballero, niño", "para dama o caballero",
            "es para dama", "es para caballero o", "tipo de corte"
        ]):
            bugs_observed.append({
                "turn": turn_num,
                "bug": "BUG-003",
                "detail": f"Asked variant after 'corte caballero' stated: {agent_response[:120]}"
            })

        # BUG-006: bot greets again after turn 1
        if turn_num > 1 and any(kw in msg_lower for kw in [
            "bienvenido a atrévete", "soy maite, la asistenta", "hola! soy maite",
            "hola, soy maite",
        ]):
            bugs_observed.append({
                "turn": turn_num,
                "bug": "BUG-006",
                "detail": f"Re-greeting on turn {turn_num}: {agent_response[:120]}"
            })

        # ── Flow termination ─────────────────────────────────────────────────
        if booking_done:
            flow_complete = True
            # Send polite ack
            print("Carlos (final ack): Perfecto, gracias!")
            ack_payload = {
                "conversation_id": conversation_id,
                "customer_phone": CUSTOMER_PHONE,
                "message_text": "Perfecto, gracias!",
                "sender_name": PERSONA_NAME,
                "customer_name": PERSONA_NAME,
                "is_audio_transcription": False,
                "audio_url": None,
            }
            await r_str.xadd(INCOMING_STREAM, {"data": json.dumps(ack_payload)})
            await asyncio.sleep(2)
            break

        # ── Next message ─────────────────────────────────────────────────────
        if turn_num == 1:
            # Always send full request on turn 2
            pending_message = "Un corte caballero con Luciana, esta semana a la mañana si se puede"
        else:
            next_reply, should_stop = decide_next_reply(turn_num, agent_response, history)
            pending_message = next_reply
            if should_stop:
                flow_complete = True
                break

    # Close pubsub
    await pubsub.unsubscribe(OUTGOING_CHANNEL)
    await pubsub.aclose()

    # ── DB Verification ──────────────────────────────────────────────────────
    print("\n--- DB Verification ---")
    db_count = 0
    try:
        import asyncpg
        conn = await asyncpg.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
        )
        row = await conn.fetchrow(
            "SELECT count(*) as cnt FROM appointments WHERE created_at > now() - interval '1 hour'"
        )
        db_count = int(row["cnt"])
        print(f"Appointments in last 1h: {db_count}")

        # Also check most recent appointment details
        recent = await conn.fetch(
            """SELECT id, customer_id, stylist_id, start_time, status, created_at
               FROM appointments
               ORDER BY created_at DESC LIMIT 3"""
        )
        for r in recent:
            print(f"  → {dict(r)}")
        await conn.close()
    except Exception as e:
        print(f"DB check error: {e}")
        db_count = -1

    appointment_in_db = db_count > 0

    # ── BUG-001 check: confirm turn fires book() → appointment_in_db ─────────
    if "confirmation_pending" in milestones_hit and not appointment_in_db:
        bugs_observed.append({
            "turn": "post-confirmation",
            "bug": "BUG-001",
            "detail": "Confirmation step reached but no appointment found in DB (book() may not have been called)"
        })

    # ── Final summary ────────────────────────────────────────────────────────
    booking_done = "booking_completed" in milestones_hit
    status = "PASS" if (booking_done and appointment_in_db) else "FAIL"

    print(f"\n{'='*70}")
    print("QA RUN SUMMARY")
    print(f"{'='*70}")
    print(f"Status:            {status}")
    print(f"Turn count:        {turn_num}")
    print(f"Milestones hit:    {milestones_hit}")
    print(f"Bugs observed:     {bugs_observed}")
    print(f"appointment_in_db: {appointment_in_db} (count={db_count})")
    print(f"{'='*70}\n")

    result = {
        "scenario_id": "returning_client",
        "persona_id": "carlos_returning_client",
        "conversation_id": conversation_id,
        "run_timestamp": datetime.now(UTC).isoformat(),
        "status": status,
        "turn_count": turn_num,
        "milestones_hit": milestones_hit,
        "bugs_observed": bugs_observed,
        "appointment_in_db": appointment_in_db,
        "db_appointment_count_last_1h": db_count,
        "turns": turns,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))

    await r_str.aclose()
    return result


if __name__ == "__main__":
    asyncio.run(run_qa())
