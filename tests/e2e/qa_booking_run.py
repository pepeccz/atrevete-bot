"""
QA Booking Flow Runner — María García persona (booking_complete flow).
Runs a complete booking conversation against the live bot via Redis.
"""

import asyncio
import json
import re
import uuid
from datetime import UTC, datetime

import redis.asyncio as redis

# ── Config ──────────────────────────────────────────────────────────────────
REDIS_URL = (
    "redis://:9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda@localhost:6379/0"
)
INCOMING_STREAM = "incoming_messages_stream"
OUTGOING_CHANNEL = "outgoing_messages"

CONVERSATION_ID = f"qa-booking-maria-{uuid.uuid4().hex[:8]}"
CUSTOMER_PHONE = "+34600222111"
SENDER_NAME = "María García"

TIMEOUT_PER_TURN = 60.0  # seconds to wait for bot reply
BATCH_WINDOW = 3.0  # seconds to collect grouped messages

_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
_SLOT_TERMS = ("hueco", "huecos", "horario", "horarios", "disponible", "disponibles")
_NAME_TERMS = ("nombre y primer apellido", "nombre completo", "tu nombre", "me dices tu nombre")
_NOTES_TERMS = ("algo que tengamos que tener en cuenta", "alguna nota", "alguna observación")
_CONSENT_TERMS = (
    "¿quieres que mire",
    "¿te viene bien que mire",
    "¿prefieres que busque",
    "si quieres, puedo mirar",
)
_ALTERNATIVE_TERMS = (
    "estas alternativas",
    "te propongo",
    "puedo ofrecerte",
    "tengo estas alternativas",
)


def _contains_slot_offer(message: str) -> bool:
    normalized = message.lower()
    return bool(_TIME_RE.search(message)) and any(term in normalized for term in _SLOT_TERMS)


def _asks_for_name(message: str) -> bool:
    normalized = message.lower()
    return any(term in normalized for term in _NAME_TERMS)


def _asks_for_notes(message: str) -> bool:
    normalized = message.lower()
    return any(term in normalized for term in _NOTES_TERMS)


def _asks_for_broadening_consent(message: str) -> bool:
    normalized = message.lower()
    return any(term in normalized for term in _CONSENT_TERMS)


def _offers_alternative_options(message: str) -> bool:
    normalized = message.lower()
    return _contains_slot_offer(message) or (
        bool(_TIME_RE.search(message)) and any(term in normalized for term in _ALTERNATIVE_TERMS)
    )


def analyze_booking_trace(trace: list[dict]) -> dict[str, int | bool | None]:
    first_slot_turn = next(
        (turn["turn"] for turn in trace if turn.get("bot") and _contains_slot_offer(turn["bot"])),
        None,
    )
    first_name_or_notes_turn = next(
        (
            turn["turn"]
            for turn in trace
            if turn.get("bot") and (_asks_for_name(turn["bot"]) or _asks_for_notes(turn["bot"]))
        ),
        None,
    )
    return {
        "first_slot_turn": first_slot_turn,
        "first_name_or_notes_turn": first_name_or_notes_turn,
        "slots_before_name_or_notes": first_slot_turn is not None
        and (first_name_or_notes_turn is None or first_slot_turn < first_name_or_notes_turn),
    }


def analyze_empty_day_trace(
    trace: list[dict], *, requires_consent: bool
) -> dict[str, int | bool | None]:
    first_consent_turn = next(
        (
            turn["turn"]
            for turn in trace
            if turn.get("bot") and _asks_for_broadening_consent(turn["bot"])
        ),
        None,
    )
    first_alternative_turn = next(
        (
            turn["turn"]
            for turn in trace
            if turn.get("bot") and _offers_alternative_options(turn["bot"])
        ),
        None,
    )
    if requires_consent:
        passes = first_consent_turn is not None and (
            first_alternative_turn is None or first_consent_turn < first_alternative_turn
        )
    else:
        passes = first_alternative_turn is not None and (
            first_consent_turn is None or first_alternative_turn <= first_consent_turn
        )
    return {
        "first_consent_turn": first_consent_turn,
        "first_alternative_turn": first_alternative_turn,
        "passes": passes,
    }


# ── Redis helpers ────────────────────────────────────────────────────────────


async def inject_message(r: redis.Redis, message_text: str) -> str:
    payload = {
        "conversation_id": CONVERSATION_ID,
        "customer_phone": CUSTOMER_PHONE,
        "message_text": message_text,
        "sender_name": SENDER_NAME,
        "customer_name": SENDER_NAME,
        "is_audio_transcription": False,
        "audio_url": None,
    }
    msg_id = await r.xadd(INCOMING_STREAM, {"data": json.dumps(payload)})
    return msg_id


