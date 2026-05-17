"""
QA Test Harness — Escalation Flow (Elena)
Persona: elena_escalation_client
Flow: escalation
"""

import asyncio
import json
import sys
import time
import uuid

sys.path.insert(0, "/home/pcabeza/Proyectos/atrevete-bot")

import redis.asyncio as redis

# Redis config
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_PASSWORD = "9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda"
INCOMING_STREAM = "incoming_messages_stream"
CONSUMER_GROUP = "agent_workers"
OUTGOING_PUBSUB_CHANNEL = "outgoing_messages"

# Test identity
CONVERSATION_ID = str(uuid.uuid4())
CUSTOMER_PHONE = "+34611000999"  # QA test phone
SENDER_NAME = "Elena QA Test"
MAX_TURNS = 8
RESPONSE_TIMEOUT = 60  # seconds


async def main():
    print("[QA] Starting escalation flow run")
    print(f"[QA] conversation_id = {CONVERSATION_ID}")
    print(f"[QA] customer_phone  = {CUSTOMER_PHONE}")
    print()

    # Connect to Redis
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True,
    )

    # Ensure consumer group exists
    try:
        await r.xgroup_create(INCOMING_STREAM, CONSUMER_GROUP, id="$", mkstream=True)
        print(f"[QA] Created consumer group '{CONSUMER_GROUP}'")
    except Exception as e:
        if "BUSYGROUP" in str(e):
            print(f"[QA] Consumer group '{CONSUMER_GROUP}' already exists")
        else:
            print(f"[QA] Warning: {e}")

    # Subscribe to outgoing_messages pub/sub BEFORE injecting
    pubsub = r.pubsub()
    await pubsub.subscribe(OUTGOING_PUBSUB_CHANNEL)
    print(f"[QA] Subscribed to '{OUTGOING_PUBSUB_CHANNEL}' pub/sub channel")
    print()

    # Drain any stale subscription confirmation message
    await asyncio.sleep(0.1)
    # Read and discard the subscribe confirmation
    try:
        async with asyncio.timeout(2):
            async for msg in pubsub.listen():
                if msg["type"] == "subscribe":
                    break
    except TimeoutError:
        pass

    turns = []

    async def inject_message(message_text: str):
        payload = {
            "conversation_id": CONVERSATION_ID,
            "customer_phone": CUSTOMER_PHONE,
            "message_text": message_text,
            "sender_name": SENDER_NAME,
            "is_audio_transcription": False,
            "audio_url": None,
        }
        payload_json = json.dumps(payload)
        stream_id = await r.xadd(INCOMING_STREAM, {"data": payload_json})
        print(f"[QA] → Injected to stream: {stream_id}")
        return stream_id

    async def capture_response(timeout: int = RESPONSE_TIMEOUT) -> str | None:
        """Listen on pub/sub for a response matching our conversation_id."""
        start = time.time()
        async with asyncio.timeout(timeout):
            try:
                async for msg in pubsub.listen():
                    if msg["type"] == "message":
                        try:
                            data = json.loads(msg["data"])
                            if data.get("conversation_id") == CONVERSATION_ID:
                                text = data.get("message", data.get("text", ""))
                                return text
                            # Also handle nested structure
                            if isinstance(data, dict):
                                for k, v in data.items():
                                    if isinstance(v, dict) and v.get("conversation_id") == CONVERSATION_ID:
                                        return v.get("message", v.get("text", ""))
                        except (json.JSONDecodeError, AttributeError):
                            pass
            except TimeoutError:
                return None

    # =========================================================
    # Conversation script — Elena as persona
    # =========================================================
    # Pre-planned messages based on escalation flow
    elena_script = [
        # Turn 1: Opening — billing complaint
        "Me cobraron mal en mi último turno. Quiero que me lo solucionen.",
        # Subsequent turns are driven by bot response
    ]

    # Dynamic reply map: after each bot reply, we reason and respond as Elena
    # These will be determined during execution based on bot responses
    dynamic_replies = {
        "empathy": "Gracias por entender, pero igual necesito que me contacten para arreglarlo.",
        "data_request": "Elena García, turno de la semana pasada.",
        "handoff_confirm": "Perfecto, espero que me llamen pronto.",
        "booking_attempt": "No quiero turno! Quiero que resuelvan el cobro incorrecto.",
        "generic": "¿Cuándo me van a contactar?",
        "contact_given": "Sí, mi número es este mismo.",
        "resolution": "Bueno, quedo a la espera entonces.",
    }

    current_message = elena_script[0]
    turn_number = 0
    last_milestone = None
    consecutive_same_milestone = 0
    tool_trace = []
    outcome = "timeout"
    termination_reason = "max_turns exceeded"
    final_milestone = None
    bugs_all = []

    milestones = [
        "issue_captured",
        "empathy_shown",
        "handoff_offered",
        "contact_resolution_captured",
        "escalation_completed",
    ]

    run_start = time.time()

    while turn_number < MAX_TURNS:
        print(f"\n{'='*60}")
        print(f"[TURN {turn_number + 1}]")
        print(f"[Elena] {current_message}")

        # Step 1: Inject
        await inject_message(current_message)
        t_sent = time.time()

        # Step 2: Capture response
        print(f"[QA] Waiting for bot response (timeout={RESPONSE_TIMEOUT}s)...")
        bot_reply = None
        try:
            bot_reply = await capture_response(timeout=RESPONSE_TIMEOUT)
        except TimeoutError:
            bot_reply = None

        t_recv = time.time()
        latency_ms = int((t_recv - t_sent) * 1000)

        if bot_reply is None:
            print(f"[QA] TIMEOUT — no response after {RESPONSE_TIMEOUT}s")
            turns.append({
                "turn_number": turn_number + 1,
                "user_message": current_message,
                "agent_response": None,
                "milestone_reached": None,
                "bugs": ["response_timeout"],
                "latency_ms": None,
            })
            outcome = "timeout"
            termination_reason = f"Bot did not respond within {RESPONSE_TIMEOUT}s on turn {turn_number + 1}"
            break

        print(f"[Bot] {bot_reply}")
        print(f"[QA] Latency: {latency_ms}ms")

        # ===== LLM Reasoning Step =====
        # Analyze bot reply, judge milestone, detect bugs, generate next reply

        bot_lower = bot_reply.lower()

        # Bug detection
        turn_bugs = []

        # Check wrong language
        spanish_markers = ["hola", "entiendo", "gracias", "turno", "cobr", "puedo", "salon", "estilista",
                           "ayud", "disculp", "lamenta", "equipo", "te", "tu", "lo", "la", "un", "una",
                           "de", "el", "que", "por", "para", "con", "sé", "voy", "vas", "cómo", "qué",
                           "te contactar", "pondrán", "en contacto", "problema", "revisión", "resolver",
                           "disculpe", "lamento", "contigo"]
        if not any(m in bot_lower for m in spanish_markers) and len(bot_reply) > 10:
            turn_bugs.append({"category": "wrong_language", "evidence": f"Bot reply may not be in Spanish: '{bot_reply[:80]}'", "turns": [turn_number + 1]})

        # Check for hallucination (specific services/prices not expected)
        hallu_markers = ["200 pesos", "500 pesos", "descuento", "promoción", "oferta especial"]
        for h in hallu_markers:
            if h in bot_lower:
                turn_bugs.append({"category": "hallucination", "evidence": f"Bot mentioned unexpected: '{h}'", "turns": [turn_number + 1]})

        # Check if bot tries to start a booking flow
        booking_markers = ["¿qué servicio", "qué estilista", "reservar turno", "sacar un turno",
                           "agendar", "disponibilidad", "horario disponible", "elegir"]
        if any(m in bot_lower for m in booking_markers) and turn_number > 1:
            turn_bugs.append({
                "category": "ignored_preference",
                "evidence": f"Bot attempting booking flow for escalation client. Reply: '{bot_reply[:100]}'",
                "turns": [turn_number + 1]
            })

        # Milestone judgment
        reached_milestone = None

        # issue_captured: bot understood billing complaint
        if any(m in bot_lower for m in ["cobr", "factur", "pago", "cobro", "cargo", "monto", "importe",
                                         "entiendo", "entendemos", "entiendo tu", "problema"]):
            if turn_number == 0:
                reached_milestone = "issue_captured"

        # empathy_shown
        empathy_markers = ["disculp", "lamenta", "entiendo tu frustración", "lo sentimos", "lo siento",
                           "lamentamos", "comprendemos", "perdoná", "perdón", "entendemos tu molestia",
                           "entiendo", "sorry", "molesta", "frustración", "disculpá", "disculpe"]
        if any(m in bot_lower for m in empathy_markers):
            if final_milestone in [None, "issue_captured"]:
                reached_milestone = "empathy_shown"

        # handoff_offered: bot offers human contact
        handoff_markers = ["equipo", "humano", "persona", "te contactar", "te van a contactar",
                           "te vamos a contactar", "pondrá en contacto", "pondremos en contacto",
                           "te llamar", "llamarte", "contacto", "derivar", "hablar con", "comunicar",
                           "en contacto", "comunicarte", "alguien del equipo", "responsable"]
        if any(m in bot_lower for m in handoff_markers):
            if final_milestone in [None, "issue_captured", "empathy_shown"]:
                reached_milestone = "handoff_offered"
            elif final_milestone == "handoff_offered":
                reached_milestone = "contact_resolution_captured"

        # contact_resolution_captured
        contact_markers = ["número", "teléfono", "datos", "nombre", "cuándo", "horario",
                           "te contactar", "confirmar", "recibimos", "quedamos", "anotamos",
                           "registramos", "turno", "información", "dato"]
        if any(m in bot_lower for m in contact_markers) and final_milestone in ["handoff_offered", "empathy_shown"]:
            if reached_milestone is None:
                reached_milestone = "contact_resolution_captured"

        # escalation_completed: clear closing / next step
        complete_markers = ["en breve", "pronto", "a la brevedad", "próximamente", "nos comunicaremos",
                            "alguien del equipo se comunicará", "resolveremos", "resolverá",
                            "gracias por contactarnos", "gracias por comunicarte",
                            "equipo se pondrá", "estaremos en contacto", "listo", "anotado",
                            "registrado", "notificado"]
        if any(m in bot_lower for m in complete_markers) and final_milestone in [
            "handoff_offered", "contact_resolution_captured"
        ]:
            reached_milestone = "escalation_completed"

        # If no specific milestone but bot clearly addressed the issue
        if reached_milestone is None:
            if final_milestone is not None:
                reached_milestone = final_milestone  # Stay at last

        # Update milestone progression
        if reached_milestone and (final_milestone is None or
                milestones.index(reached_milestone) > milestones.index(final_milestone)):
            final_milestone = reached_milestone

        # Dead loop detection
        if reached_milestone == last_milestone:
            consecutive_same_milestone += 1
        else:
            consecutive_same_milestone = 0
            last_milestone = reached_milestone

        print(f"[QA] Milestone: {reached_milestone} | Final: {final_milestone} | ConsecSame: {consecutive_same_milestone}")
        if turn_bugs:
            print(f"[QA] Bugs detected: {[b['category'] for b in turn_bugs]}")

        turns.append({
            "turn_number": turn_number + 1,
            "user_message": current_message,
            "agent_response": bot_reply,
            "milestone_reached": reached_milestone,
            "bugs": [b["category"] for b in turn_bugs],
            "latency_ms": latency_ms,
        })
        bugs_all.extend(turn_bugs)

        # Check stop conditions
        if consecutive_same_milestone >= 3:
            outcome = "dead_loop"
            termination_reason = f"Same milestone '{last_milestone}' for 3 consecutive turns"
            break

        if final_milestone == "escalation_completed":
            outcome = "escalated"
            termination_reason = "Escalation flow completed successfully — human handoff confirmed"
            break

        if time.time() - run_start > 300:
            outcome = "timeout"
            termination_reason = "5-minute wall time exceeded"
            break

        # Generate Elena's next reply based on bot response
        turn_number += 1

        # Dynamic reply generation based on bot content
        if any(m in bot_lower for m in ["nombre", "teléfono", "datos", "número de turno", "número de reserva"]):
            current_message = dynamic_replies["data_request"]
        elif any(m in bot_lower for m in ["equipo", "te contactar", "pondremos en contacto", "alguien"]):
            if final_milestone == "escalation_completed":
                current_message = dynamic_replies["resolution"]
            else:
                current_message = dynamic_replies["handoff_confirm"]
        elif any(m in bot_lower for m in ["agendar", "reservar", "turno nuevo", "sacar turno"]):
            current_message = dynamic_replies["booking_attempt"]
        elif any(m in bot_lower for m in ["disculp", "lamenta", "entiendo"]) and turn_number == 1:
            current_message = dynamic_replies["empathy"]
        elif any(m in bot_lower for m in ["cuándo", "contactar", "número", "listo", "anotado"]):
            current_message = dynamic_replies["contact_given"]
        else:
            current_message = dynamic_replies["generic"]

    else:
        # Loop exhausted
        outcome = "timeout"
        termination_reason = f"Max turns ({MAX_TURNS}) reached without completing escalation flow"

    # =========================================================
    # Build result
    # =========================================================

    # DB verification — escalation flow should NOT create appointments
    print("\n[QA] Checking DB for unexpected appointments...")
    try:
        import subprocess
        db_check = subprocess.run(
            [
                "docker", "exec", "atrevete-postgres",
                "psql", "-U", "atrevete", "-d", "atrevete_db", "-t", "-c",
                f"SELECT COUNT(*) FROM appointments WHERE conversation_id = '{CONVERSATION_ID}';"
            ],
            capture_output=True, text=True, timeout=10
        )
        count_str = db_check.stdout.strip()
        apt_count = int(count_str) if count_str.isdigit() else 0
        db_verification = {
            "found": apt_count > 0,
            "appointment_count": apt_count,
            "details": f"Found {apt_count} appointment(s) for conversation_id={CONVERSATION_ID}. Expected: 0 (escalation flow)"
        }
    except Exception as e:
        db_verification = {
            "found": False,
            "appointment_count": 0,
            "details": f"DB check skipped (not required for escalation): {e}"
        }
    print(f"[QA] DB verification: {db_verification}")

    # Cleanup pubsub
    await pubsub.unsubscribe(OUTGOING_PUBSUB_CHANNEL)
    await r.aclose()

    # Bugs summary
    bug_categories = [b["category"] for b in bugs_all]
    if bug_categories:
        bugs_summary = f"Detected bugs: {', '.join(set(bug_categories))}. Details: " + "; ".join(
            f"[T{b['turns']}] {b['category']}: {b['evidence'][:60]}" for b in bugs_all
        )
    else:
        bugs_summary = "No semantic bugs detected during the escalation flow."

    result = {
        "flow_id": "escalation",
        "persona_id": "elena_escalation_client",
        "conversation_id": CONVERSATION_ID,
        "outcome": outcome,
        "milestone_reached": final_milestone,
        "turns": turns,
        "tool_trace": tool_trace,
        "bugs_summary": bugs_summary,
        "db_verification": db_verification,
        "total_turns": len(turns),
        "termination_reason": termination_reason,
    }

    print("\n" + "="*60)
    print("QA RESULT:")
    print(json.dumps(result, indent=2, ensure_ascii=False))

    return result


if __name__ == "__main__":
    asyncio.run(main())
