"""
QA Round 4 — indecision flow / luis_indecisive_client
Commit tested: 31deed9

Fixes validated vs R3:
  - NEW-C  (friday-no-loop): "el viernes" → nearest Friday without looping ✅ (verified R3, re-verify)
  - NEW-REG-1 (service_id loop fix in 31deed9): After bot recommends "Corte de Hombre" and Luis
      confirms → service_id/name written to state → advances to add_ons (NOT stuck in service_selection)
  - BUG-001 (book-on-confirm): book() called on confirmation → appointment_in_db=true
  - BUG-002 (no narration): Zero action narration phrases in responses
  - NEW-B  (addon-implicit-decline): "empecemos con el corte" = implicit add-on decline
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import uuid
from datetime import UTC, datetime

import redis.asyncio as redis

sys.path.insert(0, "/home/pcabeza/Proyectos/atrevete-bot")

from shared.config import get_settings
from shared.redis_client import INCOMING_STREAM

RESPONSE_CHANNEL = "outgoing_messages"
TIMEOUT = 60.0
BATCH_WINDOW = 3.0
MAX_TURNS = 18
FLOW_ID = "indecision"
PERSONA_ID = "luis_indecisive_client"
SENDER_NAME = "Luis"
CUSTOMER_PHONE = "+34600112233"  # fresh phone — never reuse R3 phone

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


def milestone_rank(m):
    try:
        return MILESTONE_ORDER.index(m) if m else -1
    except ValueError:
        return -1


def build_redis_url(settings):
    if settings.REDIS_PASSWORD:
        return f"redis://:{settings.REDIS_PASSWORD}@localhost:6379/0"
    url = settings.REDIS_URL
    url = url.replace("redis://redis:", "redis://localhost:")
    url = url.replace("@redis:", "@localhost:")
    return url


def build_postgres_url(settings):
    url = settings.DATABASE_URL
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("@postgres:", "@localhost:")
    return url


def pick_slot_from_response(agent_response: str):
    """
    Return a number string (1, 2, 3…) for the first tarde option in a numbered list.
    Handles markdown asterisks like *14:00*.
    """
    stripped = agent_response.replace("*", "")
    items = re.findall(r"\d+[\.\)]\s+(.+?)(?:\n|$)", stripped)
    if not items:
        return None
    for i, item in enumerate(items, start=1):
        hour_m = re.search(r"(\d{1,2})[:h]", item)
        if hour_m:
            hour = int(hour_m.group(1))
            if 14 <= hour <= 18:
                return str(i)
    return "1"


def has_numbered_slots(agent_response: str) -> bool:
    stripped = agent_response.replace("*", "")
    return bool(re.findall(r"\d+[\.\)]\s+.+?(?:\n|$)", stripped))


def detect_milestone(agent_response: str, current_best):
    stripped = agent_response.replace("*", "").lower()
    detected = None

    booking_done = [
        "turno confirmado", "reserva confirmada", "agendé tu turno",
        "te esperamos", "quedó agendado", "quedó reservado", "quedaste anotado",
        "agendamos", "reservamos tu turno", "listo! tu turno",
        "tu turno está", "tu reserva quedó", "reservamos el turno",
        "listo! tu reserva", "¡quedaste anotado",
    ]
    if any(p in stripped for p in booking_done):
        detected = "booking_completed"

    elif any(p in stripped for p in [
        "¿confirmás", "¿confirmas", "¿lo confirmo", "¿lo reservo",
        "¿procedo con", "confirmar el turno", "¿querés que reserve",
        "¿te confirmo el turno", "¿reservo el turno",
        "¿confirmo el turno", "procedemos", "¿reservamos",
    ]):
        detected = "confirmation_done"

    elif (
        has_numbered_slots(agent_response)
        and any(kw in stripped for kw in ["viernes", "tarde", "disponible", "a las", "con pilar", "con luciana", "con andrea"])
    ) or any(p in stripped for p in [
        "disponible el viernes", "el viernes a las",
        "tenemos el viernes", "turno el viernes",
        "a las 14", "a las 15", "a las 16", "a las 17", "a las 18",
        "tenemos disponibles para", "estos horarios",
        "¿cuál de estos horarios", "¿te viene bien alguno",
        "viernes 27", "viernes 28", "viernes 29",
    ]):
        detected = "slot_resolved"

    elif any(p in stripped for p in [
        "¿querés agregar", "¿te gustaría sumar", "podemos agregar",
        "también podemos incluir", "combinar con",
        "combinarlo con barba", "le sumamos",
        "¿querés incluir", "¿te interesa agregar",
    ]) and current_best in ["service_resolved", "recommendation_given", "addons_handled"]:
        detected = "addons_handled"

    elif any(p in stripped for p in [
        "el corte caballero", "un corte caballero",
        "anotamos el corte", "reservar el corte",
        "has elegido", "perfecto! has elegido",
        "para tu corte", "para el corte",
        "¿para cuándo", "¿cuándo querés", "¿qué día",
        "cuándo te gustaría", "buscar disponibilidad",
        "buscamos un turno", "fecha o día de la semana",
        "excelente elección", "excelente eleccion",
    ]) and current_best in [None, "greeting_done", "discovery_started", "recommendation_given"]:
        detected = "service_resolved"

    elif any(p in stripped for p in [
        "te recomiendo", "recomendamos", "quedaría perfecto",
        "ideal para vos", "lo más popular", "lo más pedido",
        "el más solicitado", "corte caballero",
        "para un look completo",
    ]):
        detected = "recommendation_given"

    elif any(p in stripped for p in [
        "¿qué tipo de", "¿tenés alguna preferencia", "contame un poco",
        "¿cómo tenés el cabello", "¿qué estilo", "¿buscás algo",
        "¿te gustaría algo de", "descubrir qué necesitas",
        "¿qué te gustaría lograr",
    ]) and current_best in [None, "greeting_done"]:
        detected = "discovery_started"

    elif any(p in stripped for p in [
        "hola", "bienvenido", "soy maite",
        "asistenta virtual", "claro que sí", "claro que si",
        "en qué te ayudo",
    ]) and current_best is None:
        detected = "greeting_done"

    if detected is not None and milestone_rank(detected) > milestone_rank(current_best):
        return detected
    return current_best


class LuisState:
    def __init__(self):
        self.gave_name = False
        self.said_wants_corte = False
        self.said_change_mind = False
        # NEW-B: Luis will implicitly decline add-ons with "empecemos con el corte"
        self.addon_handled = False
        self.asked_for_friday = False
        self.slot_selected = False
        self.confirmed = False
        self.caballero_count = 0
        self.friday_turns = 0
        # NEW-REG-1 tracking: detect if bot re-asks service after recommendation
        self.service_reask_count = 0


async def capture_response(
    pubsub, conversation_id: str, timeout: float = 60.0, batch_window: float = 3.0
) -> str:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    batch_deadline = None
    messages = []

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        poll_timeout = remaining
        if batch_deadline is not None:
            batch_remaining = batch_deadline - loop.time()
            if batch_remaining <= 0:
                break
            poll_timeout = min(poll_timeout, batch_remaining)

        raw_msg = await pubsub.get_message(
            ignore_subscribe_messages=True,
            timeout=min(poll_timeout, 2.0),
        )
        if raw_msg is None:
            if messages and batch_deadline and loop.time() >= batch_deadline:
                break
            continue

        data = raw_msg.get("data")
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

        msg_text = pld.get("message", "").strip()
        if msg_text:
            messages.append(msg_text)
            if batch_deadline is None:
                batch_deadline = loop.time() + batch_window

    return "\n\n".join(messages) if messages else "[TIMEOUT]"


def generate_reply(turn_number: int, agent_response: str, current_milestone, state: LuisState):
    """Return (reply_text, should_stop).

    Priority order (highest first):
      1. booking_completed → stop
      2. name request
      3. confirmation request
      4. add-on offer (querés agregar / incluir / sumar)
      5. numbered slot list → pick number
      6. stylist preference question
      7. time/hour question (when slot is already pending)
      8. date/day question → friday
      9. caballero/dama selector
      10. milestone-based defaults
    """
    stripped = agent_response.replace("*", "").lower()

    if turn_number == 0:
        return (
            "Hola! Quería preguntar... no sé bien qué hacerme, pero quiero algo para caballero. ¿Me podés ayudar?",
            False,
        )

    if current_milestone == "booking_completed":
        return "¡Perfecto! Muchas gracias. Nos vemos el viernes 😊", True

    # 1. Name request
    if any(kw in stripped for kw in ["cómo te llamás", "tu nombre", "nombre es", "me decís tu nombre"]):
        if not state.gave_name:
            state.gave_name = True
            return "Me llamo Luis.", False
        return "Luis.", False

    # 2. Confirmation request (highest priority after booking_done)
    if current_milestone == "confirmation_done" and not state.confirmed:
        state.confirmed = True
        return "Sí, confirmo, dale.", False

    # Also catch confirm prompts by text even before milestone fires
    if any(kw in stripped for kw in [
        "¿confirmás", "¿confirmas", "¿lo confirmo", "¿lo reservo",
        "¿procedo con", "¿querés que reserve", "¿te confirmo", "¿reservo",
        "¿confirmo", "¿reservamos", "procedemos",
    ]) and state.slot_selected and not state.confirmed:
        state.confirmed = True
        return "Sí, confirmo, dale.", False

    # 3. Add-on offer — NEW-B: implicit decline "empecemos con el corte"
    if any(kw in stripped for kw in [
        "¿querés agregar", "¿te gustaría sumar", "podemos agregar",
        "también podemos incluir", "combinar con", "le sumamos",
        "¿querés incluir", "¿te interesa agregar", "quieres agregar",
        "añadir algún servicio", "servicio complementario",
    ]) and not state.addon_handled:
        state.addon_handled = True
        # NEW-B: Implicit decline
        return "No, empecemos con el corte nomás, gracias.", False

    # 4. Numbered slot list → pick number
    if has_numbered_slots(agent_response) and not state.slot_selected:
        state.slot_selected = True
        slot = pick_slot_from_response(agent_response)
        return slot or "1", False

    # 5. Stylist preference
    if any(kw in stripped for kw in [
        "estilista", "profesional", "con qué estilista", "preferís alguna",
        "con quién", "qué estilista", "preferencia de estilista",
    ]):
        return "No tengo preferencia, cualquiera que esté disponible.", False

    # 6. Time/hour question (bot asks what time, slot not yet selected)
    if any(kw in stripped for kw in [
        "a qué hora", "qué hora", "hora te", "hora preferís", "horario preferís",
    ]) and not state.slot_selected:
        return "A las 14:00 o después, tarde preferiblemente.", False

    # 7. Date/day question → friday — detect if bot proposes a specific date
    if any(kw in stripped for kw in [
        "cuándo", "cuando", "fecha", "para cuándo", "disponibilidad",
        "qué día", "te refieres a este viernes", "¿qué viernes",
        "te viene bien", "te parece bien", "te confirmo",
    ]):
        state.friday_turns += 1
        # If bot is proposing a specific date (e.g. "viernes 21 de marzo"), confirm it explicitly
        import re as _re
        date_match = _re.search(r"viernes (\d+ de \w+)", stripped)
        if date_match and not state.slot_selected:
            # Bot asked "¿Te viene bien el viernes X?" → confirm with specific time
            return f"Sí, el {date_match.group(0)} a las 16:00.", False
        if not state.asked_for_friday:
            state.asked_for_friday = True
            return "Sí, el viernes más cercano, a las 16:00 si tienen.", False
        if has_numbered_slots(agent_response) and not state.slot_selected:
            state.slot_selected = True
            return pick_slot_from_response(agent_response) or "1", False
        return "El viernes a las 16:00.", False

    # 8. caballero/dama selector
    if any(kw in stripped for kw in ["caballero, dama", "caballero o dama", "para caballero o", "dama, niño"]):
        choices = ["caballero", "1", "Corte de Hombre"]
        idx = min(state.caballero_count, len(choices) - 1)
        state.caballero_count += 1
        return choices[idx], False

    # 9. Milestone-based defaults

    if current_milestone == "slot_resolved" and not state.slot_selected:
        # Bot showed slots but no numbered list detected — ask for first afternoon
        state.slot_selected = True
        return "El primero de la tarde, por favor.", False

    if current_milestone == "service_resolved" and not state.asked_for_friday:
        state.asked_for_friday = True
        return "Perfecto, ¿tienen turno el viernes a la tarde?", False

    # NEW-REG-1: if bot re-asks what service after recommending — confirm again
    if current_milestone == "recommendation_given":
        if not state.said_change_mind:
            state.said_change_mind = True
            # NEW-B (implicit add-on decline integrated) + explicit service name to avoid search loop
            return "Quiero el Corte de Hombre, por favor.", False
        if not state.said_wants_corte:
            state.said_wants_corte = True
            return "El Corte de Hombre. ¿Para el viernes a la tarde tienen algo?", False
        state.service_reask_count += 1
        if state.service_reask_count <= 2:
            return "Corte de Hombre.", False
        return "El corte de caballero.", False

    if current_milestone == "discovery_started":
        return "Tengo el cabello corto, rizado. Quiero algo prolijo. ¿Qué me recomendás?", False

    if current_milestone == "greeting_done":
        return "¿Qué me recomendás para caballero? Quiero algo prolijo.", False

    # Fallback numbered slot catch
    if has_numbered_slots(agent_response) and not state.slot_selected:
        state.slot_selected = True
        return pick_slot_from_response(agent_response) or "1", False

    defaults = [
        "¿Qué me recomendás para caballero?",
        "No sé cuál elegir, ¿cuál es el más pedido?",
        "El corte caballero me parece bien.",
        "¿Tienen disponibilidad el viernes a la tarde?",
        "Perfecto, ese está bien.",
        "Sí, confirmo.",
        "Sí.",
    ]
    idx = min(turn_number - 1, len(defaults) - 1)
    return defaults[idx], False


async def run_qa() -> dict:
    settings = get_settings()
    redis_url = build_redis_url(settings)
    pg_url = build_postgres_url(settings)

    r = redis.from_url(redis_url, decode_responses=True)
    r_binary = redis.from_url(redis_url, decode_responses=False)

    try:
        await r.ping()
        print("✅ Redis connected")
    except Exception as e:
        return {"error": str(e)}

    conversation_id = str(uuid.uuid4())
    run_start = datetime.now(UTC)

    print(f"\n{'='*70}")
    print("QA Round 4 — indecision / luis_indecisive_client")
    print("Commit: 31deed9")
    print(f"conversation_id: {conversation_id}")
    print(f"phone:           {CUSTOMER_PHONE}")
    print(f"started_at:      {run_start.isoformat()}")
    print("Validating: NEW-REG-1 (service_id loop), NEW-C (friday), BUG-001, BUG-002, NEW-B")
    print(f"{'='*70}\n")

    # Subscribe BEFORE any injection to avoid race
    pubsub = r.pubsub()
    await pubsub.subscribe(RESPONSE_CHANNEL)
    await asyncio.sleep(0.5)
    # Drain any stale messages from previous runs
    for _ in range(20):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
        if msg is None:
            break
    print("✅ Subscribed BEFORE injecting\n")

    state = LuisState()
    turn_number = 0
    turns_result = []
    current_milestone = None
    prev_milestone = None
    consecutive_same = 0
    all_bugs = []
    outcome = "in_progress"
    termination_reason = ""

    # NEW-REG-1 specific tracking
    service_selection_repeated = 0
    last_service_question_turn = -1

    current_message, _ = generate_reply(0, "", current_milestone, state)

    while turn_number < MAX_TURNS:
        print(f"--- Turn {turn_number + 1}/{MAX_TURNS} ---")
        print(f"LUIS: {current_message}")

        ts_sent = datetime.now(UTC)
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

        agent_response = await capture_response(pubsub, conversation_id, TIMEOUT, BATCH_WINDOW)
        latency_ms = int((datetime.now(UTC) - ts_sent).total_seconds() * 1000)
        timed_out = agent_response == "[TIMEOUT]"

        if timed_out:
            print(f"BOT  ({latency_ms}ms): ⏱ TIMEOUT")
            prior_timeouts = sum(1 for t in turns_result[-2:] if t.get("timed_out"))
            turns_result.append({
                "turn_number": turn_number + 1,
                "user_message": current_message,
                "agent_response": None,
                "timed_out": True,
                "latency_ms": latency_ms,
                "milestone_reached": current_milestone,
                "bugs": [],
            })
            if prior_timeouts >= 1:
                outcome = "timeout"
                termination_reason = "Bot unresponsive for 2 consecutive turns"
                break
            current_message = "Hola? Siguen ahí?"
            turn_number += 1
            continue

        print(f"BOT  ({latency_ms}ms): {agent_response[:350]}{'...' if len(agent_response) > 350 else ''}")

        # ── Bug detection ─────────────────────────────────────────────────────
        bugs_this_turn = []

        # BUG-002: action narration
        narration_patterns = [r"llamo a\b", r"ejecuto\b", r"usando la herramienta", r"consultando la base"]
        if any(re.search(p, agent_response.lower()) for p in narration_patterns):
            bugs_this_turn.append({
                "category": "BUG-002",
                "evidence": f"Action narration on turn {turn_number + 1}: {agent_response[:100]}",
                "turn": turn_number + 1,
            })

        # NEW-REG-1: detect if bot re-asks service after it was already confirmed
        stripped_lower = agent_response.replace("*", "").lower()
        if current_milestone in ("recommendation_given", "service_resolved") and any(
            kw in stripped_lower for kw in [
                "caballero, dama", "caballero o dama", "para caballero o", "dama, niño",
                "qué tipo de servicio", "qué servicio", "elegir servicio",
            ]
        ):
            service_selection_repeated += 1
            if last_service_question_turn >= 0 and service_selection_repeated >= 2:
                bugs_this_turn.append({
                    "category": "NEW-REG-1",
                    "evidence": (
                        f"Bot re-asked service selection at turn {turn_number + 1} "
                        f"(milestone={current_milestone}): {agent_response[:120]}"
                    ),
                    "turn": turn_number + 1,
                })
            last_service_question_turn = turn_number

        # NEW-B: implicit add-on decline — detect if bot loops on add-on after "empecemos con el corte"
        if state.addon_handled and current_milestone == "addons_handled":
            if any(kw in stripped_lower for kw in ["¿querés agregar", "¿te gustaría sumar", "¿querés incluir"]):
                bugs_this_turn.append({
                    "category": "NEW-B-LOOP",
                    "evidence": f"Bot re-offered add-on after implicit decline on turn {turn_number + 1}",
                    "turn": turn_number + 1,
                })

        # Advance milestone
        new_milestone = detect_milestone(agent_response, current_milestone)
        if new_milestone and new_milestone != current_milestone:
            print(f"  📍 Milestone: {current_milestone} → {new_milestone}")
            current_milestone = new_milestone

        # Dead loop tracking
        if current_milestone == prev_milestone:
            consecutive_same += 1
        else:
            consecutive_same = 0
            prev_milestone = current_milestone

        turns_result.append({
            "turn_number": turn_number + 1,
            "user_message": current_message,
            "agent_response": agent_response,
            "timed_out": False,
            "latency_ms": latency_ms,
            "milestone_reached": current_milestone,
            "bugs": bugs_this_turn,
        })
        all_bugs.extend(bugs_this_turn)

        print(f"  milestone={current_milestone} | same_for={consecutive_same}")

        if current_milestone == "booking_completed":
            outcome = "completed"
            termination_reason = "booking_completed"
            break

        threshold = 3
        if current_milestone in [None, "greeting_done", "discovery_started"]:
            threshold = 5
        elif current_milestone in ["recommendation_given", "service_resolved"]:
            threshold = 4
        if consecutive_same >= threshold:
            outcome = "dead_loop"
            termination_reason = f"Stuck at '{current_milestone}' for {consecutive_same} turns"
            break

        current_message, should_stop = generate_reply(
            turn_number + 1, agent_response, current_milestone, state
        )
        if should_stop:
            outcome = "completed"
            termination_reason = "LLM persona completed"
            break

        turn_number += 1
    else:
        outcome = "max_turns"
        termination_reason = f"max_turns ({MAX_TURNS}) exceeded"

    print(f"\n{'='*70}")
    print(f"LOOP ENDED: outcome={outcome} | milestone={current_milestone}")
    print(f"Reason: {termination_reason}")

    # ── DB Verification ────────────────────────────────────────────────────
    db_count = 0
    db_verification = {"found": False, "count": 0, "details": "not checked"}
    final_state = {"appointment_created": False}

    try:
        import asyncpg
        conn = await asyncpg.connect(pg_url)
        try:
            row = await conn.fetchrow(
                "SELECT count(*) as cnt FROM appointments WHERE created_at > now() - interval '1 hour'"
            )
            db_count = int(row["cnt"]) if row else 0
            db_verification["count"] = db_count
        finally:
            await conn.close()
    except ImportError:
        pass
    except Exception as e:
        db_verification["count_error"] = str(e)[:200]

    if outcome == "completed":
        # Checkpoint state
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
                final_state["current_mode"] = raw.get("current_mode")
                final_state["customer_name"] = raw.get("customer_first_name")
                final_state["service_name"] = raw.get("service_name") or str(raw.get("service_id", ""))
                final_state["stylist_name"] = raw.get("stylist_name") or str(raw.get("stylist_id", ""))
                final_state["service_id"] = str(raw.get("service_id", ""))
        except Exception as e:
            print(f"  Checkpoint error: {e}")

        # DB appointment lookup
        try:
            import asyncpg
            conn2 = await asyncpg.connect(pg_url)
            try:
                appt_row = await conn2.fetchrow(
                    """
                    SELECT a.id, a.start_time, s.name as service_name,
                           st.display_name as stylist_name,
                           c.first_name as customer_name
                    FROM appointments a
                    JOIN services s ON a.service_id = s.id
                    JOIN stylists st ON a.stylist_id = st.id
                    JOIN customers c ON a.customer_id = c.id
                    WHERE (a.metadata->>'conversation_id' = $1 OR c.phone = $2)
                    ORDER BY a.created_at DESC LIMIT 1
                    """,
                    conversation_id, CUSTOMER_PHONE,
                )
                if appt_row:
                    db_verification["found"] = True
                    db_verification["details"] = (
                        f"id={appt_row['id']}, service={appt_row['service_name']}, "
                        f"stylist={appt_row['stylist_name']}, "
                        f"start={appt_row['start_time']}"
                    )
                else:
                    db_verification["found"] = False
                    db_verification["details"] = "No appointment row for this conversation"
            finally:
                await conn2.close()
        except ImportError:
            db_verification["found"] = final_state.get("appointment_created", False)
            db_verification["details"] = "Checkpoint-only (asyncpg not available)"
        except Exception as e:
            db_verification["found"] = False
            db_verification["details"] = f"DB error: {str(e)[:200]}"
    else:
        # Even if not "completed", check DB count
        db_verification["details"] = f"outcome={outcome}, DB not queried for appointment"

    try:
        await pubsub.unsubscribe(RESPONSE_CHANNEL)
        await pubsub.aclose()
    except Exception:
        pass
    await r.aclose()
    await r_binary.aclose()

    total_ms = int((datetime.now(UTC) - run_start).total_seconds() * 1000)

    milestones_hit = list(dict.fromkeys(
        t["milestone_reached"] for t in turns_result if t.get("milestone_reached")
    ))

    bug_002_present = any(b.get("category") == "BUG-002" for b in all_bugs)
    new_reg1_bug = any(b.get("category") == "NEW-REG-1" for b in all_bugs)
    new_b_loop = any(b.get("category") == "NEW-B-LOOP" for b in all_bugs)

    fixes = {
        "NEW-C (friday-no-loop)": "PASS" if "slot_resolved" in milestones_hit else "N/A",
        "NEW-REG-1 (service_id-loop-fixed)": (
            "FAIL" if new_reg1_bug else
            "PASS" if "service_resolved" in milestones_hit else "N/A"
        ),
        "BUG-001 (book-on-confirm)": (
            "PASS" if db_verification.get("found") else
            "FAIL" if outcome == "completed" else "N/A"
        ),
        "BUG-002 (no-action-narration)": "FAIL" if bug_002_present else "PASS",
        "NEW-B (addon-implicit-decline)": (
            "FAIL" if new_b_loop else
            "PASS" if "addons_handled" in milestones_hit else "N/A"
        ),
    }

    result = {
        "flow_id": FLOW_ID,
        "persona_id": PERSONA_ID,
        "conversation_id": conversation_id,
        "commit_tested": "31deed9",
        "outcome": outcome,
        "milestone_reached": current_milestone,
        "milestones_hit": milestones_hit,
        "total_turns": len(turns_result),
        "total_duration_ms": total_ms,
        "termination_reason": termination_reason,
        "appointment_in_db": db_verification.get("found", False),
        "db_count_last_hour": db_count,
        "db_verification": db_verification,
        "final_state": final_state,
        "bugs_observed": all_bugs,
        "bugs_summary": f"{len(all_bugs)} bugs" if all_bugs else "none",
        "fixes_validation": fixes,
        "turns": turns_result,
    }

    overall_pass = (
        outcome == "completed"
        and db_verification.get("found", False)
        and not bug_002_present
        and not new_reg1_bug
    )

    print(f"\n{'='*70}")
    print("RESULT SUMMARY")
    print(f"  outcome:            {outcome}")
    print(f"  milestone:          {current_milestone}")
    print(f"  milestones_hit:     {milestones_hit}")
    print(f"  turns:              {len(turns_result)}")
    print(f"  appointment_in_db:  {result['appointment_in_db']}")
    print(f"  db_count_1h:        {db_count}")
    print(f"  bugs:               {result['bugs_summary']}")
    print("\n  FIXES VALIDATION:")
    for k, v in fixes.items():
        icon = "✅" if v == "PASS" else ("❌" if v == "FAIL" else "ℹ️")
        print(f"    {icon} {k}: {v}")
    print(f"\n  OVERALL: {'✅ PASS' if overall_pass else '❌ FAIL'}")
    print(f"{'='*70}\n")

    return result


def main() -> int:
    result = asyncio.run(run_qa())

    if "error" in result:
        print(f"❌ FATAL: {result['error']}")
        return 1

    print("\n── TURN TRACE ──")
    for t in result.get("turns", []):
        status = "⏱" if t.get("timed_out") else "✅"
        m = (t.get("milestone_reached") or "—")[:25]
        preview = (t.get("agent_response") or "")[:80]
        print(f"  T{t['turn_number']:02d} {status} [{m:25s}] {preview}...")

    output_path = "/home/pcabeza/Proyectos/atrevete-bot/tests/e2e/qa_r4_indecision_result.json"
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\nTrace saved to: {output_path}")

    return 0 if result["outcome"] == "completed" and result["appointment_in_db"] else 1


if __name__ == "__main__":
    sys.exit(main())
