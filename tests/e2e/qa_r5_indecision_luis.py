"""QA Round 5 — Flow: indecision, Persona: luis_indecisive_client."""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime

import redis.asyncio as redis

sys.path.insert(0, "/home/pcabeza/Proyectos/atrevete-bot")

from tests.e2e.harness.redis_harness import RedisTestHarness

REDIS_URL = "redis://:9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda@localhost:6379/0"
DB_URL = "postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db"

PERSONA_NAME = "Luis Martínez"
PERSONA_PHONE = "+34699000501"
CONVERSATION_ID = str(uuid.uuid4())
RESPONSE_TIMEOUT = 35.0

print(f"\n{'='*60}")
print("QA ROUND 5 — Flow: indecision | Persona: luis_indecisive_client")
print(f"conversation_id: {CONVERSATION_ID}")
print(f"Started at: {datetime.now(UTC).isoformat()}")
print(f"{'='*60}\n")


# Adaptive turn-decision logic based on bot response content
def decide_next_message(turn_num: int, agent_response: str) -> str | None:
    """
    Decide the next user message based on the agent's response.
    Returns None to stop the flow.
    """
    resp_lower = agent_response.lower()

    # --- Turn 1: Initial greeting + vague intent ---
    if turn_num == 1:
        return "Hola, quería saber si pueden ayudarme con algo para el viernes a la tarde, pero no sé bien qué hacerme"

    # --- Turn 2: Bot asks what they want / discovery ---
    if turn_num == 2:
        # Bot asked clarifying questions or offered options
        if "corte" in resp_lower or "servicio" in resp_lower or "qué" in resp_lower or "ayud" in resp_lower:
            return "Soy hombre, quiero verme más prolijo pero no sé si hacerme solo un corte o algo más"
        return "Soy hombre, necesito algo para verme más prolijo"

    # --- Turn 3: Bot gives recommendation / shows services ---
    if turn_num == 3:
        # Numbered list shown → pick option 1
        if "1." in agent_response or "1)" in agent_response or "corte" in resp_lower:
            return "1"
        if "recomend" in resp_lower or "sugier" in resp_lower:
            return "1"
        return "1"

    # --- Turn 4: Service confirmed, may ask addon or stylist ---
    if turn_num == 4:
        # Add-on offer
        if "barba" in resp_lower or "hidrat" in resp_lower or "añad" in resp_lower or "agreg" in resp_lower or "servicio adicional" in resp_lower:
            return "Empecemos solo con el corte"
        # Stylist question
        if "estilista" in resp_lower or "quien" in resp_lower or "luciana" in resp_lower or "peluquer" in resp_lower:
            return "No tengo preferencia, cualquier estilista está bien"
        # Slot question
        if "viernes" in resp_lower or "hora" in resp_lower or "turno" in resp_lower or "horario" in resp_lower:
            return "1"
        # Numbered list of slots
        if "1." in agent_response or "1)" in agent_response:
            return "1"
        return "Empecemos solo con el corte"

    # --- Turn 5: May ask stylist / name / date ---
    if turn_num == 5:
        if "nombre" in resp_lower or "cómo te llam" in resp_lower or "llamás" in resp_lower:
            return "Luis Martínez"
        if "estilista" in resp_lower or "quien" in resp_lower:
            return "No tengo preferencia"
        if "barba" in resp_lower or "hidrat" in resp_lower or "añad" in resp_lower or "agreg" in resp_lower:
            return "Empecemos solo con el corte"
        if "viernes" in resp_lower or "hora" in resp_lower or "1." in agent_response or "1)" in agent_response:
            return "1"
        return "1"

    # --- Turn 6: Name / slot / stylist ---
    if turn_num == 6:
        if "nombre" in resp_lower or "cómo te llam" in resp_lower or "llamás" in resp_lower:
            return "Luis Martínez"
        if "estilista" in resp_lower or "quien" in resp_lower:
            return "Cualquiera está bien"
        if "viernes" in resp_lower or "hora" in resp_lower or "1." in agent_response or "1)" in agent_response:
            return "1"
        if "barba" in resp_lower or "hidrat" in resp_lower or "añad" in resp_lower:
            return "Empecemos solo con el corte"
        return "1"

    # --- Turn 7: More slots / name / stylist ---
    if turn_num == 7:
        if "nombre" in resp_lower or "cómo te llam" in resp_lower or "llamás" in resp_lower:
            return "Luis Martínez"
        if "estilista" in resp_lower or "quien" in resp_lower:
            return "Me da igual, cualquiera"
        if "viernes" in resp_lower or "hora" in resp_lower or "1." in agent_response or "1)" in agent_response:
            return "1"
        if "barba" in resp_lower or "hidrat" in resp_lower or "añad" in resp_lower:
            return "No gracias, solo el corte"
        return "1"

    # --- Turn 8: Confirmation or notes ---
    if turn_num == 8:
        if "nota" in resp_lower or "aclaración" in resp_lower or "algo más" in resp_lower:
            return "Sin notas"
        if "confirm" in resp_lower or "reserv" in resp_lower or "turno" in resp_lower:
            return "Sí, confirmo"
        if "nombre" in resp_lower or "cómo te llam" in resp_lower:
            return "Luis Martínez"
        if "1." in agent_response or "1)" in agent_response:
            return "1"
        return "Sí, confirmo"

    # --- Turns 9–14: Handle stragglers ---
    if turn_num <= 14:
        if "nota" in resp_lower or "aclaración" in resp_lower:
            return "Sin notas"
        if "confirm" in resp_lower or "reserv" in resp_lower:
            return "Sí, confirmo"
        if "nombre" in resp_lower or "cómo te llam" in resp_lower:
            return "Luis Martínez"
        if "estilista" in resp_lower:
            return "Cualquiera está bien"
        if "1." in agent_response or "1)" in agent_response:
            return "1"
        if "barba" in resp_lower or "hidrat" in resp_lower or "añad" in resp_lower or "agreg" in resp_lower:
            return "No gracias, solo el corte"
        # If booking is done
        if "exitosamente" in resp_lower or "confirmado" in resp_lower or "agendado" in resp_lower or "reservado" in resp_lower:
            return None  # Done
        return "Sí, confirmo"

    return None  # Max turns reached


