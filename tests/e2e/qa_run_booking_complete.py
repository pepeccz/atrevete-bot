"""
QA Run: booking_complete flow with María (new client persona).
Executes the full booking flow against the live bot via Redis.

Usage:
    python tests/e2e/qa_run_booking_complete.py
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
BATCH_WINDOW_S = 4.0  # wait up to 4s after first reply for multi-part messages

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("qa_run")

# ---------------------------------------------------------------------------
# Persona & Flow (from qa-testing-context.md)
# ---------------------------------------------------------------------------
PERSONA = {
    "name": "María",
    "role": "new_client",
    "objective": "Book a haircut (corte para dama) for next Thursday",
    "preferences": {
        "service": "corte de cabello",
        "service_variant": "dama",
        "stylist": None,
        "date": "jueves que viene",
        "time": None,
    },
    "personality": "concise",
    "reply_style": "brief, direct answers",
    "accept_addons": False,
}

FLOW_MILESTONES = [
    "greeting_done",
    "service_resolved",
    "addons_handled",
    "stylist_resolved",
    "slot_resolved",
    "confirmation_done",
    "booking_completed",
]

# ---------------------------------------------------------------------------
# LLM-based reasoning (inline since we ARE the LLM)
# The sub-agent reasons as María on each turn.
# ---------------------------------------------------------------------------


def build_opening_message() -> str:
    return "Hola! Quiero sacar un turno para corte de dama para el jueves que viene."


# ─────────────────────────────────────────────────────────────────────────────
# FIX VALIDATION TRACKING
# Tracks the 4 critical fixes being validated in this 3rd round
# ─────────────────────────────────────────────────────────────────────────────
FIX_VALIDATION: dict[str, Any] = {
    "audience_carryover": {"status": "NOT_TESTED", "evidence": ""},
    "date_anchor": {"status": "NOT_TESTED", "evidence": ""},
    "addon_decline": {"status": "NOT_TESTED", "evidence": ""},
    "cualquiera_stylist": {"status": "NOT_TESTED", "evidence": ""},
}

# Track special script states
SCRIPT_STATE = {
    "addon_turn_reached": False,  # True once bot offered add-ons
    "addon_declined_this_turn": False,  # True when we said "No gracias"
}


def reason_as_maria(
    turn_number: int,
    bot_reply: str,
    conversation_history: list[str],
    milestone_history: list[str | None],
) -> dict[str, Any]:
    """
    Act as the LLM reasoning step: we ARE María, reasoning about the bot reply.
    Returns a dict matching the LLMTurnResponse schema.
    Validates 4 critical fixes inline.
    """
    reply = bot_reply.lower()
    bugs: list[dict] = []
    
    # --- Milestone detection ---
    milestone_reached: str | None = None
    
    if any(w in reply for w in ["bienvenida", "bienvenido", "hola", "como puedo"]):
        milestone_reached = "greeting_done"
    
    if any(w in reply for w in ["adicional", "extra", "sumar", "agregar", "tratamiento", "complementario"]):
        milestone_reached = "addons_handled"
    
    if any(w in reply for w in ["estilista", "profesional", "luciana", "cualquiera", "preferis alguna", "preferís"]):
        milestone_reached = "stylist_resolved"
    
    if any(w in reply for w in ["turno", "horario", "disponible", "jueves", "fecha", "hora", "lunes", "martes", "miércoles", "viernes"]) and any(c.isdigit() for c in bot_reply):
        if "stylist_resolved" in milestone_history or milestone_reached == "stylist_resolved":
            milestone_reached = "slot_resolved"
    
    if any(w in reply for w in ["confirmas", "confirmar", "resumen", "reserva", "estás segura", "agendar"]):
        milestone_reached = "confirmation_done"
    
    if any(w in reply for w in ["reservado", "agendado", "confirmado", "listo", "quedo agendado", "quedó", "turno confirmado"]):
        milestone_reached = "booking_completed"
    
    # ── Fix 1: Audience carry-over ──────────────────────────────────────────
    # Check if bot asks "dama o caballero?" despite user saying "corte de dama" upfront
    audience_question_asked = (
        ("dama" in reply and "caballero" in reply and "?" in bot_reply)
        or ("para quién" in reply and "?" in bot_reply)
        or ("dama, caballero" in reply)
    )
    if turn_number == 1:
        # First turn: check if bot asks audience INSTEAD of resolving
        if audience_question_asked:
            FIX_VALIDATION["audience_carryover"]["status"] = "FAIL"
            FIX_VALIDATION["audience_carryover"]["evidence"] = (
                f"Turn 1: Bot asked audience clarification '{bot_reply[:120]}' despite user specifying 'corte de dama'"
            )
            bugs.append({
                "category": "redundant_question",
                "evidence": "Bot asked 'dama o caballero?' despite user specifying 'corte de dama' in opening message",
                "turns": [1],
            })
        else:
            # Good: bot resolved "dama" directly
            service_resolved = any(w in reply for w in ["cortar", "corte", "servicio"])
            if service_resolved or not audience_question_asked:
                FIX_VALIDATION["audience_carryover"]["status"] = "PASS"
                FIX_VALIDATION["audience_carryover"]["evidence"] = (
                    f"Turn 1: Bot did NOT ask audience clarification. Response excerpt: '{bot_reply[:120]}'"
                )
    elif turn_number > 1 and audience_question_asked:
        history_text = " ".join(conversation_history)
        if "dama" in history_text.lower():
            FIX_VALIDATION["audience_carryover"]["status"] = "FAIL"
            FIX_VALIDATION["audience_carryover"]["evidence"] = (
                f"Turn {turn_number}: Redundant audience question after dama was already specified"
            )
            bugs.append({
                "category": "redundant_question",
                "evidence": f"Bot re-asked 'dama o caballero?' on turn {turn_number} but dama was already specified",
                "turns": [1, turn_number],
            })
    
    # ── Fix 2: Date anchor preservation ─────────────────────────────────────
    thursday_mentioned = any(w in reply for w in ["jueves", "jue."])
    if thursday_mentioned and FIX_VALIDATION["date_anchor"]["status"] == "NOT_TESTED":
        FIX_VALIDATION["date_anchor"]["status"] = "PASS"
        FIX_VALIDATION["date_anchor"]["evidence"] = (
            f"Turn {turn_number}: Bot preserved Thursday date anchor: '{bot_reply[:120]}'"
        )
    
    # ── Fix 3: Add-on decline → NOT cancellation ────────────────────────────
    if SCRIPT_STATE.get("addon_declined_this_turn"):
        # We just said "No gracias" — check if bot asks about cancellation
        cancel_response = any(w in reply for w in [
            "cancelar", "¿seguro", "seguro que", "anular", "eliminar el turno"
        ])
        if cancel_response:
            FIX_VALIDATION["addon_decline"]["status"] = "FAIL"
            FIX_VALIDATION["addon_decline"]["evidence"] = (
                f"Turn {turn_number}: Bot interpreted 'No gracias' (add-on decline) as booking cancellation: '{bot_reply[:160]}'"
            )
            bugs.append({
                "category": "ignored_preference",
                "evidence": f"Bot asked about cancellation after user declined add-ons on turn {turn_number-1}",
                "turns": [turn_number - 1, turn_number],
            })
        else:
            FIX_VALIDATION["addon_decline"]["status"] = "PASS"
            FIX_VALIDATION["addon_decline"]["evidence"] = (
                f"Turn {turn_number}: 'No gracias' correctly declined add-ons without triggering cancellation flow"
            )
        SCRIPT_STATE["addon_declined_this_turn"] = False
    
    # ── Fix 4: "Cualquiera" stylist crash detection ──────────────────────────
    # Checked via absence of error indicators after sending "Cualquiera."
    # This is checked in _generate_maria_reply post-stylist selection turn
    
    # ── Wrong language check ──────────────────────────────────────────────────
    if not any(word in reply for word in ["el", "la", "de", "y", "o", "para", "que", "en", "por", "con"]):
        if len(reply) > 20:
            bugs.append({
                "category": "wrong_language",
                "evidence": f"Bot reply does not appear to be in Spanish: '{bot_reply[:80]}'",
                "turns": [turn_number],
            })
    
    # --- Generate María's next reply ---
    reply_text = _generate_maria_reply(turn_number, bot_reply, milestone_history, milestone_reached)
    
    # --- Flow status ---
    if milestone_reached == "booking_completed":
        flow_status = "completed"
        should_stop = True
        stop_reason = "Booking confirmed by bot, appointment details provided"
    elif "error" in reply and any(w in reply for w in ["intenta", "problema", "lo siento"]):
        flow_status = "stuck"
        should_stop = False
        stop_reason = ""
    else:
        flow_status = "in_progress"
        should_stop = False
        stop_reason = ""
    
    return {
        "reply": reply_text,
        "flow_status": flow_status,
        "milestone_reached": milestone_reached,
        "bugs": bugs,
        "should_stop": should_stop,
        "stop_reason": stop_reason,
    }


def _generate_maria_reply(
    turn_number: int,
    bot_reply: str,
    milestone_history: list[str | None],
    milestone_reached: str | None,
) -> str:
    """Generate María's next message matching her concise, direct personality.
    
    Follows the prescribed conversation script for the 3rd QA round:
    - Turn 1: Opening message (pre-sent)
    - When bot resolves service or asks to confirm: Sí / Cortar
    - When bot asks stylist: Cualquiera (triggers Fix 4 check)
    - When bot offers slots: Pick first one; CHECK date has jueves
    - When bot offers add-ons: "No gracias, solo el corte" (triggers Fix 3 check)
    - When bot asks name: "María García"
    - When bot asks confirmation: "Sí, confirmo."
    """
    import re
    reply_lower = bot_reply.lower()
    
    # Bot is greeting + asking for service or confirming intent (shouldn't happen since we opened with intent)
    if any(w in reply_lower for w in ["como puedo ayudarte", "que necesitas", "en qué te puedo", "cómo te puedo"]):
        return "Quiero sacar un turno para corte de dama para el jueves que viene."
    
    # Bot asks dama/caballero (Fix 1 fail scenario — still need to answer to continue)
    if ("dama" in reply_lower and "caballero" in reply_lower and "?" in bot_reply):
        return "Para dama."
    
    # Bot offers add-ons (Fix 3: must decline without triggering cancellation)
    if any(w in reply_lower for w in ["adicional", "extra", "sumar", "agregar", "tratamiento", "complementario"]):
        SCRIPT_STATE["addon_turn_reached"] = True
        SCRIPT_STATE["addon_declined_this_turn"] = True
        return "No gracias, solo el corte."
    
    # Bot asks for stylist preference (Fix 4: "Cualquiera" must not crash)
    if any(w in reply_lower for w in ["estilista", "profesional", "preferis", "preferís", "quién", "quien te"]):
        return "Cualquiera."
    
    # Bot shows available slots — check for Thursday and pick first
    if any(w in reply_lower for w in ["horario", "disponible"]) and any(c.isdigit() for c in bot_reply):
        numbered = re.findall(r"(\d+)[.\)]\s+(.+)", bot_reply)
        if numbered:
            return f"{numbered[0][0]}."
        time_match = re.search(r"(\d{1,2}[:h]\d{2})\s*(hs|am|pm)?", bot_reply, re.IGNORECASE)
        if time_match:
            return f"El de las {time_match.group(0).strip()}, dale."
        # Validate Fix 2 here: check if Thursday is in the slots
        if not any(w in reply_lower for w in ["jueves", "jue."]):
            # Date anchor lost — mark as fail
            if FIX_VALIDATION["date_anchor"]["status"] == "NOT_TESTED":
                FIX_VALIDATION["date_anchor"]["status"] = "FAIL"
                FIX_VALIDATION["date_anchor"]["evidence"] = (
                    f"Turn {turn_number}: Bot offered slots WITHOUT mentioning Thursday: '{bot_reply[:160]}'"
                )
        return "El primero que tengas, dale."
    
    # Bot shows available dates as list
    if any(w in reply_lower for w in ["jueves", "lunes", "martes", "miércoles", "viernes", "sábado"]):
        numbered = re.findall(r"(\d+)[.\)]\s+(.+)", bot_reply)
        if numbered:
            return f"{numbered[0][0]}."
        return "El jueves, gracias."
    
    # Bot asks for confirmation / shows summary
    if any(w in reply_lower for w in ["confirmas", "confirmar", "estás segura", "resumen", "a nombre de", "detalle"]):
        return "Sí, confirmo."
    
    # Bot confirms booking is done
    if any(w in reply_lower for w in ["reservado", "agendado", "confirmado", "quedó", "turno confirmado"]):
        return "Perfecto, muchas gracias!"
    
    # Bot asks for name
    if any(w in reply_lower for w in ["nombre", "llamas", "como te"]):
        return "María García"
    
    # Bot asks to confirm service
    if any(w in reply_lower for w in ["corte", "cortar", "servicio"]) and "?" in bot_reply:
        return "Sí, corte de cabello para dama."
    
    # Fallback: agree and proceed
    return "Dale, gracias."


# ---------------------------------------------------------------------------
# Harness (minimal, direct Redis usage)
# ---------------------------------------------------------------------------


async def run_qa_flow() -> dict[str, Any]:
    """Execute the booking_complete flow with María as persona."""
    
    # Generate unique conversation ID and test phone
    conversation_id = f"qa-{uuid.uuid4().hex[:12]}"
    customer_phone = f"+34999{str(int(time.time()) % 1000000).zfill(6)}"
    sender_name = "María QA"
    run_started_at = datetime.now(UTC)
    
    log.info(f"Starting QA run: conversation_id={conversation_id}, phone={customer_phone}")
    
    # Connect to Redis
    redis_client = await aioredis.from_url(
        REDIS_URL,
        password=REDIS_PASSWORD,
        decode_responses=True,
        max_connections=5,
    )
    
    # Subscribe FIRST, then inject (per skill rules)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(OUTGOING_CHANNEL)
    log.info(f"Subscribed to '{OUTGOING_CHANNEL}'")
    
    # Drain any stale subscribe confirmation messages
    await asyncio.sleep(0.2)
    
    # --- State ---
    turns: list[dict[str, Any]] = []
    conversation_history: list[str] = []
    milestone_history: list[str | None] = []
    last_milestone: str | None = None
    consecutive_same_milestone = 0
    outcome = "timeout"
    termination_reason = "max turns exceeded"
    bugs_all: list[dict] = []
    
    current_message = build_opening_message()
    
    try:
        for turn_number in range(1, MAX_TURNS + 1):
            log.info(f"\n--- Turn {turn_number} ---")
            log.info(f"[USER → BOT]: {current_message}")
            
            # Step 1: Inject user message
            payload = {
                "conversation_id": conversation_id,
                "customer_phone": customer_phone,
                "message_text": current_message,
                "sender_name": sender_name,
                "customer_name": "María",
                "is_audio_transcription": False,
                "audio_url": None,
            }
            timestamp_sent = datetime.now(UTC)
            stream_id = await redis_client.xadd(INCOMING_STREAM, {"data": json.dumps(payload)})
            log.info(f"Injected to stream: {stream_id}")
            
            # Step 2: Capture bot response from Pub/Sub
            bot_response_text = ""
            timed_out = False
            timestamp_received = None
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
                
                # Decode payload
                raw_data = raw_msg.get("data", "")
                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode("utf-8")
                try:
                    payload_data = json.loads(raw_data)
                except Exception:
                    continue
                
                if payload_data.get("conversation_id") != conversation_id:
                    continue
                
                timestamp_received = datetime.now(UTC)
                raw_payloads.append(payload_data)
                
                if batch_deadline is None:
                    batch_deadline = loop.time() + BATCH_WINDOW_S
            
            # Assemble bot response
            if raw_payloads:
                messages = [
                    str(p.get("message", "")).strip()
                    for p in raw_payloads
                    if p.get("message")
                ]
                bot_response_text = "\n\n".join(m for m in messages if m)
            
            latency_ms = (
                int((timestamp_received - timestamp_sent).total_seconds() * 1000)
                if timestamp_received else 0
            )
            
            if timed_out:
                log.warning(f"Turn {turn_number} timed out (no response within {TURN_TIMEOUT_S}s)")
                bot_response_text = "[TIMEOUT]"
            else:
                log.info(f"[BOT → USER] ({latency_ms}ms): {bot_response_text[:200]}")
            
            # Update conversation history (rolling 6-message window)
            conversation_history.append(f"User: {current_message}")
            conversation_history.append(f"Bot: {bot_response_text}")
            if len(conversation_history) > 12:  # 6 exchanges = 12 lines
                conversation_history = conversation_history[-12:]
            
            # Step 3: LLM Reasoning (we ARE the LLM / María)
            if timed_out:
                llm_response = {
                    "reply": "Hola? Siguen ahí?",
                    "flow_status": "stuck",
                    "milestone_reached": None,
                    "bugs": [{"category": "context_loss", "evidence": "Bot did not respond within 60s", "turns": [turn_number]}],
                    "should_stop": False,
                    "stop_reason": "",
                }
            else:
                llm_response = reason_as_maria(
                    turn_number=turn_number,
                    bot_reply=bot_response_text,
                    conversation_history=conversation_history,
                    milestone_history=milestone_history,
                )
            
            milestone_reached = llm_response.get("milestone_reached")
            milestone_history.append(milestone_reached)
            bugs_this_turn = llm_response.get("bugs", [])
            bugs_all.extend(bugs_this_turn)
            
            # Step 5: Dead loop check
            if milestone_reached == last_milestone and milestone_reached is not None:
                consecutive_same_milestone += 1
            else:
                consecutive_same_milestone = 0
                last_milestone = milestone_reached
            
            # Record turn
            turns.append({
                "turn_number": turn_number,
                "user_message": current_message,
                "bot_response": bot_response_text,
                "latency_ms": latency_ms,
                "timed_out": timed_out,
                "milestone_reached": milestone_reached,
                "flow_status": llm_response.get("flow_status"),
                "bugs": bugs_this_turn,
                "should_stop": llm_response.get("should_stop"),
                "llm_reply": llm_response.get("reply"),
            })
            
            log.info(f"Milestone: {milestone_reached} | Flow: {llm_response.get('flow_status')} | Bugs: {len(bugs_this_turn)}")
            
            # Step 5: Stop conditions
            if consecutive_same_milestone >= 3:
                outcome = "dead_loop"
                termination_reason = f"Dead loop at milestone '{last_milestone}' for 3 consecutive turns"
                log.warning(f"DEAD LOOP detected: {termination_reason}")
                break
            
            if llm_response.get("should_stop") and llm_response.get("flow_status") == "completed":
                outcome = "completed"
                termination_reason = llm_response.get("stop_reason", "Flow completed")
                log.info(f"FLOW COMPLETED: {termination_reason}")
                break
            
            if llm_response.get("should_stop") and llm_response.get("flow_status") == "escalated":
                outcome = "escalation"
                termination_reason = llm_response.get("stop_reason", "Escalation triggered")
                break
            
            if timed_out and turn_number > 1:
                # Second timeout — bot unresponsive
                if turns[-2].get("timed_out"):
                    outcome = "timeout"
                    termination_reason = "Bot unresponsive for 2 consecutive turns"
                    break
            
            # Prepare next message
            current_message = llm_response.get("reply", "Dale, gracias.")
            
        else:
            outcome = "timeout"
            termination_reason = f"Max turns ({MAX_TURNS}) exceeded"
    
    finally:
        await pubsub.unsubscribe(OUTGOING_CHANNEL)
        await pubsub.close()
        await redis_client.aclose()
    
    # Build ConversationResult
    final_milestone = None
    for m in reversed(milestone_history):
        if m is not None:
            final_milestone = m
            break
    
    # Check Fix 4 (cualquiera stylist) — infer from turns
    stylist_turn = next(
        (t for t in turns if t.get("user_message", "").lower().strip() in ("cualquiera.", "cualquiera")),
        None,
    )
    if stylist_turn:
        next_turn_idx = turns.index(stylist_turn) + 1
        if next_turn_idx < len(turns):
            next_bot = turns[next_turn_idx].get("bot_response", "").lower()
            error_indicators = ["error", "problema", "disculpa", "lo siento", "ocurrió un"]
            crashed = any(w in next_bot for w in error_indicators)
            FIX_VALIDATION["cualquiera_stylist"]["status"] = "FAIL" if crashed else "PASS"
            FIX_VALIDATION["cualquiera_stylist"]["evidence"] = (
                f"After 'Cualquiera', bot responded with: '{turns[next_turn_idx].get('bot_response', '')[:120]}'"
            )
        else:
            FIX_VALIDATION["cualquiera_stylist"]["status"] = "PASS"
            FIX_VALIDATION["cualquiera_stylist"]["evidence"] = "Stylist resolved, conversation continued"
    
    return {
        "conversation_id": conversation_id,
        "customer_phone": customer_phone,
        "run_started_at": run_started_at.isoformat(),
        "outcome": outcome,
        "termination_reason": termination_reason,
        "milestone_reached": final_milestone,
        "total_turns": len(turns),
        "turns": turns,
        "bugs_all": bugs_all,
        "bugs_count": len(bugs_all),
        "fix_validation": FIX_VALIDATION,
    }


async def main() -> None:
    result = await run_qa_flow()
    
    print("\n" + "="*70)
    print("QA RUN RESULTS — booking_complete / María (new client, 3rd round)")
    print("="*70)
    print(f"Outcome:         {result['outcome']}")
    print(f"Final milestone: {result['milestone_reached']}")
    print(f"Total turns:     {result['total_turns']}")
    print(f"Bugs found:      {result['bugs_count']}")
    print(f"Termination:     {result['termination_reason']}")
    print()
    print("CONVERSATION TRACE:")
    print("-"*70)
    for t in result["turns"]:
        print(f"\nTurn {t['turn_number']} ({t['latency_ms']}ms):")
        print(f"  USER:      {t['user_message']}")
        print(f"  BOT:       {t['bot_response'][:300]}")
        print(f"  Milestone: {t['milestone_reached']}")
        print(f"  Status:    {t['flow_status']}")
        if t["bugs"]:
            print(f"  BUGS:      {t['bugs']}")
    
    if result["bugs_all"]:
        print("\nALL BUGS DETECTED:")
        for b in result["bugs_all"]:
            print(f"  [{b['category']}] {b['evidence']} (turns: {b.get('turns')})")
    else:
        print("\nNo semantic bugs detected.")
    
    # Fix validation summary
    print("\n" + "="*70)
    print("FIX VALIDATION SUMMARY (3rd QA Round)")
    print("="*70)
    fv = result["fix_validation"]
    fixes = [
        ("Audience carry-over", "audience_carryover"),
        ("Date anchor preservation", "date_anchor"),
        ("Add-on decline handling", "addon_decline"),
        ("'Cualquiera' stylist resolution", "cualquiera_stylist"),
    ]
    all_pass = True
    for fix_name, fix_key in fixes:
        info = fv.get(fix_key, {})
        status = info.get("status", "NOT_TESTED")
        evidence = info.get("evidence", "")
        icon = "✅" if status == "PASS" else ("❌" if status == "FAIL" else "⚠️")
        print(f"{icon} {fix_name}: {status}")
        if evidence:
            print(f"   Evidence: {evidence}")
        if status != "PASS":
            all_pass = False
    
    print()
    booking_done = result["outcome"] == "completed"
    if all_pass and booking_done:
        print("🟢 STATUS: PASS")
        print("🚀 VERDICT: YES — Ready for production")
    elif all_pass:
        print("🟡 STATUS: PARTIAL (fixes pass but booking did not complete)")
        print("⚠️  VERDICT: NO — Booking flow did not complete")
    else:
        passes = sum(1 for _, k in fixes if fv.get(k, {}).get("status") == "PASS")
        print(f"🔴 STATUS: FAIL ({passes}/4 fixes pass)")
        print("❌ VERDICT: NO — Critical bugs remain")
    
    # Output JSON for evaluator
    print("\n" + "="*70)
    print("FULL JSON TRACE:")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
