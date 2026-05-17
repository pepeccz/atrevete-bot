#!/usr/bin/env python3
"""
QA Run: escalation flow with elena_escalation_client persona.
Round 2 — observing BUG-004, BUG-005, BUG-002 behavior.

Skill: atrevete-qa-tester
Critical order: SUBSCRIBE before INJECT.
"""

import asyncio
import json
import time
import uuid

import redis.asyncio as redis

# ─── Config ────────────────────────────────────────────────────────────────────
REDIS_URL = "redis://172.18.0.8:6379/0"
REDIS_PASSWORD = "9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda"
INCOMING_STREAM = "incoming_messages_stream"
OUTGOING_CHANNEL = "outgoing_messages"
RESPONSE_TIMEOUT = 30.0
CONVERSATION_ID = str(uuid.uuid4())
PHONE_NUMBER = "+34600999888"  # Elena's simulated phone

# ─── Elena's persona utterances ────────────────────────────────────────────────
# Frustrated client reporting billing error and wanting human contact
ELENA_TURNS = [
    "Hola, me cobraron mal en mi último turno y estoy muy molesta",  # T1: present problem
    "Sí, me cobraron $2500 pero el precio que me dijeron era $1800",  # T2: detail the error
    "No quiero seguir hablando con un bot, quiero hablar con alguien del salón",  # T3: demand human
    "Mi nombre es Elena García, el turno fue el martes pasado",  # T4: provide info if asked
    "Por WhatsApp o por teléfono, lo que sea más rápido",  # T5: contact preference
    "Sí, está bien, espero que me llamen hoy",  # T6: confirm follow-up
    "Gracias",  # T7: close
    "Adiós",  # T8: hard stop
]

MAX_TURNS = 8


