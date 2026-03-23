"""
QA Round 6 — returning_client / carlos_returning_client
Harness script that runs inside Docker where Redis is at redis://redis:6379/0
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

INCOMING_STREAM = "incoming_messages_stream"
OUTGOING_CHANNEL = "outgoing_messages"
REDIS_URL = "redis://:9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda@redis:6379/0"

PERSONA = {
    "name": "Carlos López",
    "phone": "+34600123456",
}

# Strict harness script per task instructions
TURNS = [
    "Hola, quiero un corte caballero con Luciana esta semana a la mañana",
    # T2-T7 are conditional — handled by the logic below
]


async def run_qa() -> dict[str, Any]:
    conversation_id = str(uuid.uuid4())
    print(f"[QA-R6] conversation_id={conversation_id}", flush=True)

    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = client.pubsub()
    # CRITICAL: subscribe BEFORE injecting any message
    await pubsub.subscribe(OUTGOING_CHANNEL)
    # Drain subscribe ACK message
    await asyncio.sleep(0.2)

    turns_result = []
    max_turns = 12
    turn_count = 0

    # Predefined harness script
    harness = {
        "t1": "Hola, quiero un corte caballero con Luciana la semana que viene a la mañana",
        "variant": "Caballero",
        "slot": "1",
        "addon": "No gracias",
        "name": "Carlos López",
        "notes": "Sin notas",
        "confirm": "Sí, confirmo",
    }

    # State machine for adaptive turn selection
    next_message = harness["t1"]
    pending_addon = False
    pending_name = False
    pending_notes = False
    pending_confirm = False
    booking_done = False

    async def inject_and_capture(msg: str, turn_num: int) -> dict[str, Any]:
        payload = {
            "conversation_id": conversation_id,
            "customer_phone": PERSONA["phone"],
            "message_text": msg,
            "sender_name": PERSONA["name"],
            "customer_name": PERSONA["name"],
            "is_audio_transcription": False,
            "audio_url": None,
        }
        ts_sent = datetime.now(UTC).isoformat()
        await client.xadd(INCOMING_STREAM, {"data": json.dumps(payload)})
        print(f"  [T{turn_num}] USER: {msg}", flush=True)

        # Wait for matching response
        deadline = asyncio.get_event_loop().time() + 30.0
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"Timeout waiting for response on turn {turn_num}")
            raw = await pubsub.get_message(ignore_subscribe_messages=True, timeout=min(remaining, 2.0))
            if raw is None:
                continue
            data = raw.get("data", "")
            if isinstance(data, bytes):
                data = data.decode()
            parsed = json.loads(data)
            if parsed.get("conversation_id") != conversation_id:
                continue
            ts_recv = datetime.now(UTC).isoformat()
            sent_dt = datetime.fromisoformat(ts_sent)
            recv_dt = datetime.fromisoformat(ts_recv)
            latency = int((recv_dt - sent_dt).total_seconds() * 1000)
            agent_msg = parsed.get("message", "")
            print(f"  [T{turn_num}] AGENT ({latency}ms): {agent_msg[:200]}", flush=True)
            return {
                "turn_number": turn_num,
                "user_message": msg,
                "agent_response": agent_msg,
                "response_latency_ms": latency,
                "timestamp_sent": ts_sent,
                "timestamp_received": ts_recv,
            }

    try:
        # T1 — always send opening message
        turn_count += 1
        result = await inject_and_capture(harness["t1"], turn_count)
        turns_result.append(result)
        agent_resp = result["agent_response"].lower()

        # Determine subsequent turns based on agent responses
        while turn_count < max_turns and not booking_done:
            next_msg = None
            agent_lower = agent_resp

            # Check for booking completion signals
            if any(kw in agent_lower for kw in ["turno confirmado", "reserva confirmada", "tu cita", "agendado", "te esperamos", "confirmamos"]):
                print(f"  [QA] Booking completion detected!", flush=True)
                booking_done = True
                break

            # Check what the agent is asking for
            if any(kw in agent_lower for kw in ["qué tipo", "caballero o dama", "para caballero o dama", "para dama", "hombre o mujer", "niño", "niña", "bebé", "para un *caballero*", "para un caballero"]):
                next_msg = harness["variant"]
            elif any(kw in agent_lower for kw in ["cuál preferís", "qué horario", "seleccioná", "elegí", "elige", "horario disponible", "slot", "1️⃣", "1."]):
                next_msg = harness["slot"]
            elif any(kw in agent_lower for kw in ["add-on", "adicional", "tratamiento", "mascarilla", "hidratación", "¿querés sumar"]):
                next_msg = harness["addon"]
            elif any(kw in agent_lower for kw in ["tu nombre", "cómo te llamás", "nombre completo", "nombre?"]):
                next_msg = harness["name"]
            elif any(kw in agent_lower for kw in ["alguna nota", "notas adicionales", "observaciones", "¿algún comentario"]):
                next_msg = harness["notes"]
            elif any(kw in agent_lower for kw in ["confirmás", "confirmar", "¿confirmamos", "¿todo bien", "¿está bien", "¿correcto", "¿confirmo", "¿confirmás"]):
                next_msg = harness["confirm"]
            elif any(kw in agent_lower for kw in ["¿te parece bien", "te parece bien", "¿buscamos", "quieres que busque", "¿querés que busque"]):
                next_msg = "Sí, dale"
            elif any(kw in agent_lower for kw in ["reserva", "cita", "turno", "agenda"]) and turn_count >= 3:
                # If agent is presenting a booking summary
                if any(kw in agent_lower for kw in ["luciana", "corte", "lunes", "martes", "miércoles", "jueves", "viernes"]):
                    next_msg = harness["confirm"]

            if next_msg is None:
                print(f"  [QA] No matching harness rule for turn {turn_count+1}, agent said: {agent_resp[:100]}", flush=True)
                # Generic affirmative response — the agent is asking permission/confirmation
                next_msg = "Sí"

            turn_count += 1
            result = await inject_and_capture(next_msg, turn_count)
            turns_result.append(result)
            agent_resp = result["agent_response"].lower()

    except TimeoutError as e:
        print(f"  [QA] TIMEOUT: {e}", flush=True)
        turns_result.append({"turn_number": turn_count, "error": str(e)})
    finally:
        await pubsub.unsubscribe(OUTGOING_CHANNEL)
        await pubsub.close()

    # DB check
    appointment_count = 0
    try:
        import asyncpg
        db_url = "postgresql://atrevete:a3f7c2e9d1b8f4a6c5e2d9b3f8a1c4e7@postgres:5432/atrevete_db"
        conn = await asyncpg.connect(db_url)
        row = await conn.fetchrow(
            "SELECT count(*) as cnt FROM appointments WHERE created_at > now() - interval '1 hour'"
        )
        appointment_count = row["cnt"]
        print(f"  [QA] DB appointments in last 1h: {appointment_count}", flush=True)
        await conn.close()
    except Exception as e:
        print(f"  [QA] DB check failed: {e}", flush=True)
        appointment_count = -1

    await client.close()

    # Determine milestones
    all_responses = " ".join(t.get("agent_response", "").lower() for t in turns_result)
    milestones_hit = []
    if turn_count >= 1:
        milestones_hit.append("greeting_done")
    if any(kw in all_responses for kw in ["luciana", "estilista", "con luciana"]):
        milestones_hit.append("stylist_locked")
    if any(kw in all_responses for kw in ["corte", "caballero"]):
        milestones_hit.append("service_resolved")
    if any(kw in all_responses for kw in ["lunes", "martes", "miércoles", "jueves", "viernes", "mañana"]):
        milestones_hit.append("slot_resolved")
    if booking_done or any(kw in all_responses for kw in ["confirmado", "confirmamos", "tu cita", "te esperamos", "agendado"]):
        milestones_hit.append("confirmation_done")
        milestones_hit.append("booking_completed")

    appointment_in_db = appointment_count > 0 if appointment_count >= 0 else False
    passed = booking_done and appointment_in_db

    result_summary = {
        "scenario_id": "returning_client",
        "persona_id": "carlos_returning_client",
        "conversation_id": conversation_id,
        "status": "PASS" if passed else "FAIL",
        "turn_count": turn_count,
        "booking_done": booking_done,
        "appointment_in_db": appointment_in_db,
        "appointments_created_last_hour": appointment_count,
        "milestones_hit": milestones_hit,
        "turns": turns_result,
    }

    print("\n" + "="*60, flush=True)
    print(json.dumps(result_summary, indent=2, ensure_ascii=False), flush=True)
    return result_summary


if __name__ == "__main__":
    asyncio.run(run_qa())
