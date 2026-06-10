---
name: atrevete-qa-runner
description: >
  Claude Code sub-agent skill: execute ONE QA scenario end-to-end against the
  live Atrévete Bot. Receives a scenario row (inline JSON from scenarios.yaml),
  a pre-generated conversation_id, and an output path. Drives the full turn loop,
  captures DB deltas and Langfuse traces, writes a run JSON file, and returns an
  executive summary to the orchestrator.
  Trigger: Executing a QA scenario regression, driving multi-turn bot conversation autonomously.
license: MIT
metadata:
  author: atrevete-bot
  version: "1.0"
  scope: [root]
  auto_invoke:
    - "Executing a QA scenario regression"
    - "Driving multi-turn bot conversation autonomously"
---

> ## ⛔ SERVER ONLY — ignore local containers
>
> **The deploy under test lives at `pepe@server:/home/pepe/Proyectos/atrevete-bot`.**
> ALL health checks, `docker compose` commands, psql queries, log reads, and turn
> helpers MUST target the SSH server deploy. If a docker stack happens to be
> running on the local machine, **IGNORE IT** — diagnosing the local stack
> produces BLOCKED/invalid runs. This drift has happened TWICE (V3 and V4:
> `indecisa-cambia-criterio-tres-veces`, `faq-atienden-hombres`). Before Step 1,
> confirm you are operating against the server deploy, not localhost.

## Purpose

Execute a single QA scenario against the live Atrévete Bot pipeline (Redis
Streams → `agent_factory.build_conversation_agent()` → 7 middleware + 6 tools).
The subagent drives the full conversation as the persona described in the scenario,
collects evidence, and writes a structured run JSON file.

**One subagent invocation = one scenario.** The orchestrator spawns N runner
subagents in parallel for N scenarios.

---

## Architecture Reference

Current agent architecture (SSOT: `agent/agent_factory.py:47-55`):

- `build_conversation_agent()` — entry point, wires `create_agent` + middleware + tools
- **7 middleware** (execution order):
  1. `DisclosureMiddleware` (`agent/middleware/disclosure.py`)
  2. `CustomerResolveMiddleware` (`agent/middleware/customer_resolve.py`)
  3. `AppointmentContextMiddleware` (`agent/middleware/appointment_context.py`)
  4. `DynamicPromptMiddleware` (`agent/middleware/dynamic_prompt.py`)
  5. `AvailabilityContextMiddleware` (`agent/middleware/availability_context.py`)
  6. `PromptAssemblyMiddleware` (`agent/middleware/prompt_assembly.py`)
  7. `SummarizeMiddleware` (`agent/middleware/summarize.py`)
- **6 tools** (`agent/tools/`):
  - `check_availability`, `get_next_available_options` (`next_available.py`)
  - `book` (`book.py`), `update_booking` (`update_booking.py`)
  - `manage_appointments` (`manage_appointments_tool.py`)
  - `escalate` / `send_to_human` (`escalation_tools.py`)

**No modes, no router, no FSM.** The agent uses a single LLM tool-calling loop.
Do NOT reference the old mode-based artifacts (deleted): `current_mode`,
`mode_context`, `mode_history`, `booking_step`.

---

## Inputs (provided in the delegation prompt)

```json
{
  "scenario": {
    "id": "change-a-new-booking",
    "persona": {"name": "María", "phone": "+34999000001"},
    "intent": "Hola, quiero pedir una cita para un corte",
    "max_turns": 8,
    "expect": {
      "outcome": "booked",
      "tool_calls_required": ["check_availability", "book"],
      "tool_calls_forbidden": [],
      "db_appointment": {"status": "confirmed"},
      "policy_accepted": true
    }
  },
  "conversation_id": "<UUID4>",
  "output_path": "tests/e2e/runs/20260608_143000/change-a-new-booking.json",
  "traces_path": "tests/e2e/runs/20260608_143000/change-a-new-booking_traces.json"
}
```

---

## Canonical Outcome Enum

The `outcome` field in the run JSON MUST be one of the values below. The v1
core covers booking flows; v2 extension (scenarios-v2.yaml) adds outcomes for
FAQ, multi-intent, out-of-scope, and edge-case scenarios.

### v1 core

