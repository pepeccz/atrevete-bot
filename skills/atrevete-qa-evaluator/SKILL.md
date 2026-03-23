---
name: atrevete-qa-evaluator
description: >
  Evaluates conversational QA traces against a five-level quality pyramid.
  Investigates root causes of L3/L4 failures by reading source code and querying the database.
  Produces an actionable report with file:line fix recommendations.
  Trigger: When evaluating a QA conversation, scoring a conversational flow, or generating a QA report.
license: MIT
metadata:
  author: atrevete-bot
  version: "2.0"
  scope: [root]
  auto_invoke:
    - "Evaluating a QA conversation"
    - "Scoring a conversational flow"
    - "Generating a QA report"
    - "Investigating QA test failures"
    - "Root cause analysis of bot behavior"
---

## Purpose

Score a captured conversation trace across five quality levels and investigate root causes of failures. The evaluator has access to Read, Grep, and Bash tools — it MUST investigate the codebase when it finds Level 3 (Execution) or Level 4 (Context) failures.

## Input

The evaluator receives:

1. **Conversation trace** — markdown with embedded JSON from the `atrevete-qa-tester` sub-agent
2. **Flow expectations** — milestones, expected_outcome, persona details
3. **Conversation ID** — for DB verification via `qa_turn_helper.py verify-booking`

### Trace Format (from tester)

The trace contains:
- Turn log as a JSON array: `[{"turn": 1, "user": "...", "bot": "...", "latency_ms": N, "milestone": "...", "bugs": []}, ...]`
- Bugs detected by the tester: table with turn, category, evidence, severity
- Final checkpoint state as a JSON block: `{"current_mode": "...", "customer_name": "...", ...}`
- Outcome: `pass`, `fail`, or `partial`

## 5-Level Quality Pyramid

Evaluate EVERY level in order. Stop ONLY if L1 fails.

### L1 — Structure (deterministic)

Check these conditions against the trace:

- [ ] Every user message got a bot response (no gaps in the turn log)
- [ ] All bot responses are non-empty valid text (not null, not empty string)
- [ ] No internal error messages leaked to the user (no Python tracebacks, no `Error:`, no `Exception`, no `Internal server error`)
- [ ] No raw JSON or tool output leaked to the user

**Scoring**: 1.0 = all pass, 0.0 = any check fails. Binary pass/fail.

**If L1 fails, STOP evaluation here.** Nothing else matters if the bot can't produce basic responses.

### L2 — Text (rubric)

Score each criterion 0.0–1.0 and average:

- **Language**: All responses in Spanish (0.0 if any response is in another language)
- **Coherence**: Responses are grammatically correct and make sense in context
- **Intent match**: Bot responses address what the user actually asked
- **No hallucination**: Bot does not invent services, prices, stylists, or hours that don't exist
- **Appropriate length**: Responses are neither excessively short (< 10 words for substantive questions) nor excessively long (> 200 words for simple confirmations)

**Scoring**: Average of all criteria. Pass threshold: >= 0.7

### L3 — Execution (deterministic)

Check against the flow's expected milestones:

- [ ] Expected milestones reached in the correct order (e.g., `greeting_done` before `service_selected` before `booking_confirmed`)
- [ ] Correct tools were called — verify via the final checkpoint state or `qa_turn_helper.py state <conv_id>`
- [ ] Booking completed when expected (for booking flows) — verify via `qa_turn_helper.py verify-booking --conv-id <conv_id>`
- [ ] Escalation triggered when expected (for escalation flows)
- [ ] No unexpected mode transitions (check `mode_history` in final state)

**Scoring**: fraction of checks passed. Pass threshold: >= 0.8

**If any L3 check fails → trigger Investigation Protocol.**

### L4 — Context (deterministic)

Check state persistence across turns:

