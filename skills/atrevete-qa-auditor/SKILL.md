---
name: atrevete-qa-auditor
description: >
  Claude Code sub-agent skill: batch-audit all run JSON files in a
  tests/e2e/runs/{ts}/ directory. Applies a 5-level audit (Structure → Payload
  → Tool calls → Side effects → UX/tone) against the current create_agent
  architecture. Writes tests/e2e/runs/{ts}/audit.md with per-scenario verdicts
  and an aggregated summary.
  Trigger: Auditing QA run results, reviewing QA batch evidence, generating QA audit report with file:line root causes.
license: MIT
metadata:
  author: atrevete-bot
  version: "1.0"
  scope: [root]
  auto_invoke:
    - "Auditing QA run results"
    - "Reviewing QA batch evidence"
    - "Generating QA audit report with file:line root causes"
---

## Purpose

Read all `{scenario_id}.json` run files produced by `atrevete-qa-runner`,
apply the 5-level audit, cross-reference with Langfuse traces when available,
and produce a comprehensive `audit.md` with per-scenario verdicts plus a
batch summary. Optionally compare against a baseline run directory for
regression detection.

**One subagent invocation = one batch audit.** The auditor reads ALL scenarios
in the run directory.

---

## Architecture Reference

Current agent architecture (SSOT: `agent/agent_factory.py:47-55`):

- `build_conversation_agent()` — entry point
- **7 middleware** (execution order):
  1. `DisclosureMiddleware` (`agent/middleware/disclosure.py`)
  2. `CustomerResolveMiddleware` (`agent/middleware/customer_resolve.py`)
  3. `AppointmentContextMiddleware` (`agent/middleware/appointment_context.py`)
  4. `DynamicPromptMiddleware` (`agent/middleware/dynamic_prompt.py`)
  5. `AvailabilityContextMiddleware` (`agent/middleware/availability_context.py`)
  6. `PromptAssemblyMiddleware` (`agent/middleware/prompt_assembly.py`) — assembles XML-fenced slots
  7. `SummarizeMiddleware` (`agent/middleware/summarize.py`)
- **6 tools** (`agent/tools/`):
  - `check_availability`, `get_next_available_options` (`next_available.py`)
  - `book` (`book.py`), `update_booking` (`update_booking.py`)
  - `manage_appointments` (`manage_appointments_tool.py`)
  - `escalate` / `send_to_human` (`escalation_tools.py`)
- **Prompts SSOT**: `agent/prompts/shared/` — `identity.md`, `critical_rules.md`, `booking_flow.md`, `glossary.md`, `tools_contract.md`

**No modes, no router, no FSM.** Do NOT reference `agent/modes/`, `BaseModeNode`,
`current_mode`, `mode_context`, `mode_history`, or `booking_step` — those
artifacts were deleted.

---

## Canonical Outcome Enum

The `outcome` field in run JSON files uses this canonical set. The v1 core
covers booking flows; v2 extension (scenarios-v2.yaml) adds outcomes for FAQ,
multi-intent, out-of-scope, and edge-case scenarios.

### v1 core (regression battery — scenarios.yaml)

| Value | Meaning |
|-------|---------|
| `booked` | Appointment successfully created in DB (`appointments` row inserted) |
| `cancelled` | Appointment successfully cancelled in DB |
| `rescheduled` | Appointment rescheduled in DB |
| `escalated` | Conversation handed off to human agent via `escalate` tool |
| `policy_accepted` | Policy gate accepted (`customer.policy_accepted_at` populated), no booking yet |
| `rejected` | Bot refused the request (e.g. IDOR attempt, invalid input, ownership check) |
| `timeout` | Agent did not respond within turn timeout (transport/infrastructure issue) |
| `error` | Unhandled exception or infrastructure failure mid-run |
| `stuck` | max_turns reached without reaching expected outcome |

### v2 extension (expansion battery — scenarios-v2.yaml)

| Value | Meaning |
|-------|---------|
| `info_provided` | Bot answered a FAQ/info question accurately, no booking attempted (zero booking tool calls). Used for hours, prices, location, audience, specialization queries. |
| `multi_completed` | Multi-intent conversation: both sub-intents completed successfully (e.g. cancel old + book new, couple booking, combo service). |
| `partial_completed` | Multi-intent conversation: only one sub-intent reached completion (e.g. cancel succeeded but rebooking stuck). Partial failure mode worth tracking separately from `stuck`. |
| `out_of_scope_handled` | Bot correctly identified an out-of-scope request and either deflected politely or asked for clarification, without falsely escalating or attempting a booking. Used for spam, generic advice, phantom-cancel, etc. |

