"""QA Round 7 — returning_client flow — carlos_returning_client persona."""
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

PERSONA_NAME = "Carlos López"
PHONE = "+34600000001"

# Harness script per task spec
TURNS = [
    "Hola, quiero un corte caballero con Luciana esta semana a la mañana",
]
FOLLOWUP_MAP = {
    "variant": "Caballero",
    "slot": "1",
    "addon": "No gracias",
    "name": "Carlos López",
    "notes": "Sin notas",
    "confirm": "Sí, confirmo",
}


def classify_response(text: str, turn_num: int) -> str | None:
    """Return next reply based on bot response content."""
    t = text.lower()
    if turn_num == 1:
        # Check if bot asks for variant clarification
        if "dama" in t or "caballero" in t and ("cuál" in t or "cual" in t or "tipo" in t or "qué" in t or "que" in t):
            return FOLLOWUP_MAP["variant"]
        # Check if bot shows slot options (numbered list)
        if any(c in t for c in ["1.", "1)", "①", "lunes", "martes", "miércoles", "jueves", "viernes"]):
            return FOLLOWUP_MAP["slot"]
    if turn_num >= 2:
        # Slot selection
        if any(c in t for c in ["1.", "1)", "lunes", "martes", "miércoles", "jueves", "viernes", "disponible"]):
            # Check if it's actually offering slots
            if "horario" in t or "opción" in t or "opcion" in t or "slot" in t or "disponib" in t or any(
                day in t for day in ["lunes", "martes", "miércoles", "jueves", "viernes"]
            ):
                return FOLLOWUP_MAP["slot"]
        # Add-on offer
        if "add" in t or "adicio" in t or "suma" in t or "también" in t or "tambien" in t or "agreg" in t:
            return FOLLOWUP_MAP["addon"]
        # Name request
        if "nombre" in t and ("cuál" in t or "cual" in t or "tu" in t or "me" in t):
            return FOLLOWUP_MAP["name"]
        # Notes request
        if "nota" in t or "comentario" in t or "algo más" in t or "algo mas" in t:
            return FOLLOWUP_MAP["notes"]
        # Confirmation request
        if "confirm" in t or "¿confirma" in t or "confirma" in t or "¿todo" in t:
            return FOLLOWUP_MAP["confirm"]
    return None


async def run_qa():
    settings = get_settings()
    conversation_id = str(uuid.uuid4())
    print(f"\n{'='*60}")
    print("QA Round 7 — returning_client flow")
    print(f"Persona: carlos_returning_client ({PERSONA_NAME})")
    print(f"Conversation ID: {conversation_id}")
    print(f"Started: {datetime.now(UTC).isoformat()}")
    print(f"{'='*60}\n")

    # Override Redis URL to use localhost when running from host (Docker uses 'redis' hostname internally)
    # Build URL with password: redis://:PASSWORD@localhost:6379/0
    redis_password = settings.REDIS_PASSWORD
    redis_url = f"redis://:{redis_password}@localhost:6379/0"
    print("Connecting to Redis at: localhost:6379/0")
    r = redis.from_url(redis_url, decode_responses=True)
    harness = RedisTestHarness(redis_client=r)

    # CRITICAL: Subscribe BEFORE injecting
    await harness.prepare_response_capture()
    print("✓ Subscribed to outgoing_messages BEFORE injecting\n")

    turns_trace = []
    max_turns = 12
    turn_num = 0

    # T1 — opening message
    current_message = TURNS[0]
    booking_completed = False

    try:
        while turn_num < max_turns:
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

            # Check if booking is completed
            response_lower = agent_response.lower()
            if any(kw in response_lower for kw in [
                "reserva", "turno confirmado", "agendad", "confirmad", "cita confirmada",
                "perfecto", "quedó", "quedo", "listo", "todo listo"
            ]):
                # Check for strong booking confirmation signals
                if any(kw in response_lower for kw in [
                    "confirmad", "agendad", "reservad", "turno el", "turno para", "quedó tu",
                    "quedo tu", "✅", "👍"
                ]):
                    print("✅ Booking completion signal detected!")
                    booking_completed = True
                    break

            # Determine next message
            next_msg = classify_response(agent_response, turn_num)
            if next_msg is None:
                # Try harder with more context
                if "confirma" in response_lower or "correcto" in response_lower:
                    next_msg = FOLLOWUP_MAP["confirm"]
                elif "nombre" in response_lower:
                    next_msg = FOLLOWUP_MAP["name"]
                elif any(d in response_lower for d in ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado"]):
                    next_msg = FOLLOWUP_MAP["slot"]
                elif "nota" in response_lower or "comentario" in response_lower:
                    next_msg = FOLLOWUP_MAP["notes"]
                elif "add" in response_lower or "adicio" in response_lower:
                    next_msg = FOLLOWUP_MAP["addon"]
                elif turn_num >= 3:
                    # Default safe response for unclear states
                    next_msg = "1"

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


async def check_db(conversation_id: str) -> dict:
    """Check DB for appointments created in last hour."""
    import asyncpg

    settings = get_settings()
    # Replace Docker hostname with localhost for host-side connection
    dsn = settings.DATABASE_URL.replace("+asyncpg", "").replace("postgresql+psycopg", "postgresql")
    dsn = dsn.replace("@postgres:", "@localhost:")
    # Use asyncpg direct connection
    conn = await asyncpg.connect(dsn)
    try:
        count_row = await conn.fetchrow(
            "SELECT count(*) as cnt FROM appointments WHERE created_at > now() - interval '1 hour'"
        )
        count = count_row["cnt"]

        recent = await conn.fetch(
            """SELECT id, customer_id, stylist_id, service_id, starts_at, status, created_at
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
        db_result = await check_db(conversation_id)
        print(f"Appointments in last hour: {db_result['count_last_hour']}")
        if db_result["recent_appointments"]:
            print("Recent appointments:")
            for appt in db_result["recent_appointments"]:
                print(f"  - ID: {appt['id']}, starts_at: {appt['starts_at']}, status: {appt['status']}")
    except Exception as e:
        print(f"DB check failed: {e}")
        db_result = {"count_last_hour": -1, "error": str(e)}

    appointment_in_db = db_result.get("count_last_hour", 0) > 0

    # Milestones check
    milestones_hit = []
    all_responses = " ".join(t.get("agent_response", "") for t in turns).lower()
    all_user = " ".join(t.get("user_message", "") for t in turns).lower()

    if turns:
        milestones_hit.append("greeting_done")
    if "luciana" in all_responses or "luciana" in all_user:
        milestones_hit.append("stylist_locked")
    if any(d in all_responses for d in ["lunes", "martes", "miércoles", "jueves", "viernes", "horario"]):
        milestones_hit.append("slot_resolved")
    if "confirma" in all_user or "sí, confirmo" in all_user:
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

    # Output structured result for engram
    result = {
        "qa_round": "QA-R7",
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
    print("\n--- STRUCTURED RESULT ---")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return result


if __name__ == "__main__":
    asyncio.run(main())