| Value | Meaning |
|-------|---------|
| `booked` | Appointment successfully created in DB |
| `cancelled` | Appointment successfully cancelled in DB |
| `rescheduled` | Appointment rescheduled in DB |
| `escalated` | Conversation handed off to human agent via `escalate` tool |
| `policy_accepted` | Policy gate accepted, no booking yet |
| `rejected` | Bot refused the request (e.g. IDOR, invalid input) |
| `timeout` | Agent did not respond within turn timeout |
| `error` | Unhandled exception or infrastructure failure |
| `stuck` | max_turns reached without reaching expected outcome |

### v2 extension

| Value | Meaning | When to write |
|-------|---------|---------------|
| `info_provided` | Bot answered a FAQ/info question accurately, no booking attempted. | Bot replied with info content (hours, prices, location, audience, specialization) and conversation ended/idled without booking tool calls. |
| `multi_completed` | Multi-intent conversation: both sub-intents completed. | E.g. cancel+rebook both succeeded, couple booking created 2 appointments, combo service booked. |
| `partial_completed` | Multi-intent conversation: only one sub-intent reached completion. | E.g. cancel succeeded but rebooking stuck. Use when at least one sub-intent fully completed AND another didn't. |
| `out_of_scope_handled` | Bot correctly deflected an out-of-scope request without falsely escalating or attempting a booking. | Spam, generic advice, phantom-cancel where bot recognized and asked for clarification or politely declined. |

### Validation

`scenarios.yaml` and `scenarios-v2.yaml` `expect.outcome` use this union enum
(v1 ∪ v2). Reject any scenario row whose `expect.outcome` is not in the
combined set above.

### Decision rule for choosing the outcome at end of run

Apply this priority order when writing the run JSON outcome:

1. If an unhandled exception or transport failure occurred → `error`
2. If the agent stopped responding entirely → `timeout`
3. If a `book` tool call succeeded with a created appointment → `booked`
4. If a `manage_appointments` cancel succeeded → `cancelled`
5. If a `manage_appointments` reschedule succeeded → `rescheduled`
6. If TWO or more sub-intents from the scenario completed → `multi_completed`
7. If ONE of multiple expected sub-intents completed → `partial_completed`
8. If the bot fired the `escalate` tool → `escalated`
9. If the policy gate was accepted AND no booking happened → `policy_accepted`
10. If the bot explicitly refused (IDOR, invalid input, ownership) → `rejected`
11. If the bot answered an info/FAQ question without booking tool calls AND the conversation terminated naturally → `info_provided`
12. If the bot correctly deflected an out-of-scope request → `out_of_scope_handled`
13. Otherwise (max_turns reached without completing) → `stuck`

---

## 10-Step Execution Protocol

Execute these steps IN ORDER.

### Step 1: Health Check

```bash
PYTHONPATH=. python tests/e2e/harness/qa_turn_helper.py health
```

Note: all harness commands below must run from the repo root with `PYTHONPATH=.`
(the scripts import `shared.*` and `tests.e2e.harness.*`).

Expected: `{"ok": true, "redis": "connected", "stream": "exists"}`

**If health check fails, STOP.** Write `{"outcome": "error", "error": "health_check_failed"}` to `output_path` and return.

### Step 2: Reset State

```bash
PYTHONPATH=. python tests/e2e/harness/state_reset.py reset \
  --conversation-id <conversation_id> \
  --phone <scenario.persona.phone>
```

This clears any prior Redis checkpoint and DB rows for the phone prefix.

### Step 2.5: Seed Appointment (only if `scenario.seed` is present)

Some scenarios (e.g. `cancel-con-razon`, `cancel-fuera-48h`) declare a seed
block describing an appointment that must exist BEFORE the conversation starts:

```yaml
seed:
  appointment:
    days_ahead: 5      # appointment date = today + days_ahead (Europe/Madrid)
    time: "11:00"      # local salon time
    status: confirmed
```

Create the customer (persona phone/name) and the appointment exactly as
declared — `days_ahead` is load-bearing: the 48h cancellation policy depends on
it (`days_ahead >= 3` → cancellable; `days_ahead <= 1` → policy blocks, bot
must escalate). Use any active stylist and any active service. Set
`gcal_sync_status='not_applicable'` (sandbox). Verify the row exists before
Step 3 so it is included in `snapshot_before`.

### Step 3: DB Snapshot Before

```bash
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml exec -T postgres \
  psql -U atrevete -d atrevete_db -c \
  "SELECT COUNT(*) AS customer_count FROM customers WHERE phone = '<phone>';
   SELECT COUNT(*) AS appt_count FROM appointments
   JOIN customers ON customers.id = appointments.customer_id
   WHERE customers.phone = '<phone>';"
```

