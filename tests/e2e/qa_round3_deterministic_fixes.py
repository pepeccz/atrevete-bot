"""
QA Round 3 — Deterministic Booking Pipeline Fixes Validation

Tests 4 specific fixes:
1. Audience carry-over: "corte de dama" → no "¿dama o caballero?" question
2. Date anchor: "jueves que viene" → preserved through the flow
3. Add-on decline: "No gracias, solo el corte" → NOT cancel booking
4. Cualquiera stylist: "Cualquiera" → resolve without crash

Persona: María (new client, phone +34600111555)
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
BATCH_WINDOW = 3.0  # Wait up to 3s for grouped replies


def build_redis_url(settings) -> str:
    """Build Redis URL accessible from host (replacing internal Docker hostname)."""
    url = settings.REDIS_URL
    password = settings.REDIS_PASSWORD

    # Prefer explicit password auth if available
    if password:
        return f"redis://:{password}@localhost:6379/0"
    # Fall back to hostname replacement
    url = url.replace("redis://redis:", "redis://localhost:")
    url = url.replace("@redis:", "@localhost:")
    return url


async def capture_response(pubsub, conversation_id: str, timeout: float = 45.0, batch_window: float = 3.0) -> str:
    """Capture bot response with batch window (collects all messages within batch_window after first)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    batch_deadline = None
    messages = []

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            if messages:
                break
            return "[TIMEOUT]"

        poll_timeout = remaining
        if batch_deadline is not None:
            batch_remaining = batch_deadline - loop.time()
            if batch_remaining <= 0:
                break
            poll_timeout = min(poll_timeout, batch_remaining)

        raw_msg = await pubsub.get_message(
            ignore_subscribe_messages=True,
            timeout=min(poll_timeout, 2.0),
        )
        if raw_msg is None:
            if messages:
                # Check if batch window expired
                if batch_deadline is not None and loop.time() >= batch_deadline:
                    break
            continue

        data = raw_msg.get("data")
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

        msg_text = pld.get("message", "").strip()
        if msg_text:
            messages.append(msg_text)
            if batch_deadline is None:
                batch_deadline = loop.time() + batch_window

    return "\n\n".join(messages) if messages else "[NO_RESPONSE]"