async def capture_response(pubsub, timeout: float = TIMEOUT_PER_TURN) -> dict:
    """
    Collect all Pub/Sub messages for this conversation_id within the batch window.
    Returns the concatenated bot reply.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    batch_deadline = None
    raw_payloads = []
    first_received = None

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            if raw_payloads:
                break
            return {"message": "", "timed_out": True, "raw_payloads": []}

        poll_timeout = remaining
        if batch_deadline is not None:
            batch_remaining = batch_deadline - loop.time()
            if batch_remaining <= 0:
                break
            poll_timeout = min(poll_timeout, batch_remaining)

        raw = await pubsub.get_message(ignore_subscribe_messages=True, timeout=poll_timeout)
        if raw is None:
            if raw_payloads:
                break
            continue

        data = raw.get("data")
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        try:
            payload = json.loads(data)
        except (TypeError, json.JSONDecodeError):
            continue

        if payload.get("conversation_id") != CONVERSATION_ID:
            continue

        raw_payloads.append(payload)
        if first_received is None:
            first_received = loop.time()
            batch_deadline = first_received + BATCH_WINDOW

    messages = [str(p.get("message", "")).strip() for p in raw_payloads if p.get("message")]
    combined = "\n\n".join(m for m in messages if m)
    return {
        "message": combined,
        "timed_out": False,
        "raw_payloads": raw_payloads,
    }


# ── Main turn loop ───────────────────────────────────────────────────────────

TURNS = [
    "Hola! Quiero un corte de dama para el jueves que viene.",
    None,  # determined by bot response
    None,
    None,
    None,
    None,
    None,
]


# LLM reasoning (we ARE the LLM) — inline decision logic per turn
def decide_next_reply(turn_number: int, bot_reply: str) -> tuple[str, str, bool]:
    """
    Simulate LLM persona reasoning.
    Returns: (reply, milestone_reached, should_stop)
    """
    normalized = bot_reply.lower()

    # ── Turn 1 response: bot should list services or ask which service ──────
    if turn_number == 1:
        # Bot likely listed services or confirmed "corte de dama"
        # Look for numbered options → pick "1" or "el primero"
        if any(c.isdigit() for c in bot_reply) and (
            "." in bot_reply or ")" in bot_reply or "-" in bot_reply
        ):
            return "1", "service_resolved", False
        # Bot may have confirmed directly
        if "cortar" in normalized or "corte" in normalized:
            return "El primero, Cortar.", "service_resolved", False
        return "El primero.", "service_resolved", False

    # ── Turn 2 response: bot confirmed service, may offer add-ons ─────────────
    if turn_number == 2:
        # Bot offered add-ons (numbered list or keywords)
        if any(
            kw in normalized
            for kw in [
                "complementario",
                "adicional",
                "extra",
                "sumar",
                "agregar",
                "peinado",
                "barro",
                "añadir",
            ]
        ):
            return "No, gracias.", "addons_handled", False
        # Bot may be asking for stylist already
        if "estilista" in normalized or "profesional" in normalized or "preferis" in normalized:
            return "La primera estilista disponible.", "stylist_resolved", False
        # Already at confirmation or slot?
        if "confirmar" in normalized or "horario" in normalized:
            return "Sí.", "slot_resolved", False
        return "No, gracias.", "addons_handled", False

    # ── Turn 3 response: bot should ask for stylist or show slot ─────────────
    if turn_number == 3:
        if "estilista" in normalized or "profesional" in normalized or "preferis" in normalized:
            return "La primera estilista disponible.", "stylist_resolved", False
        # Numbered list → pick 1
        if any(c.isdigit() for c in bot_reply):
            return "1", "stylist_resolved", False
        # Slot offered?
        if "horario" in normalized or "turno" in normalized or "jueves" in normalized:
            return "El primer horario disponible.", "slot_resolved", False
        return "La primera disponible.", "stylist_resolved", False

    # ── Turn 4 response: bot should show available slots ─────────────────────
    if turn_number == 4:
        if (
            "horario" in normalized
            or "turno" in normalized
            or "jueves" in normalized
            or "disponible" in normalized
            or "marzo" in normalized
            or "lunes" in normalized
            or "martes" in normalized
        ):
            # Use explicit slot selection text instead of just "1"
            return "El martes 24 de marzo a las 10:00, por favor.", "slot_resolved", False
        if any(c.isdigit() for c in bot_reply):
            return "El primero, martes 24 a las 10.", "slot_resolved", False
        if "nombre" in normalized or "llamás" in normalized or "llamas" in normalized:
            return "María García", "slot_resolved", False
        return "El primer horario disponible.", "slot_resolved", False

    # ── Turn 5+ response: bot confirmed slot, may ask for notes or name ───────
    if turn_number >= 5:
        # Booking already confirmed!
        if any(
            kw in normalized
            for kw in ["ha sido confirmada", "tu cita ha sido", "te esperamos", "quedaste"]
        ):
            return "Muchas gracias! Nos vemos el martes.", "booking_completed", True
        # Bot asking about notes/special preferences or "algo más"
        if any(
            kw in normalized
            for kw in [
                "algo más",
                "nota",
                "preferencia",
                "saber",
                "estilista antes",
                "especial",
                "condición",
            ]
        ):
            return "Todo bien, sin notas especiales.", "confirmation_done", False
        # Bot asking for name
        if (
            "nombre" in normalized
            or "llamás" in normalized
            or "llamas" in normalized
            or "cómo te" in normalized
        ):
            return "María García", "confirmation_done", False
        # Bot asking for confirmation
        if "confirmar" in normalized or "confirmas" in normalized or "confirmás" in normalized:
            return "Sí, confirmo.", "confirmation_done", False
        # Bot asking to cancel?
        if "cancelar" in normalized or "cancelás" in normalized:
            return "No, no quiero cancelar.", "confirmation_done", False
        # Slot selection still?
        if "horario" in normalized or "jueves" in normalized or "marzo" in normalized:
            return "El martes 24 de marzo a las 10:00.", "slot_resolved", False
        return "Sí, confirmo.", "confirmation_done", False

    # ── Turn 7+ response: booking should be confirmed ─────────────────────────
    if turn_number >= 7:
        if "reservado" in normalized or "agendado" in normalized or "confirmado" in normalized:
            return "Perfecto, muchas gracias!", "booking_completed", True
        if "confirmar" in normalized or "confirmas" in normalized:
            return "Sí, confirmo.", "confirmation_done", False
        if "nombre" in normalized:
            return "María García", "confirmation_done", False
        return "Sí.", "in_progress", False

    return "Sí.", "in_progress", False


async def run_booking_flow():
    print(f"\n{'=' * 60}")
    print("QA BOOKING FLOW — María García")
    print(f"conversation_id: {CONVERSATION_ID}")
    print(f"phone: {CUSTOMER_PHONE}")
    print(f"started: {datetime.now(UTC).isoformat()}")
    print(f"{'=' * 60}\n")

    r = redis.from_url(REDIS_URL, decode_responses=True, max_connections=5)
    pubsub = r.pubsub()

    # ── CRITICAL: Subscribe BEFORE injecting ─────────────────────────────────
    await pubsub.subscribe(OUTGOING_CHANNEL)
    print(f"✅ Subscribed to '{OUTGOING_CHANNEL}'")
    await asyncio.sleep(0.5)  # Brief pause to ensure subscription is active

    trace = []
    bugs = []
    final_bot_message = ""
    booking_created = False
    last_milestone = None
    consecutive_same_milestone = 0
    flow_status = "in_progress"
    slot_offer_seen = False

    opening_message = "Hola! Quiero un corte de dama para el jueves que viene."
    current_message = opening_message
    max_turns = 15

    try:
        for turn_number in range(1, max_turns + 1):
            print(f"\n{'─' * 50}")
            print(f"TURN {turn_number}")
            print(f"[USER] → {current_message}")

            # Step 1: Inject message
            msg_id = await inject_message(r, current_message)
            print(f"  Injected → stream msg id: {msg_id}")

            # Step 2: Capture response (with batch window)
            print(f"  Waiting for bot response (up to {TIMEOUT_PER_TURN}s)...")
            t0 = asyncio.get_event_loop().time()
            response = await capture_response(pubsub)
            elapsed = asyncio.get_event_loop().time() - t0

            if response["timed_out"] or not response["message"]:
                print(f"  ⚠️  TIMEOUT — no response after {elapsed:.1f}s")
                trace.append(
                    {
                        "turn": turn_number,
                        "user": current_message,
                        "bot": None,
                        "milestone": None,
                        "timed_out": True,
                        "latency_ms": int(elapsed * 1000),
                    }
                )
                if turn_number > 1:
                    # Send follow-up
                    current_message = "Hola? Siguen ahi?"
                    continue
                break

            bot_reply = response["message"]
            latency_ms = int(elapsed * 1000)
            print(f"  [{latency_ms}ms] [BOT] → {bot_reply}")

            final_bot_message = bot_reply

            # Step 3 (LLM reasoning): decide next reply & milestone
            next_reply, milestone, should_stop = decide_next_reply(turn_number, bot_reply)
            print(f"  milestone_reached: {milestone} | should_stop: {should_stop}")

            # Dead loop detection
            if milestone == last_milestone:
                consecutive_same_milestone += 1
            else:
                consecutive_same_milestone = 0
                last_milestone = milestone

            if consecutive_same_milestone >= 3:
                print(f"  ⚠️  DEAD LOOP detected at milestone '{milestone}' — terminating")
                flow_status = "stuck"
                break

            # Bug detection
            turn_bugs = []
            normalized_bot = bot_reply.lower()
            # Check for English language
            if any(
                word in normalized_bot
                for word in ["hello", "please select", "thank you", "available"]
            ):
                turn_bugs.append(
                    {
                        "category": "wrong_language",
                        "evidence": f"Bot replied with English text: '{bot_reply[:80]}'",
                        "turns": [turn_number],
                    }
                )
            # Check for context loss (asking for audience/gender after already stated)
            if turn_number > 1 and (
                "dama o caballero" in normalized_bot or "caballero o dama" in normalized_bot
            ):
                turn_bugs.append(
                    {
                        "category": "redundant_question",
                        "evidence": f"Bot asked dama/caballero on turn {turn_number} after user already said 'dama' on turn 1",
                        "turns": [1, turn_number],
                    }
                )

            bugs.extend(turn_bugs)
            if turn_bugs:
                print(f"  🐛 BUGS FOUND: {[b['category'] for b in turn_bugs]}")

            if _contains_slot_offer(bot_reply):
                slot_offer_seen = True
            elif not slot_offer_seen and (_asks_for_name(bot_reply) or _asks_for_notes(bot_reply)):
                late_slot_bug = {
                    "category": "late_slot_reveal",
                    "evidence": "Bot asked for name/notes before showing concrete exact-day slots.",
                    "turns": [turn_number],
                }
                turn_bugs.append(late_slot_bug)
                bugs.append(late_slot_bug)

            trace.append(
                {
                    "turn": turn_number,
                    "user": current_message,
                    "bot": bot_reply,
                    "milestone": milestone,
                    "timed_out": False,
                    "latency_ms": latency_ms,
                    "bugs": turn_bugs,
                }
            )

            # Check for booking completion — after turn 3 (past add-ons stage)
            # Look for confirmation messages containing date + stylist
            is_booking_confirmed = turn_number >= 4 and any(
                kw in normalized_bot
                for kw in [
                    "reservado",
                    "quedo agendado",
                    "queda agendado",
                    "turno confirmado",
                    "reserva confirmada",
                    "cita confirmada",
                    "te esperamos",
                    "quedaste",
                    "ha sido confirmada",
                    "tu cita ha sido",
                ]
            )
            if is_booking_confirmed:
                print("\n  🎉 BOOKING CONFIRMED in bot message!")
                booking_created = True
                flow_status = "completed"
                should_stop = True

            if should_stop:
                if milestone == "booking_completed":
                    booking_created = True
                    flow_status = "completed"
                break

            current_message = next_reply

        # ── Post-loop summary ──────────────────────────────────────────────
        if flow_status != "completed" and booking_created:
            flow_status = "completed"
        elif flow_status not in ("completed", "stuck"):
            flow_status = "timeout" if turn_number >= max_turns else "partial"

    finally:
        await pubsub.unsubscribe(OUTGOING_CHANNEL)
        await pubsub.aclose()
        await r.aclose()

    return {
        "conversation_id": CONVERSATION_ID,
        "flow_status": flow_status,
        "booking_created": booking_created,
        "turns_executed": turn_number,
        "final_bot_message": final_bot_message,
        "trace": trace,
        "bugs": bugs,
        "last_milestone": last_milestone,
        "booking_ux_checks": analyze_booking_trace(trace),
    }


async def main():
    result = await run_booking_flow()

    print(f"\n\n{'=' * 60}")
    print("QA RUN COMPLETE")
    print(f"{'=' * 60}")
    print(f"Flow Status:      {result['flow_status']}")
    print(f"Booking Created:  {'YES ✅' if result['booking_created'] else 'NO ❌'}")
    print(f"Turns Executed:   {result['turns_executed']}")
    print(f"Last Milestone:   {result['last_milestone']}")
    print(f"Bugs Found:       {len(result['bugs'])}")

    if result["bugs"]:
        print("\nBUGS:")
        for bug in result["bugs"]:
            print(f"  [{bug['category']}] {bug['evidence']}")

    print("\nFINAL BOT MESSAGE:")
    print(f"  {result['final_bot_message']}")

    print("\nCONVERSATION TRACE:")
    for turn in result["trace"]:
        status = "⏱️" if turn.get("timed_out") else "✅"
        print(f"\n  Turn {turn['turn']} {status} [{turn.get('latency_ms', 0)}ms]")
        print(f"    USER: {turn['user']}")
        print(f"    BOT:  {turn.get('bot', '<no response>')}")
        if turn.get("milestone"):
            print(f"    MILESTONE: {turn['milestone']}")
        if turn.get("bugs"):
            print(f"    BUGS: {[b['category'] for b in turn['bugs']]}")

    print(f"\n{'=' * 60}")
    return result


if __name__ == "__main__":
    asyncio.run(main())
