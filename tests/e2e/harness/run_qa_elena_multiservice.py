"""QA Test — Elena García — Multi-Service Booking (Corte de Dama + Tinte).

Validates that when a customer requests MULTIPLE services in a single booking,
ALL services are tracked through the FSM and persisted in the database.

Known bug: the FSM's selected_services list sometimes drops to 1 service
during slot_selection → confirmation transition.

Persona: Elena García (+34678901234) — new client, cooperative, knows what she wants.

Expected outcome: appointment with service_ids containing BOTH service UUIDs,
duration = sum of both service durations.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime

sys.path.insert(0, "/home/pcabeza/Proyectos/atrevete-bot")

# Force batch window to 0 for immediate processing
os.environ["MESSAGE_BATCH_WINDOW_SECONDS"] = "0"

import redis.asyncio as redis

from shared.config import get_settings
from tests.e2e.harness.redis_harness import RedisTestHarness

PERSONA_NAME = "Elena García"
PHONE = "+34678901234"
MAX_TURNS = 20


def is_booking_completed(text: str) -> bool:
    """Check if bot confirms booking creation (final, not intermediate)."""
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


def pick_response(text: str, turn_num: int) -> str | None:
    """State-machine: map bot response → next user utterance."""
    t = text.lower()

    # ── TERMINAL: booking done ─────────────────────────────────────────
    if is_booking_completed(text):
        return None  # Done

    # ── Service clarification ──────────────────────────────────────────
    if "corte de dama" in t and ("?" in text or "asegurarme" in t):
        return "Sí, corte de dama y el tinte, los dos"

    # ── Stylist preference ─────────────────────────────────────────────
    if "estilista" in t and ("preferid" in t or "preferencia" in t or "?" in text):
        return "No tengo preferencia, cualquier estilista está bien"

    # ── Slot list offered (numbered options) ───────────────────────────
    if any(kw in t for kw in ["1.", "opción 1", "opciones"]) and (
        "horario" in t or "hueco" in t or "disponib" in t or "cuál" in t
    ):
        return "La primera opción por favor"

    # ── Confirmation prompt (before booking) ───────────────────────────
    if "confirm" in t and "?" in text:
        # Check if both services are mentioned
        has_both = ("corte" in t or "cortar" in t) and ("color" in t or "tinte" in t)
        if not has_both:
            # Bug: only one service shown — ask about the missing one
            return "Espera, yo quería los dos servicios, corte de dama y tinte, ¿están incluidos los dos?"
        return "Sí, confirmo"

    # ── Name request ───────────────────────────────────────────────────
    if "nombre" in t and "?" in text:
        return "Elena García"

    # ── Notes request ──────────────────────────────────────────────────
    if "nota" in t or "observaci" in t or "comentario" in t:
        return "Sin notas"

    # ── Add-ons ────────────────────────────────────────────────────────
    if "complemento" in t or "añadir" in t or "adicional" in t:
        return "No gracias, solo esos dos servicios"

    # ── Slot not available / retry ─────────────────────────────────────
    if "no está disponible" in t or "ya no está" in t:
        return "Sí, por favor, busquemos otra opción"

    # ── Generic error / retry ──────────────────────────────────────────
    if "error" in t or "problema" in t:
        return "Intenta de nuevo por favor"

    # ── Fallback: if the bot says something unexpected ─────────────────
    if turn_num >= MAX_TURNS - 2:
        return None  # About to hit max turns

    return "Sí, dale"


async def run_test() -> dict:
    """Execute the full QA conversation and return results."""
    settings = get_settings()
    conversation_id = str(uuid.uuid4())
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    harness = RedisTestHarness(redis_client=client)

    results = {
        "persona": PERSONA_NAME,
        "phone": PHONE,
        "conversation_id": conversation_id,
        "test": "multi-service-booking",
        "started_at": datetime.now(UTC).isoformat(),
        "turns": [],
        "bugs": [],
        "outcome": "unknown",
    }

    try:
        # Turn 1: greeting + multi-service request
        first_message = "Hola, quiero reservar un corte de dama y un tinte por favor"
        turn_num = 0
        next_message = first_message

        while next_message and turn_num < MAX_TURNS:
            turn_num += 1
            print(f"\n{'='*60}")
            print(f"TURN {turn_num}")
            print(f"USER: {next_message}")

            try:
                result = await harness.execute_turn(
                    conversation_id=conversation_id,
                    user_message=next_message,
                    persona_name=PERSONA_NAME,
                    timeout=60.0,
                    customer_phone=PHONE,
                )
                bot_response = result["agent_response"]
                latency = result["response_latency_ms"]
            except TimeoutError:
                bot_response = "[TIMEOUT]"
                latency = -1
                results["bugs"].append({
                    "category": "timeout",
                    "turn": turn_num,
                    "evidence": f"Turn {turn_num} timed out",
                    "severity": "high",
                })

            print(f"BOT:  {bot_response}")
            print(f"LATENCY: {latency}ms")

            turn_data = {
                "turn": turn_num,
                "user": next_message,
                "bot": bot_response,
                "latency_ms": latency,
            }

            # Bug detection: check if confirmation only mentions 1 service
            bot_lower = bot_response.lower()
            if "confirm" in bot_lower and "?" in bot_response:
                has_corte = "corte" in bot_lower or "cortar" in bot_lower
                has_tinte = "color" in bot_lower or "tinte" in bot_lower
                if not (has_corte and has_tinte):
                    bug = {
                        "category": "context_loss",
                        "turn": turn_num,
                        "evidence": f"Confirmation only mentions "
                            f"{'corte' if has_corte else 'tinte/color'}, "
                            f"missing {'tinte/color' if has_corte else 'corte'}",
                        "severity": "high",
                    }
                    turn_data["bugs"] = [bug]
                    results["bugs"].append(bug)
                    print(f"  *** BUG: {bug['category']} — {bug['evidence']}")

            results["turns"].append(turn_data)

            if is_booking_completed(bot_response):
                results["outcome"] = "booking_confirmed"
                break

            next_message = pick_response(bot_response, turn_num)
            if next_message is None and not is_booking_completed(bot_response):
                results["outcome"] = "stuck"

        if turn_num >= MAX_TURNS:
            results["outcome"] = "max_turns"

        # Capture final state
        binary_client = redis.from_url(settings.REDIS_URL, decode_responses=False)
        state_harness = RedisTestHarness(
            redis_client=client,
            binary_redis_client=binary_client,
        )
        final_state = await state_harness.capture_final_state(conversation_id)
        results["final_state"] = final_state or {}
        await binary_client.aclose()

        # Check selected_services in state
        mode_ctx = (final_state or {}).get("mode_context", {})
        selected_services = mode_ctx.get("selected_services", [])
        results["selected_services_in_state"] = selected_services
        if len(selected_services) < 2:
            results["bugs"].append({
                "category": "context_loss",
                "turn": "final_state",
                "evidence": f"selected_services has {len(selected_services)} "
                    f"services, expected 2. Value: {selected_services}",
                "severity": "high",
            })

    except Exception as exc:
        results["outcome"] = "error"
        results["error"] = str(exc)
        import traceback
        traceback.print_exc()
    finally:
        await harness.close()
        await client.aclose()

    results["ended_at"] = datetime.now(UTC).isoformat()
    results["total_turns"] = len(results["turns"])
    results["bugs_count"] = len(results["bugs"])

    return results


async def verify_db(phone: str) -> dict:
    """Verify appointments in the database for the given phone."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)

    async with engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT a.id, a.service_ids, st.name as stylist,
                   a.start_time, a.status, a.first_name,
                   a.duration_minutes
            FROM appointments a
            JOIN stylists st ON a.stylist_id = st.id
            JOIN customers c ON a.customer_id = c.id
            WHERE c.phone = :phone
            ORDER BY a.created_at DESC
            LIMIT 5
        """), {"phone": phone})
        rows = result.fetchall()

    await engine.dispose()

    appointments = []
    for row in rows:
        appointments.append({
            "id": str(row.id),
            "service_ids": [str(sid) for sid in row.service_ids],
            "stylist": row.stylist,
            "start_time": row.start_time.isoformat(),
            "status": row.status,
            "first_name": row.first_name,
            "duration_minutes": row.duration_minutes,
            "service_count": len(row.service_ids),
        })

    return {
        "total_appointments": len(appointments),
        "appointments": appointments,
        "multi_service_found": any(a["service_count"] >= 2 for a in appointments),
    }


async def main():
    print("=" * 60)
    print("QA TEST: Elena García — Multi-Service Booking")
    print("=" * 60)

    # Run conversation
    results = await run_test()

    print("\n" + "=" * 60)
    print("CONVERSATION COMPLETE")
    print(f"Outcome: {results['outcome']}")
    print(f"Turns: {results['total_turns']}")
    print(f"Bugs: {results['bugs_count']}")

    # Verify DB
    print("\n" + "=" * 60)
    print("DATABASE VERIFICATION")
    db_results = await verify_db(PHONE)
    results["db_verification"] = db_results

    print(f"Total appointments found: {db_results['total_appointments']}")
    print(f"Multi-service booking found: {db_results['multi_service_found']}")
    for apt in db_results["appointments"]:
        print(f"  - {apt['first_name']} with {apt['stylist']}: "
              f"{apt['service_count']} services, {apt['duration_minutes']} min, "
              f"status={apt['status']}")

    # Summary
    print("\n" + "=" * 60)
    print("QA RESULTS SUMMARY")
    print(json.dumps(results, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(main())
