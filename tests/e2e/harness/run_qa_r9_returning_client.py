"""QA Round 9 — returning_client flow — carlos_returning_client persona.

State-machine harness following the exact spec script:
T1: "Hola, quiero un corte caballero con Luciana esta semana a la mañana"
T2 (variant ask): "Caballero"
T3 (stylist list): "1" (Luciana)
T3 (slots directly): "1"
T4 (numbered slot list): "1"
T5 (add-ons): "No gracias"
T6 (name): "Carlos López"
T7 (notes): "Sin notas"
T8 (confirmation): "Sí, confirmo"
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime

# Add project root to path
sys.path.insert(0, "/home/pcabeza/Proyectos/atrevete-bot")

import redis.asyncio as redis

from shared.config import get_settings
from shared.redis_client import INCOMING_STREAM
from tests.e2e.harness.redis_harness import RedisTestHarness

PERSONA_NAME = "Carlos López"
PHONE = "+34600000011"
MAX_TURNS = 12


def is_booking_completed(text: str) -> bool:
    """Check if bot confirms booking creation."""
    t = text.lower()
    return any(kw in t for kw in [
        "turno confirmado", "cita confirmada", "reserva confirmada",
        "quedó agendad", "quedo agendad", "quedó reservad", "quedo reservad",
        "agendamos tu", "✅", "turno el martes", "turno el lunes",
        "tu turno el", "tu cita el", "cita el martes", "cita el lunes",
        "cita el miércoles", "cita el miercoles", "turno el miércoles",
        "cita el jueves", "turno el jueves", "cita el viernes",
        "tu reserva está confirmada", "tu reserva quedo confirmada",
    ])


def pick_response(text: str, turn_number: int) -> str | None:
    """
    State-machine: map bot response content → next user utterance.
    Follows the exact spec script for returning_client / carlos persona.
    Returns None when done or stuck.
    """
    # Strip markdown asterisks before matching to handle bot's formatting
    t = text.lower().replace("*", "")

    # ── TERMINAL: booking done ───────────────────────────────────────────────
    if is_booking_completed(text):
        return None

    # ── CANCELLATION confusion ───────────────────────────────────────────────
    if "cancelar la reserva" in t or "seguro que quieres cancelar" in t:
        return "no"

    # ── ERROR — retry ────────────────────────────────────────────────────────
    if any(kw in t for kw in ["tuve un problema", "ocurrió un error", "error al", "no pude"]):
        return "Por favor intenta de nuevo"

    # ── CATEGORY ASK (caballero/dama/niña/bebé) ─────────────────────────────
    # Bot asks: "si el corte es para caballero, dama, niño, niña o bebé"
    if ("caballero" in t and "dama" in t) and any(kw in t for kw in [
        "para caballero", "es para caballero", "caballero, dama",
        "caballero o dama", "niño", "niña", "bebé", "bebe"
    ]):
        return "Caballero"

    # ── STYLIST LIST with numbered options ──────────────────────────────────
    # Bot shows stylists list (Luciana, Pilar, etc.) — T3: pick "1" for Luciana
    if ("luciana" in t or "pilar" in t) and any(n in t for n in ["1.", "1)", "2.", "2)"]):
        # Check if it's a stylist picker or slot picker
        # If it mentions "cualquier" or "profesional", it's a stylist picker
        if any(kw in t for kw in [
            "estilista", "profesional", "peluquera", "quién", "quien",
            "con quién", "con quien", "¿con cuál", "con cual"
        ]):
            return "1"  # Luciana is typically option 1
        # If slots are shown (time format HH:MM), pick slot 1
        if any(kw in t for kw in ["10:00", "10:40", "11:", "09:", "08:", "12:", "14:"]):
            return "1"
        # Default: it's a stylist list, pick Luciana = 1
        return "1"

    # ── SLOT LIST (numbered time options) ───────────────────────────────────
    # "1. martes 10:00 / 2. martes 10:40..." → T4: reply "1"
    if any(kw in t for kw in ["huecos disponibles", "próximos huecos", "proximos huecos", "horarios disponibles"]) or (
        any(n in t for n in ["1.", "1)", "①"]) and
        any(kw in t for kw in ["10:00", "10:40", "11:20", "09:", "11:", "12:", "14:", "15:", "16:", "08:"])
    ):
        return "1"

    # ── YES/NO SLOT CONFIRMATION (bot offers specific slot) ─────────────────
    if any(kw in t for kw in [
        "¿te viene bien", "te viene bien",
        "¿te parece bien", "te parece bien",
        "¿te va bien", "te va bien",
        "¿aceptas", "aceptas este",
        "¿quedamos el", "quedamos el",
    ]):
        return "Sí"

    # ── DATE/TIME REQUEST (open-ended) ───────────────────────────────────────
    if any(kw in t for kw in [
        "qué día", "que dia", "qué hora", "que hora",
        "cuándo", "cuando te", "qué fecha", "que fecha",
        "día y hora", "dia y hora",
        "te vendría mejor", "te viene mejor",
        "preferís mañana", "qué mañana",
    ]) and "huecos" not in t:
        return "Esta semana a la mañana"

    # ── NOTES / PREFERENCES REQUEST ─────────────────────────────────────────
    if any(kw in t for kw in [
        "algo más que deba saber", "algo mas que deba saber",
        "preferencia especial", "condición en tu cabello",
        "nota", "comentario", "algún detalle",
        "algo más antes", "algo mas antes",
        "algo que deba", "algo que quieras",
        "alguna indicación", "alguna nota",
    ]):
        return "Sin notas"

    # ── NAME REQUEST ────────────────────────────────────────────────────────
    if any(kw in t for kw in [
        "nombre", "cómo te llamas", "como te llamas",
        "¿a nombre de", "a nombre de", "apellidos",
        "tu nombre", "tu nombre completo",
    ]):
        return "Carlos López"

    # ── CONFIRMATION REQUEST ─────────────────────────────────────────────────
    if any(kw in t for kw in [
        "confirma", "¿confirmas", "confirmás", "¿confirmás",
        "¿todo correcto", "todo correcto", "es correcto",
        "¿está bien", "esta bien", "¿confirmamos", "confirmar",
        "¿confirmamos la", "¿es correcto",
    ]):
        return "Sí, confirmo"

    # ── ADD-ON OFFER ─────────────────────────────────────────────────────────
    if any(kw in t for kw in [
        "add-on", "adicional", "sumar", "agregar servicio",
        "¿deseas agregar", "deseas agregar", "quieres añadir",
        "barba", "afeitado", "tintura", "tratamiento",
    ]):
        return "No gracias"

    # ── VAGUE CONTINUATION ───────────────────────────────────────────────────
    if any(kw in t for kw in [
        "continuemos con tu reserva", "continuemos con la reserva",
        "de acuerdo, continuemos", "entendido, continuemos",
    ]):
        return "Sin notas"

    # ── FALLBACK: numbered list ──────────────────────────────────────────────
    if any(n in t for n in ["1.", "1)", "①", "2.", "2)", "②"]):
        return "1"

    return None


async def run_qa():
    settings = get_settings()
    conversation_id = str(uuid.uuid4())
    print(f"\n{'='*60}")
    print(f"QA Round 9 — returning_client flow")
    print(f"Persona: carlos_returning_client ({PERSONA_NAME})")
    print(f"Conversation ID: {conversation_id}")
    print(f"Started: {datetime.now(UTC).isoformat()}")
    print(f"{'='*60}\n")

    # Use localhost since we're running from host
    redis_password = settings.REDIS_PASSWORD
    if redis_password:
        redis_url = f"redis://:{redis_password}@localhost:6379/0"
    else:
        redis_url = "redis://localhost:6379/0"
    print(f"Connecting to Redis at: localhost:6379/0")
    r = redis.from_url(redis_url, decode_responses=True)
    harness = RedisTestHarness(redis_client=r)

    # CRITICAL: Subscribe BEFORE injecting
    await harness.prepare_response_capture()
    print("✓ Subscribed to outgoing_messages BEFORE injecting\n")

    turns_trace = []
    turn_num = 0
    # T1 fixed opening — spec harness instruction
    current_message = "Hola, quiero un corte caballero con Luciana esta semana a la mañana"
    booking_completed = False

    try:
        while turn_num < MAX_TURNS:
            turn_num += 1
            print(f"--- Turn {turn_num} ---")
            print(f"USER: {current_message}")

            result = await harness.execute_turn(
                conversation_id=conversation_id,
                user_message=current_message,
                persona_name=PERSONA_NAME,
                timeout=35.0,
                customer_phone=PHONE,
            )
            agent_response = result["agent_response"]
            latency = result["response_latency_ms"]
            print(f"BOT ({latency}ms): {agent_response}")
            print()

            turns_trace.append({
                "turn_number": turn_num,
                "user_message": current_message,
                "agent_response": agent_response,
                "response_latency_ms": latency,
            })

            # Check for booking completion
            if is_booking_completed(agent_response):
                print("✅ Booking completion signal detected!")
                booking_completed = True
                break

            # Determine next message from state machine
            next_msg = pick_response(agent_response, turn_num)
            if next_msg is None:
                print("⚠️  Could not determine next message — ending flow")
                break

            current_message = next_msg

    except TimeoutError as e:
        print(f"\n⏱️  TIMEOUT: {e}")
        turns_trace.append({"turn_number": turn_num, "error": "TIMEOUT", "details": str(e)})
    finally:
        await harness.close()
        await r.aclose()

    return conversation_id, turns_trace, booking_completed


async def check_db() -> dict:
    """Check DB for appointments created in last hour."""
    import asyncpg

    settings = get_settings()
    dsn = settings.DATABASE_URL.replace("+asyncpg", "").replace("postgresql+psycopg", "postgresql")
    dsn = dsn.replace("@postgres:", "@localhost:")
    conn = await asyncpg.connect(dsn)
    try:
        count_row = await conn.fetchrow(
            "SELECT count(*) as cnt FROM appointments WHERE created_at > now() - interval '1 hour'"
        )
        count = count_row["cnt"]
        recent = await conn.fetch(
            """SELECT id, customer_id, stylist_id, service_ids, start_time, duration_minutes, status, created_at
               FROM appointments
               WHERE created_at > now() - interval '1 hour'
               ORDER BY created_at DESC
               LIMIT 5"""
        )
        return {
            "count_last_hour": count,
            "recent_appointments": [dict(r) for r in recent],
        }
    finally:
        await conn.close()


async def main():
    conversation_id, turns, booking_completed = await run_qa()

    print(f"\n{'='*60}")
    print("CONVERSATION TRACE SUMMARY")
    print(f"{'='*60}")
    print(f"Total turns executed: {len(turns)}")
    print(f"Booking completion signal: {booking_completed}")

    # DB check
    print(f"\n{'='*60}")
    print("DATABASE CHECK")
    print(f"{'='*60}")
    try:
        db_result = await check_db()
        print(f"Appointments in last hour: {db_result['count_last_hour']}")
        if db_result["recent_appointments"]:
            print("Recent appointments:")
            for appt in db_result["recent_appointments"]:
                print(f"  - ID: {appt['id']}, start_time: {appt.get('start_time')}, status: {appt['status']}")
    except Exception as e:
        print(f"DB check failed: {e}")
        db_result = {"count_last_hour": -1, "error": str(e)}

    appointment_in_db = db_result.get("count_last_hour", 0) > 0

    # Milestones
    milestones_hit = []
    all_responses = " ".join(t.get("agent_response", "") for t in turns).lower()
    all_user = " ".join(t.get("user_message", "") for t in turns).lower()

    if turns:
        milestones_hit.append("greeting_done")
    if "luciana" in all_responses:
        milestones_hit.append("stylist_locked")
    if "caballero" in all_responses or "corte caballero" in all_responses:
        milestones_hit.append("service_resolved")
    if any(d in all_responses for d in ["lunes", "martes", "miércoles", "jueves", "viernes", "huecos disponibles"]):
        milestones_hit.append("slot_offered")
    if "1" in all_user or "primero" in all_user:
        milestones_hit.append("slot_resolved")
    if "sin notas" in all_user:
        milestones_hit.append("notes_provided")
    if "sí, confirmo" in all_user or "si, confirmo" in all_user:
        milestones_hit.append("confirmation_done")
    if booking_completed or appointment_in_db:
        milestones_hit.append("booking_completed")

    status = "PASS" if (booking_completed and appointment_in_db) else "FAIL"

    print(f"\n{'='*60}")
    print("QA RESULT")
    print(f"{'='*60}")
    print(f"Status: {status}")
    print(f"Turn count: {len(turns)}")
    print(f"Milestones hit: {milestones_hit}")
    print(f"Booking completed (signal): {booking_completed}")
    print(f"Appointment in DB: {appointment_in_db}")

    print(f"\n{'='*60}")
    print("FULL CONVERSATION TRACE")
    print(f"{'='*60}")
    for t in turns:
        print(json.dumps(t, ensure_ascii=False, indent=2, default=str))

    result = {
        "qa_round": "QA-R9",
        "flow_id": "returning_client",
        "persona_id": "carlos_returning_client",
        "conversation_id": conversation_id,
        "status": status,
        "turn_count": len(turns),
        "milestones_hit": milestones_hit,
        "appointment_created": booking_completed,
        "appointment_in_db": appointment_in_db,
        "turns": turns,
    }
    print(f"\n--- STRUCTURED RESULT ---")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return result


if __name__ == "__main__":
    asyncio.run(main())
