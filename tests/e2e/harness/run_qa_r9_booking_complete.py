"""QA Round 9 — booking_complete flow — maria_new_client persona.

Key fix in ef07ffd: slot_selection FSM no longer auto-advances on Turn 1.
It WAITS for explicit user slot pick THEN advances: CUSTOMER_NAME → NOTES → CONFIRMATION → COMPLETED.

State-machine harness strictly follows the QA-R9 spec script:
  T1: "Hola, quiero reservar un corte de cabello para dama el jueves que viene"
  T2 (variant ask): "Dama" / (service list): "El primer servicio"
  T3 (add-ons): "No gracias"
  T4 (stylist): "Sin preferencia, cualquiera"
  T5 (numbered slot list): "1"  ← CRITICAL: must reply "1" when numbered list shown
  T6 (name): "María García"
  T7 (notes): "Sin notas"
  T8 (confirmation): "Sí, confirmo"
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
from shared.redis_client import INCOMING_STREAM
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
        "reserva está confirmada", "tu cita ha sido",
        "cita confirmada", "turno confirmado",
    ])


def pick_response(text: str, turn_num: int) -> str | None:
    """
    State-machine: map bot response content → next user utterance.
    Priority order: most specific triggers first.
    Returns None when done or stuck.

    CRITICAL (ef07ffd): slot list appears BEFORE name/notes/confirmation.
    When bot shows numbered slot list (e.g. "1. 10:00 con Pilar / 2. ..."), reply "1".
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
    if ("niña" in t or "bebé" in t or "bebe" in t) and "dama" in t:
        return "Dama"

    # ── STYLIST LIST with numbered options ──────────────────────────────────
    # Bot shows stylists (Luciana, Pilar) with numbered options including
    # "cualquier profesional" as option 3
    if ("luciana" in t or "pilar" in t) and any(n in t for n in ["3.", "3)"]):
        return "3"  # pick "cualquier profesional"

    # ── SERVICE CATALOG LIST ────────────────────────────────────────────────
    if ("cortar" in t or "corte caballero" in t or "corte niña" in t) and any(
        n in t for n in ["1.", "1)", "2.", "2)"]
    ) and "luciana" not in t and "pilar" not in t and "huecos" not in t:
        if "2." in t and "cortar" in t:
            return "2"
        return "El primer servicio"

    # ── SLOT LIST (numbered time options) — CRITICAL for ef07ffd ────────────
    # Bot shows a NUMBERED list of available slots. Reply "1" to pick the first.
    # Matches patterns like:
    #   "1. 10:00 con Pilar"
    #   "Huecos disponibles: 1. ..."
    #   "①  09:00"
    if any(kw in t for kw in ["huecos disponibles", "próximos huecos", "proximos huecos",
                               "slots disponibles", "horarios disponibles"]):
        return "1"

    # Also detect by numbered time pattern (1. HH:MM or 1) HH:MM)
    if any(n in t for n in ["1.", "1)", "①"]) and any(
        kw in t for kw in ["09:", "10:", "11:", "12:", "13:", "14:", "15:", "16:", "17:"]
    ) and "luciana" not in t and "pilar" not in t:
        # Bot is showing a numbered slot list — pick slot 1
        return "1"

    # ── ADD-ON OFFER ─────────────────────────────────────────────────────────
    if any(kw in t for kw in [
        "add-on", "adicional", "sumar", "agregar servicio",
        "¿deseas agregar", "deseas agregar", "quieres añadir",
        "añadir algún", "agregar algún",
    ]):
        return "No gracias"

    # ── NAME REQUEST ────────────────────────────────────────────────────────
    if any(kw in t for kw in [
        "nombre", "cómo te llamas", "como te llamas",
        "¿a nombre de", "a nombre de", "apellidos", "tu nombre",
    ]):
        return "María García"

    # ── NOTES / PREFERENCES REQUEST ─────────────────────────────────────────
    if any(kw in t for kw in [
        "algo más que deba saber", "algo mas que deba saber",
        "preferencia especial", "condición en tu cabello",
        "nota", "comentario", "algún detalle",
        "algo más antes", "algo mas antes",
        "algo que deba", "algo que quieras",
        "dejar alguna", "añadir nota",
    ]):
        return "Sin notas"

    # ── CONFIRMATION REQUEST ─────────────────────────────────────────────────
    if any(kw in t for kw in [
        "confirma", "¿confirmas", "confirmás", "¿confirmás",
        "¿todo correcto", "todo correcto", "es correcto",
        "¿está bien", "esta bien", "¿confirmamos",
        "¿es correcto", "resumen de tu reserva",
        "¿te confirmo", "te confirmo",
    ]):
        return "Sí, confirmo"

    # ── YES/NO SLOT CONFIRMATION (bot offers specific slot and asks if it's ok) ─
    if any(kw in t for kw in [
        "¿te viene bien", "te viene bien",
        "¿te parece bien", "te parece bien",
        "¿te va bien", "te va bien",
        "¿aceptas", "aceptas este",
        "¿quedamos el", "quedamos el",
    ]):
        return "Sí"

    # ── DATE/TIME REQUEST (open-ended) ────────────────────────────────────────
    if any(kw in t for kw in [
        "qué día", "que dia", "qué hora", "que hora",
        "cuándo", "cuando te", "qué fecha", "que fecha",
        "día y hora", "dia y hora",
        "te vendría mejor", "te viene mejor",
    ]) and "huecos" not in t:
        return "El jueves que viene"

    # ── FALLBACK: numbered list without clear context ────────────────────────
    if any(n in t for n in ["1.", "1)", "①", "2.", "2)", "②"]):
        return "1"

    return None


