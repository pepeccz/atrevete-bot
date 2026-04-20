"""
QA Round 10 — Flow: indecision | Persona: luis_indecisive_client
Commit: 57ee48a — fixes slot_selection bare-number + customer_name before book()
Incorporates all R1-R9 lessons.

Key lessons applied:
- Payload uses message_text (not message)
- customer_phone must be non-None
- Subscribe BEFORE injecting (race condition prevention)
- Match by conversation_id in Pub/Sub message
- Use "1" for numbered slot list (bare number)
- Use service name (not number)
- Decline add-ons with "No, solo el corte" when asked about extras
- When asked for date/day: say a concrete day to trigger slot listing
- Timeout 30s per turn
"""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis

# ── Config ───────────────────────────────────────────────────────────────────
REDIS_PASSWORD = os.environ.get(
    "REDIS_PASSWORD", "9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda"
)
REDIS_URL = os.environ.get("REDIS_URL", f"redis://:{REDIS_PASSWORD}@localhost:6379/0")
INCOMING_STREAM = "incoming_messages_stream"
OUTGOING_CHANNEL = "outgoing_messages"
RESPONSE_TIMEOUT = 30.0
CONVERSATION_ID = str(uuid.uuid4())
CUSTOMER_PHONE = "+34999990010"

print(f"[HARNESS] QA-R10 | conversation_id={CONVERSATION_ID}")


# ── Adaptive FSM ──────────────────────────────────────────────────────────────


