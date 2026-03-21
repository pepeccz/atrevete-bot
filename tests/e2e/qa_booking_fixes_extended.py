"""
Extended QA: Continue the booking conversation beyond turn 7.
The bot got stuck in an add-on loop — test FIX 3 (bounded retry escalation).
Also manually verify the add-on "no" path.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import redis.asyncio as redis_async
from shared.config import get_settings
from shared.redis_client import INCOMING_STREAM

RESPONSE_CHANNEL = "outgoing_messages"
TIMEOUT_SECONDS = 45.0
BATCH_WINDOW_SECONDS = 4.0


async def subscribe_and_wait(pubsub, conversation_id: str, timeout: float = TIMEOUT_SECONDS, batch_window: float = BATCH_WINDOW_SECONDS) -> dict:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    batch_deadline = None
    raw_payloads = []

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            if raw_payloads:
                break
            return {"message": None, "timed_out": True}

        poll_timeout = remaining
        if batch_deadline is not None:
            batch_remaining = batch_deadline - loop.time()
            if batch_remaining <= 0:
                break
            poll_timeout = min(poll_timeout, batch_remaining)

        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=min(poll_timeout, 1.0))
        if msg is None:
            if raw_payloads:
                break
            continue

        raw_data = msg.get("data")
        if isinstance(raw_data, bytes):
            raw_data = raw_data.decode("utf-8")
        try:
            payload = json.loads(raw_data)
        except (json.JSONDecodeError, TypeError):
            continue

        if payload.get("conversation_id") != conversation_id:
            continue

        raw_payloads.append(payload)
        if batch_deadline is None:
            batch_deadline = loop.time() + batch_window

    messages = [str(p.get("message", "")).strip() for p in raw_payloads if p.get("message")]
    return {
        "message": "\n\n".join(m for m in messages if m),
        "timed_out": False,
        "raw_payloads": raw_payloads,
    }


async def inject(client, conversation_id: str, text: str) -> str:
    payload = {
        "conversation_id": conversation_id,
        "customer_phone": "+34600111333",
        "message_text": text,
        "sender_name": "María García",
        "customer_name": "María García",
        "is_audio_transcription": False,
        "audio_url": None,
    }
    return await client.xadd(INCOMING_STREAM, {"data": json.dumps(payload)})


async def run_addon_rejection_test():
    """
    Fresh conversation specifically testing the add-on rejection path and Fix 3.
    Scenario: User declines add-ons repeatedly to test if bot escalates or loops.
    """
    settings = get_settings()
    redis_url = settings.REDIS_URL.replace("redis://redis:", "redis://localhost:")
    redis_password = settings.REDIS_PASSWORD

    conn_kwargs = {"decode_responses": True, "retry_on_timeout": True}
    if redis_password:
        conn_kwargs["password"] = redis_password

    client = redis_async.from_url(redis_url, **conn_kwargs)
    conversation_id = f"qa-maria-addon-{uuid.uuid4().hex[:10]}"

    print(f"\n{'='*60}")
    print(f"FIX 3 TEST: Add-on loop / Bounded Retry Escalation")
    print(f"Conversation ID: {conversation_id}")
    print(f"{'='*60}\n")

    pubsub = client.pubsub()
    await pubsub.subscribe(RESPONSE_CHANNEL)
    await asyncio.sleep(0.3)

    turns_log = []
    consecutive_same_topic = 0
    last_topic = None

    # We'll do a fast-path booking to reach the add-on stage
    fast_turns = [
        "Hola, quiero turno para corte de dama para el jueves.",
        "Dama",
        "Cualquiera",
        "1",  # Pick first slot
        "María García",
        "+34600111333",
    ]

    print("[FAST PATH] Reaching add-on stage...")
    for i, msg in enumerate(fast_turns, 1):
        await inject(client, conversation_id, msg)
        resp = await subscribe_and_wait(pubsub, conversation_id, timeout=30, batch_window=3.0)
        bot = resp.get("message", "TIMEOUT")
        print(f"  T{i} USER: {msg}")
        print(f"  T{i}  BOT: {str(bot)[:100]}...")
        turns_log.append({"turn": i, "user": msg, "bot": bot})

    # Now we should be at add-on stage or confirmation. Test declining add-ons 3x
    print("\n[FIX 3 TEST] Declining add-ons 3 times to test dead-loop detection...")

    addon_bugs = []
    for attempt in range(1, 5):
        user_msg = "No, gracias, no quiero ningún adicional."
        print(f"\n  [ADDON T{attempt}] USER → {user_msg}")
        await inject(client, conversation_id, user_msg)
        resp = await subscribe_and_wait(pubsub, conversation_id, timeout=30, batch_window=3.0)
        bot = resp.get("message", "TIMEOUT")
        print(f"  [ADDON T{attempt}]  BOT → {str(bot)[:150]}...")

        # Detect if bot is still asking about add-ons
        addon_keywords = ["adicional", "servicio", "añadir", "agregar", "sumar", "peinado", "barro", "óleo"]
        is_addon_topic = any(kw in str(bot).lower() for kw in addon_keywords)
        completion_keywords = ["confirmado", "agendado", "reservado", "listo", "turno queda", "te esperamos"]
        is_completed = any(kw in str(bot).lower() for kw in completion_keywords)
        escalation_keywords = ["humano", "asesor", "equipo", "persona", "contactar"]
        is_escalated = any(kw in str(bot).lower() for kw in escalation_keywords)

        if is_addon_topic:
            consecutive_same_topic += 1
            if consecutive_same_topic >= 3:
                addon_bugs.append({
                    "category": "dead_loop",
                    "evidence": f"Bot asked about add-ons {consecutive_same_topic} consecutive times after user said 'No'",
                    "turns": list(range(len(turns_log)+1, len(turns_log)+attempt+1))
                })
                print(f"  ⚠️  FIX 3 FAIL: Bot stuck asking add-ons for {consecutive_same_topic} turns!")
        else:
            consecutive_same_topic = 0

        if is_completed:
            print(f"  ✅ BOOKING COMPLETED at add-on attempt {attempt}!")
            turns_log.append({"turn": len(turns_log)+attempt, "user": user_msg, "bot": bot, "outcome": "completed"})
            break
        elif is_escalated:
            print(f"  ✅ ESCALATION at attempt {attempt} — Fix 3 working (escalation triggered)")
            turns_log.append({"turn": len(turns_log)+attempt, "user": user_msg, "bot": bot, "outcome": "escalated"})
            break
        else:
            turns_log.append({"turn": len(turns_log)+attempt, "user": user_msg, "bot": bot})

        if attempt >= 4:
            print(f"  ❌ FIX 3 FAIL: Bot still looping after {attempt} 'No' responses — should have escalated or completed")

    await pubsub.unsubscribe(RESPONSE_CHANNEL)
    await pubsub.aclose()
    await client.aclose()

    fix3_pass = len(addon_bugs) == 0
    print(f"\n{'='*60}")
    print(f"FIX 3 RESULT: {'✅ PASS — No dead loop detected' if fix3_pass else '❌ FAIL — Dead loop detected'}")
    if addon_bugs:
        for bug in addon_bugs:
            print(f"  BUG: {bug['evidence']}")
    print(f"{'='*60}\n")

    return {"fix3_pass": fix3_pass, "addon_bugs": addon_bugs, "turns": turns_log}


if __name__ == "__main__":
    asyncio.run(run_addon_rejection_test())