async def run_qa():
    settings = get_settings()
    conversation_id = str(uuid.uuid4())
    print(f"\n{'='*60}")
    print(f"QA Round 9 — booking_complete flow")
    print(f"Persona: maria_new_client ({PERSONA_NAME})")
    print(f"Conversation ID: {conversation_id}")
    print(f"Started: {datetime.now(UTC).isoformat()}")
    print(f"Commit: ef07ffd")
    print(f"{'='*60}\n")

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
    # T1 fixed opening per spec
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


async def get_agent_logs(conversation_id: str) -> list[str]:
    """Fetch last agent container logs to extract booking_step progression."""
    import subprocess
    result = subprocess.run(
        ["docker", "compose", "logs", "--no-color", "--tail=200", "agent"],
        capture_output=True, text=True,
        cwd="/home/pcabeza/Proyectos/atrevete-bot"
    )
    lines = result.stdout.splitlines()
    # Filter lines relevant to this conversation
    relevant = [l for l in lines if conversation_id[:8] in l or "booking_step" in l.lower()
                or "book(" in l or "manage_customer" in l or "slot_selection" in l.lower()
                or "CUSTOMER_NAME" in l or "CONFIRMATION" in l or "COMPLETED" in l]
    return relevant


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

    # Agent log inspection
    print(f"\n{'='*60}")
    print("AGENT LOG INSPECTION (booking_step progression)")
    print(f"{'='*60}")
    try:
        log_lines = await get_agent_logs(conversation_id)
        for line in log_lines:
            print(line)
    except Exception as e:
        print(f"Log check failed: {e}")
        log_lines = []

    # Milestones
    milestones_hit = []
    all_responses = " ".join(t.get("agent_response", "") for t in turns).lower()
    all_user = " ".join(t.get("user_message", "") for t in turns).lower()

    if turns:
        milestones_hit.append("greeting_done")
    if "dama" in all_responses or "cortar" in all_responses or "corte" in all_responses:
        milestones_hit.append("service_identified")
    if any(kw in all_responses for kw in ["luciana", "pilar", "cualquier", "sin preferencia"]):
        milestones_hit.append("stylist_resolved")
    if any(d in all_responses for d in ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "huecos disponibles", "proximos huecos"]):
        milestones_hit.append("slot_offered")
    if "1" in all_user or "primero" in all_user or "el jueves" in all_user:
        milestones_hit.append("slot_selected")
    if any(kw in all_responses for kw in ["nombre", "cómo te llamas", "como te llamas"]):
        milestones_hit.append("name_asked")
    if "maría garcía" in all_user or "maria garcia" in all_user:
        milestones_hit.append("name_provided")
    if "sin notas" in all_user:
        milestones_hit.append("notes_provided")
    if "sí, confirmo" in all_user or "si, confirmo" in all_user:
        milestones_hit.append("confirmation_done")
    if booking_completed or appointment_in_db:
        milestones_hit.append("booking_completed")

    # booking_step progression from logs
    booking_steps = []
    for line in log_lines:
        for step in ["SLOT_SELECTION", "CUSTOMER_NAME", "NOTES", "CONFIRMATION", "COMPLETED",
                     "SERVICE_SELECTION", "STYLIST_SELECTION", "ADDON_OFFER", "DATE_SELECTION"]:
            if step in line and step not in booking_steps:
                booking_steps.append(step)

    status = "PASS" if (booking_completed and appointment_in_db) else "FAIL"

    print(f"\n{'='*60}")
    print("QA RESULT")
    print(f"{'='*60}")
    print(f"Status: {status}")
    print(f"Turn count: {len(turns)}")
    print(f"Milestones hit: {milestones_hit}")
    print(f"Booking completed (signal): {booking_completed}")
    print(f"Appointment in DB: {appointment_in_db}")
    print(f"Booking step progression: {booking_steps}")

    print(f"\n{'='*60}")
    print("FULL CONVERSATION TRACE")
    print(f"{'='*60}")
    for t in turns:
        print(json.dumps(t, ensure_ascii=False, indent=2, default=str))

    result = {
        "qa_round": "QA-R9",
        "flow_id": "booking_complete",
        "persona_id": "maria_new_client",
        "conversation_id": conversation_id,
        "commit": "ef07ffd",
        "status": status,
        "turn_count": len(turns),
        "milestones_hit": milestones_hit,
        "booking_step_progression": booking_steps,
        "appointment_created": booking_completed,
        "appointment_in_db": appointment_in_db,
        "turns": turns,
    }
    print(f"\n--- STRUCTURED RESULT ---")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return result


if __name__ == "__main__":
    asyncio.run(main())
