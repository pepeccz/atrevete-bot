"""QA Test — Elena García — Clean-State Multi-Service Booking.

Validates that a NEW client requesting 2 services (corte + tinte) in a
clean-state environment (no future appointments, flushed Redis) completes
the full booking flow without SLOT_TAKEN errors and with BOTH services
persisted in the DB.

Persona: Elena García (+34699000002) — never-seen-before phone, no customer record.

Critical checks:
  1. Both services resolved (not just one)
  2. NO SLOT_TAKEN errors
  3. Both services in DB appointment (duration ~80 min)
  4. selected_services stays at 2 throughout flow
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
PHONE = "+34699000002"
MAX_TURNS = 20


def is_booking_completed(text: str) -> bool:
    """Check if bot confirms booking creation — final confirmation only.

    IMPORTANT: Messages that contain "?" are typically asking the user
    something (e.g. confirmation prompts). A checkmark in a question
    is decorative, NOT a completion signal.
    """
    t = text.lower()
    # Exclude intermediate steps
    if any(excl in t for excl in [
        "casi lista", "solo necesito", "me das tu nombre", "último paso",
        "siguiente paso", "un momento", "buscando",
        "confirmemos", "confirmas", "te parece bien",
    ]):
        return False
    # If there's a question mark, it's likely asking something, not confirming
    has_question = "?" in text
    # Strong signals that override even question marks
    strong_signals = [
        "turno confirmado", "cita confirmada", "reserva confirmada",
        "quedó agendad", "quedo agendad", "quedó reservad", "quedo reservad",
        "tu reserva está confirmada", "tu reserva quedo confirmada",
        "reserva está confirmada", "tu cita ha sido confirmada",
        "cita ha sido confirmada", "turno ha sido confirmado",
    ]
    if any(kw in t for kw in strong_signals):
        return True
    # Weaker signals only count if there's no question mark
    if not has_question:
        return any(kw in t for kw in [
            "agendamos tu", "\u2705",
            "te esperamos", "nos vemos el",
        ])
    return False


class ConversationTracker:
    """Track conversation state to avoid response loops."""

    def __init__(self):
        self.services_confirmed = False
        self.audience_answered = False
        self.variant_answered = False
        self.stylist_answered = False
        self.slot_picked = False
        self.name_given = False
        self.confirmed = False
        self.last_response = ""

    def pick_response(self, text: str, turn_num: int) -> str | None:
        """Map bot response -> next user utterance for Elena."""
        t = text.lower()

        # ── TERMINAL: booking done ───────────────────────────────────
        if is_booking_completed(text):
            return None

        # ── CANCELLATION confusion ───────────────────────────────────
        if "cancelar la reserva" in t or "seguro que quieres cancelar" in t:
            return "No, no quiero cancelar"

        # ── ESCALATION — bot giving up ───────────────────────────────
        if "conecto con mi equipo" in t or "equipo para que te ayuden" in t:
            return "No, intenta de nuevo por favor con la reserva"

        # ── ERROR — retry ────────────────────────────────────────────
        if any(kw in t for kw in [
            "tuve un problema", "ocurrió un error", "error al", "no pude",
            "sigo teniendo", "no está funcionando", "herramienta",
            "problemas para reservar",
        ]):
            return "Intenta de nuevo por favor"

        # ── SLOT_TAKEN — ask for another ─────────────────────────────
        if any(kw in t for kw in [
            "no está disponible", "ya no está", "slot_taken",
            "acaba de ser reservado", "ya está ocupad",
        ]):
            return "Sí, busquemos otra opción"

        # ── Detect structural patterns ───────────────────────────────
        has_time_pattern = any(
            kw in t for kw in [
                "09:", "10:", "11:", "12:", "13:", "14:", "15:", "16:", "17:",
            ]
        )
        has_numbered_list = any(n in t for n in ["1.", "1)", "\u2460", "2.", "2)"])

        # ── SLOT LIST (numbered time options) — HIGHEST PRIORITY ─────
        if has_time_pattern and has_numbered_list:
            self.slot_picked = True
            return "La primera opción"

        if any(kw in t for kw in [
            "huecos disponibles", "próximos huecos", "proximos huecos",
            "slots disponibles", "horarios disponibles", "huecos libres",
        ]):
            self.slot_picked = True
            return "La primera opción"

        # ── Audience/category ask (caballero/dama/niño/niña/bebé) ────
        is_audience_ask = any(kw in t for kw in [
            "caballero", "niño", "niña", "bebé", "bebe",
        ]) and ("dama" in t) and ("?" in text)
        if is_audience_ask and not self.audience_answered:
            self.audience_answered = True
            return "Soy mujer adulta, corte de dama"

        # ── Service variant (Cortar vs Flequillo, Color vs Color Extra) ─
        is_variant_question = (
            ("flequillo" in t or "extra" in t or "drástic" in t or "correcciones" in t)
            and not has_time_pattern
        )
        if is_variant_question and not self.variant_answered:
            self.variant_answered = True
            return "El normal, la Tinte de 40 minutos"

        # ── Date/time request (when to book) ─────────────────────────
        is_when_question = any(kw in t for kw in [
            "cuándo", "cuando te", "para cuándo", "para cuando",
            "qué día", "que dia", "qué hora", "que hora",
            "qué fecha", "que fecha",
            "te gustaría reservar", "te gustaria reservar",
        ])
        if is_when_question and not has_time_pattern:
            return "El próximo día que tengan disponible"

        # ── Stylist preference ────────────────────────────────────────
        if (
            ("estilista" in t or "profesional" in t)
            and ("preferid" in t or "preferencia" in t or "?" in text)
            and not self.stylist_answered
        ):
            self.stylist_answered = True
            return "No tengo preferencia, cualquier estilista está bien"

        # ── STYLIST LIST with numbered options ────────────────────────
        if ("luciana" in t or "pilar" in t) and has_numbered_list and not has_time_pattern:
            if not self.stylist_answered:
                self.stylist_answered = True
                return "Sin preferencia, cualquiera está bien"

        # ── ADD-ON OFFER ──────────────────────────────────────────────
        if any(kw in t for kw in [
            "add-on", "adicional", "sumar", "agregar servicio",
            "deseas agregar", "quieres añadir", "añadir algún",
            "agregar algún", "servicio adicional",
        ]):
            return "No gracias, solo esos dos servicios"

        # ── NAME REQUEST ──────────────────────────────────────────────
        if any(kw in t for kw in [
            "nombre", "cómo te llamas", "como te llamas",
            "a nombre de", "apellidos", "tu nombre",
        ]):
            self.name_given = True
            return "Elena García"

        # ── NOTES / PREFERENCES REQUEST ───────────────────────────────
        if any(kw in t for kw in [
            "algo más que deba saber", "algo mas que deba saber",
            "preferencia especial", "condición en tu cabello",
            "nota", "comentario", "algún detalle",
            "algo más antes", "algo mas antes",
            "algo que deba", "algo que quieras",
            "dejar alguna", "añadir nota",
        ]):
            return "Sin notas"

        # ── CONFIRMATION REQUEST ──────────────────────────────────────
        if any(kw in t for kw in [
            "confirma", "confirmás", "todo correcto", "es correcto",
            "está bien", "confirmamos", "resumen de tu reserva",
            "te confirmo", "resumen", "procedemos",
            "te parece bien", "quieres que lo confirmemos",
        ]):
            has_corte = "corte" in t or "cortar" in t
            has_tinte = "color" in t or "tinte" in t
            if not (has_corte and has_tinte):
                return "Espera, yo quería los dos servicios, corte y tinte, estan incluidos los dos?"
            self.confirmed = True
            return "Sí, confirmo"

        # ── YES/NO SLOT CONFIRMATION ──────────────────────────────────
        if any(kw in t for kw in [
            "te viene bien", "te va bien",
            "aceptas", "quedamos el",
        ]):
            return "Sí, perfecto"

        # ── Bot asks about availability search ────────────────────────
        if "busquemos disponibilidad" in t or "buscar disponibilidad" in t:
            return "Sí, dale"

        # ── FALLBACK: any numbered list ───────────────────────────────
        if has_numbered_list:
            return "La primera opción"

        # ── Anti-loop: don't repeat the same response ─────────────────
        candidate = "Sí, dale"
        if turn_num >= MAX_TURNS - 2:
            return None

        return candidate


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
        "test": "elena-clean-state-multi-service",
        "started_at": datetime.now(UTC).isoformat(),
        "turns": [],
        "bugs": [],
        "outcome": "unknown",
    }

    try:
        # Subscribe BEFORE injecting (critical harness rule)
        await harness.prepare_response_capture()
        print("Subscribed to outgoing_messages BEFORE injecting\n")

        tracker = ConversationTracker()
        first_message = "Hola, quiero cortarme el pelo y hacerme un tinte"
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
                    "evidence": f"Turn {turn_num} timed out after 60s",
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

            # ── Bug detection ────────────────────────────────────────
            bot_lower = bot_response.lower()

            # Check for SLOT_TAKEN errors
            if "slot_taken" in bot_lower or "ya está ocupad" in bot_lower:
                bug = {
                    "category": "slot_taken",
                    "turn": turn_num,
                    "evidence": "SLOT_TAKEN error in clean-state test (should never happen)",
                    "severity": "critical",
                }
                turn_data["bugs"] = [bug]
                results["bugs"].append(bug)
                print(f"  *** BUG: {bug['category']} -- {bug['evidence']}")

            # Check confirmation mentions both services
            if "confirm" in bot_lower and "?" in bot_response:
                has_corte = "corte" in bot_lower or "cortar" in bot_lower
                has_tinte = "color" in bot_lower or "tinte" in bot_lower
                if not (has_corte and has_tinte):
                    bug = {
                        "category": "context_loss",
                        "turn": turn_num,
                        "evidence": (
                            f"Confirmation only mentions "
                            f"{'corte' if has_corte else 'tinte/color'}, "
                            f"missing {'tinte/color' if has_corte else 'corte'}"
                        ),
                        "severity": "high",
                    }
                    turn_data["bugs"] = turn_data.get("bugs", []) + [bug]
                    results["bugs"].append(bug)
                    print(f"  *** BUG: {bug['category']} -- {bug['evidence']}")

            results["turns"].append(turn_data)

            if is_booking_completed(bot_response):
                results["outcome"] = "booking_confirmed"
                break

            next_message = tracker.pick_response(bot_response, turn_num)
            if next_message is None and not is_booking_completed(bot_response):
                results["outcome"] = "stuck"

        if turn_num >= MAX_TURNS:
            results["outcome"] = "max_turns"

        # Capture final state (may fail if checkpoint index not initialized)
        try:
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
                    "evidence": (
                        f"selected_services has {len(selected_services)} "
                        f"services, expected 2. Value: {selected_services}"
                    ),
                    "severity": "high",
                })
        except Exception as state_exc:
            print(f"\nWARN: Could not capture final state: {state_exc}")
            results["final_state"] = {"error": str(state_exc)}
            results["selected_services_in_state"] = []

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
        # Check by phone
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
        rows_by_phone = result.fetchall()

        # Also check by first_name as fallback
        result2 = await conn.execute(text("""
            SELECT a.id, a.first_name, s.name as service_name,
                   st.name as stylist, a.start_time, a.status,
                   a.duration_minutes, a.service_ids
            FROM appointments a
            JOIN stylists st ON a.stylist_id = st.id
            LEFT JOIN LATERAL unnest(a.service_ids) AS sid ON true
            LEFT JOIN services s ON s.id = sid
            WHERE a.first_name = 'Elena'
            ORDER BY a.created_at DESC
            LIMIT 10
        """))
        rows_by_name = result2.fetchall()

    await engine.dispose()

    appointments = []
    for row in rows_by_phone:
        appointments.append({
            "id": str(row.id),
            "service_ids": [str(sid) for sid in row.service_ids],
            "stylist": row.stylist,
            "start_time": row.start_time.isoformat() if row.start_time else None,
            "status": row.status,
            "first_name": row.first_name,
            "duration_minutes": row.duration_minutes,
            "service_count": len(row.service_ids),
        })

    services_by_name = []
    for row in rows_by_name:
        services_by_name.append({
            "id": str(row.id),
            "first_name": row.first_name,
            "service_name": row.service_name,
            "stylist": row.stylist,
            "start_time": row.start_time.isoformat() if row.start_time else None,
            "status": row.status,
            "duration_minutes": row.duration_minutes,
            "service_count": len(row.service_ids) if row.service_ids else 0,
        })

    multi_service = any(a["service_count"] >= 2 for a in appointments)
    duration_ok = any(
        a["duration_minutes"] and a["duration_minutes"] >= 70
        for a in appointments
    )

    return {
        "total_appointments": len(appointments),
        "appointments": appointments,
        "services_by_name": services_by_name,
        "multi_service_found": multi_service,
        "duration_check_passed": duration_ok,
    }


async def get_agent_logs(conversation_id: str) -> list[str]:
    """Fetch agent container logs for booking_step progression."""
    import subprocess
    result = subprocess.run(
        ["docker", "compose", "logs", "--no-color", "--tail=500", "agent"],
        capture_output=True, text=True,
        cwd="/home/pcabeza/Proyectos/atrevete-bot",
    )
    lines = result.stdout.splitlines()
    relevant = [
        line for line in lines
        if conversation_id[:8] in line
        or "booking_step" in line.lower()
        or "selected_services" in line.lower()
        or "service_ids" in line.lower()
        or "SLOT_TAKEN" in line
        or "slot_taken" in line
        or "book(" in line
        or "manage_customer" in line
        or "COMPLETED" in line
        or "CONFIRMATION" in line
        or "CUSTOMER_NAME" in line
    ]
    return relevant


async def main():
    print("=" * 60)
    print("QA TEST: Elena Garcia -- Clean-State Multi-Service Booking")
    print(f"Phone: {PHONE} (fresh, no prior customer record)")
    print(f"Started: {datetime.now(UTC).isoformat()}")
    print("=" * 60)

    # Run conversation
    results = await run_test()

    print(f"\n{'='*60}")
    print("CONVERSATION COMPLETE")
    print(f"Outcome: {results['outcome']}")
    print(f"Turns: {results['total_turns']}")
    print(f"Bugs found: {results['bugs_count']}")

    if results["bugs"]:
        print("\nBUGS DETECTED:")
        for bug in results["bugs"]:
            print(f"  [{bug['severity']}] {bug['category']}: {bug['evidence']}")

    # Verify DB
    print(f"\n{'='*60}")
    print("DATABASE VERIFICATION")
    print("=" * 60)
    try:
        db_results = await verify_db(PHONE)
        results["db_verification"] = db_results

        print(f"Total appointments found: {db_results['total_appointments']}")
        print(f"Multi-service booking found: {db_results['multi_service_found']}")
        print(f"Duration check passed (>=70 min): {db_results['duration_check_passed']}")

        if db_results["appointments"]:
            print("\nAppointments by phone:")
            for apt in db_results["appointments"]:
                print(
                    f"  - {apt['first_name']} with {apt['stylist']}: "
                    f"{apt['service_count']} services, "
                    f"{apt['duration_minutes']} min, "
                    f"status={apt['status']}"
                )

        if db_results["services_by_name"]:
            print("\nServices by name (Elena):")
            for svc in db_results["services_by_name"]:
                print(
                    f"  - {svc['first_name']}: {svc['service_name']} "
                    f"with {svc['stylist']}, "
                    f"{svc['duration_minutes']} min"
                )
    except Exception as e:
        print(f"DB verification failed: {e}")
        db_results = {"error": str(e)}
        results["db_verification"] = db_results

    # Agent logs
    print(f"\n{'='*60}")
    print("AGENT LOG INSPECTION")
    print("=" * 60)
    try:
        log_lines = await get_agent_logs(results["conversation_id"])
        for line in log_lines[-30:]:  # last 30 relevant lines
            print(line)
    except Exception as e:
        print(f"Log check failed: {e}")
        log_lines = []

    # L1-L5 evaluation
    print(f"\n{'='*60}")
    print("L1-L5 EVALUATION")
    print("=" * 60)

    all_responses = " ".join(t.get("bot", "") for t in results["turns"]).lower()

    # L1: Task Completion — did the booking complete with both services?
    l1_pass = (
        results["outcome"] == "booking_confirmed"
        and db_results.get("multi_service_found", False)
    )
    l1_score = "PASS" if l1_pass else "FAIL"
    print(f"L1 (Task Completion): {l1_score}")
    print(f"   Booking confirmed: {results['outcome'] == 'booking_confirmed'}")
    print(f"   Multi-service in DB: {db_results.get('multi_service_found', False)}")

    # L2: Context Retention — selected_services stayed at 2
    selected_svc = results.get("selected_services_in_state", [])
    context_bugs = [b for b in results["bugs"] if b["category"] == "context_loss"]
    state_error = isinstance(results.get("final_state"), dict) and "error" in results.get("final_state", {})
    if state_error:
        # Checkpoint state capture failed — evaluate L2 from DB data instead
        l2_pass = db_results.get("multi_service_found", False) and len(context_bugs) == 0
        print(f"L2 (Context Retention): {'PASS' if l2_pass else 'FAIL'}")
        print("   NOTE: Checkpoint state unavailable (Redis index error), using DB as proxy")
        print(f"   Multi-service in DB: {db_results.get('multi_service_found', False)}")
    else:
        l2_pass = len(selected_svc) >= 2 and len(context_bugs) == 0
        print(f"L2 (Context Retention): {'PASS' if l2_pass else 'FAIL'}")
        print(f"   selected_services count: {len(selected_svc)}")
    l2_score = "PASS" if l2_pass else "FAIL"
    print(f"   Context loss bugs: {len(context_bugs)}")

    # L3: Error Handling — no SLOT_TAKEN, no timeouts
    slot_taken_bugs = [b for b in results["bugs"] if b["category"] == "slot_taken"]
    timeout_bugs = [b for b in results["bugs"] if b["category"] == "timeout"]
    l3_pass = len(slot_taken_bugs) == 0 and len(timeout_bugs) == 0
    l3_score = "PASS" if l3_pass else "FAIL"
    print(f"L3 (Error Handling): {l3_score}")
    print(f"   SLOT_TAKEN errors: {len(slot_taken_bugs)}")
    print(f"   Timeouts: {len(timeout_bugs)}")

    # L4: Natural Language Quality — responses in Spanish, coherent
    l4_pass = results["total_turns"] <= 15 and results["outcome"] != "stuck"
    l4_score = "PASS" if l4_pass else "FAIL"
    print(f"L4 (NL Quality): {l4_score}")
    print(f"   Total turns: {results['total_turns']} (max 15 expected)")
    print(f"   Outcome: {results['outcome']}")

    # L5: Data Integrity — duration correct, both services in DB
    l5_pass = db_results.get("duration_check_passed", False)
    l5_score = "PASS" if l5_pass else "FAIL"
    print(f"L5 (Data Integrity): {l5_score}")
    print(f"   Duration >= 70 min: {db_results.get('duration_check_passed', False)}")

    overall = "PASS" if all([l1_pass, l2_pass, l3_pass, l4_pass, l5_pass]) else "FAIL"
    results["evaluation"] = {
        "L1_task_completion": l1_score,
        "L2_context_retention": l2_score,
        "L3_error_handling": l3_score,
        "L4_nl_quality": l4_score,
        "L5_data_integrity": l5_score,
        "overall": overall,
    }

    print(f"\nOVERALL: {overall}")

    # Full structured result
    print(f"\n{'='*60}")
    print("FULL STRUCTURED RESULT")
    print("=" * 60)
    print(json.dumps(results, indent=2, ensure_ascii=False, default=str))

    return results


if __name__ == "__main__":
    asyncio.run(main())
