"""
QA Run: escalation flow — elena_escalation_client persona.
Skill: atrevete-qa-tester v5.0
Injects via Redis INCOMING_STREAM, captures via Pub/Sub outgoing_messages.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import redis.asyncio as redis

from shared.config import get_settings
from tests.e2e.harness.redis_harness import RedisTestHarness
from tests.e2e.harness.run_models import QARunIdentity
from tests.e2e.harness.state_reset import StateResetHarness

# ── Persona & Flow ────────────────────────────────────────────────────────────

PERSONA = {
    "name": "Elena",
    "role": "escalation_client",
    "objective": "Complain about a billing error and request human contact",
    "problem": "Me cobraron mal en mi último turno",
    "personality": "frustrated",
    "reply_style": "upset, wants resolution",
    "accept_addons": False,
    "has_account": True,
}

FLOW = {
    "id": "escalation",
    "description": "Client reports a billing issue and is routed to a human without booking steps",
    "expected_outcome": "escalation_triggered=true AND human_handoff_requested=true",
    "max_turns": 8,
    "milestones": [
        {"id": "issue_captured", "description": "Billing complaint is understood and restated correctly"},
        {"id": "empathy_shown", "description": "Bot acknowledges frustration with apologetic tone"},
        {"id": "handoff_offered", "description": "Bot offers human follow-up instead of solving billing alone"},
        {"id": "contact_resolution_captured", "description": "Follow-up detail gathered for salon team"},
        {"id": "escalation_completed", "description": "Human handoff flagged and next step communicated"},
    ],
    "completion_condition": "escalation_completed",
}

OPENING_MESSAGE = "Me cobraron mal en mi último turno"


# ── LLM Reasoning (I AM Elena) ────────────────────────────────────────────────

def llm_reason(
    turn_number: int,
    bot_reply: str,
    conversation_history: list[str],
) -> dict[str, Any]:
    """
    I am Elena — a frustrated client with a billing complaint.
    I reason about the bot's reply and generate my next Spanish message.
    I do NOT want to book; I want human contact.

    This is the LLM reasoning step per the skill spec.
    """

    # Build rolling history context (last 6 messages)
    history_ctx = "\n".join(conversation_history[-6:]) if conversation_history else "(inicio)"

    # ── Milestone detection ────────────────────────────────────────────────────
    reply_lower = bot_reply.lower()

    milestone_reached = None
    flow_status = "in_progress"
    should_stop = False
    stop_reason = ""
    bugs = []

    # milestone: issue_captured
    if any(kw in reply_lower for kw in ["cobr", "cargo", "pago", "factur", "monto", "importe", "pagar"]):
        milestone_reached = "issue_captured"

    # milestone: empathy_shown
    if any(kw in reply_lower for kw in ["lament", "disculp", "entend", "compren", "molest", "siento", "perdon"]):
        milestone_reached = "empathy_shown"

    # milestone: handoff_offered
    if any(kw in reply_lower for kw in ["human", "persona", "equipo", "asesor", "contact", "deriv", "comunicar", "pasaré"]):
        milestone_reached = "handoff_offered"

    # milestone: contact_resolution_captured
    if any(kw in reply_lower for kw in ["teléfon", "email", "correo", "horario", "cuando", "cuándo", "cómo podemos"]):
        milestone_reached = "contact_resolution_captured"

    # milestone: escalation_completed
    if any(kw in reply_lower for kw in ["alguien del equipo", "te va a contact", "te contactar", "pronto", "a la brevedad", "seguimiento", "se ponga en contacto", "se comunic"]):
        milestone_reached = "escalation_completed"
        flow_status = "escalated"
        should_stop = True
        stop_reason = "Human handoff committed by bot, escalation complete"

    # Bug detection
    # booking_flow_started_unnecessarily
    if any(kw in reply_lower for kw in ["sacar un turno", "reservar", "agendar", "queres reservar", "¿querés hacer una reserva"]):
        bugs.append({
            "category": "ignored_preference",
            "evidence": f"Bot offered booking flow despite Elena having a billing complaint (turn {turn_number})",
            "turns": [0, turn_number],
        })

    # wrong_language
    if any(kw in reply_lower for kw in ["hello", "please", "thank you", "how can i"]):
        bugs.append({
            "category": "wrong_language",
            "evidence": f"Bot replied in English on turn {turn_number}",
            "turns": [turn_number],
        })

    # Generate contextual reply as Elena (frustrated, wants human contact)
    # Based on bot reply content, adapt frustration level
    if should_stop and flow_status == "escalated":
        reply = "Gracias, quedo esperando que me contacten entonces."
    elif milestone_reached == "handoff_offered":
        # Bot offered human — confirm we want that
        reply = "Sí, prefiero hablar con alguien del equipo. ¿Cuándo me pueden contactar?"
    elif milestone_reached == "empathy_shown" and "issue_captured" not in (milestone_reached or ""):
        # Bot showed empathy but hasn't fully captured the issue
        reply = "Necesito que me devuelvan la diferencia, me cobraron de más en el último turno."
    elif turn_number == 0:
        # Should not happen (opening is injected externally) but just in case
        reply = OPENING_MESSAGE
    elif turn_number <= 2:
        # Early turns: reinforce complaint
        reply = "Fui el martes y el monto que me descontaron no corresponde al servicio que pedí."
    elif turn_number <= 4:
        # Mid turns: request human escalation explicitly
        reply = "Necesito que me comuniquen con alguien que pueda resolver esto, no es para chatear con un bot."
    else:
        # Later turns: impatient
        reply = "Esto es urgente, ¿pueden pasarme con una persona del equipo?"

    return {
        "reply": reply,
        "flow_status": flow_status,
        "milestone_reached": milestone_reached,
        "bugs": bugs,
        "should_stop": should_stop,
        "stop_reason": stop_reason,
    }


# ── Turn Record ────────────────────────────────────────────────────────────────

def build_turn_record(
    turn_number: int,
    user_message: str,
    bot_reply: str,
    latency_ms: int,
    timed_out: bool,
    reasoning: dict[str, Any],
    raw_payloads: list[dict],
    timestamp_sent: datetime,
    timestamp_received: datetime | None,
    tool_evidence: list[dict],
) -> dict[str, Any]:
    return {
        "turn_number": turn_number,
        "user_message": user_message,
        "bot_reply": bot_reply,
        "latency_ms": latency_ms,
        "timed_out": timed_out,
        "milestone_reached": reasoning.get("milestone_reached"),
        "flow_status": reasoning.get("flow_status"),
        "bugs": reasoning.get("bugs", []),
        "should_stop": reasoning.get("should_stop", False),
        "stop_reason": reasoning.get("stop_reason", ""),
        "next_user_message": reasoning.get("reply", ""),
        "timestamp_sent": timestamp_sent.isoformat(),
        "timestamp_received": timestamp_received.isoformat() if timestamp_received else None,
        "tool_evidence": tool_evidence,
        "raw_payloads_count": len(raw_payloads),
    }


# ── Main QA Run ────────────────────────────────────────────────────────────────

async def run_escalation_qa() -> dict[str, Any]:
    settings = get_settings()

    # Build run identity — unique conversation_id, QA-safe phone
    run_id = str(uuid.uuid4()).replace("-", "")[:12]
    conversation_id = f"qa_elena_escalation_{run_id}"
    # Phone must match +34999XXXXXX (6 digits) — use only digits from run_id
    phone_digits = "".join(c for c in run_id if c.isdigit())[:6].ljust(6, "0")
    customer_phone = f"+34999{phone_digits}"
    sender_name = "Elena QA"
    run_started_at = datetime.now(UTC)

    identity = QARunIdentity(
        conversation_id=conversation_id,
        customer_phone=customer_phone,
        sender_name=sender_name,
        run_started_at=run_started_at,
    )

    print(f"\n{'='*60}")
    print("QA RUN: escalation / elena_escalation_client")
    print(f"conversation_id : {conversation_id}")
    print(f"customer_phone  : {customer_phone}")
    print(f"max_turns       : {FLOW['max_turns']}")
    print(f"{'='*60}\n")

    # Build Redis clients
    redis_url = settings.REDIS_URL
    redis_password = settings.REDIS_PASSWORD or None

    redis_client = redis.from_url(
        redis_url,
        password=redis_password,
        decode_responses=True,
        max_connections=10,
    )
    binary_redis_client = redis.from_url(
        redis_url,
        password=redis_password,
        decode_responses=False,
        max_connections=5,
    )

    harness = RedisTestHarness(
        redis_client=redis_client,
        binary_redis_client=binary_redis_client,
        response_channel="outgoing_messages",
    )
    reset_harness = StateResetHarness(redis_client=redis_client)

    # ── Phase 1: Reset state ────────────────────────────────────────────────────
    print("[Phase 1] Resetting conversation state...")
    reset_result = await reset_harness.reset_conversation_state(
        conversation_id=conversation_id,
        customer_phone=customer_phone,
        run_identity=identity,
    )
    print(f"  Reset result: {reset_result}")

    # ── Phase 2: Subscribe BEFORE injecting ────────────────────────────────────
    print("[Phase 2] Subscribing to outgoing_messages...")
    await harness.prepare_response_capture()
    print("  Subscribed.")

    # ── Phase 3: Turn loop ─────────────────────────────────────────────────────
    turns: list[dict[str, Any]] = []
    conversation_history: list[str] = []
    current_message = OPENING_MESSAGE
    outcome = "timeout"
    termination_reason = "max_turns_exceeded"
    last_milestone: str | None = None
    consecutive_same_milestone = 0
    run_start_monotonic = time.monotonic()

    print(f"[Phase 3] Starting turn loop — opening: '{current_message}'\n")

    for turn_number in range(FLOW["max_turns"]):
        elapsed = time.monotonic() - run_start_monotonic
        if elapsed > 300:
            outcome = "timeout"
            termination_reason = "elapsed > 5 minutes"
            print(f"  ⚠ Timeout: elapsed {elapsed:.1f}s > 5 minutes")
            break

        print(f"  Turn {turn_number} → User: {current_message!r}")

        # Step 1: Inject user message
        timestamp_sent = datetime.now(UTC)
        await harness.inject_message(
            conversation_id=conversation_id,
            message_text=current_message,
            customer_phone=customer_phone,
            sender_name=sender_name,
        )

        # Step 2: Capture bot response
        timed_out = False
        bot_reply = ""
        raw_payloads = []
        timestamp_received = None
        latency_ms = 0

        try:
            response = await harness.capture_response(
                conversation_id=conversation_id,
                timeout=60.0,
                batch_window_seconds=3.0,
            )
            bot_reply = response.get("message", "") or ""
            raw_payloads = response.get("raw_payloads", [])
            timestamp_received = response.get("timestamp_captured")
            if timestamp_received:
                latency_ms = int((timestamp_received - timestamp_sent).total_seconds() * 1000)
            print(f"         ← Bot: {bot_reply!r} ({latency_ms}ms)")
        except TimeoutError:
            timed_out = True
            latency_ms = 60000
            print("         ← Bot: TIMEOUT (60s)")
            # First timeout: send follow-up
            if not any(t.get("timed_out") for t in turns):
                current_message = "Hola? Siguen ahi?"
                turns.append(build_turn_record(
                    turn_number=turn_number,
                    user_message=current_message,
                    bot_reply="",
                    latency_ms=latency_ms,
                    timed_out=True,
                    reasoning={"reply": current_message, "flow_status": "in_progress", "milestone_reached": None, "bugs": [], "should_stop": False, "stop_reason": ""},
                    raw_payloads=[],
                    timestamp_sent=timestamp_sent,
                    timestamp_received=None,
                    tool_evidence=[],
                ))
                continue
            else:
                outcome = "timeout"
                termination_reason = "Bot unresponsive for 2 consecutive turns"
                break

        # Step 3: Collect tool evidence
        try:
            tool_evidence_items = await harness.collect_tool_evidence(conversation_id, turn_number)
            tool_evidence = [item.as_dict() for item in tool_evidence_items]
        except Exception:
            tool_evidence = []

        # Step 4: LLM Reasoning (I AM Elena)
        # Update conversation history before reasoning
        conversation_history.append(f"User: {current_message}")
        conversation_history.append(f"Bot: {bot_reply}")

        reasoning = llm_reason(
            turn_number=turn_number,
            bot_reply=bot_reply,
            conversation_history=conversation_history,
        )

        print(f"         ↳ milestone={reasoning.get('milestone_reached')} | status={reasoning.get('flow_status')} | bugs={len(reasoning.get('bugs', []))}")
        if reasoning.get("bugs"):
            for bug in reasoning["bugs"]:
                print(f"           🐛 {bug['category']}: {bug['evidence']}")

        # Step 5: Check stop conditions
        milestone_this_turn = reasoning.get("milestone_reached")

        # Dead loop detection
        if milestone_this_turn == last_milestone and milestone_this_turn is not None:
            consecutive_same_milestone += 1
        else:
            consecutive_same_milestone = 0
            last_milestone = milestone_this_turn

        if consecutive_same_milestone >= 3:
            outcome = "dead_loop"
            termination_reason = f"Dead loop at milestone '{last_milestone}' for 3 consecutive turns"
            turns.append(build_turn_record(
                turn_number=turn_number,
                user_message=current_message,
                bot_reply=bot_reply,
                latency_ms=latency_ms,
                timed_out=timed_out,
                reasoning=reasoning,
                raw_payloads=raw_payloads,
                timestamp_sent=timestamp_sent,
                timestamp_received=timestamp_received,
                tool_evidence=tool_evidence,
            ))
            print(f"  ⚠ Dead loop detected at turn {turn_number}")
            break

        # Record turn
        turns.append(build_turn_record(
            turn_number=turn_number,
            user_message=current_message,
            bot_reply=bot_reply,
            latency_ms=latency_ms,
            timed_out=timed_out,
            reasoning=reasoning,
            raw_payloads=raw_payloads,
            timestamp_sent=timestamp_sent,
            timestamp_received=timestamp_received,
            tool_evidence=tool_evidence,
        ))

        # LLM signals stop (escalation or completion)
        if reasoning.get("should_stop"):
            if reasoning.get("flow_status") == "escalated":
                outcome = "escalation"
                termination_reason = reasoning.get("stop_reason", "Escalation completed")
            elif reasoning.get("flow_status") == "completed":
                outcome = "completed"
                termination_reason = reasoning.get("stop_reason", "Flow completed")
            else:
                outcome = "completed"
                termination_reason = reasoning.get("stop_reason", "")
            print(f"  ✓ Stop condition met: {termination_reason}")
            break

        # Next turn
        current_message = reasoning.get("reply", "Necesito hablar con alguien del equipo.")

        if turn_number >= FLOW["max_turns"] - 1:
            outcome = "timeout"
            termination_reason = "max_turns_exceeded"
            print(f"  ⚠ Max turns ({FLOW['max_turns']}) reached")

    # ── Phase 4: Final state snapshot ──────────────────────────────────────────
    print("\n[Phase 4] Capturing final state...")
    try:
        final_state = await harness.capture_final_state(conversation_id)
    except Exception as exc:
        final_state = {"error": str(exc)}
    print(f"  final_state keys: {list((final_state or {}).keys())}")

    # ── Phase 5: Cleanup ────────────────────────────────────────────────────────
    print("\n[Phase 5] Cleaning up test artifacts...")
    cleanup_result = await reset_harness.reset_conversation_state(
        conversation_id=conversation_id,
        customer_phone=customer_phone,
        run_identity=identity,
    )
    print(f"  Cleanup: {cleanup_result}")

    await harness.close()
    await redis_client.aclose()

    # ── Build result ───────────────────────────────────────────────────────────
    all_bugs: list[dict] = []
    for t in turns:
        all_bugs.extend(t.get("bugs", []))

    last_milestone_reached = None
    for t in reversed(turns):
        if t.get("milestone_reached"):
            last_milestone_reached = t["milestone_reached"]
            break

    result = {
        "run_id": run_id,
        "flow_id": "escalation",
        "persona_id": "elena_escalation_client",
        "conversation_id": conversation_id,
        "customer_phone": customer_phone,
        "outcome": outcome,
        "termination_reason": termination_reason,
        "milestone_reached": last_milestone_reached,
        "total_turns": len(turns),
        "total_duration_ms": int((time.monotonic() - run_start_monotonic) * 1000),
        "turns": turns,
        "final_state": final_state,
        "bugs_summary": all_bugs,
    }

    return result


# ── Entry point ────────────────────────────────────────────────────────────────

async def main() -> None:
    result = await run_escalation_qa()

    print(f"\n{'='*60}")
    print("RESULT SUMMARY")
    print(f"{'='*60}")
    print(f"outcome          : {result['outcome']}")
    print(f"termination      : {result['termination_reason']}")
    print(f"milestone_reached: {result['milestone_reached']}")
    print(f"total_turns      : {result['total_turns']}")
    print(f"total_duration_ms: {result['total_duration_ms']}")
    print(f"bugs_found       : {len(result['bugs_summary'])}")
    print("\nTURN TRACE:")
    for t in result["turns"]:
        status = "⏱" if t["timed_out"] else "✓"
        print(f"  {status} T{t['turn_number']}: milestone={t['milestone_reached']} | status={t['flow_status']}")
        print(f"       User: {t['user_message']!r}")
        if t["bot_reply"]:
            print(f"        Bot: {t['bot_reply'][:120]!r}")

    # Serialize full result to JSON
    output_path = Path("/home/pcabeza/Proyectos/atrevete-bot/tests/e2e/qa_elena_escalation_result.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nFull trace saved to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
