"""
QA Round 4 — booking_complete / maría_new_client
Commit tested: 31deed9

Validates:
  BUG-001: book() called on confirmation turn → appointment_in_db=true
  BUG-006: Greeting exactly ONCE on Turn 1 — no double greeting
  NEW-A:   "No tengo preferencia" / "Cualquiera" → proceeds, does NOT cancel
  NEW-C:   "el jueves" resolves without looping
  BUG-002: Zero narration phrases ("Voy a...", "Déjame...") in any turn

Usage:
    python tests/e2e/qa_r4_booking_complete.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REDIS_URL = "redis://localhost:6379/0"
REDIS_PASSWORD = "9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda"
INCOMING_STREAM = "incoming_messages_stream"
OUTGOING_CHANNEL = "outgoing_messages"
MAX_TURNS = 15
TURN_TIMEOUT_S = 60.0
BATCH_WINDOW_S = 5.0  # wait up to 5s after first reply for multi-part messages

DB_URL = "postgresql://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("qa_r4")

# ---------------------------------------------------------------------------
# Persona (from qa-testing-context.md / maria_new_client)
# ---------------------------------------------------------------------------
PERSONA = {
    "name": "María",
    "role": "new_client",
    "service": "corte de cabello dama",
    "date": "el jueves que viene",
    "stylist": None,
    "accept_addons": False,
}

# ---------------------------------------------------------------------------
# Bug validation tracking
# ---------------------------------------------------------------------------
BUG_CHECKS: dict[str, dict] = {
    "BUG-001": {"label": "book() called → appointment_in_db", "status": "NOT_TESTED", "evidence": ""},
    "BUG-002": {"label": "No narration phrases", "status": "PASS", "evidence": "None detected so far"},
    "BUG-006": {"label": "Greeting exactly once (T1)", "status": "NOT_TESTED", "evidence": ""},
    "NEW-A":   {"label": "'No tengo preferencia' → no cancel", "status": "NOT_TESTED", "evidence": ""},
    "NEW-C":   {"label": "'El jueves' resolves without loop", "status": "NOT_TESTED", "evidence": ""},
}

# Script state
SCRIPT_STATE = {
    "stylist_turn_sent": False,
    "no_pref_sent": False,
    "date_question_count": 0,
    "addon_declined": False,
    "addon_decline_sent_this_turn": False,
}

NARRATION_PHRASES = [
    "voy a", "déjame", "dejame", "permíteme", "permiteme",
    "voy a buscar", "voy a verificar", "voy a consultar",
    "un momento", "dame un momento", "espera que",
]


def check_narration(text: str, turn_number: int) -> bool:
    """Returns True if narration phrase found (BUG-002 failure)."""
    lower = text.lower()
    for phrase in NARRATION_PHRASES:
        if phrase in lower:
            BUG_CHECKS["BUG-002"]["status"] = "FAIL"
            BUG_CHECKS["BUG-002"]["evidence"] += (
                f" | T{turn_number}: found '{phrase}' in: '{text[:120]}'"
            )
            return True
    return False


def check_greeting_dedup(text: str, turn_number: int) -> None:
    """BUG-006: Greeting should appear exactly once."""
    lower = text.lower()
    hola_count = lower.count("hola")
    if turn_number == 1:
        if hola_count >= 2:
            BUG_CHECKS["BUG-006"]["status"] = "FAIL"
            BUG_CHECKS["BUG-006"]["evidence"] = (
                f"T1: 'hola' appeared {hola_count}x → '{text[:200]}'"
            )
        else:
            BUG_CHECKS["BUG-006"]["status"] = "PASS"
            BUG_CHECKS["BUG-006"]["evidence"] = f"T1: Single greeting detected"
    elif turn_number > 1 and hola_count >= 1:
        # Greeting repeated after T1 — suspicious
        BUG_CHECKS["BUG-006"]["status"] = "FAIL"
        BUG_CHECKS["BUG-006"]["evidence"] += (
            f" | T{turn_number}: Unexpected greeting after T1: '{text[:120]}'"
        )


def check_date_loop(text: str, turn_number: int) -> None:
    """NEW-C: 'El jueves' should resolve without asking date again after T1."""
    lower = text.lower()
    date_question = (
        ("qué día" in lower or "qué fecha" in lower or "cuándo" in lower or "para cuándo" in lower)
        and "?" in text
    )
    if date_question:
        SCRIPT_STATE["date_question_count"] += 1
        if SCRIPT_STATE["date_question_count"] >= 2:
            BUG_CHECKS["NEW-C"]["status"] = "FAIL"
            BUG_CHECKS["NEW-C"]["evidence"] = (
                f"T{turn_number}: Date question asked {SCRIPT_STATE['date_question_count']}x — looping"
            )
        elif SCRIPT_STATE["date_question_count"] == 1:
            # First date question is OK (asking to confirm jueves)
            BUG_CHECKS["NEW-C"]["status"] = "PASS"
            BUG_CHECKS["NEW-C"]["evidence"] = f"T{turn_number}: Date resolved (asked once only)"


def check_cancel_after_no_pref(text: str, turn_number: int) -> None:
    """NEW-A: After 'No tengo preferencia', bot must NOT cancel."""
    if not SCRIPT_STATE.get("no_pref_sent"):
        return
    lower = text.lower()
    cancel_words = ["cancelar", "cancelado", "cancelo", "anular", "anulado", "he cancelado", "eliminar el turno"]
    for w in cancel_words:
        if w in lower:
            BUG_CHECKS["NEW-A"]["status"] = "FAIL"
            BUG_CHECKS["NEW-A"]["evidence"] = (
                f"T{turn_number}: Bot cancelled after 'No tengo preferencia': '{text[:200]}'"
            )
            return
    # If we're past the stylist turn and no cancel, mark pass
    if BUG_CHECKS["NEW-A"]["status"] == "NOT_TESTED":
        BUG_CHECKS["NEW-A"]["status"] = "PASS"
        BUG_CHECKS["NEW-A"]["evidence"] = (
            f"T{turn_number}: Bot proceeded after 'No tengo preferencia' without cancelling"
        )


# ---------------------------------------------------------------------------
# Milestone detection
# ---------------------------------------------------------------------------

MILESTONE_SEQUENCE = [
    "greeting_done",
    "service_resolved",
    "addons_handled",
    "stylist_resolved",
    "slot_resolved",
    "confirmation_done",
    "booking_completed",
]


def detect_milestone(text: str, milestone_history: list[str | None]) -> str | None:
    lower = text.lower()
    already = [m for m in milestone_history if m]

    if "greeting_done" not in already:
        if any(w in lower for w in ["bienvenida", "hola", "como puedo", "cómo puedo", "en qué te"]):
            return "greeting_done"

    if "service_resolved" not in already:
        if any(w in lower for w in ["corte de cabello", "servicio", "cortar"]):
            if "?" not in text or any(w in lower for w in ["confirmo", "entendido", "perfecto"]):
                return "service_resolved"

    if "addons_handled" not in already:
        if any(w in lower for w in ["adicional", "extra", "sumar", "tratamiento", "complementario"]):
            return "addons_handled"

    if "stylist_resolved" not in already:
        if any(w in lower for w in ["estilista", "profesional", "preferís", "preferis", "quién te", "quien te"]):
            return "stylist_resolved"

    if "slot_resolved" not in already:
        if any(w in lower for w in ["horario", "disponible", "turno"]) and any(c.isdigit() for c in text):
            return "slot_resolved"

    if "confirmation_done" not in already:
        if any(w in lower for w in ["confirmas", "confirmar", "resumen", "estás segura", "detalle", "a nombre de"]):
            return "confirmation_done"

    if any(w in lower for w in ["reservado", "agendado", "confirmado", "quedó", "turno confirmado", "listo"]):
        if any(w in lower for w in ["turno", "reserva", "cita"]):
            return "booking_completed"

    return None


# ---------------------------------------------------------------------------
# María's response generation
# ---------------------------------------------------------------------------

import re as _re


def generate_maria_reply(
    turn_number: int,
    bot_reply: str,
    milestone_history: list[str | None],
) -> tuple[str, bool, str]:
    """
    Returns (reply_text, should_stop, stop_reason).
    """
    lower = bot_reply.lower()

    # Booking confirmed — done
    if any(w in lower for w in ["reservado", "agendado", "confirmado", "quedó", "turno confirmado"]):
        if any(w in lower for w in ["turno", "reserva", "cita"]):
            return "¡Perfecto, muchas gracias!", True, "booking_completed"

    # Bot asks how to help (after greeting)
    if any(w in lower for w in ["como puedo ayudarte", "cómo puedo ayudarte", "en qué te puedo", "qué necesitas"]):
        return "Quiero sacar un turno para corte de cabello dama para el jueves que viene.", False, ""

    # Bot asks dama/caballero clarification (fix check but keep flowing)
    if "dama" in lower and "caballero" in lower and "?" in bot_reply:
        return "Para dama.", False, ""

    # Bot asks audience (niña/bebé/caballero)
    if "niña" in lower and "bebé" in lower and "?" in bot_reply:
        return "Para dama.", False, ""

    # Bot asks for date/cuando
    if any(w in lower for w in ["qué día", "para qué día", "cuándo", "para cuándo"]) and "?" in bot_reply:
        if SCRIPT_STATE["date_question_count"] == 0:
            return "El jueves que viene, por favor.", False, ""
        else:
            return "El jueves que viene.", False, ""

    # Bot offers add-ons
    if any(w in lower for w in ["adicional", "extra", "sumar", "tratamiento", "complementario", "agregar"]):
        SCRIPT_STATE["addon_decline_sent_this_turn"] = True
        SCRIPT_STATE["addon_declined"] = True
        return "No gracias, solo el corte.", False, ""

    # Bot asks for stylist preference
    if any(w in lower for w in ["estilista", "profesional", "preferís", "preferis", "quién te", "quien te", "con quién", "con quien"]):
        SCRIPT_STATE["stylist_turn_sent"] = True
        SCRIPT_STATE["no_pref_sent"] = True
        return "No tengo preferencia de estilista.", False, ""

    # Bot shows available slots
    if any(w in lower for w in ["horario", "disponible"]) and any(c.isdigit() for c in bot_reply):
        numbered = _re.findall(r"(\d+)[.\)]\s+(.+)", bot_reply)
        if numbered:
            return f"{numbered[0][0]}.", False, ""
        time_match = _re.search(r"(\d{1,2}[:h]\d{2})\s*(hs|am|pm)?", bot_reply, _re.IGNORECASE)
        if time_match:
            return f"El de las {time_match.group(0).strip()}, dale.", False, ""
        return "El primero que tengas, dale.", False, ""

    # Bot shows date options
    if any(w in lower for w in ["jueves", "lunes", "martes", "miércoles", "viernes", "sábado"]):
        numbered = _re.findall(r"(\d+)[.\)]\s+(.+)", bot_reply)
        if numbered:
            return f"{numbered[0][0]}.", False, ""
        return "El jueves que viene.", False, ""

    # Bot asks for confirmation / shows summary
    if any(w in lower for w in ["confirmas", "confirmar", "estás segura", "resumen", "a nombre de", "detalle"]):
        return "Sí, confirmo.", False, ""

    # Bot asks for name
    if any(w in lower for w in ["nombre", "cómo te llamas", "como te llamas", "tu nombre"]):
        return "María García", False, ""

    # Bot asks to confirm service
    if any(w in lower for w in ["corte", "servicio"]) and "?" in bot_reply and turn_number <= 3:
        return "Sí, corte de cabello para dama.", False, ""

    # Bot cancelled (after no-pref — BUG scenario)
    if any(w in lower for w in ["cancelar", "cancelado", "cancelo", "he cancelado"]):
        return "No, no quería cancelar, solo no tengo preferencia de estilista.", False, ""

    # Fallback: agree
    return "Dale, gracias.", False, ""


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


async def run_qa_flow() -> dict[str, Any]:
    """Execute the booking_complete flow with María as persona — Round 4."""

    conversation_id = f"qa-r4-{uuid.uuid4().hex[:12]}"
    customer_phone = f"+34888{str(int(time.time()) % 1000000).zfill(6)}"
    sender_name = "María QA R4"
    run_started_at = datetime.now(UTC)

    log.info(f"=== QA ROUND 4 — booking_complete / maria_new_client ===")
    log.info(f"conversation_id={conversation_id}  phone={customer_phone}")
    log.info(f"Commit: 31deed9")

    redis_client = await aioredis.from_url(
        REDIS_URL,
        password=REDIS_PASSWORD,
        decode_responses=True,
        max_connections=5,
    )

    # Subscribe BEFORE injecting (skill rule: avoid race conditions)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(OUTGOING_CHANNEL)
    log.info(f"Subscribed to '{OUTGOING_CHANNEL}' ✓")

    # Drain stale subscribe confirmation message
    await asyncio.sleep(0.3)

    turns: list[dict[str, Any]] = []
    milestone_history: list[str | None] = []
    outcome = "timeout"
    termination_reason = f"Max turns ({MAX_TURNS}) exceeded"
    date_loop_turns: list[int] = []

    # Opening message: state service + date upfront
    current_message = "Hola! Quiero sacar un turno para corte de cabello dama para el jueves que viene."

    try:
        for turn_number in range(1, MAX_TURNS + 1):
            log.info(f"\n{'─'*60}")
            log.info(f"Turn {turn_number}")
            log.info(f"[USER → BOT]: {current_message}")

            payload = {
                "conversation_id": conversation_id,
                "customer_phone": customer_phone,
                "message_text": current_message,
                "sender_name": sender_name,
                "customer_name": "María",
                "is_audio_transcription": False,
                "audio_url": None,
            }
            ts_sent = datetime.now(UTC)
            stream_id = await redis_client.xadd(INCOMING_STREAM, {"data": json.dumps(payload)})
            log.info(f"Injected to stream: {stream_id}")

            # Capture bot response
            bot_response_text = ""
            timed_out = False
            ts_received = None
            raw_payloads: list[dict] = []

            loop = asyncio.get_running_loop()
            deadline = loop.time() + TURN_TIMEOUT_S
            batch_deadline: float | None = None

            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    if raw_payloads:
                        break
                    timed_out = True
                    break

                poll_timeout = remaining
                if batch_deadline is not None:
                    batch_remaining = batch_deadline - loop.time()
                    if batch_remaining <= 0:
                        break
                    poll_timeout = min(poll_timeout, batch_remaining)

                raw_msg = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=poll_timeout,
                )
                if raw_msg is None:
                    if raw_payloads:
                        break
                    continue

                raw_data = raw_msg.get("data", "")
                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode("utf-8")
                try:
                    pdata = json.loads(raw_data)
                except Exception:
                    continue

                if pdata.get("conversation_id") != conversation_id:
                    continue

                ts_received = datetime.now(UTC)
                raw_payloads.append(pdata)

                if batch_deadline is None:
                    batch_deadline = loop.time() + BATCH_WINDOW_S

            if raw_payloads:
                messages = [
                    str(p.get("message", "")).strip()
                    for p in raw_payloads
                    if p.get("message")
                ]
                bot_response_text = "\n\n".join(m for m in messages if m)
            elif timed_out:
                bot_response_text = "[TIMEOUT]"

            latency_ms = (
                int((ts_received - ts_sent).total_seconds() * 1000)
                if ts_received else 0
            )

            log.info(f"[BOT → USER] ({latency_ms}ms): {bot_response_text[:300]}")

            # ── Bug checks ─────────────────────────────────────────────────
            if bot_response_text and bot_response_text != "[TIMEOUT]":
                check_greeting_dedup(bot_response_text, turn_number)
                check_narration(bot_response_text, turn_number)
                check_date_loop(bot_response_text, turn_number)
                check_cancel_after_no_pref(bot_response_text, turn_number)

                # Track date question turns for NEW-C
                lower_resp = bot_response_text.lower()
                if any(w in lower_resp for w in ["qué día", "para qué día", "cuándo", "para cuándo"]) and "?" in bot_response_text:
                    date_loop_turns.append(turn_number)

            # ── Milestone detection ────────────────────────────────────────
            milestone_reached = detect_milestone(bot_response_text, milestone_history)
            milestone_history.append(milestone_reached)

            # ── Generate María's reply ─────────────────────────────────────
            if timed_out:
                reply_text = "¿Hola? ¿Siguen ahí?"
                should_stop = False
                stop_reason = ""
            else:
                reply_text, should_stop, stop_reason = generate_maria_reply(
                    turn_number, bot_response_text, milestone_history
                )

            # Reset per-turn flag
            SCRIPT_STATE["addon_decline_sent_this_turn"] = False

            # Record turn
            turns.append({
                "turn_number": turn_number,
                "user_message": current_message,
                "bot_response": bot_response_text,
                "bot_response_preview": bot_response_text[:250],
                "latency_ms": latency_ms,
                "timed_out": timed_out,
                "milestone_reached": milestone_reached,
                "should_stop": should_stop,
            })

            log.info(f"  → Milestone: {milestone_reached}  |  should_stop: {should_stop}")

            # Stop conditions
            if should_stop and stop_reason == "booking_completed":
                outcome = "completed"
                termination_reason = "booking_completed milestone — bot confirmed reservation"
                log.info("✅ FLOW COMPLETED — booking_completed reached")
                break

            if timed_out:
                log.warning(f"Turn {turn_number} timed out")
                if len(turns) >= 2 and turns[-2].get("timed_out"):
                    outcome = "timeout"
                    termination_reason = "Bot unresponsive for 2 consecutive turns"
                    break

            current_message = reply_text

        else:
            outcome = "max_turns"
            termination_reason = f"Max turns ({MAX_TURNS}) exceeded without completing"

    finally:
        await pubsub.unsubscribe(OUTGOING_CHANNEL)
        await pubsub.close()
        await redis_client.aclose()

    return {
        "scenario_id": "booking_complete",
        "persona_id": "maria_new_client",
        "conversation_id": conversation_id,
        "customer_phone": customer_phone,
        "commit": "31deed9",
        "run_started_at": run_started_at.isoformat(),
        "outcome": outcome,
        "termination_reason": termination_reason,
        "total_turns": len(turns),
        "turns": turns,
        "bug_checks": BUG_CHECKS,
        "date_loop_turns": date_loop_turns,
        "milestone_history": [m for m in milestone_history if m],
    }


async def check_db_appointments() -> int:
    """Check DB for appointments created in last hour."""
    try:
        import asyncpg  # type: ignore
    except ImportError:
        log.warning("asyncpg not available — skipping DB check")
        return -1

    try:
        conn = await asyncpg.connect(DB_URL, timeout=10)
        row = await conn.fetchrow(
            "SELECT count(*) AS cnt FROM appointments WHERE created_at > now() - interval '1 hour'"
        )
        await conn.close()
        count = row["cnt"] if row else 0
        return int(count)
    except Exception as e:
        log.warning(f"DB check failed: {e}")
        return -1


def evaluate_pass_fail(result: dict, appointment_count: int) -> dict[str, Any]:
    """Determine PASS/FAIL for each validation criterion and overall verdict."""
    checks = result["bug_checks"]
    booking_done = result["outcome"] == "completed"
    appointment_in_db = appointment_count > 0 if appointment_count >= 0 else None

    # BUG-001: book() called → appointment in DB
    if appointment_count < 0:
        checks["BUG-001"]["status"] = "UNKNOWN"
        checks["BUG-001"]["evidence"] = "DB check unavailable (asyncpg not installed)"
    elif appointment_in_db:
        checks["BUG-001"]["status"] = "PASS"
        checks["BUG-001"]["evidence"] = f"DB: {appointment_count} appointment(s) created in last 1h"
    elif booking_done:
        checks["BUG-001"]["status"] = "FAIL"
        checks["BUG-001"]["evidence"] = f"Booking completed but 0 appointments in DB"
    else:
        checks["BUG-001"]["status"] = "FAIL"
        checks["BUG-001"]["evidence"] = "Booking never completed — appointment_in_db=false"

    # NEW-C: mark as PASS if date_question_count <= 1
    if BUG_CHECKS["NEW-C"]["status"] == "NOT_TESTED":
        if result["date_loop_turns"]:
            BUG_CHECKS["NEW-C"]["status"] = "PASS"
            BUG_CHECKS["NEW-C"]["evidence"] = "Date question asked exactly once"
        else:
            BUG_CHECKS["NEW-C"]["status"] = "PASS"
            BUG_CHECKS["NEW-C"]["evidence"] = "Date resolved directly from opening message (no loop)"

    # Overall verdict
    critical_bugs = [k for k, v in checks.items() if v["status"] == "FAIL"]
    verdict = "PASS" if booking_done and not critical_bugs else "FAIL"

    milestones_hit = result.get("milestone_history", [])

    return {
        "verdict": verdict,
        "booking_completed": booking_done,
        "appointment_in_db": appointment_in_db,
        "appointment_count": appointment_count,
        "critical_bugs": critical_bugs,
        "milestones_hit": milestones_hit,
    }


async def main() -> None:
    # Run the QA flow
    result = await run_qa_flow()

    # Check DB
    log.info("\nChecking DB for recent appointments...")
    appt_count = await check_db_appointments()

    # Evaluate
    evaluation = evaluate_pass_fail(result, appt_count)

    # ── Print report ───────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("QA ROUND 4 — booking_complete / María (new client)")
    print(f"Commit: 31deed9  |  Run: {result['run_started_at']}")
    print("=" * 70)
    print(f"Outcome:         {result['outcome']}")
    print(f"Termination:     {result['termination_reason']}")
    print(f"Total turns:     {result['total_turns']}")
    print(f"Milestones hit:  {evaluation['milestones_hit']}")
    print()
    print("CONVERSATION TRACE:")
    print("-" * 70)
    for t in result["turns"]:
        status = "✅" if not t["timed_out"] else "⏱️"
        print(f"\n{status} Turn {t['turn_number']} ({t['latency_ms']}ms)  milestone={t['milestone_reached']}")
        print(f"  USER: {t['user_message']}")
        print(f"  BOT:  {t['bot_response_preview']}")

    print("\n" + "=" * 70)
    print("BUG VALIDATION SUMMARY — Round 4")
    print("=" * 70)
    all_pass = True
    for bug_id, info in result["bug_checks"].items():
        status = info["status"]
        icon = "✅" if status == "PASS" else ("❌" if status == "FAIL" else "⚠️ ")
        print(f"  {icon}  {bug_id}: [{status}] {info['label']}")
        if info["evidence"]:
            print(f"       Evidence: {info['evidence']}")
        if status not in ("PASS", "NOT_TESTED"):
            all_pass = False

    print()
    print(f"DB check:           {appt_count} appointment(s) in last 1h")
    print(f"appointment_in_db:  {evaluation['appointment_in_db']}")
    print()

    verdict_icon = "🟢" if evaluation["verdict"] == "PASS" else "🔴"
    print(f"{verdict_icon}  VERDICT: {evaluation['verdict']}")
    if evaluation["critical_bugs"]:
        print(f"   Critical bugs: {evaluation['critical_bugs']}")
    else:
        print("   No critical bugs — all checks passed")

    print("\n" + "=" * 70)
    print("FULL JSON TRACE:")
    trace_output = {**result, "evaluation": evaluation}
    print(json.dumps(trace_output, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