class FlowState:
    """
    Deterministic FSM. Each state has ONE expected bot pattern and ONE fixed reply.
    Order matters — earlier checks take priority.
    """

    PHASE_INIT = "init"
    PHASE_GREETED = "greeted"  # sent T1, waiting for recommendation
    PHASE_SERVICES_SHOWN = "services_shown"  # service list shown, choose service
    PHASE_SERVICE_SELECTED = "service_selected"  # service named, await confirm
    PHASE_SERVICE_CONFIRMED = "service_confirmed"  # confirmed service
    PHASE_ADDON_ASKED = "addon_asked"  # addon offered, declining
    PHASE_ADDON_DECLINED = "addon_declined"  # declined addon, await stylist q
    PHASE_STYLIST_ASKED = "stylist_asked"  # stylist asked, reply cualquiera
    PHASE_STYLIST_GIVEN = "stylist_given"  # given stylist, await date/slot ask
    PHASE_DATE_ASKED = "date_asked"  # bot asked for day → say "mañana"
    PHASE_DATE_GIVEN = "date_given"  # day given, await slot list
    PHASE_SLOTS_SHOWN = "slots_shown"  # slots listed, pick "1"
    PHASE_SLOT_SELECTED = "slot_selected"  # slot picked, await name q
    PHASE_NAME_ASKED = "name_asked"  # name asked, give name
    PHASE_NAME_GIVEN = "name_given"  # name given, await notes q
    PHASE_NOTES_ASKED = "notes_state_answered"  # notes state answered, give "Sin notas"
    PHASE_NOTES_GIVEN = "notes_given"  # notes given, await confirm summary
    PHASE_CONFIRM_ASKED = "confirm_asked"  # summary shown, confirm
    PHASE_DONE = "done"

    def __init__(self):
        self.phase = self.PHASE_INIT
        self.milestones = []
        self.turn_number = 0
        self.done = False

    def next_message(self, last_agent: str) -> str | None:
        """Decide next user message based on current phase and last agent message."""
        msg = last_agent.lower() if last_agent else ""

        # ── Phase: INIT → send greeting ──────────────────────────────────────
        if self.phase == self.PHASE_INIT:
            self.phase = self.PHASE_GREETED
            return "Hola, soy hombre y quiero verme más prolijo, ¿qué me recomendás?"

        # ── Error guard ──────────────────────────────────────────────────────
        if "tuve un problema" in msg or ("error" in msg and "lo siento" in msg):
            return "Intenta de nuevo"

        # ── Phase: GREETED → waiting for service list or recommendation ───────
        if self.phase == self.PHASE_GREETED:
            # Bot asks if corte is for "caballero" (variant confirmation step)
            if (
                "caballero" in msg
                and "?" in last_agent
                and ("para un" in msg or "para quien" in msg or "dama" in msg or "niño" in msg)
            ):
                self.phase = self.PHASE_SERVICE_SELECTED
                return "Sí, caballero"
            # Bot says "has elegido" → service already resolved
            if "elegido" in msg and "corte" in msg:
                self.phase = self.PHASE_SERVICE_SELECTED
                return "Sí, ese servicio"
            # Bot listed services (numbered list with corte)
            if ("1." in last_agent or "1)" in last_agent) and "corte" in msg:
                self.phase = self.PHASE_SERVICES_SHOWN
                return "Quiero el corte caballero"
            # Bot asked a question (like "¿qué servicio querés?") without service list
            if "?" in last_agent:
                return "Quiero el corte caballero"
            # Bot gave a recommendation without numbered list
            if "corte" in msg and ("recomiendo" in msg or "recomiend" in msg or "perfecto" in msg):
                self.phase = self.PHASE_SERVICE_SELECTED
                return "Sí, ese servicio"
            return "Quiero el corte caballero"

        # ── Phase: SERVICES_SHOWN → service selected, await confirmation ──────
        if self.phase == self.PHASE_SERVICES_SHOWN:
            # Bot says "cambiamos el servicio" (confusing response to service name) → use number
            if "cambiamos" in msg or "cuál querés" in msg or "cuál elegís" in msg:
                return "1"
            # Bot asks variant confirmation "¿el corte es para un caballero?"
            if (
                "caballero" in msg
                and "?" in last_agent
                and ("para un" in msg or "dama" in msg or "niño" in msg)
            ):
                self.phase = self.PHASE_SERVICE_SELECTED
                return "Sí, caballero"
            # Bot confirmed the service selection / asks to proceed
            if "corte caballero" in msg or "corte" in msg:
                if "agregar" in msg or "adicional" in msg or "barba" in msg:
                    # Skip to addon handling
                    self.phase = self.PHASE_ADDON_ASKED
                    return "No, solo el corte"
                if (
                    "disponibilidad" in msg
                    or "buscar" in msg
                    or "confirmar" in msg
                    or "?" in last_agent
                ):
                    self.phase = self.PHASE_SERVICE_SELECTED
                    return "Sí, ese servicio"
            return "Sí, ese servicio"

        # ── Phase: SERVICE_SELECTED → confirmed, may offer addons ─────────────
        if self.phase == self.PHASE_SERVICE_SELECTED:
            # Bot asking audience/variant: "¿para un adulto, niño, niña?" (MUST have both adult+child options)
            if (
                ("niño" in msg or "niña" in msg)
                and ("adulto" in msg or "dama" in msg)
                and "?" in last_agent
            ):
                return "Adulto, caballero"
            # Bot offering addon
            if "agregar" in msg or "adicional" in msg or "barba" in msg or "tratamiento" in msg:
                self.phase = self.PHASE_ADDON_ASKED
                return "No, solo el corte"
            # Bot asks "¿Te gustaría que busquemos disponibilidad?" → say yes to advance
            if "disponibilidad" in msg or "busquemos" in msg or "agendar" in msg or "buscar" in msg:
                self.phase = self.PHASE_SERVICE_CONFIRMED
                return "Sí"
            # Bot asked for stylist directly
            if "estilista" in msg or "peluquero" in msg or "profesional" in msg:
                self.phase = self.PHASE_STYLIST_ASKED
                return "Cualquiera disponible"
            # Bot asks to confirm service selection
            if "confirmar" in msg or "es correcto" in msg or "quieres" in msg:
                self.phase = self.PHASE_SERVICE_CONFIRMED
                return "Sí, ese servicio"
            return "Sí"

        # ── Phase: SERVICE_CONFIRMED → similar to SERVICE_SELECTED ───────────
        if self.phase == self.PHASE_SERVICE_CONFIRMED:
            if "agregar" in msg or "adicional" in msg or "barba" in msg:
                self.phase = self.PHASE_ADDON_ASKED
                return "No, solo el corte"
            if "estilista" in msg or "peluquero" in msg or "profesional" in msg:
                self.phase = self.PHASE_STYLIST_ASKED
                return "Cualquiera disponible"
            return "No, solo el corte"

        # ── Phase: ADDON_ASKED → decline ─────────────────────────────────────
        if self.phase == self.PHASE_ADDON_ASKED:
            # Bot still asking about addons
            if "agregar" in msg or "adicional" in msg or "barba" in msg or "tratamiento" in msg:
                self.phase = self.PHASE_ADDON_DECLINED
                return "No, solo el corte"
            # Bot moved on to stylist
            if "estilista" in msg or "peluquero" in msg:
                self.phase = self.PHASE_STYLIST_ASKED
                return "Cualquiera disponible"
            self.phase = self.PHASE_ADDON_DECLINED
            return "No, solo el corte"

        # ── Phase: ADDON_DECLINED → waiting for stylist question ──────────────
        if self.phase == self.PHASE_ADDON_DECLINED:
            if "estilista" in msg or "peluquero" in msg or "profesional" in msg or "quién" in msg:
                self.phase = self.PHASE_STYLIST_ASKED
                return "Cualquiera disponible"
            if "día" in msg or "horario" in msg or "fecha" in msg or "cuándo" in msg:
                self.phase = self.PHASE_DATE_ASKED
                return "mañana por la mañana"
            return "Cualquiera disponible"

        # ── Phase: STYLIST_ASKED → give "cualquiera" ──────────────────────────
        if self.phase == self.PHASE_STYLIST_ASKED:
            # Bot already showed slot list before we replied stylist
            if ("1." in last_agent or "1)" in last_agent) and (
                "disponib" in msg or "horario" in msg or "turno" in msg or "opcion" in msg
            ):
                self.phase = self.PHASE_SLOTS_SHOWN
                return "1"
            self.phase = self.PHASE_STYLIST_GIVEN
            return "Cualquiera disponible"

        # ── Phase: STYLIST_GIVEN → waiting for slot list or date question ──────
        if self.phase == self.PHASE_STYLIST_GIVEN:
            # Bot shows numbered slots
            if ("1." in last_agent or "1)" in last_agent) and (
                "disponib" in msg
                or "horario" in msg
                or "turno" in msg
                or "opcion" in msg
                or "viene" in msg
                or "mejor" in msg
            ):
                self.phase = self.PHASE_SLOTS_SHOWN
                return "1"
            # Bot asking for date/day preference
            if (
                "día" in msg
                or "fecha" in msg
                or "cuándo" in msg
                or "horario" in msg
                or "momento" in msg
            ):
                self.phase = self.PHASE_DATE_ASKED
                return "mañana por la mañana"
            # Bot asking for slot directly
            if "slot" in msg or "turno" in msg:
                self.phase = self.PHASE_DATE_ASKED
                return "mañana por la mañana"
            return "mañana por la mañana"

        # ── Phase: DATE_ASKED → date given, wait for slot list ────────────────
        if self.phase == self.PHASE_DATE_ASKED:
            self.phase = self.PHASE_DATE_GIVEN
            # Still asking for date
            if "día" in msg or "fecha" in msg or "cuándo" in msg or "momento" in msg:
                return "mañana por la mañana"
            # Got numbered slots
            if ("1." in last_agent or "1)" in last_agent) and (
                "disponib" in msg or "horario" in msg or "turno" in msg
            ):
                self.phase = self.PHASE_SLOTS_SHOWN
                return "1"
            return "mañana por la mañana"

        # ── Phase: DATE_GIVEN → wait for numbered slot list ───────────────────
        if self.phase == self.PHASE_DATE_GIVEN:
            # Got numbered slots
            if ("1." in last_agent or "1)" in last_agent) and (
                "disponib" in msg or "horario" in msg or "turno" in msg or "opcion" in msg
            ):
                self.phase = self.PHASE_SLOTS_SHOWN
                return "1"
            # Still asking for date
            if "día" in msg or "fecha" in msg or "cuándo" in msg or "momento" in msg:
                return "mañana por la mañana"
            # Asked for name → skip ahead
            if "nombre" in msg:
                self.phase = self.PHASE_NAME_ASKED
                return "Luis Martínez"
            # Ambiguous → try slot selection
            if "?" in last_agent:
                return "1"
            return "mañana por la mañana"

        # ── Phase: SLOTS_SHOWN → pick slot 1 ─────────────────────────────────
        if self.phase == self.PHASE_SLOTS_SHOWN:
            # More slot details or name question
            if "nombre" in msg:
                self.phase = self.PHASE_NAME_ASKED
                return "Luis Martínez"
            if "nota" in msg:
                self.phase = self.PHASE_NOTES_ASKED
                return "Sin notas"
            # Confirm slot selection
            self.phase = self.PHASE_SLOT_SELECTED
            return "1"

        # ── Phase: SLOT_SELECTED → waiting for name or notes question ──────────
        if self.phase == self.PHASE_SLOT_SELECTED:
            print(f"[FSM-DEBUG] slot_selected: msg_lower={repr(msg[:120])}")
            if "nombre" in msg or "cómo te llamas" in msg or "tu nombre" in msg:
                self.phase = self.PHASE_NAME_ASKED
                return "Luis Martínez"
            # "¿Hay algo más que deba saber para tu cita?" → this is the notes step
            if (
                "nota" in msg
                or "algo más" in msg
                or "deba saber" in msg
                or "preferencia" in msg
                or "primera vez" in msg
                or "primera" in msg
            ):
                self.phase = self.PHASE_NOTES_ASKED
                return "Sin notas"
            if "confirmar" in msg or "confirma" in msg or "resumen" in msg:
                self.phase = self.PHASE_CONFIRM_ASKED
                return "Sí, confirmo"
            # Still showing slots?
            if "1." in last_agent or "1)" in last_agent:
                print(f"[FSM-DEBUG] slot_selected: still showing slots, sending 1")
                return "1"
            if "?" in last_agent:
                print(f"[FSM-DEBUG] slot_selected: has ? → check notes keywords")
                if "saber" in msg or "preferencia" in msg or "primera" in msg or "algo" in msg:
                    self.phase = self.PHASE_NOTES_ASKED
                    return "Sin notas"
                return "1"
            return "Sin notas"

        # ── Phase: NAME_ASKED → give name ─────────────────────────────────────
        if self.phase == self.PHASE_NAME_ASKED:
            self.phase = self.PHASE_NAME_GIVEN
            return "Luis Martínez"

        # ── Phase: NAME_GIVEN → waiting for notes question ────────────────────
        if self.phase == self.PHASE_NAME_GIVEN:
            if (
                "nota" in msg
                or "alguna nota" in msg
                or "comentario" in msg
                or "observación" in msg
                or "algo más" in msg
                or "deba saber" in msg
                or "preferencia" in msg
            ):
                self.phase = self.PHASE_NOTES_ASKED
                return "Sin notas"
            if "confirmar" in msg or "confirma" in msg or "resumen" in msg:
                self.phase = self.PHASE_CONFIRM_ASKED
                return "Sí, confirmo"
            # Bot may ask name again (didn't catch it)
            if "nombre" in msg:
                return "Luis Martínez"
            return "Sin notas"

        # ── Phase: NOTES_ASKED → give notes ──────────────────────────────────
        if self.phase == self.PHASE_NOTES_ASKED:
            self.phase = self.PHASE_NOTES_GIVEN
            return "Sin notas"

        # ── Phase: NOTES_GIVEN → waiting for confirmation summary ─────────────
        if self.phase == self.PHASE_NOTES_GIVEN:
            if (
                "confirmar" in msg
                or "confirma" in msg
                or "resumen" in msg
                or "luis" in msg
                or "martes" in msg
                or "pilar" in msg
                or "luciana" in msg
            ):
                self.phase = self.PHASE_CONFIRM_ASKED
                return "Sí, confirmo"
            if "nota" in msg or "algo más" in msg or "deba saber" in msg:
                return "Sin notas"
            if "nombre" in msg:
                self.phase = self.PHASE_NAME_ASKED
                return "Luis Martínez"
            if "?" in last_agent:
                return "Sí, confirmo"
            return "Sí, confirmo"

        # ── Phase: CONFIRM_ASKED → confirm ────────────────────────────────────
        if self.phase == self.PHASE_CONFIRM_ASKED:
            if (
                "confirmado" in msg
                or "reserva" in msg
                and "éxito" in msg
                or "cita" in msg
                and "reserv" in msg
            ):
                self.phase = self.PHASE_DONE
                self.done = True
                return None
            # Bot still asking for confirmation
            return "Sí, confirmo"

        if self.phase == self.PHASE_DONE:
            self.done = True
            return None

        return None


