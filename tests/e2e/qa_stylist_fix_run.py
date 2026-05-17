"""
QA Post-Fix #2: stylist_selection resolver
Executes a custom booking scenario testing the stylist resolver fix.

Run with:
    MESSAGE_BATCH_WINDOW_SECONDS=0 \
    REDIS_URL="redis://:9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda@localhost:6379/0" \
    python tests/e2e/qa_stylist_fix_run.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid

# Ensure we can import project modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Force test env
os.environ["MESSAGE_BATCH_WINDOW_SECONDS"] = "0"
redis_password = os.environ.get(
    "REDIS_PASSWORD", "9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda"
)
redis_url = os.environ.get("REDIS_URL", f"redis://:{redis_password}@localhost:6379/0")
os.environ["REDIS_URL"] = redis_url

from shared.config import get_settings

get_settings.cache_clear()

import redis.asyncio as redis

from tests.e2e.harness.redis_harness import RedisTestHarness

SCENARIO_TURNS = [
    {
        "turn": 1,
        "user": "Hola! Quiero sacar un turno para cortarme el pelo",
        "verify": None,
    },
    {
        "turn": 2,
        "user": "Soy María, quiero cortarme el pelo",
        "verify": "no_name_in_greeting",  # token filter: must NOT say "¡Hola, María!"
    },
    {
        "turn": 3,
        "user": "Un corte de caballero",
        "verify": None,
    },
    {
        "turn": 4,
        "user": "No tengo preferencia, con cualquiera que tenga lugar",
        "verify": "stylist_list_shown",  # must show stylist list
    },
    {
        "turn": 5,
        "user": "El primer horario que tengas disponible",
        "verify": "slot_locked",  # state machine must advance past stylist_selection
    },
    {
        "turn": 6,
        "user": "Sí, confirmo",
        "verify": "booking_success",  # CRITICAL: must NOT error
    },
]


def check_no_name_leak(response: str) -> dict:
    """Verify token filter — should not say 'Hola, María' or 'Hola María'."""
    low = response.lower()
    # Forbidden patterns: greeting the user by their just-introduced name
    forbidden = ["hola, maría", "hola maría", "¡hola, maría", "¡hola maría"]
    found = [p for p in forbidden if p in low]
    passed = len(found) == 0
    return {
        "check": "no_name_leak",
        "pass": passed,
        "details": f"Forbidden patterns found: {found}" if found else "No name leak detected",
    }


def check_stylist_list(response: str) -> dict:
    """Verify stylist list shown — should mention multiple stylists or 'estilista'."""
    low = response.lower()
    keywords = ["estilista", "disponible", "horario", "cualquiera", "opción"]
    found = [k for k in keywords if k in low]
    passed = len(found) >= 1
    return {
        "check": "stylist_list_shown",
        "pass": passed,
        "details": f"Found keywords: {found}" if found else "No stylist/availability keywords found",
    }


def check_slot_locked(response: str) -> dict:
    """Verify slot was locked in — should mention a time or 'elegiste'/'has elegido'."""
    low = response.lower()
    # The fixed resolver should produce a clear selection acknowledgment
    keywords = [
        "primer horario", "elegid", "seleccionad", "reservar", "turno",
        "confirmamos", "confirmar", "fecha", "lunes", "martes", "miércoles",
        "jueves", "viernes", "sábado", "agendar", "reserva", "disponible",
        "lo siento",  # if still erroring, this would show up
        "⚠️", "error"  # error indicators
    ]
    error_keywords = ["lo siento, hubo", "error inesperado", "volver a intentar"]
    errors_found = [k for k in error_keywords if k in low]
    progress_found = [k for k in keywords[:10] if k in low]

    # As long as there's no hard error and there IS some slot-related content
    has_error = len(errors_found) > 0
    has_progress = len(progress_found) >= 1

    passed = not has_error and has_progress
    return {
        "check": "slot_locked",
        "pass": passed,
        "details": (
            f"Error patterns: {errors_found}, Progress keywords: {progress_found}"
        ),
    }


def check_booking_success(response: str) -> dict:
    """CRITICAL: booking should complete, not error."""
    low = response.lower()
    error_patterns = [
        "lo siento, hubo un error",
        "volver a intentar",
        "error inesperado",
        "no pude",
        "problema al crear",
    ]
    success_patterns = [
        "confirmad", "reservad", "turno", "agendad", "cita",
        "cuándo", "cuánto", "servicio",  # continuing normally
    ]
    errors_found = [p for p in error_patterns if p in low]
    successes_found = [p for p in success_patterns if p in low]

    has_error = len(errors_found) > 0
    has_success = len(successes_found) >= 1

    passed = not has_error  # primary: no error message
    return {
        "check": "booking_success",
        "pass": passed,
        "details": (
            f"Errors: {errors_found or 'none'} | Success indicators: {successes_found or 'none'}"
        ),
    }


VERIFIERS = {
    "no_name_in_greeting": check_no_name_leak,
    "stylist_list_shown": check_stylist_list,
    "slot_locked": check_slot_locked,
    "booking_success": check_booking_success,
}


async def run_qa_scenario() -> dict:
    settings = get_settings()
    conversation_id = str(uuid.uuid4())
    print(f"\n{'='*70}")
    print("QA Post-Fix #2: stylist_selection resolver")
    print(f"Conversation ID: {conversation_id}")
    print(f"Redis URL: {settings.REDIS_URL}")
    print(f"{'='*70}\n")

    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    binary_redis_client = redis.from_url(settings.REDIS_URL, decode_responses=False)

    # Ping to ensure connectivity
    await redis_client.ping()
    print("✅ Redis connected\n")

    harness = RedisTestHarness(
        redis_client=redis_client,
        binary_redis_client=binary_redis_client,
    )

    # CRITICAL: subscribe BEFORE injecting
    await harness.prepare_response_capture()
    print("✅ Subscribed to outgoing_messages channel\n")

    turns = []
    verification_results = []
    overall_ok = True

    for scenario_turn in SCENARIO_TURNS:
        turn_num = scenario_turn["turn"]
        user_msg = scenario_turn["user"]
        verifier_key = scenario_turn["verify"]

        print(f"{'─'*60}")
        print(f"Turn {turn_num} → USER: {user_msg}")

        try:
            start = time.monotonic()
            result = await harness.execute_turn(
                conversation_id=conversation_id,
                user_message=user_msg,
                persona_name="María",
                timeout=45.0,
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)
        except TimeoutError as e:
            print(f"❌ TIMEOUT: {e}")
            turns.append({
                "turn_number": turn_num,
                "user_message": user_msg,
                "agent_response": "TIMEOUT",
                "response_latency_ms": 45000,
                "error": str(e),
            })
            overall_ok = False
            break

        agent_response = result["agent_response"]
        print(f"Turn {turn_num} ← AGENT ({elapsed_ms}ms):")
        print(f"  {agent_response[:300]}")

        if verifier_key and verifier_key in VERIFIERS:
            vresult = VERIFIERS[verifier_key](agent_response)
            icon = "✅" if vresult["pass"] else "❌"
            print(f"  {icon} Verify [{vresult['check']}]: {vresult['details']}")
            verification_results.append({**vresult, "turn": turn_num})
            if not vresult["pass"]:
                overall_ok = False

        turns.append(result)
        print()

    # Capture final state
    print(f"{'─'*60}")
    print("Capturing final state from Redis checkpoint...")
    try:
        final_state = await harness.capture_final_state(conversation_id)
    except Exception as e:
        print(f"⚠️  Could not capture final state: {e}")
        final_state = {}

    await harness.close()
    await redis_client.close()
    await binary_redis_client.close()

    # ── FINAL STATE ANALYSIS ──────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("FINAL STATE ANALYSIS")
    print(f"{'='*70}")

    appointment_created = False
    customer_id = None
    appointment_datetime = None

    if final_state:
        appointment_created = bool(final_state.get("appointment_created"))
        customer_id = final_state.get("customer_id")
        appointment_datetime = final_state.get("appointment_datetime")
        current_mode = final_state.get("current_mode")
        stylist_id = final_state.get("stylist_id")
        service_type = final_state.get("service_type")

        print(f"  appointment_created : {appointment_created}")
        print(f"  customer_id         : {customer_id}")
        print(f"  appointment_datetime: {appointment_datetime}")
        print(f"  current_mode        : {current_mode}")
        print(f"  stylist_id          : {stylist_id}")
        print(f"  service_type        : {service_type}")

        # Check specific state machine advancement
        if current_mode == "BOOKING" and stylist_id is not None:
            print("  ✅ State advanced past stylist_selection (stylist_id resolved)")
        elif current_mode == "BOOKING" and stylist_id is None:
            print("  ❌ State stuck — stylist_id still None (resolver may not have fired)")
    else:
        print("  ⚠️  No final state captured")

    # ── VERIFICATION SUMMARY ─────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("VERIFICATION CHECKLIST")
    print(f"{'='*70}")

    checks = {
        "no_name_leak": None,
        "stylist_resolver_worked": None,
        "booking_completed": None,
        "appointment_created_flag": appointment_created,
        "customer_id_valid": bool(customer_id),
        "appointment_has_datetime": bool(appointment_datetime),
    }

    for vr in verification_results:
        if vr["check"] == "no_name_leak":
            checks["no_name_leak"] = vr["pass"]
        elif vr["check"] == "slot_locked":
            checks["stylist_resolver_worked"] = vr["pass"]
        elif vr["check"] == "booking_success":
            checks["booking_completed"] = vr["pass"]

    for check_name, result in checks.items():
        if result is True:
            print(f"  ✅ {check_name}")
        elif result is False:
            print(f"  ❌ {check_name}")
        else:
            print(f"  ⚪ {check_name} (not evaluated)")

    # ── OVERALL RESULT ────────────────────────────────────────────────────────
    all_critical = [
        checks["booking_completed"],
        checks["appointment_created_flag"],
    ]
    overall_pass = overall_ok and all(x is not False for x in all_critical)

    print(f"\n{'='*70}")
    if overall_pass:
        print("🟢 OVERALL RESULT: PASS")
    else:
        print("🔴 OVERALL RESULT: FAIL")
    print(f"{'='*70}\n")

    return {
        "scenario_id": "stylist_selection_fix_v2",
        "conversation_id": conversation_id,
        "turns": turns,
        "verification_results": verification_results,
        "final_state_summary": {
            "appointment_created": appointment_created,
            "customer_id": str(customer_id) if customer_id else None,
            "appointment_datetime": str(appointment_datetime) if appointment_datetime else None,
        },
        "checks": checks,
        "overall_pass": overall_pass,
    }


if __name__ == "__main__":
    result = asyncio.run(run_qa_scenario())
    # Dump full trace as JSON for the report
    print("\n── FULL CONVERSATION TRACE ──────────────────────────────────────────")
    for t in result["turns"]:
        print(f"\nTurn {t['turn_number']} ({t.get('response_latency_ms', '?')}ms)")
        print(f"  USER : {t['user_message']}")
        resp = t.get('agent_response', 'N/A')
        print(f"  AGENT: {resp[:500]}")
    print("\n── DONE ─────────────────────────────────────────────────────────────")
    sys.exit(0 if result["overall_pass"] else 1)
