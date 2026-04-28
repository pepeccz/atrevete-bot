"""
QA Round 6 — Flow: indecision — Persona: luis_indecisive_client
Commit: 6dbeacb

Key fixes from R5:
- T1 now says "Hola, soy hombre y quiero verme más prolijo, ¿qué me recomendás?"
  (direct ask, not vague) to avoid "consultoría" branch trap
- T2: if bot shows numbered list → "1" (Corte de Hombre)
- T3: always "Sí, quiero ese servicio para el viernes a la tarde" (verbal, not "1")
- Harness script is deterministic, not purely adaptive
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
PERSONA_PHONE = "+34699000601"
CONVERSATION_ID = str(uuid.uuid4())
RESPONSE_TIMEOUT = 35.0

print(f"\n{'='*60}")
print(f"QA ROUND 6 — Flow: indecision | Persona: luis_indecisive_client")
print(f"conversation_id: {CONVERSATION_ID}")
print(f"Started at: {datetime.now(UTC).isoformat()}")
print(f"Commit: 6dbeacb")
print(f"{'='*60}\n")


def decide_next_message(turn_num: int, agent_response: str) -> str | None:
    """
    Deterministic harness script — R6.
    Implements the exact harness from the QA spec:
      T1: greeting + "soy hombre y quiero verme más prolijo, ¿qué me recomendás?"
      T2: if numbered list → "1"
      T3: "Sí, quiero ese servicio para el viernes a la tarde"
      T4: if add-ons → "Empecemos solo con el corte"
      T5: if slots → "1"
      T6: if stylist → "Cualquiera"
      T7: if name → "Luis Martínez"
      T8: if notes → "Sin notas"
      T9: if confirm → "Sí, confirmo"
    """
    resp_lower = agent_response.lower()

    if turn_num == 1:
        # T1 already sent — this is what we send NEXT (T2 decision)
        # If bot shows a numbered list with service options → pick "1"
        # If bot gave direct recommendation → confirm
        if "1." in agent_response or "1)" in agent_response or "corte caballero" in resp_lower:
            return "1"
        if "recomend" in resp_lower or "sugier" in resp_lower or "corte" in resp_lower:
            return "1"
        # Bot asked clarifying question — provide more context
        return "Soy hombre, quiero verme más prolijo"

    if turn_num == 2:
        # T2 response received. Bot may have selected service or ask confirmation
        # Use verbal confirmation per harness spec: "Sí, quiero ese servicio para el viernes a la tarde"
        if "confirm" in resp_lower or "seleccionad" in resp_lower or "escogiste" in resp_lower:
            return "Sí, quiero ese servicio para el viernes a la tarde"
        # Bot shows add-on question
        if "barba" in resp_lower or "hidrat" in resp_lower or "añad" in resp_lower or "agreg" in resp_lower or "adicional" in resp_lower:
            return "Empecemos solo con el corte"
        # Bot already asking for date/time
        if "fecha" in resp_lower or "cuándo" in resp_lower or "cuando" in resp_lower or "día" in resp_lower:
            return "El viernes a la tarde"
        # Bot shows slot list
        if "viernes" in resp_lower or "1." in agent_response or "1)" in agent_response:
            return "1"
        return "Sí, quiero ese servicio para el viernes a la tarde"

    if turn_num == 3:
        # T3 response received. Bot may show slots, ask add-ons, or ask something
        if "barba" in resp_lower or "hidrat" in resp_lower or "añad" in resp_lower or "agreg" in resp_lower or "adicional" in resp_lower or "complemento" in resp_lower:
            return "Empecemos solo con el corte"
        if "1." in agent_response or "1)" in agent_response or "viernes" in resp_lower:
            return "1"
        if "estilista" in resp_lower or "quien" in resp_lower:
            return "Cualquiera"
        if "nombre" in resp_lower or "cómo te llam" in resp_lower or "llamás" in resp_lower:
            return "Luis Martínez"
        return "Empecemos solo con el corte"

    if turn_num == 4:
        # T4 response received after add-on decline or slot shown
        if "1." in agent_response or "1)" in agent_response or "viernes" in resp_lower or "turno" in resp_lower:
            return "1"
        if "estilista" in resp_lower or "quien" in resp_lower:
            return "Cualquiera"
        if "nombre" in resp_lower or "cómo te llam" in resp_lower:
            return "Luis Martínez"
        if "barba" in resp_lower or "hidrat" in resp_lower or "añad" in resp_lower or "agreg" in resp_lower:
            return "Empecemos solo con el corte"
        return "1"

    if turn_num == 5:
        if "estilista" in resp_lower or "quien" in resp_lower or "luciana" in resp_lower or "peluquer" in resp_lower:
            return "Cualquiera"
        if "nombre" in resp_lower or "cómo te llam" in resp_lower or "llamás" in resp_lower:
            return "Luis Martínez"
        if "nota" in resp_lower or "aclaración" in resp_lower or "observ" in resp_lower or "algo más" in resp_lower:
            return "Sin notas"
        if "confirm" in resp_lower or "reserv" in resp_lower:
            return "Sí, confirmo"
        if "1." in agent_response or "1)" in agent_response:
            return "1"
        return "Cualquiera"

    if turn_num == 6:
        if "nombre" in resp_lower or "cómo te llam" in resp_lower or "llamás" in resp_lower:
            return "Luis Martínez"
        if "nota" in resp_lower or "aclaración" in resp_lower or "observ" in resp_lower:
            return "Sin notas"
        if "confirm" in resp_lower or "reserv" in resp_lower:
            return "Sí, confirmo"
        if "estilista" in resp_lower or "quien" in resp_lower:
            return "Cualquiera"
        if "1." in agent_response or "1)" in agent_response:
            return "1"
        return "Luis Martínez"

    if turn_num == 7:
        if "nota" in resp_lower or "aclaración" in resp_lower or "observ" in resp_lower or "algo más" in resp_lower:
            return "Sin notas"
        if "confirm" in resp_lower or "reserv" in resp_lower or "¿confirmas" in resp_lower:
            return "Sí, confirmo"
        if "nombre" in resp_lower or "cómo te llam" in resp_lower:
            return "Luis Martínez"
        if "estilista" in resp_lower:
            return "Cualquiera"
        return "Sin notas"

    if turn_num == 8:
        if "confirm" in resp_lower or "reserv" in resp_lower or "¿confirmas" in resp_lower or "¿deseas" in resp_lower:
            return "Sí, confirmo"
        if "nota" in resp_lower or "aclaración" in resp_lower:
            return "Sin notas"
        if "nombre" in resp_lower:
            return "Luis Martínez"
        return "Sí, confirmo"

    # Turns 9–18 — handle stragglers / confirmation
    if turn_num <= 18:
        if "nota" in resp_lower or "aclaración" in resp_lower:
            return "Sin notas"
        if "confirm" in resp_lower or "reserv" in resp_lower:
            return "Sí, confirmo"
        if "nombre" in resp_lower or "cómo te llam" in resp_lower:
            return "Luis Martínez"
        if "estilista" in resp_lower:
            return "Cualquiera"
        if "1." in agent_response or "1)" in agent_response:
            return "1"
        if "barba" in resp_lower or "hidrat" in resp_lower or "agreg" in resp_lower:
            return "No gracias, solo el corte"
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

    # R6 Harness — T1 uses the specific phrasing per spec
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
        print(f"[T{turn_num}] BOT ({result['response_latency_ms']}ms): {agent_response[:300]}")

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
            print(f"[T{turn_num}] BOT ({result['response_latency_ms']}ms): {agent_response[:400]}")

            resp_lower = agent_response.lower()

            # Milestone tracking
            if "discovery_started" not in milestones_hit and any(x in resp_lower for x in ["cuéntame", "qué tip", "qué estil", "corte", "servicio"]):
                milestones_hit.append("discovery_started")
            if "recommendation_given" not in milestones_hit and any(x in resp_lower for x in ["recomend", "ideal", "sugier", "perfect", "caballero"]):
                milestones_hit.append("recommendation_given")
            if "service_resolved" not in milestones_hit and ("caballero" in resp_lower or ("corte" in resp_lower and turn_num >= 2)):
                milestones_hit.append("service_resolved")
            if "addons_handled" not in milestones_hit and any(x in resp_lower for x in ["barba", "hidrat", "adicional", "empecemos", "complemento"]):
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
    print("QA ROUND 6 RESULTS")
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
        print(f"  BOT:  {t['agent_response'][:500]}")

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
    with open("/tmp/qa_r6_indecision_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n[FINAL STATUS]: {result['status']}")
    print(f"[SAVED]: /tmp/qa_r6_indecision_result.json")
