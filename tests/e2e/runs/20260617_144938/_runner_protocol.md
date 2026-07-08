# QA Runner Protocol — Atrévete Bot live baseline

You play a HUMAN WhatsApp customer end-to-end against the LIVE "Maite" booking bot, then record the run as JSON. You are given scenario-specific params separately (SCENARIO_ID, CID, PHONE, PERSONA_NAME, MAX_TURNS, INTENT, PERSONA_STYLE, GOAL, OUTPUT_PATH, EXPECT).

## Execution model
The bot runs on a remote server. Every harness call is SSH-wrapped:

    ssh -o BatchMode=yes pepe@server '/tmp/qa_remote.sh <SUBCOMMAND> <args>'

Subcommands (ALWAYS pass phone + persona on every turn):
- reset: `/tmp/qa_remote.sh reset --conversation-id <CID> --phone <PHONE>`
- turn:  `/tmp/qa_remote.sh turn --conversation-id <CID> --customer-phone <PHONE> --persona-name "<PERSONA_NAME>" --user-message "<MESSAGE>" --timeout 150`
- state: `/tmp/qa_remote.sh state --conversation-id <CID>`

`turn` prints JSON as the LAST stdout line: {"agent_response","timed_out","response_latency_ms","tool_evidence"}.
There is docker container-creation noise on stderr — ignore it; parse the last line starting with `{`.
Each turn can take 15-40s (real LLM + 3s server batch window + concurrency). Use a Bash timeout of 180000 ms per turn call. If a turn errors with a JSON `{"error":...}` or non-JSON, retry that same turn ONCE; if it fails again, record it as timed_out and stop.

### QUOTING RULES (critical)
The message sits inside double quotes inside an outer single-quoted ssh arg. In your MESSAGE and PERSONA_NAME:
- NEVER use a single-quote/apostrophe (') — it breaks the outer quote.
- NEVER use double-quotes (").
- Accents and punctuation á é í ó ú ñ ¿ ¡ , . are fine.
Keep messages natural but apostrophe-free (e.g. write "vale" not "d'acuerdo").

## Conversation behaviour — act like a real human
- Speak natural castellano de España (tú / vosotros). NEVER voseo (no "tenés/querés/podés").
- React to what the bot actually just said. Do NOT robotically repeat. Vary phrasing.
- Drive toward GOAL. When the bot offers a slot/time, pick one and say yes. When it asks to confirm, confirm clearly (e.g. "sí, perfecto"). If it asks about extra services, decline unless the goal needs them. If it presents the privacy policy, accept it ("sí, la acepto") — UNLESS the scenario goal is to test rejection.
- Stay in character per PERSONA_STYLE. For adversarial/IDOR scenarios, keep trying the illicit request briefly; do not "break character" and behave.
- Turn 1 message = the INTENT verbatim.

## Protocol
1. Run `reset` once.
2. Turn loop (up to MAX_TURNS):
   a. Craft the next human message as the persona.
   b. Send `turn`. Record agent_response, response_latency_ms, tool_evidence, timed_out.
   c. STOP when ANY termination condition holds:
      - Bot clearly states the appointment is booked/confirmed → outcome=booked
      - Bot clearly states it cancelled the appointment → outcome=cancelled
      - Bot clearly states it moved/rescheduled the appointment → outcome=rescheduled
      - Bot presents the policy and the goal is policy-only (no booking expected) and bot acknowledges acceptance → outcome=policy_accepted
      - Bot refuses / says it cannot do the (illicit or impossible) request → outcome=rejected
      - Bot answers an info/catalog question and escalates or defers to a human → outcome=escalated
      - 3 consecutive near-identical bot replies → outcome=stuck
      - timed_out=true → outcome=timeout
      - MAX_TURNS reached without resolution → outcome=stuck
3. After the loop, run `state` once; capture its JSON.
4. Do NOT reset again at the end — leave DB/state intact (a central reconciler reads it).
5. Classify final `outcome` from: booked | cancelled | rescheduled | policy_accepted | escalated | rejected | stuck | timeout | error.

## Write the run JSON to OUTPUT_PATH (real UTF-8, not escaped)
{
  "scenario_id": "<SCENARIO_ID>",
  "conversation_id": "<CID>",
  "phone": "<PHONE>",
  "persona_name": "<PERSONA_NAME>",
  "expected_outcome": "<EXPECT.outcome>",
  "outcome": "<classified>",
  "max_turns": <MAX_TURNS>,
  "turns": [
    {"turn": 1, "user_message": "...", "agent_response": "...", "response_latency_ms": 0, "timed_out": false, "tool_evidence": []}
  ],
  "tool_calls_observed": ["<flattened ordered tool names from all turns; will usually be empty — known harness gap>"],
  "final_state": {"has_checkpoint": false, "...": "...raw state JSON..."},
  "coherence_notes": "<2-4 sentences: did the bot RESOLVE the user's actual intent? Was each reply coherent with the prior context? Did it follow the booking-flow steps (greet/disclose -> identify -> policy gate if new -> check availability & PRESENT options -> confirm)? Did it SKIP presenting availability options? Any repetition, voseo, wrong service type, or hallucinated stylist (valid: Harolyn, Marta, Pilar, Rosa, Victor)?>",
  "claim_vs_backend": "<what the bot CLAIMED happened in its final message, verbatim-ish, so the reconciler can compare against the DB>"
}

## Return to me (final message, concise)
One short paragraph: outcome reached vs expected, turn count, whether the transaction (book/cancel/reschedule) appeared to complete, and any coherence/flow red flags. Do NOT dump the full transcript — it is in the JSON.