async def run_qa():
    state = FlowState()
    trace = []
    redis_client = await aioredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = redis_client.pubsub()

    print(f"[HARNESS] Subscribing to '{OUTGOING_CHANNEL}' BEFORE injecting...")
    await pubsub.subscribe(OUTGOING_CHANNEL)

    # Drain any stale messages
    async def drain_stale():
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
            if not msg:
                break

    await drain_stale()

    async def wait_for_response(conv_id: str, timeout: float) -> dict | None:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
            if msg and msg.get("type") == "message":
                try:
                    data = json.loads(msg["data"])
                    if data.get("conversation_id") == conv_id:
                        return data
                except (json.JSONDecodeError, TypeError):
                    pass
        return None

    async def inject(user_text: str) -> float:
        payload = {
            "conversation_id": CONVERSATION_ID,
            "customer_phone": CUSTOMER_PHONE,
            "message_text": user_text,
            "sender_name": "Luis Martínez",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        wrapped = {"data": json.dumps(payload)}
        t0 = asyncio.get_event_loop().time()
        await redis_client.xadd(INCOMING_STREAM, wrapped)
        return t0

    max_turns = 18
    turn_num = 0
    last_agent_msg = ""

    try:
        while turn_num < max_turns and not state.done:
            # Decide user message based on last agent response
            user_msg = state.next_message(last_agent_msg)

            if user_msg is None:
                print(f"[HARNESS] FSM complete — no more turns needed.")
                break

            turn_num += 1
            print(f"\n[TURN {turn_num}] PHASE={state.phase} | USER: {user_msg}")

            t0 = await inject(user_msg)
            response = await wait_for_response(CONVERSATION_ID, RESPONSE_TIMEOUT)
            latency_ms = int((asyncio.get_event_loop().time() - t0) * 1000)

            if response is None:
                print(f"[TURN {turn_num}] TIMEOUT after {RESPONSE_TIMEOUT}s")
                trace.append(
                    {
                        "turn_number": turn_num,
                        "user_message": user_msg,
                        "agent_response": "<<TIMEOUT>>",
                        "latency_ms": int(RESPONSE_TIMEOUT * 1000),
                        "phase": state.phase,
                    }
                )
                break

            agent_msg = response.get("message") or response.get("message_text", "<<NO MESSAGE>>")
            last_agent_msg = agent_msg
            print(f"[TURN {turn_num}] AGENT ({latency_ms}ms): {agent_msg[:300]}")

            trace.append(
                {
                    "turn_number": turn_num,
                    "user_message": user_msg,
                    "agent_response": agent_msg,
                    "latency_ms": latency_ms,
                    "phase": state.phase,
                }
            )

            # Milestone detection from agent response
            msg_lower = agent_msg.lower()
            if (
                "hola" in msg_lower or "bienvenido" in msg_lower or "maite" in msg_lower
            ) and "greeting_done" not in state.milestones:
                state.milestones.append("greeting_done")
            if "corte caballero" in msg_lower and "recommendation_given" not in state.milestones:
                state.milestones.append("recommendation_given")
            if (
                "elegido" in msg_lower
                and "corte" in msg_lower
                and "service_resolved" not in state.milestones
            ):
                state.milestones.append("service_resolved")
            if (
                "agregar" in msg_lower or "adicional" in msg_lower
            ) and "addons_offered" not in state.milestones:
                state.milestones.append("addons_offered")
            if (
                "estilista" in msg_lower or "peluquero" in msg_lower
            ) and "stylist_asked" not in state.milestones:
                state.milestones.append("stylist_asked")
            if (
                ("1." in agent_msg or "1)" in agent_msg)
                and ("horario" in msg_lower or "disponib" in msg_lower)
                and "slots_shown" not in state.milestones
            ):
                state.milestones.append("slots_shown")
            if ("nombre" in msg_lower) and "name_asked" not in state.milestones:
                state.milestones.append("name_asked")
            if ("nota" in msg_lower) and "notes_state_answered" not in state.milestones:
                state.milestones.append("notes_state_answered")
            # booking_confirmed: must be a success message, not a failure
            if (
                "booking_confirmed" not in state.milestones
                and (
                    "confirmado" in msg_lower
                    or "reservada" in msg_lower
                    or "reservado" in msg_lower
                )
                and "problema" not in msg_lower
                and "error" not in msg_lower
            ):
                state.milestones.append("booking_confirmed")
                state.done = True

        # ── Post-run DB check ─────────────────────────────────────────────────
        print("\n[HARNESS] Checking DB for appointments created in last hour...")
        db_count = await check_db()

        final_status = "PASS" if "booking_confirmed" in state.milestones else "FAIL"

        return {
            "status": final_status,
            "turn_count": turn_num,
            "milestones_hit": state.milestones,
            "appointment_in_db": db_count > 0,
            "db_appointment_count": db_count,
            "conversation_id": CONVERSATION_ID,
            "final_phase": state.phase,
            "trace": trace,
        }

    finally:
        await pubsub.unsubscribe(OUTGOING_CHANNEL)
        await redis_client.aclose()


async def check_db() -> int:
    """Check PostgreSQL for appointments via docker exec."""
    result = subprocess.run(
        [
            "docker",
            "exec",
            "atrevete-postgres",
            "psql",
            "-U",
            "atrevete",
            "-d",
            "atrevete_db",
            "-t",
            "-c",
            "SELECT count(*) FROM appointments WHERE created_at > now() - interval '1 hour';",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0:
        count_str = result.stdout.strip()
        try:
            return int(count_str)
        except ValueError:
            print(f"[DB] Unexpected output: {repr(count_str)}")
            return -1
    print(f"[DB] Error: {result.stderr}")
    return -1


async def main():
    result = await run_qa()

    print("\n" + "=" * 60)
    print("QA-R10 RESULT")
    print("=" * 60)
    print(f"Status:             {result['status']}")
    print(f"Turn count:         {result['turn_count']}")
    print(f"Final phase:        {result['final_phase']}")
    print(f"Milestones hit:     {result['milestones_hit']}")
    print(
        f"appointment_in_db:  {result['appointment_in_db']} (count={result['db_appointment_count']})"
    )
    print(f"conversation_id:    {result['conversation_id']}")
    print("\n--- FULL TRACE ---")
    for t in result["trace"]:
        print(f"\n[T{t['turn_number']}] PHASE={t.get('phase', '?')} | USER: {t['user_message']}")
        print(f"[T{t['turn_number']}] AGENT ({t['latency_ms']}ms): {t['agent_response'][:400]}")
    print("\n" + "=" * 60)

    # Save JSON result
    with open("/tmp/qa_r10_result.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"[HARNESS] Result saved to /tmp/qa_r10_result.json")

    return result


if __name__ == "__main__":
    asyncio.run(main())
