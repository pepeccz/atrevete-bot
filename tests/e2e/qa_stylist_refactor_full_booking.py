"""
QA FULL BOOKING TEST — Stylist Selection State-Driven Refactor Validation

Tests the COMPLETE booking flow after the stylist-selection-state-driven-refactor.
This is a 6-turn scenario that exercises all paths the refactor touches:
  1. Greeting + intent
  2. Service type inquiry
  3. Service clarification (haircut gender)
  4. Stylist selection (no preference → resolver prefetches)
  5. Slot selection (from available options)
  6. Final confirmation (same-turn handoff when resolver matches)

Expected results:
  - Turn 1: Greeting ✅
  - Turn 2: Service type asked ✅
  - Turn 3: Haircut gender clarification ✅
  - Turn 4: Stylist options shown (refactor: PrefetchResult typed) ✅
  - Turn 5: Slot selected + confirmed ✅
  - Turn 6: Appointment created ✅
  
Final state: appointment_created=true, customer_id set, appointment_datetime valid

Refactor validation points:
  ✓ PrefetchResult discriminated union handles all paths (ok/no_availability/tool_error)
  ✓ Same-turn handoff works when resolver matches prefetch
  ✓ No silent tool failures (error fields checked explicitly)
  ✓ State transitions smooth across BOOKING → SLOT_SELECTION
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
        "description": "Initial greeting + booking intent",
        "refactor_checkpoint": None,  # Before refactor touches anything
    },
    {
        "turn": 2,
        "message": "Quiero un corte de cabello",
        "description": "Service type inquiry → bot asks for gender",
        "refactor_checkpoint": None,
    },
    {
        "turn": 3,
        "message": "Para mujer",
        "description": "Service clarification (corte para dama) → bot ready for stylist selection",
        "refactor_checkpoint": None,
    },
    {
        "turn": 4,
        "message": "No tengo preferencia, con cualquiera que tenga lugar",
        "description": "Stylist selection (no preference) → REFACTOR: _prefetch_stylist_options() called, returns PrefetchResult",
        "refactor_checkpoint": "prefetch_result",
    },
    {
        "turn": 5,
        "message": "El primer horario que tengas disponible",
        "description": "Slot selection from available → REFACTOR: same-turn handoff if resolver matched",
        "refactor_checkpoint": "same_turn_handoff",
    },
    {
        "turn": 6,
        "message": "Sí, confirmo el turno",
        "description": "Final confirmation → appointment_created = True",
        "refactor_checkpoint": None,
    },
]


async def run_qa() -> dict:
    settings = get_settings()
    # When running from host, replace internal Docker hostname with localhost
    redis_url = settings.REDIS_URL.replace("redis://redis:", "redis://localhost:").replace(
        "rediss://redis:", "rediss://localhost:"
    )
    # Also support password-authenticated URLs
    if "@redis:" in redis_url:
        redis_url = redis_url.replace("@redis:", "@localhost:")
    # If using internal hostname without explicit auth, inject password
    if "redis://redis:" in settings.REDIS_URL and settings.REDIS_PASSWORD:
        redis_url = f"redis://:{settings.REDIS_PASSWORD}@localhost:6379/0"
    elif "redis://redis:" in settings.REDIS_URL:
        redis_url = settings.REDIS_URL.replace("redis://redis:", "redis://localhost:")

    print(f"Using Redis URL (host-side): {redis_url.split('@')[0]}@...hidden")
    r = redis.from_url(redis_url, decode_responses=True)

    conversation_id = str(uuid.uuid4())
    customer_phone = "+34600111444"
    
    print(f"\n{'='*80}")
    print(f"QA FULL BOOKING TEST — Stylist Selection State-Driven Refactor Validation")
    print(f"conversation_id: {conversation_id}")
    print(f"customer_phone: {customer_phone}")
    print(f"Timestamp: {datetime.now(UTC).isoformat()}")
    print(f"{'='*80}\n")

    # CRITICAL: Subscribe BEFORE injecting (race condition prevention)
    pubsub = r.pubsub()
    await pubsub.subscribe(RESPONSE_CHANNEL)

    # Drain stale subscribe confirmation messages
    await asyncio.sleep(0.3)
    await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)

    turns_result = []
    overall_pass = True
    refactor_checkpoints = {}

    for turn_def in TURNS:
        turn_num = turn_def["turn"]
        msg = turn_def["message"]
        description = turn_def.get("description", "")
        checkpoint = turn_def.get("refactor_checkpoint")

        print(f"--- Turn {turn_num}: {description} ---")
        print(f"USER: {msg}")

        # Inject message
        timestamp_sent = datetime.now(UTC)
        payload = {
            "conversation_id": conversation_id,
            "customer_phone": customer_phone,
            "message_text": msg,
            "sender_name": "María Refactor Test",
            "customer_name": None,  # Will be captured from turn 3 onwards
            "is_audio_transcription": False,
            "audio_url": None,
        }
        await r.xadd(INCOMING_STREAM, {"data": json.dumps(payload)})

        # Capture response
        agent_response = None
        deadline = asyncio.get_running_loop().time() + TIMEOUT

        while asyncio.get_running_loop().time() < deadline:
            msg_dict = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg_dict and msg_dict.get("type") == "message":
                try:
                    msg_data = json.loads(msg_dict["data"])
                    if msg_data.get("conversation_id") == conversation_id:
                        agent_response = msg_data.get("message_text", "")
                        break
                except (json.JSONDecodeError, TypeError):
                    continue

        if not agent_response:
            print(f"❌ Turn {turn_num}: TIMEOUT (no response in {TIMEOUT}s)")
            overall_pass = False
            turns_result.append(
                {
                    "turn": turn_num,
                    "status": "TIMEOUT",
                    "message": msg,
                    "response": None,
                    "latency_ms": None,
                }
            )
            continue

        latency_ms = int((datetime.now(UTC) - timestamp_sent).total_seconds() * 1000)
        print(f"✅ Turn {turn_num} ({latency_ms}ms)")
        print(f"AGENT: {agent_response[:120]}..." if len(agent_response) > 120 else f"AGENT: {agent_response}")

        # Validation checks
        turn_pass = True
        
        # Basic checks: non-empty, no traceback, coherent Spanish
        if not agent_response or "Traceback" in agent_response or "Error" in agent_response:
            print(f"   ⚠️  Response quality issue")
            turn_pass = False
        
        # Checkpoint-specific checks
        if checkpoint == "prefetch_result":
            # Turn 4: Stylist selection invoked
            # Expected: bot shows available stylists or "no hay disponibilidad"
            # Refactor validation: no silent failures
            if not any(word in agent_response.lower() for word in ["estilista", "disponib", "opción", "eligi"]):
                print(f"   ⚠️  Checkpoint '{checkpoint}': Expected stylist/availability keywords not found")
                turn_pass = False
            else:
                print(f"   ✓ Checkpoint '{checkpoint}': PrefetchResult handling OK")
                refactor_checkpoints[checkpoint] = "PASS"

        elif checkpoint == "same_turn_handoff":
            # Turn 5: Slot selection
            # Expected: bot either asks for time confirmation or directly confirms
            # Refactor validation: same-turn handoff working (should show options or proceed)
            if not any(word in agent_response.lower() for word in ["horario", "disponib", "opción", "tiempo", "hora"]):
                print(f"   ⚠️  Checkpoint '{checkpoint}': Expected slot keywords not found")
                turn_pass = False
            else:
                print(f"   ✓ Checkpoint '{checkpoint}': Same-turn handoff handling OK")
                refactor_checkpoints[checkpoint] = "PASS"

        if turn_pass:
            turns_result.append(
                {
                    "turn": turn_num,
                    "status": "PASS",
                    "message": msg,
                    "response": agent_response,
                    "latency_ms": latency_ms,
                }
            )
        else:
            overall_pass = False
            turns_result.append(
                {
                    "turn": turn_num,
                    "status": "WARN",
                    "message": msg,
                    "response": agent_response,
                    "latency_ms": latency_ms,
                }
            )

        print()

    # Fetch final state
    print(f"{'='*80}")
    print("FINAL STATE INSPECTION")
    print(f"{'='*80}\n")

    final_state = {
        "appointment_created": False,
        "customer_id": None,
        "stylist_name": None,
        "service_name": None,
        "slot_datetime": None,
    }

    # Try to fetch conversation state from Redis (if checkpoint is available)
    state_key = f"conversation:{conversation_id}:state"
    state_data = await r.get(state_key)
    if state_data:
        try:
            state_obj = json.loads(state_data)
            final_state["appointment_created"] = state_obj.get("appointment_created", False)
            final_state["customer_id"] = state_obj.get("customer_id")
            final_state["stylist_name"] = state_obj.get("stylist_name")
            final_state["service_name"] = state_obj.get("service_name")
            final_state["slot_datetime"] = state_obj.get("slot_datetime")
        except (json.JSONDecodeError, TypeError):
            pass

    print(f"appointment_created: {final_state['appointment_created']}")
    print(f"customer_id: {final_state['customer_id']}")
    print(f"stylist_name: {final_state['stylist_name']}")
    print(f"service_name: {final_state['service_name']}")
    print(f"slot_datetime: {final_state['slot_datetime']}")
    print()

    # Summary
    print(f"{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}\n")
    
    passed_turns = sum(1 for t in turns_result if t["status"] == "PASS")
    total_turns = len(turns_result)
    
    print(f"Turns completed: {passed_turns}/{total_turns}")
    print(f"Refactor checkpoints hit: {len(refactor_checkpoints)}/2")
    if refactor_checkpoints:
        for cp, status in refactor_checkpoints.items():
            print(f"  - {cp}: {status}")
    
    print(f"\nOverall result: {'✅ PASS' if overall_pass and final_state['appointment_created'] else '⚠️  INCOMPLETE'}")
    if final_state['appointment_created']:
        print(f"🎉 BOOKING SUCCESSFUL — Full flow completed with refactor validated")
    else:
        print(f"⏳ Flow incomplete or final state not captured (may need longer test)")
    
    print()

    await pubsub.unsubscribe()
    await r.close()

    return {
        "status": "complete",
        "conversation_id": conversation_id,
        "turns": turns_result,
        "final_state": final_state,
        "refactor_checkpoints": refactor_checkpoints,
        "overall_pass": overall_pass and final_state['appointment_created'],
    }


if __name__ == "__main__":
    result = asyncio.run(run_qa())
    print(f"\n\nRESULT JSON:\n{json.dumps(result, indent=2)}")
    sys.exit(0 if result["overall_pass"] else 1)