### Audit semantics

- When comparing `outcome` vs `expect.outcome`, flag a mismatch as FAIL.
- Any scenario `expect.outcome` outside the union of v1+v2 enum values is a
  schema violation — flag as CRITICAL in the audit report.
- For v2 scenarios specifically, additional level checks apply:
  - **`info_provided`** scenarios: confirm `tool_calls_required` is empty AND no
    `book`/`update_booking` tool fired. If the bot answered correctly but ALSO
    pushed booking, downgrade L5 score (poor scope discipline).
  - **`multi_completed`** scenarios: confirm BOTH expected DB effects materialized
    (e.g. one row cancelled AND one row inserted). If only one happened, the
    correct outcome is `partial_completed`.
  - **`out_of_scope_handled`** scenarios: confirm bot did NOT invoke `escalate`
    unless explicitly listed in `tool_calls_required`. Spam and generic advice
    should be deflected, not escalated to a human.
  - **`stuck`** for emoji-only / unparseable input: this is acceptable if the
    bot asked for clarification instead of guessing. Verify L1 by checking
    bot's response is a clarification request, not a hallucinated booking.

---

## Inputs (provided in the delegation prompt)

```
Run directory: tests/e2e/runs/20260608_143000/
Baseline directory (optional): tests/e2e/runs/20260607_120000/
```

---

## Execution Protocol

### Step 1: Enumerate Run Files

List all `*.json` files in the run directory that do NOT end in `_traces.json`
and are NOT named `audit.md`. These are the scenario run files.

```bash
fd --extension json --max-depth 1 . tests/e2e/runs/20260608_143000/ | grep -v "_traces.json"
```

### Step 2: Per-Scenario Audit

For each scenario run file, execute the 5-level audit below. Load the companion
`{scenario_id}_traces.json` if present; proceed without it if absent (mark
Langfuse checks as `SKIP — no traces`).

---

### L1 — Structure

**Deterministic. FAIL stops further audit for this scenario.**

