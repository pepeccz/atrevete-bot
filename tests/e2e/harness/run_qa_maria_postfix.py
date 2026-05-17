"""QA Post-Fix Retest — María García — Happy-Path Booking.

Validates the fixes from commits adfc018, ce56c4b, 55ab710, 57ee48a, ef07ffd:
  - Slots offered are ACTUALLY available (no SLOT_TAKEN errors)
  - Booking confirms on first attempt
  - No infinite retry loops
  - Clean FSM flow from greeting to booking_confirmed

Persona: María García — new client, corte de dama, no stylist preference.
Phone: +34612345678

Expected outcome: booking_confirmed in <=8 turns, appointment in DB.
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime

sys.path.insert(0, "/home/pcabeza/Proyectos/atrevete-bot")

import redis.asyncio as redis

from shared.config import get_settings
from tests.e2e.harness.redis_harness import RedisTestHarness

PERSONA_NAME = "María García"
PHONE = "+34612345678"
MAX_TURNS = 15


def is_booking_completed(text: str) -> bool:
    """Check if bot confirms booking creation."""
    t = text.lower()
    if any(excl in t for excl in [
        "casi lista", "solo necesito", "me das tu nombre", "último paso",
        "siguiente paso", "un momento", "buscando",
    ]):
        return False
    return any(kw in t for kw in [
        "turno confirmado", "cita confirmada", "reserva confirmada",
        "quedó agendad", "quedo agendad", "quedó reservad", "quedo reservad",
        "agendamos tu", "✅",
        "tu reserva está confirmada", "tu reserva quedo confirmada",
        "reserva está confirmada", "tu cita ha sido confirmada",
        "cita ha sido confirmada", "turno ha sido confirmado",
        "te esperamos", "nos vemos el",
    ])


def is_slot_taken(text: str) -> bool:
    """Detect if bot reports a slot collision."""
    t = text.lower()
    return any(kw in t for kw in [
        "acaba de ser reservado", "ya está ocupado", "ya no está disponible",
        "slot taken", "slot_taken", "horario acaba",
    ])


def pick_response(text: str, turn_num: int) -> str | None:
    """Map bot response → next user utterance."""
    t = text.lower()

    if is_booking_completed(text):
        return None

    # Error / slot taken — retry
    if is_slot_taken(text):
        return "Sí, busquemos otra opción"

    if any(kw in t for kw in ["tuve un problema", "ocurrió un error", "error al",
                               "no pude", "problema técnico"]):
        return "Intenta de nuevo"

    # Escalation offer (dead end)
    if "conecte con" in t or "equipo" in t and "ayuden" in t:
        return None

    # Category ask (dama/niña/bebé)
    if ("niña" in t or "bebé" in t or "bebe" in t) and "dama" in t:
        return "Dama"

    # Availability confirmation prompt
    if "busquemos disponibilidad" in t or "buscar disponibilidad" in t:
        return "Sí, dale"

    # Numbered slot list with times
    if any(n in t for n in ["1.", "1)", "①"]) and any(
        kw in t for kw in ["09:", "10:", "11:", "12:", "13:", "14:", "15:", "16:", "17:"]
    ):
        return "La primera opción"

    # Stylist list
    if ("luciana" in t or "pilar" in t) and any(n in t for n in ["2.", "3."]) and not any(
        kw in t for kw in ["09:", "10:", "11:", "12:", "13:", "14:", "15:", "16:", "17:"]
    ):
        return "Sin preferencia, cualquiera"

    # Service catalog
    if ("cortar" in t or "corte" in t) and any(n in t for n in ["1.", "1)"]):
        return "El primero"

    # Add-on offer
    if any(kw in t for kw in ["adicional", "agregar", "add-on", "tratamiento", "sumar"]):
        return "No gracias"

    # Name request
    if any(kw in t for kw in ["nombre", "cómo te llamas", "como te llamas",
                               "a nombre de", "tu nombre"]):
        return "María García"

    # Notes
    if any(kw in t for kw in ["algo más", "algo mas", "nota", "comentario", "detalle"]):
        return "Sin notas"

    # Confirmation
    if any(kw in t for kw in ["confirma", "¿confirmas", "confirmás", "¿confirmás",
                               "todo correcto", "es correcto", "¿confirmamos",
                               "te confirmo", "resumen", "procedemos"]):
        return "Sí, confirmo"

    # Yes/no slot confirmation
    if any(kw in t for kw in ["te viene bien", "te parece bien", "te va bien"]):
        return "Sí"

    # Date request
    if any(kw in t for kw in ["qué día", "que dia", "qué hora", "cuándo", "cuando"]):
        return "El jueves que viene"

    # Fallback numbered list
    if any(n in t for n in ["1.", "1)", "2."]):
        return "1"

    return None


async def run_qa():
    settings = get_settings()
    conversation_id = str(uuid.uuid4())
    print(f"\n{'='*60}")
    print("QA Post-Fix Retest — María García Happy Path")
    print(f"Persona: {PERSONA_NAME} | Phone: {PHONE}")
    print(f"Conversation ID: {conversation_id}")
    print(f"Started: {datetime.now(UTC).isoformat()}")
    print(f"{'='*60}\n")

    redis_password = settings.REDIS_PASSWORD
    redis_url = f"redis://:{redis_password}@localhost:6379/0" if redis_password else "redis://localhost:6379/0"
    r = redis.from_url(redis_url, decode_responses=True)
    harness = RedisTestHarness(redis_client=r)

    await harness.prepare_response_capture()
    print("Subscribed to outgoing_messages\n")

    turns_trace = []
    turn_num = 0
    current_message = "Hola, quiero un corte de cabello para dama"
    booking_completed = False
    slot_taken_count = 0

    try:
        while turn_num < MAX_TURNS:
            turn_num += 1
            print(f"--- Turn {turn_num} ---")
            print(f"USER: {current_message}")

            result = await harness.execute_turn(
                conversation_id=conversation_id,
                user_message=current_message,
                persona_name=PERSONA_NAME,
                timeout=45.0,
                customer_phone=PHONE,
            )
            agent_response = result["agent_response"]
            latency = result["response_latency_ms"]
            print(f"BOT ({latency}ms): {agent_response}\n")

            turns_trace.append({
                "turn_number": turn_num,
                "user_message": current_message,
                "agent_response": agent_response,
                "response_latency_ms": latency,
            })

            if is_slot_taken(agent_response):
                slot_taken_count += 1

            if is_booking_completed(agent_response):
                print("BOOKING CONFIRMED!")
                booking_completed = True
                break

            next_msg = pick_response(agent_response, turn_num)
            if next_msg is None:
                print("No valid next message — ending flow")
                break

            current_message = next_msg

    except TimeoutError as e:
        print(f"\nTIMEOUT: {e}")
        turns_trace.append({"turn_number": turn_num, "error": "TIMEOUT", "details": str(e)})
    finally:
        await harness.close()
        await r.aclose()

    return conversation_id, turns_trace, booking_completed, slot_taken_count


async def check_db() -> dict:
    """Check DB for appointments from this phone."""
    import asyncpg

    settings = get_settings()
    dsn = settings.DATABASE_URL.replace("+asyncpg", "").replace("postgresql+psycopg", "postgresql")
    dsn = dsn.replace("@postgres:", "@localhost:")
    conn = await asyncpg.connect(dsn)
    try:
        recent = await conn.fetch(
            """SELECT a.id, st.name as stylist, a.start_time, a.status, a.first_name
               FROM appointments a
               JOIN stylists st ON a.stylist_id = st.id
               JOIN customers c ON a.customer_id = c.id
               WHERE c.phone = $1
               ORDER BY a.created_at DESC
               LIMIT 3""",
            PHONE,
        )
        return {
            "count": len(recent),
            "appointments": [dict(r) for r in recent],
        }
    finally:
        await conn.close()


async def main():
    conversation_id, turns, booking_completed, slot_taken_count = await run_qa()

    print(f"\n{'='*60}")
    print("DATABASE CHECK")
    print(f"{'='*60}")
    try:
        db_result = await check_db()
        print(f"Appointments for {PHONE}: {db_result['count']}")
        for appt in db_result["appointments"]:
            print(f"  - stylist={appt['stylist']}, start={appt['start_time']}, "
                  f"status={appt['status']}, name={appt['first_name']}")
    except Exception as e:
        print(f"DB check failed: {e}")
        db_result = {"count": 0}

    appointment_in_db = db_result.get("count", 0) > 0

    # Critical checks
    print(f"\n{'='*60}")
    print("CRITICAL CHECKS")
    print(f"{'='*60}")
    checks = {
        "no_slot_taken_errors": slot_taken_count == 0,
        "booking_confirmed_first_attempt": booking_completed and slot_taken_count == 0,
        "no_infinite_retry": len(turns) <= 10,
        "clean_fsm_flow": booking_completed,
        "appointment_in_db": appointment_in_db,
    }
    for check, passed in checks.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {check}")

    overall = "PASS" if all(checks.values()) else "FAIL"
    print(f"\nOverall: {overall}")
    print(f"Turns: {len(turns)}")
    print(f"Slot-taken errors: {slot_taken_count}")

    result = {
        "qa_test": "maria-postfix-retest",
        "conversation_id": conversation_id,
        "status": overall,
        "turn_count": len(turns),
        "booking_completed": booking_completed,
        "appointment_in_db": appointment_in_db,
        "slot_taken_count": slot_taken_count,
        "checks": checks,
        "turns": turns,
    }
    print("\n--- STRUCTURED RESULT ---")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return result


if __name__ == "__main__":
    asyncio.run(main())
