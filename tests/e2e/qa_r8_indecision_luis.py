"""
QA Round 8 — Flow: indecision — Persona: luis_indecisive_client
Commit: 9910cdb

Key changes from R7 (incorporating R7 lessons):
1. T6: Accept what bot offers — "El primero que tengan disponible" (NOT "viernes" specific)
2. detect 'notes' step BEFORE confirmation: send "Sin notas" if bot asks for notes
3. If bot confirms a slot is selected, next msg is "Sin notas" to advance FSM
4. Slot selection: send EXPLICIT slot text (e.g. "1" or "el martes a las 14:00")
5. manage_customer should be called by T2-T3 to get customer_id before book()
6. Never insist on "el viernes" — accept the nearest available day (3-day rule)
7. If book() fails once, try "Sí, confirmo" then on next fail also try "Confirmo la cita"
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime

import redis.asyncio as redis

sys.path.insert(0, "/home/pcabeza/Proyectos/atrevete-bot")

from tests.e2e.harness.redis_harness import RedisTestHarness

REDIS_URL = "redis://:9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda@localhost:6379/0"
DB_CONTAINER = "atrevete-postgres"

PERSONA_NAME = "Luis Martínez"
PERSONA_PHONE = "+34699000802"  # Fresh phone number for R8
CONVERSATION_ID = str(uuid.uuid4())
RESPONSE_TIMEOUT = 35.0

print(f"\n{'='*60}")
print(f"QA ROUND 8 — Flow: indecision | Persona: luis_indecisive_client")
print(f"conversation_id: {CONVERSATION_ID}")
print(f"Started at: {datetime.now(UTC).isoformat()}")
print(f"Commit: 9910cdb")
print(f"{'='*60}\n")


def decide_next_message(turn_num: int, agent_response: str) -> str | None:
    """
    R8 Harness script with R7 lessons applied.

    CRITICAL FIXES vs R7:
    1. Slot selection: "El primero que tengan disponible" (no specific day name)
       This avoids "viernes" mismatch when bot only shows martes/miércoles slots.
    2. Notes step: explicitly detect and respond "Sin notas" BEFORE confirmation.
    3. If bot says algo como "¿Deseás agregar notas?" → "Sin notas" (not "Sí, confirmo")
    4. If slot shown numbered (1. / 1)) → respond with "1" or accept first option plainly
    5. If book() tool error → keep retrying with "Sí, confirmo" up to 3 times,
       then switch to "Confirmo la cita por favor"
    """
    resp_lower = agent_response.lower()

    # Global: booking success → stop
    if any(x in resp_lower for x in ["exitosamente", "confirmado tu cita", "agendado", "reservado exitosamente", "tu turno quedó"]):
        return None  # Done!

    if turn_num == 1:
        # T2 — bot responded to greeting
        if "corte caballero" in resp_lower or "1." in agent_response or "1)" in agent_response:
            return "Quiero el corte caballero"
        if any(x in resp_lower for x in ["recomend", "sugier", "corte", "servicio"]):
            return "Quiero el corte caballero"
        return "Soy hombre, quiero verme más prolijo con un corte"

    if turn_num == 2:
        # T3 — after service name offered
        # If bot asks for verbal confirm
        if any(x in resp_lower for x in ["confirm", "seleccionad", "escogiste", "elegiste", "querés el"]):
            return "Sí, quiero ese servicio"
        # If bot skipped straight to add-ons
        if any(x in resp_lower for x in ["barba", "hidrat", "añad", "agreg", "adicional", "complemento"]):
            return "No, solo el corte"
        # If bot skipped to date/slot directly
        if any(x in resp_lower for x in ["fecha", "cuándo", "cuando", "día", "horario", "disponib"]):
            return "El primero que tengan disponible"
        # If bot asks stylist
        if any(x in resp_lower for x in ["estilista", "quien", "quién"]):
            return "Cualquiera que esté disponible"
        # Default: service confirmation
        return "Sí, quiero ese servicio"

    if turn_num == 3:
        # T4 — after verbal service confirm
        if any(x in resp_lower for x in ["barba", "hidrat", "añad", "agreg", "adicional", "complemento"]):
            return "No, solo el corte"
        if any(x in resp_lower for x in ["fecha", "cuándo", "cuando", "día"]):
            return "El primero que tengan disponible"
        if any(x in resp_lower for x in ["disponib", "horario", "1.", "1)"]):
            return "El primero que tengan disponible"
        if any(x in resp_lower for x in ["estilista", "quien", "quién"]):
            return "Cualquiera que esté disponible"
        if any(x in resp_lower for x in ["nombre", "cómo te llam", "llamás"]):
            return "Luis Martínez"
        if any(x in resp_lower for x in ["nota", "aclaración", "observ", "algo más"]):
            return "Sin notas"
        return "No, solo el corte"

    if turn_num == 4:
        # T5 — after add-ons declined
        if any(x in resp_lower for x in ["fecha", "cuándo", "cuando", "día"]):
            return "El primero que tengan disponible"
        if any(x in resp_lower for x in ["disponib", "horario"]) or "1." in agent_response or "1)" in agent_response:
            return "El primero que tengan disponible"
        if any(x in resp_lower for x in ["estilista", "quien", "quién"]):
            return "Cualquiera que esté disponible"
        if any(x in resp_lower for x in ["nombre", "cómo te llam", "llamás"]):
            return "Luis Martínez"
        if any(x in resp_lower for x in ["barba", "hidrat", "añad", "agreg"]):
            return "No, solo el corte"
        if any(x in resp_lower for x in ["nota", "aclaración", "observ", "algo más"]):
            return "Sin notas"
        if any(x in resp_lower for x in ["confirm", "reserv"]):
            return "Sí, confirmo"
        return "El primero que tengan disponible"

    if turn_num == 5:
        # T6 — stylist / first slot
        if any(x in resp_lower for x in ["estilista", "quién", "quien", "luciana", "peluquer"]):
            return "Cualquiera que esté disponible"
        if any(x in resp_lower for x in ["nombre", "cómo te llam", "llamás"]):
            return "Luis Martínez"
        if any(x in resp_lower for x in ["nota", "aclaración", "observ", "algo más"]):
            return "Sin notas"
        if any(x in resp_lower for x in ["confirm", "reserv", "¿confirmas", "¿deseas"]):
            return "Sí, confirmo"
        if "1." in agent_response or "1)" in agent_response or any(x in resp_lower for x in ["disponib", "horario", "lunes", "martes", "miércoles", "jueves", "viernes"]):
            return "El primero que tengan disponible"
        return "Cualquiera que esté disponible"

    if turn_num == 6:
        # T7 — name, notes or confirm
        if any(x in resp_lower for x in ["nombre", "cómo te llam", "llamás"]):
            return "Luis Martínez"
        if any(x in resp_lower for x in ["nota", "aclaración", "observ", "algo más"]):
            return "Sin notas"
        if any(x in resp_lower for x in ["confirm", "reserv", "¿confirmas"]):
            return "Sí, confirmo"
        if any(x in resp_lower for x in ["estilista", "quien", "quién"]):
            return "Cualquiera que esté disponible"
        if "1." in agent_response or "1)" in agent_response or any(x in resp_lower for x in ["disponib", "horario", "lunes", "martes", "miércoles"]):
            return "El primero que tengan disponible"
        return "Luis Martínez"

    if turn_num == 7:
        # T8 — notes or confirm
        if any(x in resp_lower for x in ["nota", "aclaración", "observ", "algo más"]):
            return "Sin notas"
        if any(x in resp_lower for x in ["confirm", "reserv", "¿confirmas", "¿deseas"]):
            return "Sí, confirmo"
        if any(x in resp_lower for x in ["nombre", "cómo te llam"]):
            return "Luis Martínez"
        if any(x in resp_lower for x in ["estilista"]):
            return "Cualquiera que esté disponible"
        return "Sin notas"

    if turn_num == 8:
        # T9 — confirmation
        if any(x in resp_lower for x in ["confirm", "reserv", "¿confirmas", "¿deseas"]):
            return "Sí, confirmo"
        if any(x in resp_lower for x in ["nota", "aclaración"]):
            return "Sin notas"
        if any(x in resp_lower for x in ["nombre"]):
            return "Luis Martínez"
        return "Sí, confirmo"

    # Turns 9–18 — handle stragglers / confirmation loops
    # R7 lesson: book() fails → keep confirming, alternate wording after 3 fails
    if turn_num <= 18:
        # Check for error/retry message from bot
        error_phrases = ["tuve un problema", "no está funcionando", "error", "no pude"]
        if any(x in resp_lower for x in error_phrases):
            # Alternate phrasing after repeated failures
            if turn_num % 2 == 0:
                return "Confirmo la cita por favor"
            else:
                return "Sí, confirmo"
        if any(x in resp_lower for x in ["nota", "aclaración"]):
            return "Sin notas"
        if any(x in resp_lower for x in ["confirm", "reserv"]):
            return "Sí, confirmo"
        if any(x in resp_lower for x in ["nombre", "cómo te llam"]):
            return "Luis Martínez"
        if any(x in resp_lower for x in ["estilista"]):
            return "Cualquiera que esté disponible"
        if "1." in agent_response or "1)" in agent_response:
            return "El primero que tengan disponible"
        if any(x in resp_lower for x in ["barba", "hidrat", "agreg"]):
            return "No, solo el corte"
        return "Sí, confirmo"

    return None


def check_appointment_in_db() -> int:
    """Check if appointment was created in DB in the last hour via docker exec."""
    import subprocess
    result = subprocess.run(
        [
            "docker", "exec", DB_CONTAINER,
            "psql", "-U", "atrevete", "-d", "atrevete_db",
            "-t", "-c",
            "SELECT count(*) FROM appointments WHERE created_at > now() - interval '1 hour';"
        ],
        capture_output=True, text=True
    )
    raw = result.stdout.strip()
    try:
        return int(raw)
    except ValueError:
        print(f"  [DB CHECK ERROR] stdout={result.stdout!r} stderr={result.stderr!r}")
        return -1


async def run_indecision_flow():
    r = redis.from_url(REDIS_URL, decode_responses=True, max_connections=10)
    harness = RedisTestHarness(redis_client=r, response_channel="outgoing_messages")

    # CRITICAL: Subscribe BEFORE injecting
    await harness.prepare_response_capture()
    print("[✓] Subscribed to outgoing_messages pubsub")

    turns = []
    milestones_hit = []
    bugs_observed = []

    agent_response = ""
    turn_num = 0

    # R8 Harness — T1 per spec
    T1_MESSAGE = "Hola, soy hombre y quiero verme más prolijo, ¿qué me recomendás?"

    try:
        # Turn 1
        turn_num = 1
        print(f"\n[T{turn_num}] USER: {T1_MESSAGE}")
        result = await harness.execute_turn(
            conversation_id=CONVERSATION_ID,
            user_message=T1_MESSAGE,
            persona_name=PERSONA_NAME,
            timeout=RESPONSE_TIMEOUT,
            customer_phone=PERSONA_PHONE,
        )
        agent_response = result["agent_response"]
        turns.append(result)
        print(f"[T{turn_num}] BOT ({result['response_latency_ms']}ms): {agent_response[:400]}")

        if agent_response:
            milestones_hit.append("greeting_done")

        # Bug checks
        narration_phrases = ["*El agente", "*Busco", "*Verifico", "*Compruebo"]
        for phrase in narration_phrases:
            if phrase.lower() in agent_response.lower():
                bugs_observed.append(f"BUG-002: narration phrase in T{turn_num}: '{phrase}'")

        # Main loop
        while turn_num < 18:
            next_msg = decide_next_message(turn_num, agent_response)
            if next_msg is None:
                print(f"\n[✓] Flow completed after {turn_num} turns (booking confirmed)")
                break

            turn_num += 1
            print(f"\n[T{turn_num}] USER: {next_msg}")

            result = await harness.execute_turn(
                conversation_id=CONVERSATION_ID,
                user_message=next_msg,
                persona_name=PERSONA_NAME,
                timeout=RESPONSE_TIMEOUT,
                customer_phone=PERSONA_PHONE,
            )
            agent_response = result["agent_response"]
            turns.append(result)
            print(f"[T{turn_num}] BOT ({result['response_latency_ms']}ms): {agent_response[:500]}")

            resp_lower = agent_response.lower()

            # Milestone tracking
            if "discovery_started" not in milestones_hit and any(x in resp_lower for x in ["cuéntame", "qué tip", "qué estil", "corte", "servicio"]):
                milestones_hit.append("discovery_started")
            if "recommendation_given" not in milestones_hit and any(x in resp_lower for x in ["recomend", "ideal", "sugier", "perfect", "caballero"]):
                milestones_hit.append("recommendation_given")
            if "service_resolved" not in milestones_hit and ("caballero" in resp_lower or ("corte" in resp_lower and turn_num >= 2)):
                milestones_hit.append("service_resolved")
            if "addons_handled" not in milestones_hit and any(x in resp_lower for x in ["barba", "hidrat", "adicional", "solo el corte", "complemento", "sin servicios adicionales"]):
                milestones_hit.append("addons_handled")
            if "slot_resolved" not in milestones_hit and any(x in resp_lower for x in ["viernes", "martes", "lunes", "miércoles", "jueves", "hora", "disponib"]) and turn_num >= 3:
                milestones_hit.append("slot_resolved")
            if "name_provided" not in milestones_hit and "luis" in resp_lower and turn_num >= 4:
                milestones_hit.append("name_provided")
            if "confirmation_done" not in milestones_hit and any(x in resp_lower for x in ["confirm", "reserv", "agend"]):
                milestones_hit.append("confirmation_done")
            if "booking_completed" not in milestones_hit and any(x in resp_lower for x in ["exitosamente", "confirmado tu cita", "agendado", "reservado exitosamente", "turno quedó"]):
                milestones_hit.append("booking_completed")

            # Bug checks
            for phrase in narration_phrases:
                if phrase.lower() in agent_response.lower():
                    bugs_observed.append(f"BUG-002: narration phrase in T{turn_num}: '{phrase}'")

            # Unexpected escalation check
            if any(x in resp_lower for x in ["escalación", "operador", "humano"]) and turn_num <= 5:
                bugs_observed.append(f"UNEXPECTED_ESCALATION at T{turn_num}")
                print(f"[!] WARNING: Unexpected early escalation at T{turn_num}")

            # book() failure detection
            if any(x in resp_lower for x in ["tuve un problema", "no está funcionando", "herramienta para reservar"]):
                bugs_observed.append(f"BOOK_TOOL_FAILURE at T{turn_num}")
                print(f"[!] WARNING: book() tool failure at T{turn_num}")

            if "booking_completed" in milestones_hit:
                print(f"\n[✓] booking_completed milestone hit at T{turn_num}")
                break

    except TimeoutError as e:
        print(f"\n[TIMEOUT] {e}")
        bugs_observed.append(f"TIMEOUT at T{turn_num}: {e}")
    finally:
        await harness.close()
        await r.aclose()

    # DB check
    print(f"\n{'='*60}")
    print("DB CHECK — appointments in last hour:")
    appointment_count = check_appointment_in_db()
    appointment_in_db = appointment_count > 0
    print(f"  count(*) = {appointment_count} → appointment_in_db={appointment_in_db}")

    recommendation_provided = "recommendation_given" in milestones_hit
    appointment_created = "booking_completed" in milestones_hit

    status = "PASS" if (recommendation_provided and appointment_created and appointment_in_db) else "FAIL"

    print(f"\n{'='*60}")
    print("QA ROUND 8 RESULTS")
    print(f"{'='*60}")
    print(f"Status: {status}")
    print(f"Turn count: {turn_num}")
    print(f"recommendation_provided: {recommendation_provided}")
    print(f"appointment_created: {appointment_created}")
    print(f"appointment_in_db: {appointment_in_db}")
    print(f"Milestones hit: {milestones_hit}")
    print(f"Bugs observed: {bugs_observed if bugs_observed else 'None'}")
    print(f"\n--- CONVERSATION TRACE ---")
    for t in turns:
        print(f"\nTurn {t['turn_number']} ({t['response_latency_ms']}ms)")
        print(f"  USER: {t['user_message']}")
        print(f"  BOT:  {t['agent_response'][:600]}")

    return {
        "status": status,
        "turn_count": turn_num,
        "conversation_id": CONVERSATION_ID,
        "recommendation_provided": recommendation_provided,
        "appointment_created": appointment_created,
        "appointment_in_db": appointment_in_db,
        "milestones_hit": milestones_hit,
        "bugs_observed": bugs_observed,
        "turns": turns,
    }


if __name__ == "__main__":
    result = asyncio.run(run_indecision_flow())
    # Save full result
    with open("/tmp/qa_r8_indecision_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n[FINAL STATUS]: {result['status']}")
    print(f"[SAVED]: /tmp/qa_r8_indecision_result.json")
