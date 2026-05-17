"""QA Round 11 — indecision flow — luis_indecisive_client persona.

Harness script per spec:
  T1: "Hola, soy hombre y quiero verme más prolijo, ¿qué me recomendás?"
  (shows service list) → "Quiero el corte caballero"
  (asks to confirm service) → "Sí, ese servicio"
  (asks add-ons) → "No, solo el corte"
  (asks stylist) → "Cualquiera disponible"
  (NUMBERED SLOT LIST shown) → "1"
  (asks name) → "Luis Martínez"
  (asks notes) → "Sin notas"
  (shows confirmation) → "Sí, confirmo"
  (error) → "Intenta de nuevo"

Expected outcome: recommendation_provided=true AND appointment_created=true AND appointment_in_db=true
Commit: 55ab710
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

PERSONA_NAME = "Luis Martínez"
PHONE = "+34600000099"  # fresh phone for R11
MAX_TURNS = 18


def is_booking_completed(text: str) -> bool:
    """Check if bot confirms booking creation — STRICT: must be final confirmation."""
    t = text.lower()
    # Exclude intermediate steps
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


def pick_response(text: str, turn_num: int, state: dict) -> str | None:
    """
    State-machine: map bot response content → next user utterance.
    Follows exact spec harness for luis_indecisive_client / indecision flow.
    Returns None when done or stuck.

    Key logic:
    - T1 is open-ended ("qué me recomendás") → bot should provide recommendations
    - When bot shows service list → "Quiero el corte caballero" (name, not number)
    - When bot asks to confirm service → "Sí, ese servicio"
    - Add-ons → "No, solo el corte"
    - Stylist → "Cualquiera disponible"
    - NUMBERED SLOT LIST → "1"
    - Name → "Luis Martínez"
    - Notes → "Sin notas"
    - Confirmation → "Sí, confirmo"
    - Error → "Intenta de nuevo"
    """
    # Strip markdown before matching
    t = text.lower().replace("*", "")

    # ── TERMINAL: booking done ───────────────────────────────────────────────
    if is_booking_completed(text):
        return None

    # ── CANCELLATION confusion ───────────────────────────────────────────────
    if "cancelar la reserva" in t or "seguro que quieres cancelar" in t:
        return "no"

    # ── ERROR — retry ────────────────────────────────────────────────────────
    if any(kw in t for kw in ["tuve un problema", "ocurrió un error", "error al", "no pude"]):
        return "Intenta de nuevo"

    # ── SLOT LIST (numbered time options) — check BEFORE stylist list ─────────
    # Bot shows numbered list of available slots
    if any(kw in t for kw in ["huecos disponibles", "próximos huecos", "proximos huecos",
                               "slots disponibles", "horarios disponibles",
                               "huecos libres"]):
        return "1"

    # Detect numbered time pattern (1. HH:MM or 1) HH:MM) — slot list
    if any(n in t for n in ["1.", "1)", "①"]) and any(
        kw in t for kw in ["09:", "10:", "11:", "12:", "13:", "14:", "15:", "16:", "17:"]
    ):
        return "1"

    # ── STYLIST LIST with numbered options ──────────────────────────────────
    if ("luciana" in t or "pilar" in t) and any(n in t for n in ["1.", "1)", "2.", "2)"]) and not any(
        kw in t for kw in ["09:", "10:", "11:", "12:", "13:", "14:", "15:", "16:", "17:"]
    ):
        return "Cualquiera disponible"

    # ── STYLIST ASK (open-ended, no list) ───────────────────────────────────
    if any(kw in t for kw in [
        "estilista", "peluquera", "profesional", "con quién", "con quien",
        "preferís alguna", "preferís a", "alguna estilista",
        "¿con cuál", "¿qué estilista",
    ]) and not any(kw in t for kw in ["huecos", "09:", "10:", "11:", "12:", "13:", "14:", "15:"]):
        return "Cualquiera disponible"

    # ── SERVICE CONFIRMATION (bot asks to confirm specific service) ──────────
    # After bot has shown a recommendation and asks to confirm
    if any(kw in t for kw in [
        "¿es ese el servicio", "¿ese es el servicio", "confirmar el servicio",
        "¿confirmamos el", "¿elegís el", "elegís el corte",
        "¿procedemos con el", "procedemos con el corte",
        "¿te parece bien el corte", "¿te parece bien ese",
        "¿seguimos con el corte", "seguimos con el corte",
    ]):
        return "Sí, ese servicio"

    # ── SERVICE CATALOG LIST (bot shows numbered service list) ──────────────
    # Bot shows numbered service list: "1. Corte caballero / 2. ..."
    # Use service NAME per spec (not number)
    if any(kw in t for kw in ["corte caballero", "caballero"]) and any(
        n in t for n in ["1.", "1)", "2.", "2)"]
    ) and "huecos" not in t and not any(
        kw in t for kw in ["09:", "10:", "11:", "12:", "13:", "14:", "15:", "16:", "17:"]
    ) and not state.get("service_selected"):
        state["service_selected"] = True
        return "Quiero el corte caballero"

    # ── RECOMMENDATION / GREETING (first response with guidance) ────────────
    # Bot provides recommendations before showing service list
    if not state.get("service_selected") and any(kw in t for kw in [
        "recomend", "prolijo", "corte", "caballero", "servicios", "podría",
        "opciones", "para caballero", "para hombre",
    ]) and any(n in t for n in ["1.", "1)", "2.", "2)"]):
        # Bot showed a list with recommendations — pick corte caballero
        state["service_selected"] = True
        return "Quiero el corte caballero"

    # ── SERVICE RE-ASK (bot asks for service again after we already sent choice) ─
    # If bot asks "qué servicio" or "corte o color" after service already selected
    if state.get("service_selected") and any(kw in t for kw in [
        "qué servicio", "que servicio", "cuál servicio", "cual servicio",
        "qué tipo de servicio", "que tipo de servicio",
        "decime si buscas", "decime si buscás", "buscás un corte",
        "para seguir", "corte o color", "para mujer, hombre", "niño o niña",
    ]):
        return "Quiero el corte caballero"

    # ── NOTES / PREFERENCES REQUEST — MUST come BEFORE add-on check ──────────
    # "nota", "comentario adicional", "algún detalle" → notes step
    if any(kw in t for kw in [
        "algo más que deba saber", "algo mas que deba saber",
        "preferencia especial", "condición en tu cabello",
        "nota", "comentario", "algún detalle",
        "algo más antes", "algo mas antes",
        "algo que deba", "algo que quieras",
        "dejar alguna", "añadir nota",
        "indicación", "instrucción",
        "comentario adicional",
    ]):
        return "Sin notas"

    # ── ADD-ON OFFER (distinct from notes — must contain service keywords) ───
    # "agregar servicio", "deseas agregar", add-on service names
    if any(kw in t for kw in [
        "add-on", "sumar", "agregar servicio",
        "¿deseas agregar", "deseas agregar", "quieres añadir",
        "añadir algún", "agregar algún", "servicio adicional",
        "tratamiento", "masaje", "barba", "afeitado",
    ]) and not any(kw in t for kw in ["nota", "comentario"]):
        return "No, solo el corte"

    # ── NAME REQUEST ────────────────────────────────────────────────────────
    if any(kw in t for kw in [
        "nombre", "cómo te llamas", "como te llamas",
        "¿a nombre de", "a nombre de", "apellidos", "tu nombre",
        "tu nombre completo",
    ]):
        return "Luis Martínez"

    # ── CONFIRMATION REQUEST ─────────────────────────────────────────────────
    if any(kw in t for kw in [
        "confirma", "¿confirmas", "confirmás", "¿confirmás",
        "¿todo correcto", "todo correcto", "es correcto",
        "¿está bien", "esta bien", "¿confirmamos",
        "¿es correcto", "resumen de tu reserva",
        "¿te confirmo", "te confirmo", "resumen",
        "¿procedemos", "procedemos", "confirmar",
    ]):
        return "Sí, confirmo"

    # ── YES/NO SLOT CONFIRMATION ────────────────────────────────────────────
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
        "qué tarde", "viernes", "mañana", "horario",
    ]) and "huecos" not in t:
        return "El viernes a la tarde"

    # ── CATEGORY ASK (caballero/dama) ───────────────────────────────────────
    if ("caballero" in t and "dama" in t) and any(kw in t for kw in [
        "para caballero", "es para caballero", "caballero, dama",
        "caballero o dama", "niño", "niña", "bebé", "bebe"
    ]):
        return "Caballero"

    # ── FALLBACK: numbered list without clear context ────────────────────────
    if any(n in t for n in ["1.", "1)", "①", "2.", "2)", "②"]) and not state.get("service_selected"):
        # First numbered list seen → pick service by name
        state["service_selected"] = True
        return "Quiero el corte caballero"

    if any(n in t for n in ["1.", "1)", "①", "2.", "2)", "②"]) and state.get("service_selected"):
        return "1"

    return None


async def run_qa():
    settings = get_settings()
    conversation_id = str(uuid.uuid4())
    print(f"\n{'='*60}")
    print("QA Round 11 — indecision flow")
    print(f"Persona: luis_indecisive_client ({PERSONA_NAME})")
    print(f"Conversation ID: {conversation_id}")
    print(f"Started: {datetime.now(UTC).isoformat()}")
    print("Commit: 55ab710")
    print(f"{'='*60}\n")

    redis_password = settings.REDIS_PASSWORD
    if redis_password:
        redis_url = f"redis://:{redis_password}@localhost:6379/0"
    else:
        redis_url = "redis://localhost:6379/0"
    print("Connecting to Redis at: localhost:6379/0")
    r = redis.from_url(redis_url, decode_responses=True)
    harness = RedisTestHarness(redis_client=r)

    # CRITICAL (skill rule): Subscribe BEFORE injecting
    await harness.prepare_response_capture()
    print("✓ Subscribed to outgoing_messages BEFORE injecting\n")

    turns_trace = []
    turn_num = 0
    # T1: spec says start with indecisive open question
    current_message = "Hola, soy hombre y quiero verme más prolijo, ¿qué me recomendás?"
    booking_completed = False
    state: dict = {}  # shared state across turns

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
            next_msg = pick_response(agent_response, turn_num, state)
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
        ["docker", "compose", "logs", "--no-color", "--tail=400", "agent"],
        capture_output=True, text=True,
        cwd="/home/pcabeza/Proyectos/atrevete-bot"
    )
    lines = result.stdout.splitlines()
    relevant = [l for l in lines if conversation_id[:8] in l
                or "booking_step" in l.lower()
                or "book(" in l
                or "manage_customer" in l
                or "slot_selection" in l.lower()
                or "CUSTOMER_NAME" in l
                or "CONFIRMATION" in l
                or "COMPLETED" in l
                or "ADDON" in l
                or "SERVICE_SELECTION" in l
                or "STYLIST_SELECTION" in l
                or "intent=" in l
                or "substep" in l.lower()
                or "recommendation" in l.lower()]
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
    if any(kw in all_responses for kw in ["recomend", "podría", "para hombre", "prolijo", "opciones"]):
        milestones_hit.append("discovery_started")
    if any(kw in all_responses for kw in ["corte caballero", "corte de caballero", "recomiendo", "sugerimos"]):
        milestones_hit.append("recommendation_given")
    if "corte caballero" in all_user or "ese servicio" in all_user:
        milestones_hit.append("service_resolved")
    if any(kw in all_responses for kw in ["adicional", "agregar", "add-on", "barba", "tratamiento"]):
        milestones_hit.append("addons_handled")
    if "cualquiera" in all_user or "cualquiera disponible" in all_user:
        milestones_hit.append("stylist_resolved")
    if any(d in all_responses for d in ["lunes", "martes", "miércoles", "miercoles", "jueves",
                                         "viernes", "sábado", "sabado", "huecos disponibles",
                                         "proximos huecos", "próximos huecos"]):
        milestones_hit.append("slot_offered")
    if "1" in all_user or "viernes" in all_user:
        milestones_hit.append("slot_resolved")
    if any(kw in all_responses for kw in ["nombre", "cómo te llamas"]):
        milestones_hit.append("name_asked")
    if "luis martínez" in all_user or "luis martinez" in all_user:
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
        for step in ["SERVICE_SELECTION", "ADDON_OFFER", "STYLIST_SELECTION", "SLOT_SELECTION",
                     "CUSTOMER_NAME", "NOTES", "CONFIRMATION", "COMPLETED", "DATE_SELECTION"]:
            if step in line and step not in booking_steps:
                booking_steps.append(step)

    # recommendation_provided flag
    recommendation_provided = "recommendation_given" in milestones_hit or "discovery_started" in milestones_hit

    status = "PASS" if (recommendation_provided and booking_completed and appointment_in_db) else "FAIL"

    print(f"\n{'='*60}")
    print("QA RESULT")
    print(f"{'='*60}")
    print(f"Status: {status}")
    print(f"Turn count: {len(turns)}")
    print(f"Milestones hit: {milestones_hit}")
    print(f"Recommendation provided: {recommendation_provided}")
    print(f"Booking completed (signal): {booking_completed}")
    print(f"Appointment in DB: {appointment_in_db}")
    print(f"Booking step progression: {booking_steps}")

    print(f"\n{'='*60}")
    print("FULL CONVERSATION TRACE")
    print(f"{'='*60}")
    for t in turns:
        print(json.dumps(t, ensure_ascii=False, indent=2, default=str))

    result = {
        "qa_round": "QA-R11",
        "flow_id": "indecision",
        "persona_id": "luis_indecisive_client",
        "conversation_id": conversation_id,
        "commit": "55ab710",
        "status": status,
        "turn_count": len(turns),
        "milestones_hit": milestones_hit,
        "recommendation_provided": recommendation_provided,
        "appointment_created": booking_completed,
        "appointment_in_db": appointment_in_db,
        "booking_step_progression": booking_steps,
        "turns": turns,
    }
    print("\n--- STRUCTURED RESULT ---")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return result


if __name__ == "__main__":
    asyncio.run(main())
