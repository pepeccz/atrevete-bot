"""
QA Indecision Flow — Luis (indecisive client) full booking flow.

Flow: indecision
Persona: luis_indecisive_client
Expected: recommendation_provided=true AND appointment_created=true AND appointment_in_db=true

Milestones:
  greeting_done          → Bot greeted and detected uncertainty
  discovery_started      → Bot asked clarifying questions
  recommendation_given   → Bot recommended a service
  service_resolved       → Client chose a service
  addons_handled         → Add-ons offered and accepted/declined
  slot_resolved          → Friday afternoon slot selected
  confirmation_done      → Client confirmed
  booking_completed      → Booking tool executed, appointment in DB [COMPLETION]
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime

import redis.asyncio as redis

sys.path.insert(0, "/home/pcabeza/Proyectos/atrevete-bot")

from shared.config import get_settings
from shared.redis_client import INCOMING_STREAM

RESPONSE_CHANNEL = "outgoing_messages"
TIMEOUT = 60.0
MAX_TURNS = 18
FLOW_ID = "indecision"
PERSONA_ID = "luis_indecisive_client"
SENDER_NAME = "Luis"
CUSTOMER_PHONE = "+34600999777"  # unique QA phone for this run


# ─── MILESTONE ORDERING (for progression checks) ──────────────────────────────
MILESTONE_ORDER = [
    "greeting_done",
    "discovery_started",
    "recommendation_given",
    "service_resolved",
    "addons_handled",
    "slot_resolved",
    "confirmation_done",
    "booking_completed",
]


def milestone_rank(m: str | None) -> int:
    if m is None:
        return -1
    try:
        return MILESTONE_ORDER.index(m)
    except ValueError:
        return -1


def build_redis_url(settings) -> str:
    url = settings.REDIS_URL
    url = url.replace("redis://redis:", "redis://localhost:")
    url = url.replace("rediss://redis:", "rediss://localhost:")
    if "@redis:" in url:
        url = url.replace("@redis:", "@localhost:")
    if settings.REDIS_PASSWORD:
        url = f"redis://:{settings.REDIS_PASSWORD}@localhost:6379/0"
    return url


def build_postgres_url(settings) -> str:
    url = settings.DATABASE_URL
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("@postgres:", "@localhost:")
    return url


# ─── LUIS CONVERSATIONAL STATE MACHINE ────────────────────────────────────────
# We track a simple internal state for Luis to ensure coherent replies:
# - what we've said
# - what the bot has offered
# - what Luis has decided
# This prevents sending the same message twice.


class LuisState:
    def __init__(self):
        self.gave_name = False
        self.expressed_indecision = False
        self.got_service_list = False
        self.asked_recommendation = False
        self.got_recommendation = False
        self.said_wants_corte = False
        self.said_change_mind = False
        self.addon_offered = False
        self.addon_accepted = False
        self.asked_for_friday = False
        self.selected_slot = False
        self.confirmed = False
        self.last_bot_response = ""
        self.caballero_answer_count = 0  # Track how many times we've answered the clarification


luis_state = LuisState()


def detect_milestone(agent_response: str, current_best: str | None) -> str | None:
    """
    Detect what milestone the bot's response implies.
    Never regress — only advance to a higher milestone.
    """
    r = agent_response.lower()
    detected = None

    # booking_completed: explicit booking confirmation
    booking_done_phrases = [
        "turno confirmado",
        "reserva confirmada",
        "agendé tu turno",
        "te esperamos",
        "quedó agendado",
        "quedó reservado",
        "quedaste anotado",
        "agendamos",
        "reservamos tu turno",
        "¡listo! tu turno",
        "tu turno está",
        "tu reserva quedó",
    ]
    if any(phrase in r for phrase in booking_done_phrases):
        detected = "booking_completed"

    # confirmation_done: bot asking to confirm
    elif any(
        phrase in r
        for phrase in [
            "¿confirmás",
            "¿confirmas",
            "¿lo confirmo",
            "¿lo reservo",
            "¿procedo con",
            "confirmar el turno",
            "¿querés que reserve",
            "¿te confirmo el turno",
            "¿reservo el turno",
        ]
    ):
        detected = "confirmation_done"

    # slot_resolved: bot is showing available time slots
    elif any(
        phrase in r
        for phrase in [
            "disponible el viernes",
            "el viernes a las",
            "tenemos el viernes",
            "turno el viernes",
            "podría ser el viernes",
            "disponible a las",
            "a las 14:",
            "a las 15:",
            "a las 16:",
            "a las 17:",
            "a las 18:",
            "tenemos disponibles para",
            "estos horarios",
            "¿cuál de estos horarios",
            "¿te viene bien alguno",
        ]
    ):
        detected = "slot_resolved"

    # addons_handled: bot explicitly offered add-ons alongside chosen service
    elif any(
        phrase in r
        for phrase in [
            "¿querés agregar",
            "¿te gustaría sumar",
            "podemos agregar",
            "adicionalmente",
            "también podemos incluir",
            "combinar con",
            "combinarlo con barba",
            "le sumamos",
        ]
    ) and current_best in ["service_resolved", "recommendation_given", "addons_handled"]:
        detected = "addons_handled"

    # service_resolved: bot confirmed the service we chose or is asking for when
    elif any(
        phrase in r
        for phrase in [
            "el corte caballero",
            "un corte caballero",
            "anotamos el corte",
            "reservar el corte",
            "el servicio elegido",
            "elegiste el corte",
            "has elegido",
            "perfecto! has elegido",
            "tu servicio será",
            "el servicio es",
            "para tu corte",
            "para el corte",
            # Bot asking when — implies service is resolved
            "¿para cuándo",
            "¿cuándo querés",
            "¿qué día",
            "¿cuándo te gustaría",
            "cuándo te gustaría",
            "buscar disponibilidad",
            "buscamos un turno",
            "tengo alguna fecha",
            "tienes alguna fecha",
            "fecha o día de la semana",
        ]
    ) and current_best in [None, "greeting_done", "discovery_started", "recommendation_given"]:
        detected = "service_resolved"

    # recommendation_given: bot recommended something specific
    elif any(
        phrase in r
        for phrase in [
            "te recomiendo",
            "recomendamos",
            "quedaría perfecto",
            "ideal para vos",
            "lo más popular",
            "lo más pedido",
            "el más solicitado",
            "el servicio más pedido",
            "corte caballero. dura",
            "el corte caballero",
            "lo combinan con",
            "para un look completo",
            "es el más solicitado",
        ]
    ):
        detected = "recommendation_given"

    # discovery_started: bot asked about style/preferences/goals
    elif any(
        phrase in r
        for phrase in [
            "¿qué tipo de",
            "¿tenés alguna preferencia",
            "contame un poco",
            "¿cómo tenés el cabello",
            "¿qué estilo",
            "¿buscás algo",
            "¿te gustaría algo de",
            "peluquería o estética",
            "¿qué te gustaría lograr",
            "cuéntame qué",
        ]
    ) and current_best in [None, "greeting_done"]:
        detected = "discovery_started"

    # greeting_done: bot introduced itself
    elif (
        any(
            phrase in r
            for phrase in [
                "hola",
                "bienvenido",
                "bienvenida",
                "soy maite",
                "asistenta virtual",
                "claro que sí",
                "en qué te ayudo",
            ]
        )
        and current_best is None
    ):
        detected = "greeting_done"

    # Never regress milestone
    if detected is not None and milestone_rank(detected) > milestone_rank(current_best):
        return detected

    return current_best


def generate_luis_reply(
    turn_number: int,
    agent_response: str,
    current_milestone: str | None,
    state: LuisState,
) -> str:
    """
    Generate next reply as Luis, using state to avoid repeating messages.
    Luis is hesitant, needs guidance, prefers Friday afternoon, accepts add-ons.
    """
    r = agent_response.lower()
    state.last_bot_response = agent_response

    # ── Turn 0: Opening ────────────────────────────────────────────────────
    if turn_number == 0:
        state.expressed_indecision = True
        return "Hola! Quería preguntar... no sé bien qué hacerme, pero quiero algo para caballero. ¿Me podés ayudar?"

    # ── If bot asks for name ───────────────────────────────────────────────
    if any(kw in r for kw in ["cómo te llamás", "tu nombre", "nombre es"]):
        if not state.gave_name:
            state.gave_name = True
            return "Me llamo Luis."
        return "Ya te dije, me llamo Luis."

    # ── If bot asks caballero/dama/niño clarification (again) ─────────────
    if any(
        kw in r
        for kw in [
            "caballero, dama",
            "caballero o dama",
            "para caballero, dama",
            "dama, niño",
            "niña o bebé",
        ]
    ):
        # Try different phrasings to unlock the bot's state parser
        caballero_responses = [
            "caballero",
            "1",
            "Corte de Hombre",
            "Para caballero. Opción 1.",
        ]
        idx = min(state.caballero_answer_count, len(caballero_responses) - 1)
        state.caballero_answer_count += 1
        return caballero_responses[idx]

    # ── greeting_done milestone: bot showed service menu or asked what we want ─
    if current_milestone == "greeting_done" and not state.asked_recommendation:
        state.asked_recommendation = True
        # Bot offered a consultation service or asked about goals
        if "consultor" in r or "opción" in r or "opcion" in r or "cuál prefieres" in r:
            # Go with option 2: tell what we want
            return "Quiero mantener mi estilo pero más prolijo. Tengo el cabello corto y rizado. ¿Qué me recomendás para caballero?"
        # Bot listed services
        if "corte" in r or "servicio" in r:
            state.got_service_list = True
            return "¿Qué me recomendás vos? No sé bien cuál elegir... algo que quede prolijo."
        return "No sé bien... ¿qué servicios tienen para caballero?"

    # ── discovery_started: bot is asking about hair/style ─────────────────
    if current_milestone == "discovery_started":
        return "Tengo el cabello corto, medio rizado. Quiero algo prolijo. ¿Me recomendás algo?"

    # ── recommendation_given: bot recommended something ────────────────────
    if current_milestone == "recommendation_given":
        if not state.said_change_mind and not state.said_wants_corte:
            # Luis changes his mind once
            state.said_change_mind = True
            return "Hmm, no sé... ¿y si me hago también la barba? Aunque bueno, empecemos con el corte."
        elif not state.said_wants_corte:
            state.said_wants_corte = True
            return "Sí, el corte caballero. ¿Para cuándo tendrían disponibilidad?"

    # ── service_resolved: bot confirmed service ────────────────────────────
    if current_milestone == "service_resolved" and not state.addon_offered:
        return "Perfecto. ¿Y cuándo tendrían turno? Prefiero el viernes a la tarde."

    # ── addons_handled: bot offered add-ons ───────────────────────────────
    if current_milestone == "addons_handled" and not state.addon_accepted:
        state.addon_accepted = True
        # Luis accepts the add-on
        if "barba" in r:
            return "Dale, sí, agrego la barba también. ¿Y para el viernes a la tarde tienen algo?"
        elif "tratamiento" in r or "hidratación" in r or "hidratacion" in r:
            return "Dale, ¿por qué no? Agrego el tratamiento. ¿Para cuándo sería?"
        else:
            return "Dale, sí, lo agrego. ¿Y para cuándo están disponibles? Prefiero el viernes."

    # ── If bot says no availability for Friday → accept alternative ─────────
    if any(
        kw in r
        for kw in [
            "no tengo disponibilidad",
            "no hay disponibilidad",
            "sin disponibilidad",
            "no hay turnos",
            "busco otras opciones",
            "¿te gustaría que busque otras",
        ]
    ):
        return "Dale, sí, busquen para otro día de la semana entonces."

    # ── If bot is asking when / date / slot ───────────────────────────────
    if any(kw in r for kw in ["cuándo", "cuando", "fecha", "día", "disponible"]):
        if not state.asked_for_friday:
            state.asked_for_friday = True
            return "Prefiero el viernes a la tarde, si tienen disponibilidad."

    # ── slot_resolved: bot showed time options ─────────────────────────────
    if current_milestone == "slot_resolved" and not state.selected_slot:
        state.selected_slot = True
        # Pick a Friday afternoon slot
        if "viernes" in r:
            # Look for a specific time
            for time_str in ["17:00", "17", "16:00", "16", "15:00", "15", "18:00", "18"]:
                if time_str in r:
                    hour = time_str.split(":")[0]
                    return f"El viernes a las {hour} está perfecto."
            return "El primer viernes que haya a la tarde me viene bien."
        else:
            # Bot didn't show Friday — ask explicitly
            state.selected_slot = False  # not resolved yet
            return "¿El viernes a la tarde no tienen nada disponible?"

    # ── If bot is asking stylist preference ───────────────────────────────
    if any(
        kw in r
        for kw in [
            "estilista",
            "profesional",
            "preferís alguna",
            "alguna de",
            "con qué estilista",
            "qué estilista",
            "¿con qué",
        ]
    ):
        return "No tengo preferencia de estilista, cualquiera que esté disponible."

    # ── confirmation_done: bot asks to confirm ────────────────────────────
    if current_milestone == "confirmation_done" and not state.confirmed:
        state.confirmed = True
        return "Sí, confirmo, dale."

    # ── booking_completed ─────────────────────────────────────────────────
    if current_milestone == "booking_completed":
        return "¡Perfecto! Muchas gracias."

    # ── Default progressive nudges ─────────────────────────────────────────
    # Use different defaults per turn to avoid loop
    defaults = [
        "¿Qué me recomendás para caballero?",
        "No sé bien cuál elegir, ¿cuál es el más pedido?",
        "El corte caballero suena bien. ¿Tienen el viernes a la tarde?",
        "Prefiero el viernes a la tarde si hay lugar.",
        "Sí, está bien, el viernes a la tarde.",
        "Sí, confirmo.",
    ]
    idx = min(turn_number - 1, len(defaults) - 1)
    return defaults[idx]


def detect_bugs(
    turn_number: int,
    agent_response: str,
    conversation_history: list[dict],
    state: LuisState,
) -> list[dict]:
    """Detect semantic bugs in the bot's response."""
    bugs = []
    r = agent_response.lower()

    # redundant_question: asked for name again
    if turn_number >= 3 and state.gave_name:
        if any(kw in r for kw in ["cómo te llamás", "tu nombre", "nombre"]):
            bugs.append(
                {
                    "category": "redundant_question",
                    "evidence": f"Bot re-asked for name on turn {turn_number} after Luis provided it",
                    "turns": [turn_number],
                }
            )

    # redundant_question: asked caballero/dama after Luis specified caballero multiple times
    # Luis mentioned "caballero" in initial messages
    user_msgs_text = " ".join(m.get("user", "") for m in conversation_history)
    if (
        turn_number >= 3
        and "caballero" in user_msgs_text.lower()
        and any(
            kw in r
            for kw in ["caballero, dama", "para caballero o", "caballero o dama", "dama, niño"]
        )
    ):
        bugs.append(
            {
                "category": "redundant_question",
                "evidence": f"Bot re-asked caballero/dama on turn {turn_number} after Luis specified 'caballero' multiple times",
                "turns": [turn_number],
            }
        )

    # ignored_preference: bot says no availability for Friday entirely
    if state.asked_for_friday and any(
        kw in r
        for kw in [
            "no tengo disponibilidad para ese día",
            "no hay disponibilidad para ese día",
            "no tenemos disponibilidad para ese",
        ]
    ):
        bugs.append(
            {
                "category": "ignored_preference",
                "evidence": f"Bot rejected Friday entirely on turn {turn_number} without offering Friday alternatives",
                "turns": [turn_number],
            }
        )

    # ignored_preference: Luis mentioned Friday but bot only offers other days
    if state.asked_for_friday and turn_number >= 3:
        has_friday = "viernes" in r
        has_other_days = any(d in r for d in ["lunes", "martes", "miércoles", "jueves"])
        if not has_friday and has_other_days:
            bugs.append(
                {
                    "category": "ignored_preference",
                    "evidence": f"Luis specified viernes but bot only offered other days on turn {turn_number}",
                    "turns": [turn_number],
                }
            )

    # wrong_language
    english_kws = ["hello", "please", "thank you", "appointment", "available"]
    if any(kw in r for kw in english_kws):
        bugs.append(
            {
                "category": "wrong_language",
                "evidence": f"English detected in bot response on turn {turn_number}",
                "turns": [turn_number],
            }
        )

    # hallucination: services that don't exist in a barbershop/salon
    suspicious_services = ["manicure", "pedicure", "tatuaje", "color fantasía", "extensiones"]
    found_suspicious = [s for s in suspicious_services if s in r]
    if found_suspicious:
        bugs.append(
            {
                "category": "hallucination",
                "evidence": f"Bot mentioned suspicious service(s): {found_suspicious} on turn {turn_number}",
                "turns": [turn_number],
            }
        )

    # context_loss: if we already chose a service and bot asks again
    if state.said_wants_corte and any(
        kw in r for kw in ["¿qué servicio", "que servicio", "elegir un servicio"]
    ):
        bugs.append(
            {
                "category": "context_loss",
                "evidence": f"Bot asked for service choice again on turn {turn_number} after Luis already chose corte",
                "turns": [turn_number],
            }
        )

    return bugs


