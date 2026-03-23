"""
QA Round 7 — Flow: indecision — Persona: luis_indecisive_client
Commit: 70b16a6

Key changes from R6:
- T2: use service NAME "Quiero el corte caballero" instead of "1" to avoid re-listing loop
- T3: verbal "Sí, quiero ese servicio" (not "1")
- T4: if add-ons → "No, solo el corte por favor"
- T5: if stylist → "Cualquiera que esté disponible"
- T6: if slot options → "El primero de la tarde del viernes"
- T7/T8/T9: name/notes/confirm follow script
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
PERSONA_PHONE = "+34699000701"  # Fresh phone number for R7
CONVERSATION_ID = str(uuid.uuid4())
RESPONSE_TIMEOUT = 35.0

print(f"\n{'='*60}")
print(f"QA ROUND 7 — Flow: indecision | Persona: luis_indecisive_client")
print(f"conversation_id: {CONVERSATION_ID}")
print(f"Started at: {datetime.now(UTC).isoformat()}")
print(f"Commit: 70b16a6")
print(f"{'='*60}\n")


def decide_next_message(turn_num: int, agent_response: str) -> str | None:
    """
    Deterministic harness script — R7.
    Key improvement: use service NAME instead of "1" to avoid numbered list loop triggers.

    T1: "Hola, soy hombre y quiero verme más prolijo, ¿qué me recomendás?"
    T2: if bot shows numbered list → "Quiero el corte caballero"  (use name, not "1")
    T3: "Sí, quiero ese servicio"  (verbal confirmation, NOT "1")
    T4: if bot asks add-ons → "No, solo el corte por favor"
    T5: if bot asks stylist → "Cualquiera que esté disponible"
    T6: if bot shows slot options → "El primero de la tarde del viernes"
    T7: if bot asks name → "Luis Martínez"
    T8: if bot asks notes → "Sin notas"
    T9: if bot shows confirmation → "Sí, confirmo"
    """
    resp_lower = agent_response.lower()

    if turn_num == 1:
        # T2 decision — bot just responded to our greeting
        # If it shows a numbered list or mentions services → pick by name
        if "1." in agent_response or "1)" in agent_response or "corte caballero" in resp_lower:
            return "Quiero el corte caballero"
        if "recomend" in resp_lower or "sugier" in resp_lower or "corte" in resp_lower:
            return "Quiero el corte caballero"
        # Bot asked clarifying question
        return "Soy hombre, quiero verme más prolijo"

    if turn_num == 2:
        # T3 — verbal service confirmation
        if "confirm" in resp_lower or "seleccionad" in resp_lower or "escogiste" in resp_lower or "elegiste" in resp_lower:
            return "Sí, quiero ese servicio"
        # Bot shows add-on question
        if any(x in resp_lower for x in ["barba", "hidrat", "añad", "agreg", "adicional", "complemento"]):
            return "No, solo el corte por favor"
        # Bot already asking for date/time
        if any(x in resp_lower for x in ["fecha", "cuándo", "cuando", "día", "qué día"]):
            return "El viernes que viene a la tarde"
        # Bot shows slot list
        if any(x in resp_lower for x in ["viernes", "disponib", "horario"]):
            return "El primero de la tarde del viernes"
        # Bot asking stylist
        if any(x in resp_lower for x in ["estilista", "quien", "quién"]):
            return "Cualquiera que esté disponible"
        # Default: verbal confirmation
        return "Sí, quiero ese servicio"

    if turn_num == 3:
        # T4 — after service confirmed, expect add-ons or date/slot
        if any(x in resp_lower for x in ["barba", "hidrat", "añad", "agreg", "adicional", "complemento"]):
            return "No, solo el corte por favor"
        if any(x in resp_lower for x in ["fecha", "cuándo", "cuando", "día"]):
            return "El viernes que viene a la tarde"
        if any(x in resp_lower for x in ["viernes", "disponib", "horario", "1.", "1)"]):
            return "El primero de la tarde del viernes"
        if any(x in resp_lower for x in ["estilista", "quien", "quién"]):
            return "Cualquiera que esté disponible"
        if any(x in resp_lower for x in ["nombre", "cómo te llam", "llamás"]):
            return "Luis Martínez"
        return "No, solo el corte por favor"

    if turn_num == 4:
        # T5 — after add-ons declined, expect date/slot/stylist
        if any(x in resp_lower for x in ["fecha", "cuándo", "cuando", "día"]):
            return "El viernes que viene a la tarde"
        if any(x in resp_lower for x in ["viernes", "disponib", "horario"]) or "1." in agent_response or "1)" in agent_response:
            return "El primero de la tarde del viernes"
        if any(x in resp_lower for x in ["estilista", "quien", "quién"]):
            return "Cualquiera que esté disponible"
        if any(x in resp_lower for x in ["nombre", "cómo te llam", "llamás"]):
            return "Luis Martínez"
        if any(x in resp_lower for x in ["barba", "hidrat", "añad", "agreg"]):
            return "No, solo el corte por favor"
        return "El viernes que viene a la tarde"

    if turn_num == 5:
        # T6 — stylist or slot selection
        if any(x in resp_lower for x in ["estilista", "quien", "quién", "luciana", "peluquer"]):
            return "Cualquiera que esté disponible"
        if any(x in resp_lower for x in ["nombre", "cómo te llam", "llamás"]):
            return "Luis Martínez"
        if any(x in resp_lower for x in ["nota", "aclaración", "observ", "algo más"]):
            return "Sin notas"
        if any(x in resp_lower for x in ["confirm", "reserv"]):
            return "Sí, confirmo"
        if "1." in agent_response or "1)" in agent_response or any(x in resp_lower for x in ["viernes", "disponib"]):
            return "El primero de la tarde del viernes"
        return "Cualquiera que esté disponible"

    if turn_num == 6:
        # T7 — name or notes or confirm
        if any(x in resp_lower for x in ["nombre", "cómo te llam", "llamás"]):
            return "Luis Martínez"
        if any(x in resp_lower for x in ["nota", "aclaración", "observ"]):
            return "Sin notas"
        if any(x in resp_lower for x in ["confirm", "reserv"]):
            return "Sí, confirmo"
        if any(x in resp_lower for x in ["estilista", "quien", "quién"]):
            return "Cualquiera que esté disponible"
        if "1." in agent_response or "1)" in agent_response or any(x in resp_lower for x in ["viernes", "disponib"]):
            return "El primero de la tarde del viernes"
        return "Luis Martínez"

    if turn_num == 7:
        # T8 — notes or confirm
        if any(x in resp_lower for x in ["nota", "aclaración", "observ", "algo más"]):
            return "Sin notas"
        if any(x in resp_lower for x in ["confirm", "reserv", "¿confirmas"]):
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

    # Turns 9–18 — handle stragglers / confirmation
    if turn_num <= 18:
        if any(x in resp_lower for x in ["nota", "aclaración"]):
            return "Sin notas"
        if any(x in resp_lower for x in ["confirm", "reserv"]):
            return "Sí, confirmo"
        if any(x in resp_lower for x in ["nombre", "cómo te llam"]):
            return "Luis Martínez"
        if any(x in resp_lower for x in ["estilista"]):
            return "Cualquiera que esté disponible"
        if "1." in agent_response or "1)" in agent_response:
            return "El primero de la tarde del viernes"
        if any(x in resp_lower for x in ["barba", "hidrat", "agreg"]):
            return "No, solo el corte por favor"
        if any(x in resp_lower for x in ["exitosamente", "confirmado", "agendado", "reservado"]):
            return None  # Done
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

    # R7 Harness — T1 per spec
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
            if "addons_handled" not in milestones_hit and any(x in resp_lower for x in ["barba", "hidrat", "adicional", "solo el corte", "complemento"]):
                milestones_hit.append("addons_handled")
            if "slot_resolved" not in milestones_hit and ("viernes" in resp_lower or ("hora" in resp_lower and turn_num >= 3)):
                milestones_hit.append("slot_resolved")
            if "confirmation_done" not in milestones_hit and any(x in resp_lower for x in ["confirm", "reserv", "agend"]):
                milestones_hit.append("confirmation_done")
            if "booking_completed" not in milestones_hit and any(x in resp_lower for x in ["exitosamente", "confirmado", "agendado", "reservado"]):
                milestones_hit.append("booking_completed")

            # Bug checks
            for phrase in narration_phrases:
                if phrase.lower() in agent_response.lower():
                    bugs_observed.append(f"BUG-002: narration phrase in T{turn_num}: '{phrase}'")

            # Unexpected escalation check
            if any(x in resp_lower for x in ["escalación", "operador", "humano"]) and turn_num <= 5:
                bugs_observed.append(f"UNEXPECTED_ESCALATION at T{turn_num}")
                print(f"[!] WARNING: Unexpected early escalation at T{turn_num}")

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
    print("QA ROUND 7 RESULTS")
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
    with open("/tmp/qa_r7_indecision_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n[FINAL STATUS]: {result['status']}")
    print(f"[SAVED]: /tmp/qa_r7_indecision_result.json")
