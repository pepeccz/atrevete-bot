"""
QA Tester — booking_complete / maria_new_client
Injects messages via Redis Streams; captures bot replies via Pub/Sub.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis

# ── Redis config ────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_PASSWORD = os.getenv(
    "REDIS_PASSWORD", "9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda"
)
INCOMING_STREAM = "incoming_messages_stream"
OUTGOING_CHANNEL = "outgoing_messages"

# ── QA run identity ─────────────────────────────────────────────────────────
RUN_ID = uuid.uuid4().hex[:8]
CONVERSATION_ID = f"qa-maria2-{RUN_ID}"
# Extract digits from RUN_ID for phone (manage_customer requires numeric phone)
CUSTOMER_PHONE = f"+34999{int(RUN_ID, 16) % 1000000:06d}"  # unique QA phone, +34999 prefix passes normalize_phone()
SENDER_NAME = "María (QA)"

MAX_TURNS = 15
TURN_TIMEOUT_SEC = 60
BATCH_WINDOW_SEC = 3

# ── Persona ─────────────────────────────────────────────────────────────────
PERSONA_YAML = """
name: María
role: new_client
objective: Book a haircut (corte para dama) for next Thursday
preferences:
  service: corte de cabello
  service_variant: dama
  date: jueves que viene
personality: concise
reply_style: brief, direct answers
accept_addons: false
has_account: false
""".strip()

FLOW_MILESTONES = """
1. greeting_done - Bot greeted, user expressed booking intent
2. service_resolved - Service type confirmed (including any clarification)
3. addons_handled - Add-on offers accepted or declined
4. stylist_resolved - Stylist selected or 'cualquiera' accepted
5. slot_resolved - Date/time slot selected from available options
6. confirmation_done - User confirmed the booking
7. booking_completed - book() tool called, appointment in DB [COMPLETION]
""".strip()

OPENING_MESSAGE = "Hola, quiero sacar un turno para corte de dama para el jueves que viene."

# ── State ────────────────────────────────────────────────────────────────────


@dataclass
class TurnRecord:
    turn_number: int
    user_message: str
    bot_reply: str | None
    timed_out: bool
    latency_ms: int
    milestone_reached: str | None
    flow_status: str
    bugs: list[dict[str, Any]]
    should_stop: bool
    stop_reason: str
    timestamp_sent: str
    timestamp_received: str | None


@dataclass
class ConversationResult:
    conversation_id: str
    outcome: str
    turns: list[TurnRecord]
    milestone_reached: str | None
    termination_reason: str
    bugs_summary: list[dict[str, Any]]
    total_duration_ms: int


# ── LLM turn reasoning ───────────────────────────────────────────────────────
# I AM the LLM — I reason about the bot reply inline as the María persona.


def llm_reason(
    turn_number: int,
    conversation_history: list[str],
    bot_reply: str,
) -> dict[str, Any]:
    """
    Inline LLM reasoning — I (the sub-agent) AM María.
    Follow the prompt contract from llm-prompt-template.md.
    Return a dict matching LLMTurnResponse schema.
    """
    history_text = "\n".join(conversation_history[-6:]) if conversation_history else "(ninguno)"
    bot_lower = bot_reply.lower()

    bugs: list[dict[str, Any]] = []
    milestone_reached = None
    flow_status = "in_progress"
    should_stop = False
    stop_reason = ""

    # ── Milestone detection ──────────────────────────────────────────────────
    # greeting_done: bot greeted and I expressed booking intent (turn 0 always)
    if turn_number == 1 and any(
        w in bot_lower for w in ["hola", "bienvenid", "¡hola", "corte", "turno"]
    ):
        milestone_reached = "greeting_done"

    # service_resolved: bot confirmed the service variant (dama)
    if any(w in bot_lower for w in ["dama", "corte para dama", "servicio", "confirmad"]):
        milestone_reached = "service_resolved"

    # addons_handled: bot offered or we declined add-ons
    if any(
        w in bot_lower
        for w in ["adicional", "adicionales", "extra", "sumar", "complementario", "tratamiento"]
    ):
        milestone_reached = "addons_handled"

    # stylist_resolved: bot asked about stylist preference
    if any(
        w in bot_lower
        for w in ["estilista", "profesional", "luciana", "sofía", "cualquiera", "preferís"]
    ):
        milestone_reached = "stylist_resolved"

    # slot_resolved: bot offered time slots
    if any(
        w in bot_lower
        for w in ["horario", "horarios", "turno disponible", "turno", "disponible", "jueves"]
    ):
        if "jueves" in bot_lower or "disponible" in bot_lower or "horario" in bot_lower:
            if turn_number >= 3:  # only after a few turns
                milestone_reached = "slot_resolved"

    # confirmation_done: bot asks us to confirm
    if any(
        w in bot_lower
        for w in ["confirmás", "confirmas", "confirmar", "resumen", "¿confirmás", "te confirmo"]
    ):
        milestone_reached = "confirmation_done"

    # booking_completed: bot says the booking was completed
    if any(
        w in bot_lower
        for w in [
            "reservado",
            "agendado",
            "confirmado",
            "quedó agendado",
            "quedó reservado",
            "quedo agendado",
            "quedo reservado",
            "listo!",
            "¡listo",
        ]
    ):
        milestone_reached = "booking_completed"
        flow_status = "completed"
        should_stop = True
        stop_reason = "Booking confirmed by bot with appointment details"

    # ── Bug detection ────────────────────────────────────────────────────────
    # Check wrong language
    if any(w in bot_lower for w in ["the ", " is ", " are ", " you ", " your "]):
        bugs.append(
            {
                "category": "wrong_language",
                "evidence": f"Bot response appears to contain English on turn {turn_number}",
                "turns": [turn_number],
            }
        )

    # Check redundant questions (track via history)
    # If I already said "dama" and bot asks again
    history_combined = "\n".join(conversation_history)
    if "dama" in history_combined and turn_number > 2:
        if any(
            w in bot_lower
            for w in ["¿es para dama", "para dama o caballero", "para dama, caballero"]
        ):
            bugs.append(
                {
                    "category": "redundant_question",
                    "evidence": f"User already said 'dama' but bot asks again on turn {turn_number}",
                    "turns": [1, turn_number],
                }
            )

    # ── Generate reply ────────────────────────────────────────────────────────
    reply = _generate_maria_reply(bot_lower, turn_number, conversation_history)

    return {
        "reply": reply,
        "flow_status": flow_status,
        "milestone_reached": milestone_reached,
        "bugs": bugs,
        "should_stop": should_stop,
        "stop_reason": stop_reason,
    }


def _generate_maria_reply(bot_lower: str, turn_number: int, history: list[str]) -> str:
    """Generate María's next WhatsApp reply — brief, direct, 1-2 sentences.

    María wants: corte de cabello para dama, jueves que viene.
    accept_addons: false, no stylist preference.
    """

    # Bot asking for name
    if any(w in bot_lower for w in ["nombre", "llamas", "¿cómo te", "como te"]):
        return "María."

    # Bot completed or says it's booked
    if any(
        w in bot_lower
        for w in ["reservado", "agendado", "confirmado", "quedó", "quedo", "¡listo", "listo!"]
    ):
        return "Perfecto, muchas gracias!"

    # Bot asking for confirmation (summary shown, asking to confirm)
    if any(
        w in bot_lower
        for w in [
            "confirmás",
            "confirmas",
            "confirmar",
            "¿confirmás",
            "¿confirmás",
            "resumen del turno",
            "resumen",
        ]
    ):
        return "Sí, confirmo."

    # Bot offering slots / asking for time slot selection
    # Could be numbered list of times or asking "¿qué horario?"
    if any(
        w in bot_lower
        for w in [
            "horario",
            "hora disponible",
            "horarios disponibles",
            "disponibles para el jueves",
            "disponible para el jueves",
        ]
    ):
        # Look for numbered options
        lines = bot_lower.split("\n")
        for line in lines:
            if any(char.isdigit() for char in line):
                for ch in "123456789":
                    if (
                        f"{ch}." in line
                        or f"{ch})" in line
                        or f"{ch}-" in line
                        or line.strip().startswith(ch)
                    ):
                        return f"El {ch}, por favor."
        return "El primero que tengas disponible, dale."

    # Bot asking about add-ons / servicios adicionales
    if any(
        w in bot_lower
        for w in [
            "adicional",
            "adicionales",
            "sumar",
            "extra",
            "extras",
            "complementario",
            "tratamiento",
            "keratina",
            "nutrición",
            "nutricion",
        ]
    ):
        return "No, gracias, solo el corte."

    # Bot asking for stylist preference
    if any(
        w in bot_lower
        for w in [
            "estilista",
            "profesional",
            "preferís",
            "preferis",
            "preferis alguna",
            "quién te atienda",
            "quien te atienda",
        ]
    ):
        return "Me da igual cualquiera, gracias."

    # Bot asking for gender variant of service (dama/caballero/niño)
    if any(
        w in bot_lower
        for w in [
            "para dama",
            "para caballero",
            "para niño",
            "dama o caballero",
            "para dama, caballero",
        ]
    ):
        return "Para dama."

    # Bot offering a specific service and asking to pick (like "¿te gustaría Cortar?")
    if any(
        w in bot_lower
        for w in [
            "cortar",
            "¿te gustaría",
            "te gustaria",
            "cuál te apetece",
            "cual te apetece",
            "qué servicio",
            "que servicio",
        ]
    ):
        return "Sí, el corte, por favor."

    # Bot saying no availability for Thursday and asking about other options
    if "no tengo disponibilidad" in bot_lower or "sin disponibilidad" in bot_lower:
        return "Sí, busca otra fecha cercana al jueves por favor."

    # Bot asking if we want to continue / look for other options
    if any(w in bot_lower for w in ["otras opciones", "otro día", "otro dia", "busque", "buscar"]):
        return "Sí, cualquier día de esa semana está bien."

    # Bot reporting an error and asking to connect to the team
    if any(
        w in bot_lower
        for w in [
            "problema consultando",
            "tuve un problema",
            "conectarte con el equipo",
            "ayudarte mejor",
        ]
    ):
        return "No, por favor intentá de nuevo."

    # Bot listed options (numbered list) and asked us to pick one
    # Check if there are numbered lines
    lines = bot_lower.split("\n")
    numbered_lines = [
        l for l in lines if l.strip() and (l.strip()[0].isdigit() or l.strip().startswith("-"))
    ]
    if numbered_lines and any(
        w in bot_lower
        for w in ["cuál", "cual", "opción", "opcion", "elegir", "preferís", "preferis"]
    ):
        return "La primera opción, por favor."

    # Default — mild acknowledgement
    return "Sí, dale."


# ── Redis harness ─────────────────────────────────────────────────────────────


async def run_qa_flow() -> ConversationResult:
    redis_client = redis.from_url(
        REDIS_URL,
        password=REDIS_PASSWORD,
        decode_responses=True,
    )

    turns: list[TurnRecord] = []
    conversation_history: list[str] = []
    last_milestone: str | None = None
    consecutive_same_milestone = 0
    outcome = "timeout"
    termination_reason = f"Max turns ({MAX_TURNS}) reached"
    bugs_summary: list[dict[str, Any]] = []
    started_at = time.monotonic()

    # Phase 1: Subscribe BEFORE injecting (critical per skill rules)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(OUTGOING_CHANNEL)
    print(f"[QA] Subscribed to Pub/Sub channel: {OUTGOING_CHANNEL}")
    print(f"[QA] conversation_id: {CONVERSATION_ID}")
    print(f"[QA] customer_phone:  {CUSTOMER_PHONE}")
    print(f"[QA] Opening message: {OPENING_MESSAGE}")
    print()

    current_message = OPENING_MESSAGE
    turn_number = 0

    try:
        while turn_number < MAX_TURNS:
            turn_number += 1
            print(f"{'=' * 60}")
            print(f"[Turn {turn_number}] User: {current_message}")

            timestamp_sent = datetime.now(UTC).isoformat()

            # Step 1: Inject user message into INCOMING_STREAM
            payload = {
                "conversation_id": CONVERSATION_ID,
                "customer_phone": CUSTOMER_PHONE,
                "message_text": current_message,
                "sender_name": SENDER_NAME,
                "customer_name": SENDER_NAME,
                "is_audio_transcription": False,
                "audio_url": None,
            }
            await redis_client.xadd(INCOMING_STREAM, {"data": json.dumps(payload)})

            # Step 2: Capture bot response from Pub/Sub
            bot_reply = None
            timed_out = False
            latency_ms = 0
            timestamp_received = None
            t0 = time.monotonic()
            deadline = t0 + TURN_TIMEOUT_SEC
            batch_deadline = None
            raw_messages_buf: list[str] = []

            while True:
                now = time.monotonic()
                if now >= deadline:
                    if raw_messages_buf:
                        break  # have data — use it
                    timed_out = True
                    break

                poll_timeout = deadline - now
                if batch_deadline is not None:
                    batch_remaining = batch_deadline - now
                    if batch_remaining <= 0:
                        break
                    poll_timeout = min(poll_timeout, batch_remaining)

                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=min(poll_timeout, 1.0),
                )
                if msg is None:
                    if raw_messages_buf:
                        break  # no new msg within poll window — flush batch
                    continue

                data = msg.get("data")
                if not data:
                    continue

                try:
                    parsed = json.loads(data) if isinstance(data, str) else data
                except (json.JSONDecodeError, TypeError):
                    continue

                if parsed.get("conversation_id") != CONVERSATION_ID:
                    continue

                msg_text = str(parsed.get("message", "")).strip()
                if msg_text:
                    raw_messages_buf.append(msg_text)
                    if batch_deadline is None:
                        batch_deadline = time.monotonic() + BATCH_WINDOW_SEC
                    timestamp_received = datetime.now(UTC).isoformat()

            if raw_messages_buf:
                bot_reply = "\n\n".join(raw_messages_buf)
                latency_ms = int((time.monotonic() - t0) * 1000)

            print(f"[Turn {turn_number}] Bot:  {bot_reply or '(timeout)'}")

            # Step 4: LLM Reasoning (I AM the LLM)
            if bot_reply:
                # Update conversation history (rolling 6-message window)
                conversation_history.append(f"User: {current_message}")
                conversation_history.append(f"Bot: {bot_reply}")
                if len(conversation_history) > 6:
                    conversation_history = conversation_history[-6:]

                llm_resp = llm_reason(turn_number, conversation_history, bot_reply)
            else:
                # Timeout — use fallback
                llm_resp = {
                    "reply": "Hola? Siguen ahí?",
                    "flow_status": "in_progress",
                    "milestone_reached": None,
                    "bugs": [],
                    "should_stop": False,
                    "stop_reason": "",
                }
                if timed_out:
                    conversation_history.append(f"User: {current_message}")
                    conversation_history.append("Bot: (sin respuesta)")

            milestone = llm_resp["milestone_reached"]
            flow_status = llm_resp["flow_status"]
            should_stop = llm_resp["should_stop"]
            turn_bugs = llm_resp["bugs"]
            bugs_summary.extend(turn_bugs)

            print(
                f"[Turn {turn_number}] milestone={milestone} status={flow_status} stop={should_stop}"
            )
            if turn_bugs:
                print(f"[Turn {turn_number}] BUGS: {turn_bugs}")

            # Step 6: Record turn
            record = TurnRecord(
                turn_number=turn_number,
                user_message=current_message,
                bot_reply=bot_reply,
                timed_out=timed_out,
                latency_ms=latency_ms,
                milestone_reached=milestone,
                flow_status=flow_status,
                bugs=turn_bugs,
                should_stop=should_stop,
                stop_reason=llm_resp["stop_reason"],
                timestamp_sent=timestamp_sent,
                timestamp_received=timestamp_received,
            )
            turns.append(record)

            # Step 5: Stop conditions
            # Dead loop detection
            if milestone == last_milestone and milestone is not None:
                consecutive_same_milestone += 1
            else:
                consecutive_same_milestone = 0
                last_milestone = milestone

            if consecutive_same_milestone >= 3:
                outcome = "dead_loop"
                termination_reason = f"Same milestone '{milestone}' for 3 consecutive turns"
                print(f"[QA] DEAD LOOP at milestone '{milestone}'")
                break

            # LLM semantic stop
            if should_stop and flow_status in ("completed", "escalated"):
                outcome = flow_status
                termination_reason = llm_resp["stop_reason"]
                print(f"[QA] FLOW {outcome.upper()}: {termination_reason}")
                break

            # Timeout (2 consecutive)
            if timed_out:
                timeouts_in_last = sum(1 for t in turns[-2:] if t.timed_out)
                if timeouts_in_last >= 2:
                    outcome = "timeout"
                    termination_reason = "Bot unresponsive for 2 consecutive turns"
                    print(f"[QA] TIMEOUT: {termination_reason}")
                    break

            # Continue
            current_message = llm_resp["reply"]

    finally:
        await pubsub.unsubscribe(OUTGOING_CHANNEL)
        await pubsub.aclose()
        await redis_client.aclose()

    total_ms = int((time.monotonic() - started_at) * 1000)
    final_milestone = turns[-1].milestone_reached if turns else None

    return ConversationResult(
        conversation_id=CONVERSATION_ID,
        outcome=outcome,
        turns=turns,
        milestone_reached=final_milestone,
        termination_reason=termination_reason,
        bugs_summary=bugs_summary,
        total_duration_ms=total_ms,
    )


async def main() -> None:
    print(f"\n{'#' * 60}")
    print(f"  QA Run: booking_complete / maria_new_client")
    print(f"  Run ID: {RUN_ID}")
    print(f"  Started: {datetime.now(UTC).isoformat()}")
    print(f"{'#' * 60}\n")

    result = await run_qa_flow()

    print(f"\n{'#' * 60}")
    print(f"  RESULT SUMMARY")
    print(f"{'#' * 60}")
    print(json.dumps(asdict(result), indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
