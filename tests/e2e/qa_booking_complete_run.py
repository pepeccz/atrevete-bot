"""
QA Booking Complete — Maria (new client) full booking flow.

Flow: booking_complete
Persona: maria_new_client
Expected: appointment_created=True

Turns:
  1. "Hola, quiero reservar un turno"  (GREETING)
  2. "Quiero un corte de cabello"       (BOOKING)
  3. "Para el jueves que viene"         (BOOKING)
  4. "Sí, confirmo el turno"            (BOOKING - confirmation)
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
        "message": "Hola, quiero reservar un turno",
        "expected_keywords": ["hola", "bienvenida", "ayudar", "turno", "salón"],
    },
    {
        "turn": 2,
        "message": "Quiero un corte de cabello",
        "expected_keywords": ["corte", "servicio", "estilista", "disponib", "cuándo"],
    },
    {
        "turn": 3,
        "message": "Para el jueves que viene",
        "expected_keywords": ["jueves", "horario", "confirmar", "disponib", "turno"],
    },
    {
        "turn": 4,
        "message": "Sí, confirmo el turno",
        "expected_keywords": ["confirm", "reserv", "turno", "gracias", "listo"],
    },
]


def build_redis_url(settings) -> str:
    """Build host-side Redis URL (replace internal Docker hostname with localhost)."""
    url = settings.REDIS_URL
    # Replace internal docker hostname with localhost
    url = url.replace("redis://redis:", "redis://localhost:")
    url = url.replace("rediss://redis:", "rediss://localhost:")
    if "@redis:" in url:
        url = url.replace("@redis:", "@localhost:")
    # Inject password if REDIS_URL uses internal hostname without explicit auth
    if "redis://redis:" in settings.REDIS_URL and settings.REDIS_PASSWORD:
        url = f"redis://:{settings.REDIS_PASSWORD}@localhost:6379/0"
    elif "@redis:" not in settings.REDIS_URL and settings.REDIS_PASSWORD:
        # Simple URL like redis://localhost:6379/0 — inject password
        url = f"redis://:{settings.REDIS_PASSWORD}@localhost:6379/0"
    return url


async def run_qa() -> dict:
    settings = get_settings()
    redis_url = build_redis_url(settings)

    print(f"Redis URL (host): {redis_url.split('@')[0]}@...")
    print(f"Incoming stream: {INCOMING_STREAM}")
    print(f"Response channel: {RESPONSE_CHANNEL}")

    r = redis.from_url(redis_url, decode_responses=True)
    r_binary = redis.from_url(redis_url, decode_responses=False)

    # Verify connectivity
    try:
        await r.ping()
        print("Redis: connected OK")
    except Exception as e:
        print(f"Redis connection failed: {e}")
        return {"error": str(e)}

    conversation_id = str(uuid.uuid4())
    run_start = datetime.now(UTC)

    print(f"\n{'='*70}")
    print(f"QA Booking Complete — Maria (new client)")
    print(f"conversation_id: {conversation_id}")
    print(f"Started: {run_start.isoformat()}")
    print(f"{'='*70}\n")

    # CRITICAL: Subscribe BEFORE injecting (race condition prevention)
    pubsub = r.pubsub()
    await pubsub.subscribe(RESPONSE_CHANNEL)

    # Drain stale subscribe confirmation messages
    await asyncio.sleep(0.3)
    await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)

    turns_result = []
    any_timeout = False

    for turn_def in TURNS:
        turn_num = turn_def["turn"]
        msg = turn_def["message"]
        expected_kw = turn_def.get("expected_keywords", [])

        print(f"--- Turn {turn_num} ---")
        print(f"USER: {msg}")

        # Inject message into incoming stream
        timestamp_sent = datetime.now(UTC)
        payload = {
            "conversation_id": conversation_id,
            "customer_phone": "+34600000001",
            "message_text": msg,
            "sender_name": "María",
            "customer_name": "María",
            "is_audio_transcription": False,
            "audio_url": None,
        }
        await r.xadd(INCOMING_STREAM, {"data": json.dumps(payload)})

        # Capture response from Pub/Sub
        agent_response = None
        raw_payload = None
        timed_out = False
        deadline = asyncio.get_running_loop().time() + TIMEOUT

        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                print(f"  TIMEOUT: No response after {TIMEOUT}s")
                agent_response = "[TIMEOUT]"
                timed_out = True
                any_timeout = True
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
                # Different conversation — keep listening
                continue

            raw_payload = pld
            agent_response = pld.get("message", "")
            break

        timestamp_received = datetime.now(UTC)
        latency_ms = int((timestamp_received - timestamp_sent).total_seconds() * 1000)

        print(f"AGENT ({latency_ms}ms): {agent_response}")

        # Keyword checks
        kw_hits = []
        kw_misses = []
        for kw in expected_kw:
            if kw.lower() in (agent_response or "").lower():
                kw_hits.append(kw)
            else:
                kw_misses.append(kw)

        if kw_hits:
            print(f"  Keywords found: {kw_hits}")
        if kw_misses:
            print(f"  Keywords missing: {kw_misses}")

        turns_result.append({
            "turn_number": turn_num,
            "user_message": msg,
            "agent_response": agent_response,
            "response_latency_ms": latency_ms,
            "timed_out": timed_out,
            "expected_keywords": expected_kw,
            "keywords_found": kw_hits,
            "keywords_missing": kw_misses,
            "raw_response": raw_payload or {},
        })
        print()

    # Capture final state from LangGraph checkpoint
    print("Capturing final state from LangGraph checkpoint...")
    final_state_raw = {}
    final_state = {
        "appointment_created": False,
        "customer_id": None,
        "customer_name": None,
        "stylist_name": None,
        "service_name": None,
        "slot_datetime": None,
        "current_mode": None,
    }

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
            final_state_raw = dict(channel_values) if isinstance(channel_values, dict) else {}

            # Extract meaningful fields
            final_state["appointment_created"] = bool(final_state_raw.get("appointment_created"))
            final_state["customer_id"] = str(final_state_raw.get("customer_id", "")) or None
            final_state["customer_name"] = (
                final_state_raw.get("customer_first_name") or
                final_state_raw.get("customer_name") or
                None
            )
            final_state["stylist_name"] = (
                final_state_raw.get("stylist_name") or
                str(final_state_raw.get("stylist_id", "")) or
                None
            )
            final_state["service_name"] = (
                final_state_raw.get("service_name") or
                str(final_state_raw.get("service_id", "")) or
                None
            )
            final_state["slot_datetime"] = str(
                final_state_raw.get("appointment_datetime") or
                final_state_raw.get("selected_slot") or
                ""
            ) or None
            final_state["current_mode"] = final_state_raw.get("current_mode")

            print(f"  appointment_created: {final_state['appointment_created']}")
            print(f"  customer_id: {final_state['customer_id']}")
            print(f"  customer_name: {final_state['customer_name']}")
            print(f"  stylist_name: {final_state['stylist_name']}")
            print(f"  service_name: {final_state['service_name']}")
            print(f"  slot_datetime: {final_state['slot_datetime']}")
            print(f"  current_mode: {final_state['current_mode']}")
        else:
            print("  WARNING: No checkpoint found for this conversation")

    except Exception as e:
        print(f"  WARNING: Could not capture final state: {e}")
        import traceback
        traceback.print_exc()

    await pubsub.unsubscribe(RESPONSE_CHANNEL)
    await pubsub.close()
    await r.aclose()
    await r_binary.aclose()

    run_end = datetime.now(UTC)
    total_duration_ms = int((run_end - run_start).total_seconds() * 1000)
    turns_successful = sum(1 for t in turns_result if not t["timed_out"])

    trace = {
        "scenario_id": "booking_complete",
        "persona_id": "maria_new_client",
        "conversation_id": conversation_id,
        "execution_summary": {
            "total_duration_ms": total_duration_ms,
            "turns_attempted": len(turns_result),
            "turns_successful": turns_successful,
            "any_timeout": any_timeout,
            "final_outcome": "appointment_created" if final_state["appointment_created"] else "incomplete",
        },
        "turns": turns_result,
        "final_state": final_state,
    }

    return trace


def main():
    trace = asyncio.run(run_qa())

    print("\n" + "=" * 70)
    print("QA TRACE — BOOKING COMPLETE")
    print("=" * 70)

    summary = trace.get("execution_summary", {})
    print(f"\nTotal duration: {summary.get('total_duration_ms', 0)}ms")
    print(f"Turns successful: {summary.get('turns_successful')}/{summary.get('turns_attempted')}")
    print(f"Any timeout: {summary.get('any_timeout')}")
    print(f"Final outcome: {summary.get('final_outcome')}")

    print("\nTurn Summary:")
    for t in trace.get("turns", []):
        status = "TIMEOUT" if t.get("timed_out") else "OK"
        preview = (t.get("agent_response") or "")[:100]
        print(f"  Turn {t['turn_number']} ({t['response_latency_ms']}ms) [{status}]: {preview}")

    print("\nFinal State:")
    for k, v in trace.get("final_state", {}).items():
        print(f"  {k}: {v}")

    # Save full trace to file
    output_path = "/tmp/qa_booking_complete_trace.json"
    clean_turns = []
    for t in trace.get("turns", []):
        clean_t = dict(t)
        # Keep raw_response but serialise datetime objects
        clean_turns.append(clean_t)
    trace_to_save = {**trace, "turns": clean_turns}

    with open(output_path, "w") as f:
        json.dump(trace_to_save, f, indent=2, default=str)
    print(f"\nFull trace saved to {output_path}")

    # Print full JSON trace
    print("\n" + "=" * 70)
    print("FULL JSON TRACE:")
    print("=" * 70)
    print(json.dumps(trace_to_save, indent=2, default=str))

    return 0 if trace.get("final_state", {}).get("appointment_created") else 1


if __name__ == "__main__":
    sys.exit(main())