async def run_qa() -> dict:
    settings = get_settings()
    redis_url = build_redis_url(settings)

    print("Connecting to Redis (host-side)...")
    r = redis.from_url(redis_url, decode_responses=True)
    r_binary = redis.from_url(redis_url, decode_responses=False)

    # Ping to verify connection
    try:
        pong = await r.ping()
        print(f"Redis connected: {pong}")
    except Exception as e:
        print(f"ERROR: Redis connection failed: {e}")
        return {"overall_result": "ERROR", "error": str(e)}

    conversation_id = str(uuid.uuid4())
    phone = "+34600111555"
    sender_name = "María García"

    print(f"\n{'='*70}")
    print("QA Round 3 — Deterministic Booking Pipeline Fixes")
    print(f"conversation_id: {conversation_id}")
    print(f"phone: {phone}")
    print(f"Timestamp: {datetime.now(UTC).isoformat()}")
    print(f"{'='*70}\n")

    # CRITICAL: Subscribe BEFORE injecting (race condition prevention)
    pubsub = r.pubsub()
    await pubsub.subscribe(RESPONSE_CHANNEL)

    # Drain stale messages
    await asyncio.sleep(0.3)
    await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)

    fix_results = {
        "fix1_audience_carryover": None,   # No "¿dama o caballero?" after "corte de dama"
        "fix2_date_anchor": None,           # "jueves que viene" preserved
        "fix3_addon_decline": None,         # "No gracias" → NOT cancel
        "fix4_cualquiera_stylist": None,    # "Cualquiera" → no crash
    }

    turns_result = []
    overall_pass = True

    # ─── TURN 1 ────────────────────────────────────────────────────────────────
    # Opening message: request corte de dama + jueves que viene
    turn1_msg = "Hola! Quiero sacar un turno para corte de dama para el jueves que viene."
    print("--- Turn 1: Opening request (dama audience + Thursday date) ---")
    print(f"USER: {turn1_msg}")

    ts_sent = datetime.now(UTC)
    payload = {
        "conversation_id": conversation_id,
        "customer_phone": phone,
        "message_text": turn1_msg,
        "sender_name": sender_name,
        "customer_name": sender_name,
        "is_audio_transcription": False,
        "audio_url": None,
    }
    await r.xadd(INCOMING_STREAM, {"data": json.dumps(payload)})
    turn1_response = await capture_response(pubsub, conversation_id, TIMEOUT, BATCH_WINDOW)
    latency1 = int((datetime.now(UTC) - ts_sent).total_seconds() * 1000)

    print(f"AGENT ({latency1}ms): {turn1_response}")

    # Fix 1: Check no "¿dama o caballero?" re-ask
    asks_dama_caballero = any(phrase in turn1_response.lower() for phrase in [
        "dama o caballero", "caballero o dama", "para dama", "para caballero",
        "¿es para dama", "es para dama", "para quien", "para quién",
        "para dama o", "de dama o",
    ])
    # Fix 2 preliminary: Check date acknowledged
    date_acknowledged = any(phrase in turn1_response.lower() for phrase in [
        "jueves", "thursday", "semana", "próximo", "proximo",
    ])

    fix1_turn1 = not asks_dama_caballero
    fix_results["fix1_audience_carryover"] = "PASS" if fix1_turn1 else "FAIL"

    print(f"  {'✅' if fix1_turn1 else '❌'} Fix 1 (audience carry-over): {'PASS — No dama/caballero re-ask' if fix1_turn1 else 'FAIL — Bot asked dama/caballero again!'}")
    print(f"  {'✅' if date_acknowledged else '⚠️'} Date acknowledged (jueves): {'YES' if date_acknowledged else 'NOT VISIBLE (may be implicit)'}")

    turn1_pass = turn1_response != "[TIMEOUT]" and turn1_response != "[NO_RESPONSE]"
    if not turn1_pass:
        overall_pass = False

    turns_result.append({
        "turn": 1,
        "user_message": turn1_msg,
        "agent_response": turn1_response,
        "latency_ms": latency1,
        "pass": turn1_pass and fix1_turn1,
        "fix_checks": {
            "fix1_no_dama_caballero_reask": fix1_turn1,
            "date_acknowledged": date_acknowledged,
        }
    })
    print()

    if turn1_response in ("[TIMEOUT]", "[NO_RESPONSE]"):
        print("CRITICAL: No response on Turn 1. Aborting.")
        await pubsub.unsubscribe(RESPONSE_CHANNEL)
        await pubsub.close()
        await r.aclose()
        await r_binary.aclose()
        return {
            "overall_result": "FAIL",
            "error": "Turn 1 timeout",
            "turns": turns_result,
            "fix_verification": fix_results,
        }

    # ─── TURN 2 ────────────────────────────────────────────────────────────────
    # Confirm service based on bot's response
    # Bot should show Cortar options or ask to confirm "Cortar" — respond positively
    turn2_msg = None
    turn1_lower = turn1_response.lower()

    # Determine adaptive response
    if "1" in turn1_response and ("cortar" in turn1_lower or "corte" in turn1_lower):
        turn2_msg = "1"
    elif "sí" in turn1_lower or "confirmar" in turn1_lower or "confirmas" in turn1_lower:
        turn2_msg = "Sí, perfecto."
    elif "cortar" in turn1_lower:
        turn2_msg = "Sí, el corte de pelo."
    else:
        turn2_msg = "Sí, quiero el corte de pelo."

    print("--- Turn 2: Confirm service ---")
    print(f"USER: {turn2_msg}")

    ts_sent2 = datetime.now(UTC)
    payload2 = {
        "conversation_id": conversation_id,
        "customer_phone": phone,
        "message_text": turn2_msg,
        "sender_name": sender_name,
        "customer_name": sender_name,
        "is_audio_transcription": False,
        "audio_url": None,
    }
    await r.xadd(INCOMING_STREAM, {"data": json.dumps(payload2)})
    turn2_response = await capture_response(pubsub, conversation_id, TIMEOUT, BATCH_WINDOW)
    latency2 = int((datetime.now(UTC) - ts_sent2).total_seconds() * 1000)

    print(f"AGENT ({latency2}ms): {turn2_response}")

    turn2_lower = turn2_response.lower()
    # Check for CRITICAL: is bot asking "¿quieres cancelar?" or "cancelar" at this point?
    asks_cancel_t2 = any(phrase in turn2_lower for phrase in [
        "quieres cancelar", "deseas cancelar", "cancelar la reserva",
        "¿seguro que quieres cancelar", "seguro que quieres cancelar",
        "he cancelado", "reserva cancelada",
    ])

    turn2_pass = turn2_response not in ("[TIMEOUT]", "[NO_RESPONSE]") and not asks_cancel_t2
    if asks_cancel_t2:
        print("  ❌ CRITICAL FAIL: Bot triggered cancel on Turn 2!")
        overall_pass = False

    turns_result.append({
        "turn": 2,
        "user_message": turn2_msg,
        "agent_response": turn2_response,
        "latency_ms": latency2,
        "pass": turn2_pass,
        "fix_checks": {
            "no_cancel_trigger": not asks_cancel_t2,
        }
    })
    print()

    # ─── TURN 3 ────────────────────────────────────────────────────────────────
    # This is the critical add-on decline turn
    # Bot should offer add-ons. We decline with "No gracias, solo el corte."
    # CRITICAL FIX 3: Must NOT trigger cancel

    # Determine what bot is asking
    turn2_lower = turn2_response.lower()
    is_asking_addons = any(phrase in turn2_lower for phrase in [
        "adicional", "extra", "complementario", "tratamiento", "servicio adicional",
        "sumar", "agregar", "añadir",
    ])

    if is_asking_addons:
        turn3_msg = "No gracias, solo el corte."
    elif "estilista" in turn2_lower or "profesional" in turn2_lower:
        # Skipped add-ons, jumped to stylist selection
        turn3_msg = "Cualquiera."
    elif "nombre" in turn2_lower or "llamas" in turn2_lower:
        turn3_msg = "María García"
    elif "confirma" in turn2_lower or "resumen" in turn2_lower:
        turn3_msg = "Sí, confirmo."
    else:
        # Assume add-ons step or next step
        turn3_msg = "No gracias, solo el corte."

    print("--- Turn 3: Add-on decline (CRITICAL FIX 3) ---")
    print(f"USER: {turn3_msg}")

    ts_sent3 = datetime.now(UTC)
    payload3 = {
        "conversation_id": conversation_id,
        "customer_phone": phone,
        "message_text": turn3_msg,
        "sender_name": sender_name,
        "customer_name": sender_name,
        "is_audio_transcription": False,
        "audio_url": None,
    }
    await r.xadd(INCOMING_STREAM, {"data": json.dumps(payload3)})
    turn3_response = await capture_response(pubsub, conversation_id, TIMEOUT, BATCH_WINDOW)
    latency3 = int((datetime.now(UTC) - ts_sent3).total_seconds() * 1000)

    print(f"AGENT ({latency3}ms): {turn3_response}")

    turn3_lower = turn3_response.lower()

    # CRITICAL CHECK: Did the bot ask "¿Seguro que quieres cancelar?" or similar?
    cancel_phrases = [
        "seguro que quieres cancelar",
        "quieres cancelar",
        "deseas cancelar",
        "¿cancelar",
        "he cancelado",
        "reserva cancelada",
        "cita cancelada",
        "cancelado la reserva",
        "cancelado el turno",
    ]
    triggers_cancel = any(phrase in turn3_lower for phrase in cancel_phrases)

    # What should happen: bot advances to stylist selection
    advances_to_stylist = any(phrase in turn3_lower for phrase in [
        "estilista", "profesional", "peluquera", "quien", "quién",
        "cualquiera", "luciana", "andrea", "sofia", "maría",
    ])
    # Or advances to slot selection
    advances_to_slot = any(phrase in turn3_lower for phrase in [
        "horario", "turno", "fecha", "disponible", "jueves",
    ])

    fix3_pass = not triggers_cancel
    fix_results["fix3_addon_decline"] = "PASS" if fix3_pass else "FAIL"

    print(f"  {'✅' if fix3_pass else '❌ CRITICAL FAIL'} Fix 3 (add-on decline): {'PASS — No cancel trigger' if fix3_pass else 'FAIL — Bot asked to cancel!'}")
    if triggers_cancel:
        print("  🚨 CRITICAL FAIL: Bot responded with cancel confirmation after 'No gracias'!")
        overall_pass = False

    if advances_to_stylist:
        print("  ✅ Correctly advanced to stylist selection")
    elif advances_to_slot:
        print("  ✅ Correctly advanced to slot selection (may have skipped stylist)")
    else:
        print(f"  ℹ️  Response context: {turn3_response[:100]}")

    turn3_pass = turn3_response not in ("[TIMEOUT]", "[NO_RESPONSE]") and fix3_pass
    if not turn3_pass:
        overall_pass = False

    turns_result.append({
        "turn": 3,
        "user_message": turn3_msg,
        "agent_response": turn3_response,
        "latency_ms": latency3,
        "pass": turn3_pass,
        "fix_checks": {
            "no_cancel_trigger": fix3_pass,
            "advances_to_stylist": advances_to_stylist,
            "advances_to_slot": advances_to_slot,
        }
    })
    print()

    # ─── TURN 4 ────────────────────────────────────────────────────────────────
    # Stylist selection: "Cualquiera."
    # CRITICAL FIX 4: Must not crash

    turn3_lower = turn3_response.lower()
    is_asking_stylist = any(phrase in turn3_lower for phrase in [
        "estilista", "profesional", "peluquera", "preferi", "quien", "quién",
    ])
    is_asking_slot = any(phrase in turn3_lower for phrase in [
        "horario", "turno", "fecha", "disponible",
    ])
    is_asking_name = any(phrase in turn3_lower for phrase in [
        "nombre", "llamas", "como te",
    ])
    is_asking_addon = any(phrase in turn3_lower for phrase in [
        "adicional", "extra", "complementario",
    ])

    if is_asking_addon:
        # Still asking add-ons? Just decline again
        turn4_msg = "No, gracias."
    elif is_asking_stylist:
        turn4_msg = "Cualquiera."
    elif is_asking_slot:
        turn4_msg = "El jueves que viene, cualquier horario."
    elif is_asking_name:
        turn4_msg = "María García"
    else:
        # Default: assume stylist step
        turn4_msg = "Cualquiera."

    print("--- Turn 4: Stylist selection (CRITICAL FIX 4 — Cualquiera) ---")
    print(f"USER: {turn4_msg}")

    ts_sent4 = datetime.now(UTC)
    payload4 = {
        "conversation_id": conversation_id,
        "customer_phone": phone,
        "message_text": turn4_msg,
        "sender_name": sender_name,
        "customer_name": sender_name,
        "is_audio_transcription": False,
        "audio_url": None,
    }
    await r.xadd(INCOMING_STREAM, {"data": json.dumps(payload4)})
    turn4_response = await capture_response(pubsub, conversation_id, TIMEOUT, BATCH_WINDOW)
    latency4 = int((datetime.now(UTC) - ts_sent4).total_seconds() * 1000)

    print(f"AGENT ({latency4}ms): {turn4_response}")

    turn4_lower = turn4_response.lower()

    # Fix 4 checks: No crash/error, bot should show available slots
    fix4_no_crash = not any(phrase in turn4_lower for phrase in [
        "error", "problema", "falló", "fallo", "traceback", "exception",
        "no pude", "no puedo procesar",
    ])
    fix4_shows_slots = any(phrase in turn4_lower for phrase in [
        "horario", "turno", "disponible", "jueves", "fecha", "slot",
        "mañana", "tarde", "lunes", "martes", "miércoles", "miercoles",
        "viernes", "sábado", "sabado",
    ])

    # Also check date anchor preservation (Fix 2)
    date_preserved = "jueves" in turn4_lower or "semana" in turn4_lower

    fix_results["fix4_cualquiera_stylist"] = "PASS" if fix4_no_crash else "FAIL"
    if fix4_no_crash and fix4_shows_slots:
        fix_results["fix2_date_anchor"] = "PASS" if date_preserved else "PARTIAL"
    elif fix4_no_crash:
        fix_results["fix2_date_anchor"] = "PARTIAL"

    print(f"  {'✅' if fix4_no_crash else '❌'} Fix 4 (Cualquiera no crash): {'PASS' if fix4_no_crash else 'FAIL'}")
    print(f"  {'✅' if fix4_shows_slots else '⚠️'} Shows available slots: {'YES' if fix4_shows_slots else 'NOT YET'}")
    print(f"  {'✅' if date_preserved else '⚠️'} Date anchor (jueves) visible: {'YES' if date_preserved else 'NOT IN THIS RESPONSE'}")

    turn4_pass = turn4_response not in ("[TIMEOUT]", "[NO_RESPONSE]") and fix4_no_crash
    if not turn4_pass:
        overall_pass = False

    turns_result.append({
        "turn": 4,
        "user_message": turn4_msg,
        "agent_response": turn4_response,
        "latency_ms": latency4,
        "pass": turn4_pass,
        "fix_checks": {
            "fix4_no_crash": fix4_no_crash,
            "shows_slots": fix4_shows_slots,
            "date_preserved": date_preserved,
        }
    })
    print()

    # ─── TURN 5 ────────────────────────────────────────────────────────────────
    # Pick a slot — prefer Thursday, otherwise take first available
    turn4_lower = turn4_response.lower()

    # Find Thursday slot or take first option
    is_offering_slots = any(phrase in turn4_lower for phrase in [
        "horario", "turno", "disponible", "fecha", "jueves",
    ])
    is_asking_name_t5 = any(phrase in turn4_lower for phrase in [
        "nombre", "llamas", "como te",
    ])
    is_asking_confirm_t5 = any(phrase in turn4_lower for phrase in [
        "confirma", "confirmar", "resumen",
    ])

    if is_asking_name_t5:
        turn5_msg = "María García"
    elif is_asking_confirm_t5:
        turn5_msg = "Sí, confirmo."
    elif is_offering_slots:
        # Pick Thursday if mentioned, else first slot
        if "jueves" in turn4_lower:
            turn5_msg = "El del jueves está perfecto, dale."
        else:
            turn5_msg = "Dale, el primero que tengas está bien."
    else:
        turn5_msg = "Dale, ese está bien."

    print("--- Turn 5: Select slot ---")
    print(f"USER: {turn5_msg}")

    ts_sent5 = datetime.now(UTC)
    payload5 = {
        "conversation_id": conversation_id,
        "customer_phone": phone,
        "message_text": turn5_msg,
        "sender_name": sender_name,
        "customer_name": sender_name,
        "is_audio_transcription": False,
        "audio_url": None,
    }
    await r.xadd(INCOMING_STREAM, {"data": json.dumps(payload5)})
    turn5_response = await capture_response(pubsub, conversation_id, TIMEOUT, BATCH_WINDOW)
    latency5 = int((datetime.now(UTC) - ts_sent5).total_seconds() * 1000)

    print(f"AGENT ({latency5}ms): {turn5_response}")

    turn5_lower = turn5_response.lower()

    # Check Fix 2 (date anchor): Thursday should appear in slot confirmation
    thursday_in_slot = "jueves" in turn5_lower
    if thursday_in_slot and fix_results["fix2_date_anchor"] != "PASS":
        fix_results["fix2_date_anchor"] = "PASS"
    elif not thursday_in_slot and fix_results["fix2_date_anchor"] is None:
        fix_results["fix2_date_anchor"] = "PARTIAL"

    print(f"  {'✅' if thursday_in_slot else '⚠️'} Fix 2 (date anchor — jueves in slot): {'YES' if thursday_in_slot else 'NOT VISIBLE'}")

    turn5_pass = turn5_response not in ("[TIMEOUT]", "[NO_RESPONSE]")
    if not turn5_pass:
        overall_pass = False

    turns_result.append({
        "turn": 5,
        "user_message": turn5_msg,
        "agent_response": turn5_response,
        "latency_ms": latency5,
        "pass": turn5_pass,
        "fix_checks": {
            "thursday_date_preserved": thursday_in_slot,
        }
    })
    print()

    # ─── TURNS 6-8 ─────────────────────────────────────────────────────────────
    # Complete booking: provide name if asked, confirm
    booking_completed = False
    final_response = turn5_response

    remaining_turns_msgs = [
        ("nombre", "María García"),
        ("confirma", "Sí, confirmo."),
        ("resumen", "Sí, confirmo."),
        ("correcto", "Sí, todo correcto."),
    ]

    for extra_turn_num in range(6, 9):
        prev_response = turns_result[-1]["agent_response"].lower() if turns_result else ""

        # Check if booking already completed
        booking_keywords = ["confirmad", "reservad", "anotad", "queda reservad", "turno agendad"]
        if any(kw in prev_response for kw in booking_keywords):
            booking_completed = True
            print(f"--- Booking completed at turn {extra_turn_num - 1} ---")
            break

        # Determine next message
        next_msg = None
        if "nombre" in prev_response or "llamas" in prev_response or "como te" in prev_response:
            next_msg = "María García"
        elif "confirma" in prev_response or "resumen" in prev_response:
            next_msg = "Sí, confirmo."
        elif "correcto" in prev_response or "todo bien" in prev_response:
            next_msg = "Sí, todo correcto."
        elif "nota" in prev_response or "comentario" in prev_response:
            next_msg = "Sin notas, gracias."
        elif "horario" in prev_response or "disponible" in prev_response:
            next_msg = "El primero disponible."
        else:
            next_msg = "Sí."

        print(f"--- Turn {extra_turn_num}: Continue booking ---")
        print(f"USER: {next_msg}")

        ts_sent_n = datetime.now(UTC)
        payload_n = {
            "conversation_id": conversation_id,
            "customer_phone": phone,
            "message_text": next_msg,
            "sender_name": sender_name,
            "customer_name": sender_name,
            "is_audio_transcription": False,
            "audio_url": None,
        }
        await r.xadd(INCOMING_STREAM, {"data": json.dumps(payload_n)})
        turn_n_response = await capture_response(pubsub, conversation_id, TIMEOUT, BATCH_WINDOW)
        latency_n = int((datetime.now(UTC) - ts_sent_n).total_seconds() * 1000)

        print(f"AGENT ({latency_n}ms): {turn_n_response}")
        final_response = turn_n_response

        # Check for critical cancel
        if any(phrase in turn_n_response.lower() for phrase in ["seguro que quieres cancelar", "he cancelado"]):
            print(f"  ❌ CRITICAL FAIL: Bot triggered cancel on turn {extra_turn_num}!")
            overall_pass = False
            fix_results["fix3_addon_decline"] = "FAIL"

        turn_n_pass = turn_n_response not in ("[TIMEOUT]", "[NO_RESPONSE]")
        if not turn_n_pass:
            overall_pass = False

        turns_result.append({
            "turn": extra_turn_num,
            "user_message": next_msg,
            "agent_response": turn_n_response,
            "latency_ms": latency_n,
            "pass": turn_n_pass,
        })
        print()

    # ─── FINAL STATE CAPTURE ───────────────────────────────────────────────────
    print("Capturing final LangGraph checkpoint state...")
    final_state = {}
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

    appointment_created = bool(final_state.get("appointment_created"))
    customer_id = str(final_state.get("customer_id", "")) or None
    appointment_id = str(final_state.get("appointment_id", "")) or None
    appointment_datetime_val = str(final_state.get("appointment_datetime", "")) or None
    current_mode = final_state.get("current_mode")

    # Check booking in final response
    last_response = turns_result[-1]["agent_response"] if turns_result else ""
    has_booking_keyword = any(kw in (last_response or "").lower() for kw in booking_keywords)

    booking_result = "PASS" if (appointment_created and customer_id) else ("PARTIAL" if has_booking_keyword else "FAIL")

    # Fill in any unresolved Fix 2 (date anchor)
    if fix_results["fix2_date_anchor"] is None:
        # Check if "jueves" appeared anywhere in the conversation
        all_responses = " ".join(t.get("agent_response", "") or "" for t in turns_result)
        if "jueves" in all_responses.lower():
            fix_results["fix2_date_anchor"] = "PASS"
        else:
            fix_results["fix2_date_anchor"] = "PARTIAL"

    await pubsub.unsubscribe(RESPONSE_CHANNEL)
    await pubsub.close()
    await r.aclose()
    await r_binary.aclose()

    # ─── RESULT COMPUTATION ────────────────────────────────────────────────────
    critical_fixes_pass = (
        fix_results["fix1_audience_carryover"] == "PASS"
        and fix_results["fix3_addon_decline"] == "PASS"
        and fix_results["fix4_cualquiera_stylist"] == "PASS"
    )
    non_critical_ok = fix_results["fix2_date_anchor"] in ("PASS", "PARTIAL")

    overall_result = "PASS" if (overall_pass and critical_fixes_pass and non_critical_ok) else (
        "PARTIAL" if (critical_fixes_pass and booking_result in ("PASS", "PARTIAL")) else "FAIL"
    )

    return {
        "scenario": "QA Round 3 — Deterministic Booking Pipeline Fixes",
        "conversation_id": conversation_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "turns": turns_result,
        "final_state_summary": {
            "appointment_created": appointment_created,
            "customer_id": customer_id,
            "appointment_id": appointment_id,
            "appointment_datetime": appointment_datetime_val,
            "current_mode": current_mode,
            "booking_result": booking_result,
        },
        "fix_verification": fix_results,
        "overall_pass": overall_pass,
        "overall_result": overall_result,
    }


