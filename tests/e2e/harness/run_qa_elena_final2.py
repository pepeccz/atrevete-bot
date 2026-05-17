"""QA Test — Elena García — FINAL Multi-Service Validation (attempt 3).

Post-fix validation for multi-service booking flow.
Confirms that a NEW client requesting 2 services (corte + tinte) in a
clean-state environment completes the full booking flow without
SLOT_TAKEN errors and with BOTH services persisted in the DB.

Persona: Elena García (+34699000004) — fresh phone, no customer record.

Critical checks:
  1. Both services in DB appointment (service_ids array has 2 UUIDs)
  2. Duration ~80 min (not 40)
  3. NO SLOT_TAKEN errors
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
PHONE = "+34699000004"
MAX_TURNS = 20


def is_booking_completed(text: str) -> bool:
    """Check if bot confirms booking creation — final confirmation only."""
    t = text.lower()
    # Exclude intermediate steps
    if any(excl in t for excl in [
        "casi lista", "solo necesito", "me das tu nombre", "ultimo paso",
        "siguiente paso", "un momento", "buscando",
        "confirmemos", "confirmas", "te parece bien",
    ]):
        return False
    has_question = "?" in text
    strong_signals = [
        "turno confirmado", "cita confirmada", "reserva confirmada",
        "quedo agendad", "quedo reservad",
        "tu reserva esta confirmada", "tu reserva quedo confirmada",
        "reserva esta confirmada", "tu cita ha sido confirmada",
        "cita ha sido confirmada", "turno ha sido confirmado",
    ]
    if any(kw in t for kw in strong_signals):
        return True
    if not has_question:
        return any(kw in t for kw in [
            "agendamos tu", "\u2705",
            "te esperamos", "nos vemos el",
        ])
    return False


class ConversationTracker:
    """Track conversation state to avoid response loops."""

    def __init__(self):
        self.audience_answered = False
        self.variant_answered = False
        self.stylist_answered = False
        self.slot_picked = False
        self.name_given = False
        self.confirmed = False

    def pick_response(self, text: str, turn_num: int) -> str | None:
        """Map bot response -> next user utterance for Elena."""
        t = text.lower()

        # Terminal: booking done
        if is_booking_completed(text):
            return None

        # Cancellation confusion
        if "cancelar la reserva" in t or "seguro que quieres cancelar" in t:
            return "No, no quiero cancelar"

        # Escalation
        if "conecto con mi equipo" in t or "equipo para que te ayuden" in t:
            return "No, intenta de nuevo por favor con la reserva"

        # Error — retry
        if any(kw in t for kw in [
            "tuve un problema", "ocurrio un error", "error al", "no pude",
            "sigo teniendo", "no esta funcionando", "herramienta",
            "problemas para reservar",
        ]):
            return "Intenta de nuevo por favor"

        # SLOT_TAKEN — ask for another
        if any(kw in t for kw in [
            "no esta disponible", "ya no esta", "slot_taken",
            "acaba de ser reservado", "ya esta ocupad",
        ]):
            return "Si, busquemos otra opcion"

        # Detect structural patterns
        has_time_pattern = any(
            kw in t for kw in [
                "09:", "10:", "11:", "12:", "13:", "14:", "15:", "16:", "17:",
            ]
        )
        has_numbered_list = any(n in t for n in ["1.", "1)", "\u2460", "2.", "2)"])

        # Slot list (numbered time options) — highest priority
        if has_time_pattern and has_numbered_list:
            self.slot_picked = True
            return "La primera opcion"

        if any(kw in t for kw in [
            "huecos disponibles", "proximos huecos",
            "slots disponibles", "horarios disponibles", "huecos libres",
        ]):
            self.slot_picked = True
            return "La primera opcion"

        # Audience/category ask
        is_audience_ask = any(kw in t for kw in [
            "caballero", "nino", "nina", "bebe",
        ]) and ("dama" in t) and ("?" in text)
        if is_audience_ask and not self.audience_answered:
            self.audience_answered = True
            return "Para dama"

        # Service variant (Cortar vs Flequillo, Color vs Color Extra)
        is_variant_question = (
            ("flequillo" in t or "extra" in t or "drastic" in t or "correcciones" in t)
            and not has_time_pattern
        )
        if is_variant_question and not self.variant_answered:
            self.variant_answered = True
            return "El normal, la Tinte de 40 minutos"

        # Date/time request
        is_when_question = any(kw in t for kw in [
            "cuando", "para cuando",
            "que dia", "que hora", "que fecha",
            "te gustaria reservar",
        ])
        if is_when_question and not has_time_pattern:
            return "El proximo dia que tengan disponible"

        # Stylist preference
        if (
            ("estilista" in t or "profesional" in t)
            and ("preferid" in t or "preferencia" in t or "?" in text)
            and not self.stylist_answered
        ):
            self.stylist_answered = True
            return "No tengo preferencia, cualquier estilista esta bien"

        # Stylist list with numbered options
        if ("luciana" in t or "pilar" in t) and has_numbered_list and not has_time_pattern:
            if not self.stylist_answered:
                self.stylist_answered = True
                return "Sin preferencia, cualquiera esta bien"

        # Add-on offer
        if any(kw in t for kw in [
            "add-on", "adicional", "sumar", "agregar servicio",
            "deseas agregar", "quieres anadir", "anadir algun",
            "agregar algun", "servicio adicional",
        ]):
            return "No gracias, solo esos dos servicios"

        # Name request
        if any(kw in t for kw in [
            "nombre", "como te llamas",
            "a nombre de", "apellidos", "tu nombre",
        ]):
            self.name_given = True
            return "Elena García"

        # Notes / preferences request
        if any(kw in t for kw in [
            "algo mas que deba saber",
            "preferencia especial", "condicion en tu cabello",
            "nota", "comentario", "algun detalle",
            "algo mas antes",
            "algo que deba", "algo que quieras",
            "dejar alguna", "anadir nota",
        ]):
            return "Sin notas"

        # Confirmation request
        if any(kw in t for kw in [
            "confirma", "todo correcto", "es correcto",
            "esta bien", "confirmamos", "resumen de tu reserva",
            "te confirmo", "resumen", "procedemos",
            "te parece bien", "quieres que lo confirmemos",
        ]):
            has_corte = "corte" in t or "cortar" in t
            has_tinte = "color" in t or "tinte" in t
            if not (has_corte and has_tinte):
                return "Espera, yo queria los dos servicios, corte y tinte, estan incluidos los dos?"
            self.confirmed = True
            return "Si, confirmo"

        # Yes/no slot confirmation
        if any(kw in t for kw in [
            "te viene bien", "te va bien",
            "aceptas", "quedamos el",
        ]):
            return "Si, perfecto"

        # Bot asks about availability search
        if "busquemos disponibilidad" in t or "buscar disponibilidad" in t:
            return "Si, dale"

        # Fallback: any numbered list
        if has_numbered_list:
            return "La primera opcion"

        # Anti-loop
        if turn_num >= MAX_TURNS - 2:
            return None

        return "Si, dale"


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
        "test": "elena-final2-multiservice-validation",
        "started_at": datetime.now(UTC).isoformat(),
        "turns": [],
        "bugs": [],
        "outcome": "unknown",
    }

    try:
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

            # Bug detection
            bot_lower = bot_response.lower()

            # Check for SLOT_TAKEN errors
            if "slot_taken" in bot_lower or "ya esta ocupad" in bot_lower:
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

        # Capture final state
        try:
            binary_client = redis.from_url(settings.REDIS_URL, decode_responses=False)
            state_harness = RedisTestHarness(
                redis_client=client,
                binary_redis_client=binary_client,
            )
            final_state = await state_harness.capture_final_state(conversation_id)
            results["final_state"] = final_state or {}
            await binary_client.aclose()

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
        # Query 1: appointments + service count + stylist + duration
        result = await conn.execute(text("""
            SELECT a.id, a.first_name, array_length(a.service_ids, 1) as num_services,
                   a.duration_minutes, st.name as stylist, a.start_time, a.status,
                   a.service_ids
            FROM appointments a
            JOIN stylists st ON a.stylist_id = st.id
            WHERE a.first_name = 'Elena'
            ORDER BY a.created_at DESC LIMIT 3
        """))
        rows_by_name = result.fetchall()

        # Query 2: expanded services
        result2 = await conn.execute(text("""
            SELECT s.name FROM appointments a
            JOIN services s ON s.id = ANY(a.service_ids)
            WHERE a.first_name = 'Elena'
            ORDER BY a.created_at DESC LIMIT 5
        """))
        service_rows = result2.fetchall()

        # Query 3: by phone (via customer join)
        result3 = await conn.execute(text("""
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
        rows_by_phone = result3.fetchall()

    await engine.dispose()

    appointments = []
    for row in rows_by_name:
        appointments.append({
            "id": str(row.id),
            "first_name": row.first_name,
            "num_services": row.num_services,
            "duration_minutes": row.duration_minutes,
            "stylist": row.stylist,
            "start_time": row.start_time.isoformat() if row.start_time else None,
            "status": row.status,
            "service_ids": [str(sid) for sid in row.service_ids] if row.service_ids else [],
        })

    service_names = [row.name for row in service_rows]

    phone_appointments = []
    for row in rows_by_phone:
        phone_appointments.append({
            "id": str(row.id),
            "first_name": row.first_name,
            "service_count": len(row.service_ids) if row.service_ids else 0,
            "duration_minutes": row.duration_minutes,
            "stylist": row.stylist,
            "start_time": row.start_time.isoformat() if row.start_time else None,
            "status": row.status,
        })

    multi_service = any(
        a["num_services"] and a["num_services"] >= 2
        for a in appointments
    )
    duration_ok = any(
        a["duration_minutes"] and a["duration_minutes"] >= 70
        for a in appointments
    )

    return {
        "total_appointments": len(appointments),
        "appointments_by_name": appointments,
        "service_names": service_names,
        "appointments_by_phone": phone_appointments,
        "multi_service_found": multi_service,
        "duration_check_passed": duration_ok,
    }