- [ ] `customer_name` persists after collection — not asked again in later turns
- [ ] Service selection persists — bot doesn't re-ask for service after user chose one
- [ ] Stylist preference persists — bot doesn't forget user's stylist choice
- [ ] Date/time selection persists — booking details consistent across turns
- [ ] No contradictory information between turns (bot doesn't say one thing then another)

**Scoring**: fraction of checks passed. Pass threshold: >= 0.8

**If any L4 check fails → trigger Investigation Protocol.**

### L5 — UX/Tone (rubric)

Score 1–5 on each criterion and average:

- **Natural flow**: Conversation feels natural, not like a rigid form-fill (1=robotic, 5=human-like)
- **Warmth**: Bot is friendly and welcoming, uses appropriate greetings (1=cold, 5=warm)
- **Professionalism**: Bot maintains salon-appropriate tone (1=too casual/sloppy, 5=professional)
- **Recovery**: When user is unclear or changes mind, bot handles it gracefully (1=crashes/loops, 5=smooth recovery)
- **Brand voice**: Consistent with a beauty salon assistant persona (1=generic chatbot, 5=on-brand)

**Scoring**: Average of all criteria (1.0–5.0). Pass threshold: >= 3.0

## Investigation Protocol

**MANDATORY when L3 or L4 fails.** Do NOT just report the symptom — find the root cause.

### Step 1: Identify the failure point

From the trace, determine:
- Which turn did the failure occur?
- What was the bot's `current_mode` at that point?
- What tool call (if any) was expected but didn't happen?

### Step 2: Read the relevant source code

Based on the failure's mode, read the corresponding mode file:

| Mode | File |
|------|------|
| GREETING | `agent/modes/greeting_mode.py` |
| BOOKING | `agent/modes/booking_mode.py` |
| GENERAL | `agent/modes/general_mode.py` |
| ESCALATION | `agent/modes/escalation_mode.py` |
| Router | `agent/modes/router.py` |
| Prompts | `agent/prompts/modes/{mode}.md` |

Use Grep to search for the function or logic handling the failed step. Look for:
- Missing guard clauses (e.g., not checking if `customer_name` already exists)
- Incorrect state reads (e.g., reading wrong key from `mode_context`)
- FSM transition bugs (e.g., wrong next state after tool call)

### Step 3: Check the final checkpoint state

Parse the `Final State` JSON block from the trace. Verify:
- `current_mode` matches expected mode at conversation end
- `customer_name` is set (for flows that collect it)
- `mode_context` contains expected booking details
- `mode_history` shows expected transitions

### Step 4: Verify business outcome in DB

If the expected outcome is `booking_confirmed`, run:

```bash
docker exec -it atrevete-postgres psql -U atrevete -d atrevete_db -c \
  "SELECT id, customer_name, service_name, stylist_name, start_time, status FROM appointments WHERE customer_phone = '<phone>' ORDER BY created_at DESC LIMIT 1;"
```

Replace `<phone>` with the test persona's phone number from the trace.

If the expected outcome is `escalated`, check the conversation was handed off:

```bash
docker exec -it atrevete-postgres psql -U atrevete -d atrevete_db -c \
  "SELECT id, status, escalation_reason FROM conversations WHERE id = '<conv_id>';"
```

### Step 5: Provide fix recommendations

For each root cause found, provide:
- **File path**: Exact file where the fix should be applied
- **Line number**: Approximate line (from your Grep/Read investigation)
- **Analysis**: What the code does wrong
- **Fix suggestion**: What the code should do instead

## Output Format

Produce a markdown report with this EXACT structure:

```markdown
## QA Evaluation Report

### Overall: PASS / FAIL

### Level Scores
| Level | Score | Pass | Evidence |
|-------|-------|------|----------|
| L1 Structure | 1.0 | ✅ | All 12 turns got responses |
| L2 Text | 0.9 | ✅ | Minor: Turn 5 response too verbose |
| L3 Execution | 0.8 | ⚠️ | Stylist selection skipped |
| L4 Context | 1.0 | ✅ | All context preserved |
| L5 UX/Tone | 4/5 | ✅ | Natural, warm tone throughout |

### Business Outcome
- Goal: {expected_outcome}
- Result: ✅/❌ {description}
- DB Evidence: {appointment details or "not found"}

### Investigation (only if L3 or L4 failed)

#### Failure: {description of what failed}
- **Turn**: {N}
- **Mode**: {mode at failure}
- **Expected**: {what should have happened}
- **Actual**: {what happened}
- **Root cause**: `{file}:{line}` — {explanation}
- **Fix**: {what to change}

### Bugs Found (from tester + evaluator)
| # | Category | Turn | Evidence | Root Cause | Fix |
|---|----------|------|----------|------------|-----|
| 1 | redundant_question | 7 | Bot asked name again | `booking_mode.py:245` doesn't check `customer_name` in state | Add guard: `if state.get("customer_name"): skip name step` |

### Recommendations
1. [Priority: HIGH] {description} — `{file}:{line}`
2. [Priority: MEDIUM] {description} — `{file}:{line}`
3. [Priority: LOW] {description} — `{file}:{line}`
```

## Rules

1. **ALWAYS evaluate L1 first** — if L1 fails, stop. Nothing else matters if the bot can't produce basic responses.
2. **ALWAYS check DB for business outcome verification** — use `qa_turn_helper.py verify-booking` or direct `docker exec psql`.
3. **NEVER claim business completion without DB evidence** — the trace saying "booking confirmed" is not proof. The DB is the source of truth.
4. **Investigation is MANDATORY for L3/L4 failures** — don't just report the symptom. Read the source code, find the root cause, provide file:line references.
5. **Keep recommendations actionable** — every recommendation MUST include a file path. Vague suggestions like "improve error handling" are useless.
6. **Tester bugs are NOT pre-validated** — the tester detects bugs heuristically. The evaluator MUST confirm or dismiss each bug with evidence.
7. **L2 and L5 are rubric-based** — provide explicit evidence for scores. Quote specific turns when citing issues.
8. **L3 and L4 are deterministic** — use the trace data, final state JSON, and DB queries. No subjective judgment.

## Usage

This skill is invoked by the QA orchestrator after the `atrevete-qa-tester` sub-agent completes a conversation. The evaluator receives the full trace as input and produces the evaluation report as output.

```bash
# DB verification command template
docker exec -it atrevete-postgres psql -U atrevete -d atrevete_db -c \
  "SELECT id, customer_name, service_name, stylist_name, start_time, status FROM appointments WHERE customer_phone = '<phone>' ORDER BY created_at DESC LIMIT 1;"

# Final state capture (if not in trace)
python tests/e2e/harness/qa_turn_helper.py state <conv_id>

# Verify booking via helper
python tests/e2e/harness/qa_turn_helper.py verify-booking --conv-id <conv_id>
```
