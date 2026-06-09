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

The `outcome` field in the run JSON MUST be one of:

| Value | Meaning |
|-------|---------|
| `booked` | Appointment successfully created in DB |
| `cancelled` | Appointment successfully cancelled in DB |
| `rescheduled` | Appointment rescheduled in DB |
| `escalated` | Conversation handed off to human agent |
| `policy_accepted` | Policy gate accepted, no booking yet |
| `rejected` | Bot refused the request (e.g. IDOR, invalid input) |
| `timeout` | Agent did not respond within turn timeout |
| `error` | Unhandled exception or infrastructure failure |
| `stuck` | max_turns reached without reaching expected outcome |

`scenarios.yaml` `expect.outcome` uses the same enum. Reject any scenario row
whose `expect.outcome` is not in the set above.

---

## 10-Step Execution Protocol

Execute these steps IN ORDER.

### Step 1: Health Check

```bash
python tests/e2e/harness/qa_turn_helper.py health
```

Expected: `{"ok": true, "redis": "connected", "stream": "exists"}`

**If health check fails, STOP.** Write `{"outcome": "error", "error": "health_check_failed"}` to `output_path` and return.

### Step 2: Reset State

```bash
python tests/e2e/harness/state_reset.py reset \
  --conversation-id <conversation_id> \
  --phone <scenario.persona.phone>
```

This clears any prior Redis checkpoint and DB rows for the phone prefix.

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
python tests/e2e/harness/qa_turn_helper.py turn \
  --conversation-id <conversation_id> \
  --message "<your_message>" \
  --phone <scenario.persona.phone> \
  --name "<scenario.persona.name>" \
  --timeout 90
```

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
| Outcome reached | Bot response matches expected outcome (appointment confirmed, cancellation confirmed, escalation message, policy gate accepted) | `booked` / `cancelled` / `rescheduled` / `escalated` / `policy_accepted` |
| Request rejected | Bot refuses the request without completing it | `rejected` |
| Max turns | Turn count == min(max_turns, 15) | `stuck` |
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
python tests/e2e/harness/qa_turn_helper.py state \
  --conversation-id <conversation_id>
```

Record the output JSON as `final_state`.

### Step 7: Pull Langfuse Traces

```bash
python tests/e2e/harness/langfuse_pull.py \
  --conv-id <conversation_id> \
  --out <traces_path> \
  --retries 4
```

If this fails (non-zero exit), set `langfuse_trace_path: null` and continue.

### Step 8: Cleanup

```bash
python tests/e2e/harness/state_reset.py reset \
  --conversation-id <conversation_id> \
  --phone <scenario.persona.phone>
```

### Step 9: Write Run JSON

Write to `output_path`:

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
passes the exact `output_path` and `traces_path` — the runner does not create
the directory structure itself.

Each scenario produces two files:
- `{scenario_id}.json` — run evidence (this skill writes it)
- `{scenario_id}_traces.json` — Langfuse traces (written by `langfuse_pull.py`)