async def check_appointment_in_db() -> int:
    """Check if appointment was created in DB in the last hour."""
    try:
        import asyncpg
        conn = await asyncpg.connect(
            "postgresql://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db"
        )
        count = await conn.fetchval(
            "SELECT count(*) FROM appointments WHERE created_at > now() - interval '1 hour'"
        )
        await conn.close()
        return int(count)
    except Exception as e:
        print(f"  [DB CHECK ERROR] {e}")
        return -1


async def run_indecision_flow():
    # Build Redis client (sync URL → external host)
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

    try:
        # Turn 1 — Initial message
        turn_num = 1
        user_msg = "Hola, quería saber si pueden ayudarme con algo para el viernes a la tarde, pero no sé bien qué hacerme"

        print(f"\n[T{turn_num}] USER: {user_msg}")
        result = await harness.execute_turn(
            conversation_id=CONVERSATION_ID,
            user_message=user_msg,
            persona_name=PERSONA_NAME,
            timeout=RESPONSE_TIMEOUT,
            customer_phone=PERSONA_PHONE,
        )
        agent_response = result["agent_response"]
        turns.append(result)
        print(f"[T{turn_num}] BOT ({result['response_latency_ms']}ms): {agent_response[:200]}")

        # Track milestone: greeting_done
        if agent_response:
            milestones_hit.append("greeting_done")

        # Check BUG-002: narration phrases
        narration_phrases = ["*El agente", "*Busco", "*Verifico", "*Compruebo"]
        for phrase in narration_phrases:
            if phrase.lower() in agent_response.lower():
                bugs_observed.append(f"BUG-002: narration phrase found in T{turn_num}: '{phrase}'")

        # Continue loop
        while turn_num < 18:
            next_msg = decide_next_message(turn_num + 1, agent_response)
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
            print(f"[T{turn_num}] BOT ({result['response_latency_ms']}ms): {agent_response[:300]}")

            # Track milestones
            resp_lower = agent_response.lower()
            if "discovery_started" not in milestones_hit and ("cuéntame" in resp_lower or "qué tip" in resp_lower or "qué estil" in resp_lower or "corte" in resp_lower):
                milestones_hit.append("discovery_started")
            if "recommendation_given" not in milestones_hit and ("recomend" in resp_lower or "ideal" in resp_lower or "sugier" in resp_lower or "perfect" in resp_lower):
                milestones_hit.append("recommendation_given")
            if "service_resolved" not in milestones_hit and ("caballero" in resp_lower or ("corte" in resp_lower and turn_num >= 3)):
                milestones_hit.append("service_resolved")
            if "addons_handled" not in milestones_hit and ("barba" in resp_lower or "hidrat" in resp_lower or "adicional" in resp_lower or "empecemos" in resp_lower):
                milestones_hit.append("addons_handled")
            if "slot_resolved" not in milestones_hit and ("viernes" in resp_lower or ("hora" in resp_lower and turn_num >= 4)):
                milestones_hit.append("slot_resolved")
            if "confirmation_done" not in milestones_hit and ("confirm" in resp_lower or "reserv" in resp_lower or "agend" in resp_lower):
                milestones_hit.append("confirmation_done")
            if "booking_completed" not in milestones_hit and ("exitosamente" in resp_lower or "confirmado" in resp_lower or "agendado" in resp_lower or "reservado" in resp_lower):
                milestones_hit.append("booking_completed")

            # Check BUG-002
            for phrase in narration_phrases:
                if phrase.lower() in agent_response.lower():
                    bugs_observed.append(f"BUG-002: narration phrase in T{turn_num}: '{phrase}'")

            # Stop if booking confirmed
            if "booking_completed" in milestones_hit:
                print(f"\n[✓] booking_completed milestone hit at T{turn_num}")
                break

            # Stop if escalation triggered (unexpected)
            if "escalación" in resp_lower or "humano" in resp_lower or "equipo" in resp_lower:
                bugs_observed.append(f"UNEXPECTED_ESCALATION at T{turn_num}")
                print(f"[!] WARNING: Unexpected escalation at T{turn_num}")
                break

    except TimeoutError as e:
        print(f"\n[TIMEOUT] {e}")
        bugs_observed.append(f"TIMEOUT at T{turn_num}: {e}")
    finally:
        await harness.close()
        await r.aclose()

    # --- DB CHECK ---
    print(f"\n{'='*60}")
    print("DB CHECK — appointments in last hour:")
    appointment_count = await check_appointment_in_db()
    appointment_in_db = appointment_count > 0
    print(f"  count(*) = {appointment_count} → appointment_in_db={appointment_in_db}")

    # --- RESULTS ---
    recommendation_provided = "recommendation_given" in milestones_hit
    appointment_created = "booking_completed" in milestones_hit

    status = "PASS" if (recommendation_provided and appointment_created and appointment_in_db) else "FAIL"

    print(f"\n{'='*60}")
    print("QA ROUND 5 RESULTS")
    print(f"{'='*60}")
    print(f"Status: {status}")
    print(f"Turn count: {turn_num}")
    print(f"recommendation_provided: {recommendation_provided}")
    print(f"appointment_created: {appointment_created}")
    print(f"appointment_in_db: {appointment_in_db}")
    print(f"Milestones hit: {milestones_hit}")
    print(f"Bugs observed: {bugs_observed if bugs_observed else 'None'}")
    print("\n--- CONVERSATION TRACE ---")
    for t in turns:
        print(f"\nTurn {t['turn_number']} ({t['response_latency_ms']}ms)")
        print(f"  USER: {t['user_message']}")
        print(f"  BOT:  {t['agent_response'][:400]}")

    # Return structured result for engram
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
    print(f"\n[FINAL STATUS]: {result['status']}")