Record `snapshot_before = {"customer_count": N, "appt_count": N}`.

### Step 4: Turn Loop

Execute up to `min(scenario.max_turns, 15)` turns. Hard cap is 15.

#### Per-Turn Cycle

**4a. Decide the next user message.**

Think as the persona. Use `scenario.persona.name`, the persona `style` field
(if present), the intent, and all prior bot responses to decide what to say
next. Be natural — real customers don't front-load all info at once.

**4b. Send the turn.**

```bash
PYTHONPATH=. python tests/e2e/harness/qa_turn_helper.py turn \
  --conversation-id <conversation_id> \
  --user-message "<your_message>" \
  --customer-phone <scenario.persona.phone> \
  --persona-name "<scenario.persona.name>" \
  --timeout 90
```

> Flag contract: the `turn` subcommand takes `--customer-phone` and
> `--persona-name` (only the `reset` subcommand takes `--phone`). The
> authoritative source is `_build_parser()` in
> `tests/e2e/harness/qa_turn_helper.py`; a consistency test
> (`tests/unit/test_qa_runner_skill_doc_cli_consistency.py`) keeps this doc in
> sync.

> Batching quirk: `qa_turn_helper.py` forces `MESSAGE_BATCH_WINDOW_SECONDS=0`
> in its own process — runner mode disables inbound message batching so each
> `turn` call maps to exactly one processed turn. The production default
> (window > 0) merges multi-message turns inside the batch window and
> mis-times the runner's response waits. Do NOT remove the `=0` override, and
> when a scenario intentionally tests batching (e.g.
> `impaciente-multiples-mensajes`), remember the agent container under test
> applies ITS OWN batch window — rapid messages may legitimately produce a
> single merged reply.

Output JSON: `{"agent_response": "...", "timed_out": bool, "response_latency_ms": N, "tool_evidence": {...}}`

**4c. Record the turn.**

```json
{
  "turn": N,
  "user_message": "...",
  "agent_response": "...",
  "latency_ms": N,
  "timed_out": false,
  "tool_calls_observed": ["check_availability"],
  "bugs": [],
  "milestone": "..."
}
```

**4d. Check termination conditions.**

| Condition | Trigger | Set outcome |
|-----------|---------|-------------|
| Booking/transaction completed | Bot confirms appointment, cancellation, reschedule, escalation, or policy acceptance | `booked` / `cancelled` / `rescheduled` / `escalated` / `policy_accepted` |
| Multi-intent both done | Two or more sub-intents reached completion (e.g. cancel old + book new) | `multi_completed` |
| Multi-intent one done | One sub-intent completed, another did not reach completion within max_turns | `partial_completed` |
| FAQ / info answered | Bot answered an info question accurately, conversation terminated without booking tool calls | `info_provided` |
| Out-of-scope deflected | Bot recognized out-of-scope (spam, generic advice, phantom-cancel) and deflected politely without booking or escalation | `out_of_scope_handled` |
| Request rejected | Bot explicitly refuses (IDOR, invalid input, ownership check) | `rejected` |
| Max turns | Turn count == min(max_turns, 15) without reaching any other terminal condition | `stuck` |
| Dead loop | 3 consecutive identical agent responses | `stuck` |
| Timeout | `timed_out == true` in turn output | `timeout` |
| Error | CLI exits non-zero with exception text | `error` |

#### Bug Detection (inline, per turn)

Flag a bug in `turn.bugs` when:
- `redundant_question`: bot asks for info the user already provided in a prior turn
- `context_loss`: bot re-initiates a step already completed
- `ignored_preference`: bot ignores an explicitly stated preference
- `hallucination`: bot mentions a service, stylist, or fact not in the system
- `wrong_language`: bot responds with substantial non-Spanish text
- `voseo_detected`: bot uses voseo (`tenés`, `hacé`, `podés`) — agent must use Castellano

### Step 5: DB Snapshot After

Same query as Step 3. Record `snapshot_after`.

```
db_delta = {
  "customer_count_delta": snapshot_after.customer_count - snapshot_before.customer_count,
  "appt_count_delta": snapshot_after.appt_count - snapshot_before.appt_count
}
```

### Step 6: State Capture

```bash
PYTHONPATH=. python tests/e2e/harness/qa_turn_helper.py state \
  --conversation-id <conversation_id>
```

Record the output JSON as `final_state`.

### Step 7: Pull Langfuse Traces