async def run_qa_indecision() -> dict:
    settings = get_settings()
    redis_url = build_redis_url(settings)

    print("Redis URL: masked")
    print(f"Incoming stream: {INCOMING_STREAM}")
    print(f"Response channel: {RESPONSE_CHANNEL}")

    r = redis.from_url(redis_url, decode_responses=True)
    r_binary = redis.from_url(redis_url, decode_responses=False)

    try:
        await r.ping()
        print("✅ Redis connected OK")
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        return {"error": str(e)}

    conversation_id = str(uuid.uuid4())
    run_start = datetime.now(UTC)

    print(f"\n{'=' * 70}")
    print("QA Flow: indecision — Luis (indecisive client)")
    print(f"conversation_id: {conversation_id}")
    print(f"Started: {run_start.isoformat()}")
    print(f"Max turns: {MAX_TURNS}")
    print(f"{'=' * 70}\n")

    # CRITICAL: Subscribe BEFORE injecting
    pubsub = r.pubsub()
    await pubsub.subscribe(RESPONSE_CHANNEL)
    await asyncio.sleep(0.5)
    # Drain stale messages
    for _ in range(5):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
        if msg is None:
            break

    print(f"✅ Subscribed to '{RESPONSE_CHANNEL}' BEFORE injecting\n")

    # ── Turn loop state ──────────────────────────────────────────────────
    state = LuisState()
    turn_number = 0
    conversation_history: list[dict] = []
    turns_result: list[dict] = []
    current_milestone: str | None = None
    prev_milestone: str | None = None
    consecutive_same_milestone = 0
    outcome = "in_progress"
    termination_reason = ""
    tool_trace: list[str] = []

    # Opening message (turn 0)
    current_message = generate_luis_reply(0, "", current_milestone, state)

    while turn_number < MAX_TURNS:
        print(f"--- Turn {turn_number + 1} ---")
        print(f"LUIS: {current_message}")

        # ── Inject ──────────────────────────────────────────────────────
        timestamp_sent = datetime.now(UTC)
        payload = {
            "conversation_id": conversation_id,
            "customer_phone": CUSTOMER_PHONE,
            "message_text": current_message,
            "sender_name": SENDER_NAME,
            "customer_name": SENDER_NAME,
            "is_audio_transcription": False,
            "audio_url": None,
        }
        await r.xadd(INCOMING_STREAM, {"data": json.dumps(payload)})

        # ── Capture response ─────────────────────────────────────────────
        agent_response = None
        raw_payload = None
        timed_out = False
        deadline = asyncio.get_running_loop().time() + TIMEOUT

        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                print(f"  ⏱ TIMEOUT after {TIMEOUT}s")
                agent_response = "[TIMEOUT]"
                timed_out = True
                break

            raw_message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=min(remaining, 2.0),
            )
            if raw_message is None:
                continue

            data = raw_message.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            if not data:
                continue

            try:
                pld = json.loads(data)
            except json.JSONDecodeError:
                continue

            if pld.get("conversation_id") != conversation_id:
                continue

            raw_payload = pld
            agent_response = pld.get("message", "")
            if pld.get("tool_calls"):
                tool_trace.extend(pld["tool_calls"])
            break

        timestamp_received = datetime.now(UTC)
        latency_ms = int((timestamp_received - timestamp_sent).total_seconds() * 1000)

        print(f"BOT  ({latency_ms}ms): {agent_response}")

        # ── Timeout handling ─────────────────────────────────────────────
        if timed_out:
            prior_timeouts = sum(1 for t in turns_result[-2:] if t.get("timed_out"))
            turns_result.append(
                {
                    "turn_number": turn_number + 1,
                    "user_message": current_message,
                    "agent_response": "[TIMEOUT]",
                    "milestone_reached": current_milestone,
                    "bugs": [],
                    "timed_out": True,
                    "latency_ms": latency_ms,
                }
            )
            if prior_timeouts >= 1:
                outcome = "timeout"
                termination_reason = "Bot unresponsive for 2 consecutive turns"
                break
            current_message = "Hola? Siguen ahí?"
            turn_number += 1
            continue

        # ── Update milestone (never regress) ─────────────────────────────
        new_milestone = detect_milestone(agent_response, current_milestone)
        if new_milestone and new_milestone != current_milestone:
            print(f"  📍 Milestone advanced: {current_milestone} → {new_milestone}")
            current_milestone = new_milestone

        # ── Update Luis state flags ──────────────────────────────────────
        r_lower = agent_response.lower()
        if any(kw in r_lower for kw in ["adicional", "tratamiento", "barba", "extra", "sumar"]):
            if current_milestone in ["service_resolved", "recommendation_given", "addons_handled"]:
                state.addon_offered = True
        if any(kw in r_lower for kw in ["servicio", "corte", "barba", "color"]):
            state.got_service_list = True

        # ── Bug detection ────────────────────────────────────────────────
        bugs = detect_bugs(turn_number + 1, agent_response, conversation_history, state)
        if bugs:
            for bug in bugs:
                print(f"  🐛 BUG [{bug['category']}]: {bug['evidence']}")

        # ── Dead loop detection ──────────────────────────────────────────
        if current_milestone == prev_milestone:
            consecutive_same_milestone += 1
        else:
            consecutive_same_milestone = 0
            prev_milestone = current_milestone

        # ── Update rolling history ───────────────────────────────────────
        conversation_history.append({"user": current_message, "bot": agent_response})
        if len(conversation_history) > 6:
            conversation_history = conversation_history[-6:]

        # ── Record turn ──────────────────────────────────────────────────
        turns_result.append(
            {
                "turn_number": turn_number + 1,
                "user_message": current_message,
                "agent_response": agent_response,
                "milestone_reached": current_milestone,
                "bugs": bugs,
                "timed_out": False,
                "latency_ms": latency_ms,
            }
        )

        print(
            f"  📍 Current milestone: {current_milestone} (same for {consecutive_same_milestone} turns)"
        )

        # ── Check completion ─────────────────────────────────────────────
        if current_milestone == "booking_completed":
            outcome = "completed"
            termination_reason = "booking_completed milestone reached"
            break

        # ── Check dead loop ──────────────────────────────────────────────
        # Allow more tolerance for early/None state; strict for mid-flow
        if current_milestone is None:
            dead_loop_threshold = 6
        elif current_milestone in [
            "greeting_done",
            "discovery_started",
            "recommendation_given",
            "service_resolved",
        ]:
            dead_loop_threshold = 5  # Allow extra retries for bot clarification loops
        else:
            dead_loop_threshold = 3
        if consecutive_same_milestone >= dead_loop_threshold:
            outcome = "dead_loop"
            termination_reason = (
                f"Stuck at milestone '{current_milestone}' for {consecutive_same_milestone}+ turns"
            )
            break

        # ── Escalation check (real human handoff, not just keyword) ─────────
        # "persona" appears in "personalizado", "personalizada" — must be exact
        escalation_phrases = [
            "derivar a un humano",
            "contactar con el equipo",
            "te va a llamar",
            "te llamará un asesor",
            "hablar con una persona del equipo",
            "atención humana",
            "transferir tu consulta",
            "escalamos",
        ]
        if any(phrase in r_lower for phrase in escalation_phrases):
            outcome = "escalated"
            termination_reason = "Unexpected escalation triggered"
            break

        # ── Generate next Luis reply ─────────────────────────────────────
        current_message = generate_luis_reply(
            turn_number + 1, agent_response, current_milestone, state
        )
        turn_number += 1

    else:
        outcome = "timeout"
        termination_reason = f"max_turns ({MAX_TURNS}) exceeded"

    print(f"\n{'=' * 70}")
    print(f"LOOP ENDED: outcome={outcome}, milestone={current_milestone}")
    print(f"Reason: {termination_reason}")
    print(f"{'=' * 70}\n")

    # ── DB Verification ────────────────────────────────────────────────────
    db_verification = {"found": False, "details": "not checked (flow did not complete)"}
    final_state = {
        "appointment_created": False,
        "customer_id": None,
        "customer_name": None,
        "service_name": None,
        "stylist_name": None,
        "slot_datetime": None,
        "current_mode": None,
    }

    if outcome == "completed":
        # LangGraph checkpoint
        print("Checking LangGraph checkpoint...")
        try:
            from langgraph.checkpoint.redis.aio import AsyncRedisSaver

            checkpointer = AsyncRedisSaver(redis_client=r_binary)
            config = {"configurable": {"thread_id": conversation_id}}
            checkpoint = await checkpointer.aget(config)

            if checkpoint:
                checkpoint_data = getattr(checkpoint, "checkpoint", checkpoint)
                channel_values = checkpoint_data.get("channel_values", {})
                raw = dict(channel_values) if isinstance(channel_values, dict) else {}

                final_state["appointment_created"] = bool(raw.get("appointment_created"))
                final_state["customer_id"] = str(raw.get("customer_id", "")) or None
                final_state["customer_name"] = raw.get("customer_first_name") or raw.get(
                    "customer_name"
                )
                final_state["service_name"] = (
                    raw.get("service_name") or str(raw.get("service_id", "")) or None
                )
                final_state["stylist_name"] = (
                    raw.get("stylist_name") or str(raw.get("stylist_id", "")) or None
                )
                final_state["slot_datetime"] = (
                    str(raw.get("appointment_datetime") or raw.get("selected_slot") or "") or None
                )
                final_state["current_mode"] = raw.get("current_mode")

                for k, v in final_state.items():
                    print(f"  {k}: {v}")
            else:
                print("  WARNING: No checkpoint found")
        except Exception as e:
            print(f"  WARNING: Checkpoint error: {e}")

        # PostgreSQL check
        print("\nVerifying appointment in PostgreSQL...")
        try:
            import asyncpg

            conn = await asyncpg.connect(build_postgres_url(settings))
            try:
                row = await conn.fetchrow(
                    """
                    SELECT a.id, a.start_time, s.name as service_name,
                           st.display_name as stylist_name,
                           c.first_name as customer_name
                    FROM appointments a
                    JOIN services s ON a.service_id = s.id
                    JOIN stylists st ON a.stylist_id = st.id
                    JOIN customers c ON a.customer_id = c.id
                    WHERE (a.metadata->>'conversation_id' = $1 OR c.phone = $2)
                    ORDER BY a.created_at DESC
                    LIMIT 1
                    """,
                    conversation_id,
                    CUSTOMER_PHONE,
                )
                if row:
                    db_verification = {
                        "found": True,
                        "details": (
                            f"id={row['id']}, service={row['service_name']}, "
                            f"stylist={row['stylist_name']}, customer={row['customer_name']}, "
                            f"start_time={row['start_time']}"
                        ),
                    }
                    print(f"  ✅ {db_verification['details']}")
                else:
                    db_verification = {
                        "found": False,
                        "details": "No appointment found for this conversation_id or phone",
                    }
                    print("  ❌ No appointment found in DB")
            finally:
                await conn.close()

        except ImportError:
            print("  INFO: asyncpg not installed, skipping direct DB check")
            db_verification = {
                "found": final_state.get("appointment_created", False),
                "details": "Checkpoint-only verification (asyncpg unavailable)",
            }
        except Exception as e:
            print(f"  WARNING: DB error: {e}")
            db_verification = {"found": False, "details": f"DB error: {str(e)[:200]}"}

    # ── Cleanup ────────────────────────────────────────────────────────────
    try:
        await pubsub.unsubscribe(RESPONSE_CHANNEL)
        await pubsub.aclose()
    except Exception:
        pass
    await r.aclose()
    await r_binary.aclose()

    run_end = datetime.now(UTC)
    total_duration_ms = int((run_end - run_start).total_seconds() * 1000)

    # ── Bug summary ────────────────────────────────────────────────────────
    all_bugs = [bug for t in turns_result for bug in t.get("bugs", [])]
    if all_bugs:
        cats: dict[str, list[str]] = {}
        for bug in all_bugs:
            cats.setdefault(bug["category"], []).append(bug["evidence"])
        bugs_summary = " | ".join(f"{cat} ({len(evs)}): {evs[0][:80]}" for cat, evs in cats.items())
    else:
        bugs_summary = "No semantic bugs detected"

    # ── Tool chain evidence ────────────────────────────────────────────────
    all_responses = " ".join(t.get("agent_response", "") for t in turns_result).lower()
    tool_chain_evidence = list(tool_trace)  # from raw payloads
    # search_services removed — service catalog is in-prompt via catalog_builder.py
    if any(kw in all_responses for kw in ["disponible", "horario", "viernes", "turno el"]):
        if "check_availability → confirmed" not in tool_chain_evidence:
            tool_chain_evidence.append("check_availability → slots offered to user")
    if outcome == "completed" and db_verification.get("found"):
        tool_chain_evidence.append("book_appointment → confirmed via DB")

    return {
        "flow_id": FLOW_ID,
        "persona_id": PERSONA_ID,
        "conversation_id": conversation_id,
        "outcome": outcome,
        "milestone_reached": current_milestone,
        "turns": turns_result,
        "tool_trace": tool_chain_evidence,
        "bugs_summary": bugs_summary,
        "db_verification": db_verification,
        "total_turns": len(turns_result),
        "termination_reason": termination_reason,
        "execution_summary": {
            "total_duration_ms": total_duration_ms,
            "turns_attempted": len(turns_result),
            "turns_successful": sum(1 for t in turns_result if not t.get("timed_out")),
            "any_timeout": any(t.get("timed_out") for t in turns_result),
            "final_state": final_state,
        },
    }


