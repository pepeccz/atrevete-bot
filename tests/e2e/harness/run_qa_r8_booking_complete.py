"""QA Round 8 — booking_complete flow — maria_new_client persona.

State-machine harness that strictly follows the spec script.
Responses are chosen based on what the bot ACTUALLY says, not scripted slots.
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
from tests.e2e.harness.redis_harness import RedisTestHarness

PERSONA_NAME = "María García"
PHONE = "+34600000099"
MAX_TURNS = 15


def is_booking_completed(text: str) -> bool:
    """Check if bot confirms booking creation."""
    t = text.lower()
    return any(kw in t for kw in [
        "turno confirmado", "cita confirmada", "reserva confirmada",
        "quedó agendad", "quedo agendad", "quedó reservad", "quedo reservad",
        "agendamos tu", "✅", "turno el martes", "turno el jueves",
        "tu turno el", "tu cita el", "cita el martes", "cita el jueves",
        "tu reserva está confirmada", "tu reserva quedo confirmada",
    ])


def pick_response(text: str) -> str | None:
    """
    State-machine: map bot response content → next user utterance.
    Priority order: most specific triggers first.
    Returns None when done or stuck.
    """
    t = text.lower()

    # ── TERMINAL: booking done ───────────────────────────────────────────────
    if is_booking_completed(text):
        return None

    # ── CANCELLATION confusion ───────────────────────────────────────────────
    if "cancelar la reserva" in t or "seguro que quieres cancelar" in t:
        return "no"

    # ── ERROR — retry ────────────────────────────────────────────────────────
    if any(kw in t for kw in ["tuve un problema", "ocurrió un error", "error al", "no pude"]):
        return "Por favor intenta de nuevo"

    # ── CATEGORY ASK (dama/niña/bebé) ───────────────────────────────────────
    # Bot asks whether cut is for dama, niña, or bebé
    if ("niña" in t or "bebé" in t or "bebe" in t) and "dama" in t:
        return "Dama"

    # ── STYLIST LIST with numbered options ──────────────────────────────────
    # Bot shows stylists (Luciana, Pilar) with numbered options including
    # "cualquier profesional" as option 3
    if ("luciana" in t or "pilar" in t) and any(n in t for n in ["3.", "3)"]):
        return "3"  # pick "cualquier profesional"

    # ── SERVICE CATALOG LIST ────────────────────────────────────────────────
    # Bot shows numbered service options (Corte de Hombre, Cortar, etc.)
    # We already confirmed "Dama" but bot still shows catalog (re-ask after category skip)
    # Pick "Cortar" (option 2) as the generic ladies' haircut
    if ("cortar" in t or "corte caballero" in t or "corte niña" in t) and any(
        n in t for n in ["1.", "1)", "2.", "2)"]
    ) and "luciana" not in t and "pilar" not in t:
        # Bot is showing service catalog - pick "Cortar" (usually option 2)
        # or option 1 if that's what's available for dama
        if "2." in t and "cortar" in t:
            return "2"  # "Cortar" is the dama service
        return "1"

    # ── YES/NO SLOT CONFIRMATION (bot offers specific slot and asks if it's ok) ─
    # "¿Te viene bien esa fecha y hora?" / "¿Te parece bien el martes...?"
    if any(kw in t for kw in [
        "¿te viene bien", "te viene bien",
        "¿te parece bien", "te parece bien",
        "¿te va bien", "te va bien",
        "¿aceptas", "aceptas este",
        "¿quedamos el", "quedamos el",
    ]):
        return "Sí"

    # ── DATE/TIME REQUEST (open-ended: "qué día y hora") ────────────────────
    # Bot chose stylist/service and now asks for preferred day/time
    # May also mention the next available slot as a hint
    if any(kw in t for kw in [
        "qué día", "que dia", "qué hora", "que hora",
        "cuándo", "cuando te", "qué fecha", "que fecha",
        "día y hora", "dia y hora",
        "te vendría mejor", "te viene mejor",
    ]) and "huecos" not in t:
        # If bot hints at a specific date/time, just confirm that
        return "El martes que viene a las 10"

    # ── SLOT LIST (numbered time options) ───────────────────────────────────
    # Bot shows numbered time slots
    if any(kw in t for kw in ["huecos disponibles", "próximos huecos", "proximos huecos"]) or (
        any(n in t for n in ["1.", "1)", "①"]) and
        any(kw in t for kw in ["10:00", "10:40", "11:20", "09:", "11:", "12:", "14:", "15:", "16:"])
    ):
        return "1"

    # ── NOTES / PREFERENCES REQUEST ─────────────────────────────────────────
    # "¿Hay algo más que deba saber tu estilista antes de la cita?"
    if any(kw in t for kw in [
        "algo más que deba saber", "algo mas que deba saber",
        "preferencia especial", "condición en tu cabello",
        "nota", "comentario", "algún detalle",
        "algo más antes", "algo mas antes",
        "algo que deba", "algo que quieras",
    ]):
        return "Sin notas"

    # ── NAME REQUEST ────────────────────────────────────────────────────────
    if any(kw in t for kw in [
        "nombre", "cómo te llamas", "como te llamas",
        "¿a nombre de", "a nombre de", "apellidos"
    ]):
        return "María García"

    # ── CONFIRMATION REQUEST ─────────────────────────────────────────────────
    if any(kw in t for kw in [
        "confirma", "¿confirmas", "confirmás", "¿confirmás",
        "¿todo correcto", "todo correcto", "es correcto",
        "¿está bien", "esta bien", "¿confirmamos",
    ]):
        return "Sí, confirmo"

    # ── ADD-ON OFFER ─────────────────────────────────────────────────────────
    if any(kw in t for kw in [
        "add-on", "adicional", "sumar", "agregar servicio",
        "¿deseas agregar", "deseas agregar", "quieres añadir",
    ]):
        return "No gracias"

    # ── VAGUE CONTINUATION responses ─────────────────────────────────────────
    # Bot says something like "de acuerdo, continuemos" without a clear question
    # After name was given, most likely next is notes or confirmation
    if any(kw in t for kw in [
        "continuemos con tu reserva", "continuemos con la reserva",
        "de acuerdo", "entendido", "perfecto", "genial",
    ]) and not any(kw in t for kw in [
        "elegido", "seleccionado", "has elegido", "has seleccionado"
    ]):
        # Try notes as next logical step
        return "Sin notas"

    # ── FALLBACK: numbered list without clear context ────────────────────────
    if any(n in t for n in ["1.", "1)", "①", "2.", "2)", "②"]):
        return "1"

    return None


async def run_qa():
    settings = get_settings()
    conversation_id = str(uuid.uuid4())
    print(f"\n{'='*60}")
    print("QA Round 8 — booking_complete flow")
    print(f"Persona: maria_new_client ({PERSONA_NAME})")
    print(f"Conversation ID: {conversation_id}")
    print(f"Started: {datetime.now(UTC).isoformat()}")
    print(f"{'='*60}\n")

    # Use localhost since we're running from host
    redis_password = settings.REDIS_PASSWORD
    if redis_password:
        redis_url = f"redis://:{redis_password}@localhost:6379/0"
    else:
        redis_url = "redis://localhost:6379/0"
    print("Connecting to Redis at: localhost:6379/0")
    r = redis.from_url(redis_url, decode_responses=True)
    harness = RedisTestHarness(redis_client=r)

    # CRITICAL: Subscribe BEFORE injecting
    await harness.prepare_response_capture()
    print("✓ Subscribed to outgoing_messages BEFORE injecting\n")

    turns_trace = []
    turn_num = 0
    # T1 fixed opening
    current_message = "Hola, quiero reservar un corte de cabello para dama el jueves que viene"
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
            next_msg = pick_response(agent_response)
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
    if "dama" in all_responses or "cortar" in all_responses or "corte" in all_responses:
        milestones_hit.append("service_identified")
    if any(d in all_responses for d in ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "huecos disponibles"]):
        milestones_hit.append("slot_offered")
    if "1" in all_user or "primero" in all_user or "el jueves" in all_user:
        milestones_hit.append("slot_selected")
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
        "qa_round": "QA-R8",
        "flow_id": "booking_complete",
        "persona_id": "maria_new_client",
        "conversation_id": conversation_id,
        "status": status,
        "turn_count": len(turns),
        "milestones_hit": milestones_hit,
        "appointment_created": booking_completed,
        "appointment_in_db": appointment_in_db,
        "turns": turns,
    }
    print("\n--- STRUCTURED RESULT ---")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return result


if __name__ == "__main__":
    asyncio.run(main())