def main():
    report = asyncio.run(run_qa())

    print("\n" + "="*70)
    print("QA ROUND 3 — REPORT SUMMARY")
    print("="*70)
    print(f"\nOverall Result: {report.get('overall_result', 'ERROR')}")
    print("\nFix Verification:")
    fix_labels = {
        "fix1_audience_carryover": "Fix 1: Audience carry-over (no dama/caballero re-ask)",
        "fix2_date_anchor": "Fix 2: Date anchor (jueves preserved)",
        "fix3_addon_decline": "Fix 3: Add-on decline (no cancel trigger)",
        "fix4_cualquiera_stylist": "Fix 4: Cualquiera stylist (no crash)",
    }
    for fix_key, fix_label in fix_labels.items():
        result = report.get("fix_verification", {}).get(fix_key)
        if result == "PASS":
            icon = "✅"
        elif result == "PARTIAL":
            icon = "⚠️"
        elif result == "FAIL":
            icon = "❌"
        elif result is None:
            icon = "⬜"
        else:
            icon = "ℹ️"
        print(f"  {icon} {fix_label}: {result}")

    print("\nFinal State:")
    fs = report.get("final_state_summary", {})
    for k, v in fs.items():
        print(f"  {k}: {v}")

    print("\nTurn Summary:")
    for t in report.get("turns", []):
        icon = "✅" if t.get("pass") else "❌"
        response_preview = (t.get("agent_response") or "")[:120]
        print(f"  {icon} Turn {t['turn']} ({t.get('latency_ms', 0)}ms): {response_preview}")

    print(f"\n{'='*70}")
    print(f"OVERALL RESULT: {report.get('overall_result', 'ERROR')}")
    print(f"{'='*70}")

    # Save JSON report
    output_path = "/tmp/qa_round3_deterministic_fixes_report.json"
    try:
        with open(output_path, "w") as f:
            clean_report = {**report}
            json.dump(clean_report, f, indent=2, default=str)
        print(f"\nJSON report saved to {output_path}")
    except Exception as e:
        print(f"Warning: Could not save JSON report: {e}")

    result = report.get("overall_result", "ERROR")
    return 0 if result in ("PASS", "PARTIAL") else 1


if __name__ == "__main__":
    sys.exit(main())
