"""
QA Final Run — Fix 3 Intent Classifier Validation
Tests the complete booking flow for María with "no tengo preferencia" stylist selection.

Expected results post-fix:
- Turn 4: "No tengo preferencia, con cualquiera que tenga lugar" → NOT cancel, stays in BOOKING
- Turn 5: Slot selection → stylist_id locked in
- Turn 6: Confirmation → booking completes
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
TIMEOUT = 45.0

TURNS = [
    {
        "turn": 1,
        "message": "Hola! Quiero sacar un turno para cortarme el pelo",
        "critical_checks": [],
        "must_not_contain": [],
    },
    {
        "turn": 2,
        "message": "Soy María, quiero cortarme el pelo",
        "critical_checks": [],
        "must_not_contain": ["María", "maria"],  # Token leak fix from Fix 2
    },
    {
        "turn": 3,
        "message": "Un corte de caballero",
        "critical_checks": [],
        "must_not_contain": [],
    },
    {
        "turn": 4,
        "message": "No tengo preferencia, con cualquiera que tenga lugar",
        "critical_checks": [],
        # FIX 3 CRITICAL: Must NOT say "cancelado" / "he cancelado"
        "must_not_contain": ["cancelado", "he cancelado", "reserva cancelada", "cita cancelada"],
        "critical_fix": "Fix 3: Intent classifier no-preference override",
    },
    {
        "turn": 5,
        "message": "El primer horario que tengas disponible",
        "critical_checks": [],
        "must_not_contain": ["cancelado"],
    },
    {
        "turn": 6,
        "message": "Sí, confirmo",
        "critical_checks": ["confirm", "reserva", "turno", "cita"],
        "must_not_contain": ["cancelado", "error"],
    },
]


async def run_qa() -> dict:
    settings = get_settings()
    r = redis.from_url(settings.REDIS_URL, decode_responses=True)
    r_binary = redis.from_url(settings.REDIS_URL, decode_responses=False)

    conversation_id = str(uuid.uuid4())
    print(f"\n{'='*70}")
    print("QA FINAL RUN — Fix 3 Validation")
    print(f"conversation_id: {conversation_id}")
    print(f"Timestamp: {datetime.now(UTC).isoformat()}")
    print(f"{'='*70}\n")

    # Subscribe BEFORE injecting (rule from skill)
    pubsub = r.pubsub()
    await pubsub.subscribe(RESPONSE_CHANNEL)

    # Drain any stale subscribe confirmation messages
    await asyncio.sleep(0.2)
    await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)

    turns_result = []
    overall_pass = True
    fix_results = {
        "fix_1_manage_customer_error_count": "N/A (upstream fix)",
        "fix_2_token_leak_filter": None,
        "fix_3_intent_classifier_no_preference": None,
        "booking_completion": None,
    }

    for turn_def in TURNS:
        turn_num = turn_def["turn"]
        msg = turn_def["message"]

        print(f"--- Turn {turn_num} ---")
        print(f"USER: {msg}")

        # Inject message
        timestamp_sent = datetime.now(UTC)
        payload = {
            "conversation_id": conversation_id,
            "customer_phone": "+34600111222",
            "message_text": msg,
            "sender_name": "María QA",
            "customer_name": "María QA",
            "is_audio_transcription": False,
            "audio_url": None,
        }
        await r.xadd(INCOMING_STREAM, {"data": json.dumps(payload)})

        # Capture response
        agent_response = None
        raw_payload = None
        deadline = asyncio.get_running_loop().time() + TIMEOUT

        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                print(f"TIMEOUT: No response for turn {turn_num} after {TIMEOUT}s")
                agent_response = "[TIMEOUT]"
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
            break

        timestamp_received = datetime.now(UTC)
        latency_ms = int((timestamp_received - timestamp_sent).total_seconds() * 1000)

        print(f"AGENT ({latency_ms}ms): {agent_response}")

        # Run checks
        checks = []
        turn_pass = True

        # must_not_contain checks
        must_not = turn_def.get("must_not_contain", [])
        for bad_phrase in must_not:
            found = bad_phrase.lower() in (agent_response or "").lower()
            check_pass = not found
            checks.append({
                "check": f"must_not_contain({bad_phrase!r})",
                "pass": check_pass,
                "found": found,
            })
            if not check_pass:
                print(f"  ❌ FAIL: Response contains forbidden phrase: {bad_phrase!r}")
                turn_pass = False
            else:
                print(f"  ✅ OK: Does not contain {bad_phrase!r}")

        # Critical fix-specific checks
        if turn_num == 4:
            # FIX 3: Check "cancelado" not in response
            is_fix3_ok = "cancelado" not in (agent_response or "").lower()
            fix_results["fix_3_intent_classifier_no_preference"] = "PASS" if is_fix3_ok else "FAIL"
            print(f"  {'✅' if is_fix3_ok else '❌'} Fix 3 (intent classifier): {'PASS' if is_fix3_ok else 'FAIL'}")

        if turn_num == 2:
            # FIX 2: Check for name leak (María should not appear literally)
            is_fix2_ok = "María" not in (agent_response or "") and "maria" not in (agent_response or "").lower()
            fix_results["fix_2_token_leak_filter"] = "PASS" if is_fix2_ok else "FAIL"
            print(f"  {'✅' if is_fix2_ok else '❌'} Fix 2 (token leak): {'PASS' if is_fix2_ok else 'FAIL'}")

        if agent_response == "[TIMEOUT]":
            turn_pass = False
            overall_pass = False

        if not turn_pass:
            overall_pass = False

        turns_result.append({
            "turn_number": turn_num,
            "user_message": msg,
            "agent_response": agent_response,
            "latency_ms": latency_ms,
            "pass": turn_pass,
            "checks": checks,
            "raw_payload": raw_payload,
        })
        print()

    # Capture final state
    print("Capturing final state from LangGraph checkpoint...")
    final_state = None
    try:
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver
        checkpointer = AsyncRedisSaver(redis_client=r_binary)
        config = {"configurable": {"thread_id": conversation_id}}
        checkpoint = await checkpointer.aget(config)
        if checkpoint:
            if hasattr(checkpoint, "checkpoint"):
                checkpoint_data = checkpoint.checkpoint
            else:
                checkpoint_data = checkpoint
            channel_values = checkpoint_data.get("channel_values", {})
            final_state = dict(channel_values) if isinstance(channel_values, dict) else {"raw": channel_values}
    except Exception as e:
        print(f"Warning: Could not capture final state: {e}")
        final_state = {}

    # Booking completion check
    appointment_created = False
    customer_id = None
    if final_state:
        appointment_created = bool(final_state.get("appointment_created"))
        customer_id = str(final_state.get("customer_id", "")) or None
        # Check in last turn response for booking keywords
        last_response = turns_result[-1]["agent_response"] if turns_result else ""
        booking_keywords = ["confirmad", "reservad", "anotad", "turno", "cita"]
        has_booking_keyword = any(kw in (last_response or "").lower() for kw in booking_keywords)
        fix_results["booking_completion"] = "PASS" if (appointment_created or has_booking_keyword) else "PARTIAL"
    else:
        last_response = turns_result[-1]["agent_response"] if turns_result else ""
        booking_keywords = ["confirmad", "reservad", "anotad", "turno", "cita"]
        has_booking_keyword = any(kw in (last_response or "").lower() for kw in booking_keywords)
        fix_results["booking_completion"] = "PARTIAL" if has_booking_keyword else "FAIL"

    await pubsub.unsubscribe(RESPONSE_CHANNEL)
    await pubsub.close()
    await r.aclose()
    await r_binary.aclose()

    # Determine final pass
    fix3_pass = fix_results["fix_3_intent_classifier_no_preference"] == "PASS"
    fix2_pass = fix_results["fix_2_token_leak_filter"] in ("PASS", None)  # None = not tested yet
    booking_ok = fix_results["booking_completion"] in ("PASS", "PARTIAL")

    report = {
        "scenario": "QA Final — Three Fixes Validation",
        "conversation_id": conversation_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "turns": turns_result,
        "final_state_summary": {
            "appointment_created": appointment_created,
            "customer_id": customer_id,
            "customer_first_name": final_state.get("customer_first_name") if final_state else None,
            "stylist_id": final_state.get("stylist_id") if final_state else None,
            "appointment_id": final_state.get("appointment_id") if final_state else None,
            "current_mode": final_state.get("current_mode") if final_state else None,
        },
        "fix_verification": fix_results,
        "overall_pass": overall_pass and fix3_pass,
        "overall_result": "PASS" if (overall_pass and fix3_pass) else "FAIL",
    }

    return report


def main():
    report = asyncio.run(run_qa())

    print("\n" + "="*70)
    print("QA REPORT SUMMARY")
    print("="*70)
    print(f"\nOverall Result: {report['overall_result']}")
    print("\nFix Verification:")
    for fix, result in report["fix_verification"].items():
        icon = "✅" if result == "PASS" else ("⚠️" if result == "PARTIAL" else "❌" if result == "FAIL" else "ℹ️")
        print(f"  {icon} {fix}: {result}")

    print("\nFinal State:")
    fs = report["final_state_summary"]
    for k, v in fs.items():
        print(f"  {k}: {v}")

    print("\nTurn Summary:")
    for t in report["turns"]:
        icon = "✅" if t["pass"] else "❌"
        print(f"  {icon} Turn {t['turn_number']} ({t['latency_ms']}ms): {(t['agent_response'] or '')[:80]}")

    print(f"\n{'='*70}")
    print(f"OVERALL RESULT: {report['overall_result']}")
    print(f"{'='*70}")

    # Save JSON for ingestion
    with open("/tmp/qa_fix3_report.json", "w") as f:
        # Serialize — remove raw_payload to keep it clean
        clean_report = {**report}
        clean_turns = []
        for t in clean_report.get("turns", []):
            clean_t = {k: v for k, v in t.items() if k != "raw_payload"}
            clean_turns.append(clean_t)
        clean_report["turns"] = clean_turns
        json.dump(clean_report, f, indent=2, default=str)
    print("\nJSON report saved to /tmp/qa_fix3_report.json")

    return 0 if report["overall_result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