async def run_qa():
    print(f"\n{'='*60}")
    print("QA RUN: escalation / elena_escalation_client")
    print(f"conversation_id: {CONVERSATION_ID}")
    print(f"{'='*60}\n")

    # Connect to Redis
    client = redis.from_url(
        REDIS_URL,
        password=REDIS_PASSWORD,
        decode_responses=True,
    )

    # ── STEP 1: Subscribe BEFORE injecting (critical per skill) ────────────────
    pubsub = client.pubsub()
    await pubsub.subscribe(OUTGOING_CHANNEL)

    # Drain any stale messages from the channel
    async def drain_stale():
        try:
            async for msg in pubsub.listen():
                if msg["type"] == "subscribe":
                    break
        except Exception:
            pass

    await asyncio.wait_for(drain_stale(), timeout=2.0)
    print(f"[*] Subscribed to '{OUTGOING_CHANNEL}' channel")

    # ── STEP 2: Helper: wait for a response matching our conversation_id ────────
    async def wait_for_response(timeout: float = RESPONSE_TIMEOUT) -> str | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = deadline - time.time()
            try:
                msg = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=min(1.0, remaining))
                if msg and msg["type"] == "message":
                    try:
                        data = json.loads(msg["data"])
                        # Check conversation_id match
                        if data.get("conversation_id") == CONVERSATION_ID:
                            return data.get("message") or data.get("message_text") or str(data)
                    except json.JSONDecodeError:
                        pass
            except TimeoutError:
                pass
        return None

    # ── STEP 3: Execute turns ────────────────────────────────────────────────────
    turns = []
    escalation_triggered = False
    issue_description_captured = False
    contact_preference_captured = False
    bugs_observed = []

    for i, utterance in enumerate(ELENA_TURNS, start=1):
        print(f"\n--- Turn {i} ---")
        print(f"[Elena] {utterance}")

        # Build payload using production field names (T4.1)
        payload = {
            "conversation_id": CONVERSATION_ID,
            "message_text": utterance,
            "customer_phone": PHONE_NUMBER,
            "sender_name": "Elena García",
            "channel": "whatsapp",
            "source": "qa_tester",
        }

        # Inject message into INCOMING_STREAM using flat fields (production schema)
        t_inject = time.time()
        stream_id = await client.xadd(
            INCOMING_STREAM,
            payload,
        )
        print(f"[>] Injected to stream, id={stream_id}")

        # Wait for agent response
        response = await wait_for_response(timeout=RESPONSE_TIMEOUT)
        t_response = time.time()
        latency_ms = int((t_response - t_inject) * 1000)

        if response is None:
            print(f"[!] TIMEOUT — no response after {RESPONSE_TIMEOUT}s")
            turns.append({
                "turn_number": i,
                "user_message": utterance,
                "agent_response": "TIMEOUT",
                "response_latency_ms": int(RESPONSE_TIMEOUT * 1000),
            })
            # Continue instead of break — record the timeout and move on
            continue

        print(f"[Bot] {response}")
        print(f"[~] Latency: {latency_ms}ms")

        # ── Analyze response for bugs and milestones ──────────────────────────
        response_lower = response.lower()

        # BUG-002: action narration leak
        narration_phrases = ["voy a ", "déjame ", "déjame ", "procedo a ", "estoy procesando"]
        for phrase in narration_phrases:
            if phrase in response_lower:
                bug_note = f"BUG-002 (action narration leak) detected at turn {i}: '{phrase}'"
                print(f"[BUG] {bug_note}")
                if bug_note not in bugs_observed:
                    bugs_observed.append(bug_note)

        # BUG-004: canned response detection (repeated boilerplate)
        canned_phrases = [
            "para proceder con la escalación",
            "¿cuál es el motivo de tu consulta?",
            "¿en qué puedo ayudarte?",
            "entiendo que tienes un problema",
        ]
        if i >= 2:
            for phrase in canned_phrases:
                if phrase in response_lower and turns:
                    prev_response = turns[-1]["agent_response"].lower() if turns else ""
                    if phrase in prev_response:
                        bug_note = f"BUG-004 (canned/repeated response) detected at turn {i}"
                        print(f"[BUG] {bug_note}")
                        if bug_note not in bugs_observed:
                            bugs_observed.append(bug_note)

        # BUG-005: check if issue description was captured
        issue_keywords = ["cobr", "turno", "pago", "precio", "cargo", "monto"]
        if any(kw in response_lower for kw in issue_keywords):
            issue_description_captured = True

        # Check if contact preference was asked/captured
        contact_keywords = ["contacto", "llamar", "whatsapp", "teléfono", "comunicar", "hablar"]
        if any(kw in response_lower for kw in contact_keywords):
            contact_preference_captured = True

        # Check if escalation is triggered
        escalation_keywords = ["humano", "persona", "equipo", "salón", "contactar", "derivar", "representante", "encargado"]
        if any(kw in response_lower for kw in escalation_keywords):
            escalation_triggered = True

        turns.append({
            "turn_number": i,
            "user_message": utterance,
            "agent_response": response,
            "response_latency_ms": latency_ms,
        })

        # Stop if bot signals completion or we're past a clear escalation closure
        if i >= 6 and escalation_triggered:
            print(f"\n[*] Escalation detected, completing after turn {i}")
            break

    # ── STEP 4: Cleanup ─────────────────────────────────────────────────────────
    await pubsub.unsubscribe(OUTGOING_CHANNEL)
    await client.aclose()

    # ── STEP 5: Build result ────────────────────────────────────────────────────
    # Determine PASS/FAIL
    # Expected: escalation_triggered=true AND human_handoff_requested=true
    human_handoff = any(
        any(kw in t["agent_response"].lower() for kw in ["humano", "persona del equipo", "equipo del salón", "alguien del salón", "encargad"])
        for t in turns if t["agent_response"] != "TIMEOUT"
    )

    milestones_hit = []
    full_text = " ".join(t["agent_response"].lower() for t in turns if t["agent_response"] != "TIMEOUT")

    if any(kw in full_text for kw in ["cobr", "turno anterior", "último turno", "pago"]):
        milestones_hit.append("issue_captured")
    if any(kw in full_text for kw in ["disculp", "lament", "entend", "sentir"]):
        milestones_hit.append("empathy_shown")
    if any(kw in full_text for kw in ["humano", "persona", "equipo", "salón", "representante"]):
        milestones_hit.append("handoff_offered")
    if contact_preference_captured:
        milestones_hit.append("contact_resolution_captured")
    if escalation_triggered and human_handoff:
        milestones_hit.append("escalation_completed")

    status = "PASS" if (escalation_triggered and human_handoff) else "FAIL"

    result = {
        "status": status,
        "scenario_id": "escalation",
        "persona_id": "elena_escalation_client",
        "conversation_id": CONVERSATION_ID,
        "turn_count": len(turns),
        "escalation_triggered": escalation_triggered,
        "human_handoff_requested": human_handoff,
        "issue_description_captured": issue_description_captured,
        "contact_preference_captured": contact_preference_captured,
        "milestones_hit": milestones_hit,
        "bugs_observed": bugs_observed,
        "turns": turns,
    }

    # ── Print summary ────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"RESULT: {status}")
    print(f"Turns: {len(turns)}")
    print(f"escalation_triggered: {escalation_triggered}")
    print(f"human_handoff_requested: {human_handoff}")
    print(f"issue_description_captured: {issue_description_captured}")
    print(f"contact_preference_captured: {contact_preference_captured}")
    print(f"Milestones: {milestones_hit}")
    print(f"Bugs observed: {bugs_observed}")
    print(f"{'='*60}\n")

    # Output JSON for capture
    print("JSON_RESULT_START")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("JSON_RESULT_END")

    return result


if __name__ == "__main__":
    asyncio.run(run_qa())