Check:
- [ ] `turns` array is non-empty
- [ ] Every turn has `user_message` and `agent_response`
- [ ] No agent response is null or empty string
- [ ] No Python traceback leaked: `rg "Traceback|Internal server error|Exception:" agent_response`
- [ ] No raw JSON or tool output leaked to user (agent_response doesn't start with `{` or contain `"tool_calls"`)
- [ ] `outcome` field is present and is one of: `booked`, `cancelled`, `rescheduled`, `escalated`, `policy_accepted`, `rejected`, `timeout`, `error`, `stuck`, `info_provided`, `multi_completed`, `partial_completed`, `out_of_scope_handled` (v1 + v2 union — see Canonical Outcome Enum section)

**If any L1 check fails, mark this scenario `FAIL (L1)` and skip L2–L5.**

---

### L2 — Payload Integrity

**Requires Langfuse traces.** Skip with `WARN — no traces` if absent.

From the Langfuse trace system prompt (the first `messages[0].content` in each
LLM call, which `PromptAssemblyMiddleware` assembles):

- [ ] System prompt contains `<customer>` XML slot (CustomerResolveMiddleware output)
- [ ] System prompt contains `<availability>` XML slot (AvailabilityContextMiddleware output)
- [ ] System prompt contains `<appointment_context>` XML slot (AppointmentContextMiddleware output)
- [ ] Tool definitions are complete — all 6 tools present in the tool call spec
- [ ] Tool call arguments do NOT contain `customer_phone` (InjectedState contract — R-32/R-33 in `critical_rules.md`)

Root-cause pointer for tool arg violations: `agent/tools/*.py` — look for
`customer_phone` in the tool's Pydantic input schema.

---

### L3 — Tool Calls

**Deterministic.**

#### tool_evidence reliability (Change H — read before scoring L3)

As of Change H, `tool_evidence[]` in every turn object is populated by a
3-tier fallback chain:
  1. LangGraph checkpoint (fastest)
  2. Redis Stream `qa_tool_trace:{conv_id}`
  3. PostgreSQL `conversation_turns.tool_calls` JSONB (`source="db_turns"`)

**`tool_evidence: []` is now DEFINITIVE — it means no tools fired during that
turn**, NOT missing data. The 3-tier chain always runs; empty means empty.

When all turns have `tool_evidence: []` but `tool_calls_required` is non-empty,
that IS an L3 failure (tools were expected but never called), not a data-gap.

When `source="db_turns"` appears in evidence items, the data is post-flush
(slightly delayed compared to checkpoint) — still reliable for L3 checks, but
downgrade L3 confidence to "likely" if ALL evidence comes from `db_turns` and
Langfuse traces are also absent (L2 skipped).

From `turn.tool_calls_observed` across all turns:

- [ ] All tools in `expect.tool_calls_required` appear at least once
- [ ] No tool in `expect.tool_calls_forbidden` appears in any turn
- [ ] For booking flows: `check_availability` or `get_next_available_options` called BEFORE `book`
- [ ] For cancellation flows: `manage_appointments` used (NOT `book`)
- [ ] Policy gate: if `expect.policy_accepted == true`, confirm the policy gate
  fired (look for policy-related system prompt slot or bot message referencing
  the privacy policy URL before the first `book` call)

Root-cause investigation when L3 fails:
1. Identify the turn where the expected tool call was missing
2. Read `agent/agent_factory.py:47-55` — confirm tool is registered
3. Read the relevant tool file — confirm the tool description matches the user intent
4. Read `agent/prompts/shared/tools_contract.md` — check if usage rules block the tool
5. Read `agent/prompts/shared/booking_flow.md` — check flow rules

---

### L4 — Side Effects

**Deterministic.**

- [ ] `db_delta.appt_count_delta` matches `expect.db_appointment`:
  - `+1` for `booked`, `rescheduled`
  - `-1` for `cancelled`
  - `0` for `escalated`, `rejected`, `policy_accepted`, `info_provided`, `out_of_scope_handled`, `stuck`, `timeout`, `error`
  - For `multi_completed`: delta depends on the multi-intent shape (e.g. cancel+book → 0, couple/combo → +2, on-behalf-of → +1)
  - For `partial_completed`: delta is partial (e.g. -1 if only cancel succeeded, +1 if only book succeeded)
- [ ] For created appointments: `gcal_sync_status == 'not_applicable'` in DB (confirms `TEST_MODE_GCAL_SKIP` was active)
- [ ] For `escalated` outcomes: `Notification` row exists in DB for the conversation
- [ ] For `info_provided` outcomes: NO `Notification` row was created (info responses must not trigger escalation noise)
- [ ] For `policy_accepted` without follow-up `book`: confirm `customer.policy_accepted_at` IS populated (catches Pattern C/D from 2026-06-09 audit — policy persistence currently only fires on book)
- [ ] `passed == (outcome == expect.outcome)` consistent

Check `gcal_sync_status`:

```bash
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml exec -T postgres \
  psql -U atrevete -d atrevete_db -c \
  "SELECT gcal_sync_status, gcal_operation FROM appointments
   JOIN customers ON customers.id = appointments.customer_id
   WHERE customers.phone = '<phone>'
   ORDER BY appointments.created_at DESC LIMIT 1;"
```

Root-cause investigation when L4 fails:
- `appt_count_delta` wrong → read `agent/tools/book.py` or `manage_appointments_tool.py`
- `gcal_sync_status != 'not_applicable'` → confirm `TEST_MODE_GCAL_SKIP=true` env, read `agent/services/gcal_push_service.py` bypass guard
- Notification missing → read `api/services/conversation_inbox_service.py`

---

### L5 — UX/Tone

**Rubric-based (1–5 per criterion).**

Score each criterion by reading the conversation turns:

| Criterion | 1 (poor) | 5 (excellent) |
|-----------|----------|---------------|
| **Natural flow** | Robotic form-fill, bot ignores context | Conversational, adapts to user |
| **Warmth** | Cold, transactional | Friendly, welcoming tone |
| **Professionalism** | Too casual or sloppy | Salon-appropriate professional |
| **Recovery** | Crashes or loops on unclear input | Smooth graceful recovery |
| **Castellano compliance** | Uses voseo (`tenés`, `hacé`, `podés`) | Clean Castilian (`tienes`, `haz`, `puedes`) |

Average score (1.0–5.0). Pass threshold: >= 3.0.

Voseo detection — flag as FAIL:
```
rg "tenés|hacé|podés|sabés|querés|estás" turn.agent_response
```

Root-cause for voseo: `agent/prompts/shared/critical_rules.md` R-papercut-fixes
rule. Check if rule is present; if absent, that's the root cause.

No hallucinations check: stylists are Lucía, Carmen, Ana, Sofía, Elena. Flag
any bot response mentioning a different stylist name as a hallucination.

---

### Step 3: Compute Verdict Per Scenario

| Verdict | Condition |
|---------|-----------|
| `PASS` | L1–L4 all pass AND L5 >= 3.0 |
| `WARN` | L1–L4 pass AND (L5 < 3.0 OR any check skipped due to missing traces) |
| `FAIL` | Any L1–L4 check fails |

---

### Step 4: Regression Diff (optional, if baseline provided)

```bash
python tests/e2e/harness/diff.py \
  --base <baseline_dir> \
  --head <run_dir> \
  --out <run_dir>/diff.md
```

List regressions: scenarios that were PASS in baseline and are FAIL/WARN in head.

---

### Step 5: Write audit.md

Write `{run_dir}/audit.md`:

```markdown
# QA Audit Report

**Run**: tests/e2e/runs/20260608_143000/
**Date**: 2026-06-08
**Scenarios**: 15
**PASS**: 13  **WARN**: 1  **FAIL**: 1

## Summary

| Scenario | Outcome | Expected | Verdict | L1 | L2 | L3 | L4 | L5 |
|----------|---------|----------|---------|----|----|----|----|-----|
| change-a-new-booking | booked | booked | PASS | ✅ | ✅ | ✅ | ✅ | 4.2 |
| change-b-cancel | cancelled | cancelled | PASS | ✅ | ✅ | ✅ | ✅ | 3.8 |
| change-c-escalation | stuck | escalated | FAIL | ✅ | ✅ | ❌ | — | — |

## Findings

### CRITICAL

(none)

### WARNING

- **change-a-policy-gate**: L2 skipped — no Langfuse traces available. Manual verification required.

### Detailed Findings

#### change-c-escalation — FAIL (L3)

**Root cause**: `escalate` tool not called despite escalation trigger phrase.

- Turn 7: user said "quiero hablar con alguien" — clear escalation trigger.
- `tool_calls_observed` in turns: `[check_availability]`. Missing: `send_to_human`.
- **File**: `agent/prompts/shared/tools_contract.md` — verify escalation trigger
  phrases match the pattern in booking_flow.md.
- **File**: `agent/tools/escalation_tools.py` — confirm `send_to_human` is
  registered and description is clear.

**Recommendation** [PRIORITY: HIGH]: Review escalation trigger phrase list in
`agent/prompts/shared/tools_contract.md` and ensure "quiero hablar con alguien"
is covered.

## Regression Diff

(none — no baseline provided)

## Recommendations

1. [HIGH] Fix escalation trigger: `agent/prompts/shared/tools_contract.md`
2. [MEDIUM] Enable Langfuse for all test runs to unblock L2 audits
```

---

## Step 6: Return Executive Summary

Return to the orchestrator:

```
Audit complete: tests/e2e/runs/20260608_143000/
Scenarios: 15 | PASS: 13 | WARN: 1 | FAIL: 1

FAIL: change-c-escalation (L3) — escalate tool missing; see audit.md:§change-c-escalation
WARN: change-a-policy-gate (L2) — no Langfuse traces

Top recommendation: Review escalation triggers in tools_contract.md

Audit written: tests/e2e/runs/20260608_143000/audit.md
```

---

## Investigation Protocol

When any L3 or L4 check fails, MUST investigate before writing the finding.

1. Identify the failure turn and the missing/unexpected tool call.
2. Read `agent/agent_factory.py:47-55` — confirm tool registration.
3. Read the relevant tool file in `agent/tools/` — confirm tool description.
4. Read `agent/prompts/shared/tools_contract.md` — check tool usage rules.
5. Read `agent/prompts/shared/booking_flow.md` — check flow-level rules.
6. Read `agent/prompts/shared/critical_rules.md` — check R-rule violations.
7. Provide exact `file:line` reference in the finding.

For L4 DB failures:
1. Run the psql query to verify actual DB state.
2. Cross-reference with `db_delta` in the run JSON.
3. Read the relevant tool in `agent/tools/` for the create/cancel/update path.

---

## Rules

1. **Always audit L1 first.** If L1 fails, skip L2–L5 for that scenario.
2. **Never claim DB outcome without running the psql verification query.**
3. **Investigation is mandatory for L3/L4 failures.** Report `file:line`, not just symptoms.
4. **L2 requires Langfuse traces.** Skip with WARN if absent — do NOT fail.
5. **L5 voseo is always checked** from turn text regardless of traces.
6. **Write audit.md even if all scenarios fail** — partial evidence is better than none.
7. **Do NOT reference deleted artifacts**: `agent/modes/`, `BaseModeNode`,
   `current_mode`, `mode_context`, `mode_history`, `booking_step`.
8. **Hallucination check**: valid stylist names are Lucía, Carmen, Ana, Sofía, Elena.
   Any other name in bot response is a hallucination.
