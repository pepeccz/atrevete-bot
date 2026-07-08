# QA Targeted Run Protocol — Atrévete Bot (upgraded harness)

Play a HUMAN WhatsApp customer end-to-end against the LIVE "Maite" bot, then write the run as JSON. Params (CID, PHONE, PERSONA_NAME, MAX_TURNS, INTENT, GOAL, OUTPUT_PATH, FIRST_TURN_BURST) are given separately.

## Execution model — every harness call is SSH-wrapped
    ssh -o BatchMode=yes pepe@server '/tmp/qa_remote.sh <SUBCOMMAND> <args>'

Subcommands (ALWAYS pass phone + persona on turns):
- reset:  `/tmp/qa_remote.sh reset --conversation-id <CID> --phone <PHONE>`
- turn:   `/tmp/qa_remote.sh turn --conversation-id <CID> --customer-phone <PHONE> --persona-name "<PERSONA_NAME>" --user-message "<MSG>" --timeout 150`
- burst:  `/tmp/qa_remote.sh burst --conversation-id <CID> --customer-phone <PHONE> --persona-name "<PERSONA_NAME>" --user-message "<MSG1>" --user-message "<MSG2>" --timeout 150`  (injects MSG1, MSG2 back-to-back so the agent merges them into one turn)

`turn`/`burst` print JSON as the LAST stdout line: {agent_response, timed_out, response_latency_ms, tool_evidence, [burst_messages]}. Ignore docker noise on stderr; parse the last line starting with `{`. Each call can take 15-40s — Bash timeout 180000 ms. On a JSON `{"error":...}` or non-JSON, retry that call ONCE, else record timed_out and stop.

QUOTING: message text sits in double quotes inside an outer single-quoted ssh arg. NEVER use a single-quote/apostrophe (') or double-quote (") in MESSAGE or PERSONA_NAME. Accents á é í ó ú ñ ¿ ¡ are fine.

## Behaviour — act like a real human
- Natural castellano de España (tú/vosotros), NEVER voseo. React to what the bot just said; don't repeat robotically.
- Drive toward GOAL. When the bot offers a slot, pick one and say yes; when it asks to confirm, confirm ("sí, perfecto"); decline extra services unless the goal needs them; accept the privacy policy if asked ("sí, la acepto").
- For cancel/reschedule goals: FIRST complete the booking, THEN ask to cancel / move it.

## Protocol
1. `reset` once.
2. Turn 1: if FIRST_TURN_BURST is given (a list of messages), send it via the `burst` subcommand. Otherwise send INTENT verbatim via `turn`. Record it as turn 1.
3. Continue the turn loop (up to MAX_TURNS) with `turn`, crafting each human message as the persona.
4. STOP when: booking/cancel/reschedule clearly confirmed → outcome booked|cancelled|rescheduled; refusal → rejected; 3 near-identical replies → stuck; timed_out → timeout; MAX_TURNS reached → stuck.
5. `state` once at the end; capture it. Do NOT reset at the end (a central reconciler reads the DB).
6. Write the run JSON to OUTPUT_PATH (real UTF-8):
{
  "scenario_id": "...", "conversation_id": "<CID>", "phone": "<PHONE>", "persona_name": "...",
  "expected_outcome": "...", "outcome": "<classified>", "max_turns": N,
  "turns": [{"turn":1,"user_message":"...","agent_response":"...","response_latency_ms":0,"timed_out":false,"tool_evidence":[],"burst_messages":[...optional...]}],
  "tool_calls_observed": ["<flattened ordered tool names from tool_evidence — now populated by the fixed harness>"],
  "final_state": {...state JSON...},
  "claim_vs_backend": "<the bot's final claim, verbatim-ish, for DB reconciliation>",
  "coherence_notes": "<2-4 sentences: did the bot RESOLVE the user's intent? coherent turn-to-turn? for the burst: did the single reply address BOTH messages? any repetition/voseo/hallucinated stylist (valid: Harolyn, Marta, Pilar, Rosa, Victor)?>"
}

## Return to me (concise)
One short paragraph: outcome vs expected, turn count, total tool calls observed, whether the transaction completed, and any red flag. No full transcript.
