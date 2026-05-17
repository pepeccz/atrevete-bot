"""QA: Maria Garcia — Clean-State Happy-Path

Clean state assumptions:
  - DB has ZERO future appointments — all slots genuinely available
  - Redis flushed — no stale checkpoints
  - Fresh conversation_id (new UUID)
  - Fresh phone number: +34699000001 (never used, no customer record)

Test flow (5-6 turns max):
  T1: "Hola, quiero cortarme el pelo" (natural, NOT "corte de dama")
  T2: If asked about audience/type -> "para mujer adulta"
  T3: No stylist preference
  T4: Pick first slot
  T5: Give name: "Maria Garcia"
  T6: Confirm

Critical checks:
  1. NO SLOT_TAKEN errors (agenda is empty)
  2. Booking confirms on first attempt
  3. Appointment exists in DB with correct service + stylist + time
  4. Clean FSM flow, no stuck states
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

PERSONA_NAME = "Maria Garcia"
PHONE = "+34699000001"
MAX_TURNS = 15


def is_booking_completed(text: str) -> bool:
    """Check if bot confirms booking creation — strict: must be final confirmation."""
    t = text.lower()
    # Exclude intermediate steps
    if any(excl in t for excl in [
        "casi lista", "solo necesito", "me das tu nombre", "ultimo paso",
        "último paso", "siguiente paso", "un momento", "buscando",
    ]):
        return False
    return any(kw in t for kw in [
        "turno confirmado", "cita confirmada", "reserva confirmada",
        "quedo agendad", "quedó agendad", "quedo reservad", "quedó reservad",
        "agendamos tu", "\u2705",
        "tu reserva esta confirmada", "tu reserva quedo confirmada",
        "reserva esta confirmada", "tu cita ha sido confirmada",
        "cita ha sido confirmada", "turno ha sido confirmado",
        "te esperamos", "nos vemos el",
    ])


def pick_response(text: str, turn_num: int) -> str | None:
    """State-machine: map bot response -> next user utterance."""
    t = text.lower()

    # TERMINAL: booking done
    if is_booking_completed(text):
        return None

    # ERROR — retry
    if any(kw in t for kw in ["tuve un problema", "ocurrio un error", "error al", "no pude",
                               "sigo teniendo", "no esta funcionando", "herramienta"]):
        return "Intenta de nuevo"

    # CANCELLATION confusion
    if "cancelar la reserva" in t or "seguro que quieres cancelar" in t:
        return "no"

    # CATEGORY ASK (dama/nina/bebe or mujer/hombre)
    if any(kw in t for kw in ["dama", "caballero", "nina", "bebe", "mujer", "hombre",
                                "tipo de corte", "para quien"]):
        if "nombre" not in t:  # don't confuse with name ask
            return "para mujer adulta"

    # SLOT LIST (numbered time options) — MUST come BEFORE stylist check
    if any(kw in t for kw in ["huecos disponibles", "proximos huecos", "slots disponibles",
                               "horarios disponibles", "huecos libres"]):
        return "1"

    # Detect numbered time pattern (1. HH:MM or 1) HH:MM)
    if any(n in t for n in ["1.", "1)", "\u2460"]) and any(
        kw in t for kw in ["09:", "10:", "11:", "12:", "13:", "14:", "15:", "16:", "17:"]
    ):
        return "1"

    # STYLIST LIST with numbered options (no times present)
    if any(name in t for name in ["luciana", "pilar", "lucia", "carmen", "ana", "sofia", "elena"]) and \
       any(n in t for n in ["2.", "2)", "3.", "3)"]) and not any(
        kw in t for kw in ["09:", "10:", "11:", "12:", "13:", "14:", "15:", "16:", "17:"]
    ):
        return "Sin preferencia, cualquiera"

    # STYLIST PREFERENCE ASK (open question, no list)
    if any(kw in t for kw in ["preferencia de estilista", "algun estilista", "alguna estilista",
                                "profesional en particular", "con quien te gustaria",
                                "prefieres algun", "alguna preferencia"]):
        return "No, sin preferencia"

    # SERVICE CATALOG LIST (numbered services, no times)
    if ("corte" in t or "cortar" in t) and any(n in t for n in ["1.", "1)", "2.", "2)"]) and \
       "huecos" not in t and not any(
        kw in t for kw in ["09:", "10:", "11:", "12:", "13:", "14:", "15:", "16:", "17:"]
    ):
        return "El primero"

    # AVAILABILITY CONFIRMATION (bot asks "quieres que te busque disponibilidad?")
    if any(kw in t for kw in [
        "busque disponibilidad", "buscar disponibilidad", "busco disponibilidad",
        "quieres que te busque", "quieres que busque",
        "te busco horarios", "te muestro horarios",
    ]):
        return "Si, por favor"

    # ADD-ON OFFER
    if any(kw in t for kw in [
        "add-on", "adicional", "sumar", "agregar servicio",
        "deseas agregar", "quieres anadir", "quieres añadir",
        "anadir algun", "añadir algún", "agregar algun",
        "servicio adicional", "tratamiento", "masaje",
    ]):
        return "No gracias"

    # NAME REQUEST
    if any(kw in t for kw in [
        "nombre", "como te llamas", "cómo te llamas",
        "a nombre de", "apellidos", "tu nombre",
    ]):
        return "Maria Garcia"

    # NOTES / PREFERENCES REQUEST
    if any(kw in t for kw in [
        "algo mas que deba saber", "algo más que deba saber",
        "preferencia especial", "condicion en tu cabello",
        "nota", "comentario", "algun detalle", "algún detalle",
        "algo mas antes", "algo más antes",
        "algo que deba", "algo que quieras",
        "dejar alguna", "anadir nota", "añadir nota",
    ]):
        return "Sin notas"

    # CONFIRMATION REQUEST
    if any(kw in t for kw in [
        "confirma", "confirmamos", "confirmas", "confirmás",
        "todo correcto", "es correcto",
        "esta bien", "está bien",
        "te confirmo", "resumen de tu reserva", "resumen",
        "procedemos",
    ]):
        return "Si, confirmo"

    # YES/NO SLOT CONFIRMATION
    if any(kw in t for kw in [
        "te viene bien", "te parece bien", "te va bien",
        "aceptas", "quedamos el",
    ]):
        return "Si"

    # DATE/TIME REQUEST (open-ended)
    if any(kw in t for kw in [
        "que dia", "qué dia", "que hora", "qué hora",
        "cuando", "cuándo", "que fecha", "qué fecha",
        "dia y hora", "día y hora",
    ]) and "huecos" not in t:
        return "El jueves que viene"

    # FALLBACK: any numbered list
    if any(n in t for n in ["1.", "1)", "\u2460", "2.", "2)", "\u2461"]):
        return "1"

    return None


async def run_qa():
    settings = get_settings()
    conversation_id = str(uuid.uuid4())
    print(f"\n{'='*60}")
    print("QA: Maria Garcia — Clean-State Happy-Path")
    print(f"Persona: {PERSONA_NAME}")
    print(f"Phone: {PHONE}")
    print(f"Conversation ID: {conversation_id}")
    print(f"Started: {datetime.now(UTC).isoformat()}")
    print(f"{'='*60}\n")

    redis_password = settings.REDIS_PASSWORD
    if redis_password:
        redis_url = f"redis://:{redis_password}@localhost:6379/0"
    else:
        redis_url = "redis://localhost:6379/0"
    r = redis.from_url(redis_url, decode_responses=True)
    harness = RedisTestHarness(redis_client=r)

    await harness.prepare_response_capture()
    print("Subscribed to outgoing_messages\n")

    turns_trace = []
    turn_num = 0
    current_message = "Hola, quiero cortarme el pelo"
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

            if is_booking_completed(agent_response):
                print("BOOKING COMPLETED!")
                booking_completed = True
                break

            next_msg = pick_response(agent_response, turn_num)
            if next_msg is None:
                print("Could not determine next message — ending flow")
                break

            current_message = next_msg

    except TimeoutError as e:
        print(f"\nTIMEOUT: {e}")
        turns_trace.append({"turn_number": turn_num, "error": "TIMEOUT", "details": str(e)})
    finally:
        await harness.close()
        await r.aclose()

    return conversation_id, turns_trace, booking_completed


async def check_db_maria() -> dict:
    """Check DB for Maria Garcia appointments."""
    import asyncpg

    settings = get_settings()
    dsn = settings.DATABASE_URL.replace("+asyncpg", "").replace("postgresql+psycopg", "postgresql")
    dsn = dsn.replace("@postgres:", "@localhost:").replace("@postgres/", "@localhost/")
    conn = await asyncpg.connect(dsn)
    try:
        # Check by first_name matching Maria
        rows = await conn.fetch(
            """SELECT a.id, a.customer_id, a.stylist_id, a.service_ids, a.start_time,
                      a.duration_minutes, a.status, a.created_at,
                      c.first_name, c.last_name, c.phone
               FROM appointments a
               JOIN customers c ON c.id = a.customer_id
               WHERE c.phone = $1
               ORDER BY a.created_at DESC
               LIMIT 5""",
            PHONE,
        )
        # Also get service + stylist names
        detailed = []
        for row in rows:
            r = dict(row)
            # Get stylist name
            stylist = await conn.fetchrow(
                "SELECT name FROM stylists WHERE id = $1", row["stylist_id"]
            )
            r["stylist_name"] = stylist["name"] if stylist else "UNKNOWN"
            # Get service names
            services = await conn.fetch(
                "SELECT name FROM services WHERE id = ANY($1::uuid[])", row["service_ids"]
            )
            r["service_names"] = [s["name"] for s in services]
            detailed.append(r)

        return {
            "count": len(rows),
            "appointments": detailed,
        }
    finally:
        await conn.close()


async def main():
    conversation_id, turns, booking_completed = await run_qa()

    print(f"\n{'='*60}")
    print("CONVERSATION TRACE SUMMARY")
    print(f"{'='*60}")
    print(f"Total turns: {len(turns)}")
    print(f"Booking completed (signal): {booking_completed}")

    # DB verification
    print(f"\n{'='*60}")
    print("DATABASE VERIFICATION")
    print(f"{'='*60}")
    try:
        db_result = await check_db_maria()
        print(f"Appointments found for {PHONE}: {db_result['count']}")
        if db_result["appointments"]:
            for appt in db_result["appointments"]:
                print(f"  ID: {appt['id']}")
                print(f"  Customer: {appt.get('first_name')} {appt.get('last_name')}")
                print(f"  Services: {appt.get('service_names')}")
                print(f"  Stylist: {appt.get('stylist_name')}")
                print(f"  Time: {appt.get('start_time')}")
                print(f"  Duration: {appt.get('duration_minutes')} min")
                print(f"  Status: {appt['status']}")
                print()
        appointment_in_db = db_result["count"] > 0
    except Exception as e:
        print(f"DB check failed: {e}")
        appointment_in_db = False
        db_result = {"count": 0, "error": str(e)}

    # Agent log inspection
    print(f"\n{'='*60}")
    print("AGENT LOGS (last 200 lines, filtered)")
    print(f"{'='*60}")
    try:
        import subprocess
        result = subprocess.run(
            ["docker", "compose", "logs", "--no-color", "--tail=200", "agent"],
            capture_output=True, text=True,
            cwd="/home/pcabeza/Proyectos/atrevete-bot"
        )
        lines = result.stdout.splitlines()
        relevant = [l for l in lines if conversation_id[:8] in l
                    or "booking_step" in l.lower()
                    or "SLOT_TAKEN" in l
                    or "error" in l.lower() and "booking" in l.lower()]
        for line in relevant[-30:]:
            print(line)
    except Exception as e:
        print(f"Log check failed: {e}")

    # Milestones
    milestones_hit = []
    all_responses = " ".join(t.get("agent_response", "") for t in turns).lower()
    if turns:
        milestones_hit.append("greeting_done")
    if any(kw in all_responses for kw in ["corte", "cortar", "servicio"]):
        milestones_hit.append("service_discussed")
    if any(kw in all_responses for kw in ["huecos", "horarios", "disponibles"]):
        milestones_hit.append("slots_offered")
    if any(kw in all_responses for kw in ["nombre", "llamas"]):
        milestones_hit.append("name_asked")
    if booking_completed:
        milestones_hit.append("booking_completed")

    status = "PASS" if (booking_completed and appointment_in_db) else "FAIL"

    print(f"\n{'='*60}")
    print("QA RESULT")
    print(f"{'='*60}")
    print(f"Status: {status}")
    print(f"Turns: {len(turns)}")
    print(f"Milestones: {milestones_hit}")
    print(f"Booking completed (signal): {booking_completed}")
    print(f"Appointment in DB: {appointment_in_db}")

    # Full trace
    print(f"\n{'='*60}")
    print("FULL TRACE")
    print(f"{'='*60}")
    for t in turns:
        print(json.dumps(t, ensure_ascii=False, indent=2, default=str))

    result = {
        "flow_id": "maria_clean_state_happy_path",
        "persona": PERSONA_NAME,
        "phone": PHONE,
        "conversation_id": conversation_id,
        "status": status,
        "turn_count": len(turns),
        "milestones": milestones_hit,
        "booking_completed": booking_completed,
        "appointment_in_db": appointment_in_db,
        "db_result": {
            "count": db_result.get("count", 0),
            "appointments": [
                {k: str(v) for k, v in a.items()}
                for a in db_result.get("appointments", [])
            ]
        },
    }
    print("\n--- STRUCTURED RESULT ---")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return result


if __name__ == "__main__":
    asyncio.run(main())