```bash
PYTHONPATH=. python tests/e2e/harness/langfuse_pull.py \
  --conv-id <conversation_id> \
  --out <traces_path> \
  --retries 4
```

If this fails (non-zero exit), set `langfuse_trace_path: null` and continue.

### Step 8: Cleanup

```bash
PYTHONPATH=. python tests/e2e/harness/state_reset.py reset \
  --conversation-id <conversation_id> \
  --phone <scenario.persona.phone>
```

### Step 9: Write Run JSON

#### Output Path Contract (REQ-H1)

Write to EXACTLY `output_path` as passed by the orchestrator. Never derive a
different path. Never write to a fallback location.

Before writing, create the parent directory:
```python
from pathlib import Path
Path(output_path).parent.mkdir(parents=True, exist_ok=True)
```

This is a defensive guard — the orchestrator owns directory creation, but the
runner MUST call `mkdir` as a safety net to avoid `FileNotFoundError`.

#### Output JSON Writer (REQ-H3)

Serialize the run dict using a SINGLE call with `ensure_ascii=False` and
`default=str` so that user messages, agent responses, and any field containing
double-quotes, newlines, or Unicode characters do NOT corrupt the output:

```python
import json
from pathlib import Path

path = Path(output_path)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(
    json.dumps(run_dict, ensure_ascii=False, default=str),
    encoding="utf-8",
)
```

Never use f-string concatenation or `json.dumps` on individual fields — always
dump the assembled `run_dict` in one call.

This same contract applies even when `outcome == "error"` — the partial run dict
MUST be written to `output_path` regardless of how far the run progressed.

#### Run JSON Schema

```json
{
  "scenario_id": "...",
  "conversation_id": "...",
  "outcome": "booked",
  "turns_taken": N,
  "turns": [...],
  "bugs": [...],
  "milestones_reached": [...],
  "db_delta": {"customer_count_delta": 1, "appt_count_delta": 1},
  "snapshot_before": {...},
  "snapshot_after": {...},
  "final_state": {...},
  "langfuse_trace_path": ".../_traces.json",
  "expect": {...},
  "passed": true
}
```

`passed` is `true` when `outcome == expect.outcome`.

### Step 10: Return Executive Summary

Return to the orchestrator:

```
Scenario: change-a-new-booking
Outcome: booked (expected: booked) — PASS
Turns: 6 / 8
Bugs: 0
DB delta: +1 customer, +1 appointment
Run JSON: tests/e2e/runs/20260608_143000/change-a-new-booking.json
```

---

## Rules

1. **NEVER** reuse a `conversation_id` — it must be a pre-generated UUID4 from the orchestrator.
2. **ALWAYS** run the health check before any turn.
3. **ALWAYS** reset state before AND after a run (Steps 2 + 8).
4. **Stay in character** as the persona — do not break the fourth wall.
5. **Hard cap** is 15 turns regardless of `max_turns` in the scenario.
6. **Do NOT call Redis directly** — all bot communication goes through `qa_turn_helper.py`.
7. **Sandbox phones only**: all scenario phones MUST start with `+34999`. Refuse if not.
8. `TEST_MODE_GCAL_SKIP=true` MUST be set in the environment before running. If absent, `gcal_sync_status` in DB will not be `not_applicable` and L4 audits will fail.
9. If `langfuse_pull.py` fails, do NOT abort — set `langfuse_trace_path: null` and proceed.
10. Write the run JSON even if outcome is `error` or `stuck` — the auditor needs the partial evidence.

---

## Environment Prerequisites

```bash
# Must be set before running any scenario
export TEST_MODE_GCAL_SKIP=true
export TEST_PHONE_PREFIX=+34999

# Docker services must be running
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml ps
# Expect: api, agent, postgres, redis all Up
```

---

## Output File Location

Runs are written to `tests/e2e/runs/{timestamp}/` where `{timestamp}` is
`YYYYMMDD_HHMMSS` set by the orchestrator at batch start. The orchestrator
passes the exact `output_path` and `traces_path`. The runner writes ONLY to
those exact paths — no derived paths, no fallback directories.

The runner calls `Path(output_path).parent.mkdir(parents=True, exist_ok=True)`
as a defensive guard (see Step 9 — Output Path Contract).

Each scenario produces two files:
- `{scenario_id}.json` — run evidence (this skill writes it)
- `{scenario_id}_traces.json` — Langfuse traces (written by `langfuse_pull.py`)