def main() -> int:
    result = asyncio.run(run_qa_indecision())

    if "error" in result:
        print(f"\n❌ FATAL ERROR: {result['error']}")
        return 1

    print("\n" + "=" * 70)
    print("QA TRACE — INDECISION FLOW (Luis)")
    print("=" * 70)
    print(f"\nOutcome:           {result['outcome']}")
    print(f"Milestone reached: {result['milestone_reached']}")
    print(f"Total turns:       {result['total_turns']}")
    print(f"Termination:       {result['termination_reason']}")
    print(f"Bugs:              {result['bugs_summary']}")
    print(
        f"DB verified:       {result['db_verification']['found']} — {result['db_verification']['details']}"
    )

    summary = result.get("execution_summary", {})
    print(f"\nDuration: {summary.get('total_duration_ms', 0)}ms")
    print(f"Turns OK: {summary.get('turns_successful')}/{summary.get('turns_attempted')}")

    print("\nTurn Summary:")
    for t in result.get("turns", []):
        status = "⏱" if t.get("timed_out") else "✅"
        m = (t.get("milestone_reached") or "—")[:25]
        preview = (t.get("agent_response") or "")[:70]
        bugs_n = len(t.get("bugs", []))
        bug_str = f" [🐛{bugs_n}]" if bugs_n else ""
        print(f"  T{t['turn_number']:02d} {status} [{m:25s}] {preview}...{bug_str}")

    print("\nTool trace:")
    for t in result.get("tool_trace", []):
        print(f"  → {t}")

    output_path = "/tmp/qa_indecision_luis_trace.json"
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\nFull trace saved to: {output_path}")

    print("\n" + "=" * 70)
    print("FULL JSON TRACE:")
    print("=" * 70)
    print(json.dumps(result, indent=2, default=str))

    return 0 if result["outcome"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