async def get_agent_logs() -> list[str]:
    """Fetch agent container logs for auto-resolve, selected_services, injected."""
    import subprocess
    result = subprocess.run(
        ["docker", "compose", "logs", "--no-color", "--tail=50", "agent"],
        capture_output=True, text=True,
        cwd="/home/pcabeza/Proyectos/atrevete-bot",
    )
    lines = result.stdout.splitlines()
    relevant = [
        line for line in lines
        if any(kw in line.lower() for kw in [
            "auto-resolved", "auto_resolved", "autoresolved",
            "selected_services", "injected",
        ])
    ]
    return relevant


async def main():
    print("=" * 60)
    print("QA TEST: Elena García — FINAL Multi-Service Validation (attempt 3)")
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

        if db_results["appointments_by_name"]:
            print("\nAppointments (by first_name='Elena'):")
            for apt in db_results["appointments_by_name"]:
                print(
                    f"  - {apt['first_name']} with {apt['stylist']}: "
                    f"{apt['num_services']} services, "
                    f"{apt['duration_minutes']} min, "
                    f"status={apt['status']}"
                )

        if db_results["service_names"]:
            print(f"\nService names found: {db_results['service_names']}")

        if db_results["appointments_by_phone"]:
            print(f"\nAppointments (by phone {PHONE}):")
            for apt in db_results["appointments_by_phone"]:
                print(
                    f"  - {apt['first_name']} with {apt['stylist']}: "
                    f"{apt['service_count']} services, "
                    f"{apt['duration_minutes']} min, "
                    f"status={apt['status']}"
                )
    except Exception as e:
        print(f"DB verification failed: {e}")
        import traceback
        traceback.print_exc()
        db_results = {"error": str(e)}
        results["db_verification"] = db_results

    # Agent logs — check for auto-resolve
    print(f"\n{'='*60}")
    print("AGENT LOG INSPECTION (auto-resolve / selected_services / injected)")
    print("=" * 60)
    try:
        log_lines = await get_agent_logs()
        if log_lines:
            for line in log_lines[-30:]:
                print(line)
        else:
            print("(no matching log lines found)")
    except Exception as e:
        print(f"Log check failed: {e}")
        log_lines = []

    # L1-L5 evaluation
    print(f"\n{'='*60}")
    print("L1-L5 EVALUATION")
    print("=" * 60)

    # L1: Task Completion
    l1_pass = (
        results["outcome"] == "booking_confirmed"
        and db_results.get("multi_service_found", False)
    )
    l1_score = "PASS" if l1_pass else "FAIL"
    print(f"L1 (Task Completion): {l1_score}")
    print(f"   Booking confirmed: {results['outcome'] == 'booking_confirmed'}")
    print(f"   Multi-service in DB: {db_results.get('multi_service_found', False)}")

    # L2: Context Retention
    selected_svc = results.get("selected_services_in_state", [])
    context_bugs = [b for b in results["bugs"] if b["category"] == "context_loss"]
    state_error = (
        isinstance(results.get("final_state"), dict)
        and "error" in results.get("final_state", {})
    )
    if state_error:
        l2_pass = db_results.get("multi_service_found", False) and len(context_bugs) == 0
        print(f"L2 (Context Retention): {'PASS' if l2_pass else 'FAIL'}")
        print("   NOTE: Checkpoint state unavailable, using DB as proxy")
        print(f"   Multi-service in DB: {db_results.get('multi_service_found', False)}")
    else:
        l2_pass = len(selected_svc) >= 2 and len(context_bugs) == 0
        print(f"L2 (Context Retention): {'PASS' if l2_pass else 'FAIL'}")
        print(f"   selected_services count: {len(selected_svc)}")
    l2_score = "PASS" if l2_pass else "FAIL"
    print(f"   Context loss bugs: {len(context_bugs)}")

    # L3: Error Handling
    slot_taken_bugs = [b for b in results["bugs"] if b["category"] == "slot_taken"]
    timeout_bugs = [b for b in results["bugs"] if b["category"] == "timeout"]
    l3_pass = len(slot_taken_bugs) == 0 and len(timeout_bugs) == 0
    l3_score = "PASS" if l3_pass else "FAIL"
    print(f"L3 (Error Handling): {l3_score}")
    print(f"   SLOT_TAKEN errors: {len(slot_taken_bugs)}")
    print(f"   Timeouts: {len(timeout_bugs)}")

    # L4: Natural Language Quality
    l4_pass = results["total_turns"] <= 15 and results["outcome"] != "stuck"
    l4_score = "PASS" if l4_pass else "FAIL"
    print(f"L4 (NL Quality): {l4_score}")
    print(f"   Total turns: {results['total_turns']} (max 15 expected)")
    print(f"   Outcome: {results['outcome']}")

    # L5: Data Integrity
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
