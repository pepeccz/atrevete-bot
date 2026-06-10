# QA Audit Report — V3 Smoke + Extended Batch

**Run**: `tests/e2e/runs/20260609_171708/`
**Date**: 2026-06-09
**Scenarios executed**: 10
**PASS**: 7  **WARN**: 3  **FAIL**: 0 (one WARN carries a CRITICAL data-integrity finding)

L2 (payload integrity via Langfuse) and L5 trace-derived signals are `N/A` across the whole batch — Langfuse returned 401 throughout the run. L5 was scored from turn text only.

---

## 1. Summary Table

| # | Scenario | Outcome | Expected | Verdict | L1 | L2 | L3 | L4 | L5 |
|---|----------|---------|----------|---------|----|----|----|----|-----|
| 1 | alergia-mencionada-en-booking | booked | booked | PASS | OK | N/A | OK | OK | 4.0 |
| 2 | faq-precio-tinte | info_provided | info_provided | PASS | OK | N/A | OK | OK | 4.0 |
| 3 | faq-horarios | info_provided | info_provided | PASS | OK | N/A | OK | OK | 4.2 |
| 4 | consejo-pelo-generico | out_of_scope_handled | out_of_scope_handled | PASS | OK | N/A | OK | OK | 4.0 |
| 5 | spam-marketing-mensaje | out_of_scope_handled | out_of_scope_handled | PASS | OK | N/A | OK | OK | 4.0 |
| 6 | indecisa-cambia-criterio-tres-veces | booked | booked | PASS | OK | N/A | OK | OK | 3.8 |
| 7 | todos-ocupados-fecha-corta | booked (NEW-G fallback) | booked | PASS | OK | N/A | OK | OK | 3.8 |
| 8 | cliente-leal-lo-de-siempre | stuck | booked | WARN | OK | N/A | OK | OK (0) | 3.4 |
| 9 | mensaje-no-procesable-emoji-solo | stuck | out_of_scope_handled / stuck | WARN | OK | N/A | OK | OK | 3.0 |
| 10 | multi-cita-pareja | partial_completed | multi_completed | WARN | OK | N/A | FAIL\* | FAIL\* | 3.0 |

\* Scenario 10 carries a CRITICAL UUID hallucination + multi-customer split gap. Verdict downgraded to WARN (not FAIL) because the single-customer half of the conversation persisted correctly; the second booking attempt errored at tool boundary, not at L1 transport.

---

## 2. CRITICAL Findings

### C1 — UUID hallucination in `book` for second customer (multi-cita-pareja)

- **Symptom**: agent invoked `book` with a fabricated `service_id` UUID for the second person in the couple booking. DB rejected (FK violation) and the second appointment never persisted.
- **Engram**: #6505.
- **Root cause path**:
  - `agent/tools/book.py` accepts `service_id` as an opaque UUID without validating it exists in `services` before insert. The model has no constraint to only emit IDs surfaced by `check_availability` / `get_next_available_options`.
  - System prompt does not currently enforce "echo only IDs returned by availability tools" for `book` arguments.
- **Blast radius**: any multi-intent / couple / on-behalf-of flow where the LLM has to recall a second `service_id` from context. Single-customer happy paths are unaffected because the just-returned availability payload still grounds the first ID.
- **Proposed fix**:
  1. In `agent/tools/book.py`, before insert: `SELECT 1 FROM services WHERE id = :service_id`. If miss → return a structured error to the LLM (`{"error":"unknown_service_id", "hint":"call check_availability again"}`) instead of raising.
  2. Add R-rule in `agent/prompts/shared/critical_rules.md`: "book.service_id MUST be a UUID previously surfaced by check_availability or get_next_available_options in the current turn's availability slot. Never invent."
  3. Add invariant test in `tests/integration/` asserting `book` rejects unknown UUIDs.

### C2 — Infra leak: `TEST_MODE_GCAL_SKIP` not propagated to agent container

- **Symptom**: across the batch, `appointments.gcal_sync_status` for sandbox bookings was NOT consistently `not_applicable`. Real GCal pushes risked firing against the production calendar IDs used in dev.
- **Engram**: #6508.
- **Root cause**: `docker-compose.yml` does not pass `TEST_MODE_GCAL_SKIP` into the `agent` service env block. The variable is set in the host shell but not forwarded into the container.
- **Blast radius**: every E2E sandbox run leaks a real Google Calendar API call per booking. Quota risk + dirties shared dev calendars + makes `gcal_sync_status` checks in L4 untrustworthy.
- **Proposed fix**:
  - Add to `docker-compose.yml` under `services.agent.environment`: `TEST_MODE_GCAL_SKIP=${TEST_MODE_GCAL_SKIP:-false}`.
  - Same for the `archiver` service if it ever pushes (it does not today, but cheap defense).
  - Restart agent container after change; re-run a single booking scenario and verify `gcal_sync_status='not_applicable'`.

---

## 3. WARNING Findings

### W1 — Duplicate sentence in turn 1 of multiple scenarios

- **Engram**: #6500.
- **Symptom**: opening greeting includes the same disclosure-style sentence twice. Cosmetic but visible.
- **Likely root cause**: `DisclosureMiddleware` injects opener, and `PromptAssemblyMiddleware` re-emits an identical line from `identity.md` for first-contact customers.
- **Proposed fix**: in `agent/middleware/disclosure.py`, suppress the duplicated sentence when assembly already contains it, OR centralize the opener in one place. Low priority — pure polish.

### W2 — Emoji-only / unparseable input handled as `stuck` instead of clarification

- **Engram**: #6502.
- **Symptom**: scenario 9 (`mensaje-no-procesable-emoji-solo`) — bot attempts to infer a category from a single emoji rather than asking "¿podrías contarme qué necesitas?".
- **Per SKILL semantics**: `stuck` is acceptable for unparseable input **if and only if** the bot asked for clarification. Here it inferred → fails the spirit of the check.
- **Proposed fix**: add explicit rule in `agent/prompts/shared/critical_rules.md`: "When user input is a single emoji, whitespace, or has no parseable intent → ask one short clarification question. Do NOT infer service or audience." Add booking_flow.md hook in turn-1 handling.

### W3 — Turn-2 context loss / input echo loop

- **Engram**: #6503.
- **Symptom**: in some flows the agent re-asks for information the user already provided in turn 1, or visibly loops on the same input. Suggests `AppointmentContextMiddleware` or `CustomerResolveMiddleware` is overwriting the in-turn working memory between turn 1 → turn 2.
- **Proposed fix**: instrument middleware order in `agent/agent_factory.py:47-55`; verify that turn-1 user message survives into turn-2 assembly. Investigate whether `SummarizeMiddleware` is triggering too early on short conversations and dropping detail.

### W4 — Scenario 8 (`cliente-leal-lo-de-siempre`) max_turns too tight + missing seed

- **Symptom**: scenario expected the bot to look up the loyal customer's "usual" appointment shape from history, but the sandbox customer has no seeded history → bot can't deliver "lo de siempre" inference, and `max_turns` cap fires before the bot can recover via fallback questions.
- **Proposed fix**: (a) bump `max_turns` for new-customer-without-history flows in `tests/e2e/harness/scenarios-v2.yaml`; (b) backlog: add seed mechanism for "returning customer with N past appointments" personas (deferred to Change I+).

### W5 — Multi-customer split gap (also touched by C1)

- **Engram**: #6506.
- **Symptom**: there's no first-class flow for "book person A, then book person B in the same conversation". The agent re-uses the first customer's resolved `customer_id` for the second leg, or fabricates a UUID (see C1).
- **Proposed fix** (deferred to NEW-F): add explicit `book_on_behalf_of` semantics + a multi-customer state slot in `appointment_context.py`. Out of scope for Change I.

### W6 — Runner SKILL.md flag drift (`--message` vs `--user-message`)

- **Engram**: #6498.
- **Symptom**: `skills/atrevete-qa-runner/SKILL.md` documents the wrong CLI flag for sending a user turn. Caused at least one runner restart this batch.
- **Proposed fix**: align SKILL.md with actual runner CLI. One-line doc edit.

---

## 4. PASS Confirmations (Change G live verification)

| Rule | Scenario | Evidence | Engram |
|------|----------|----------|--------|
| **R-37** (allergy safety: bot must surface contraindication, not silently book) | alergia-mencionada-en-booking | Bot acknowledged allergy, asked confirmation before booking, persisted note | #6496 |
| **R-38** (scope discipline: no generic hair advice) | consejo-pelo-generico | Bot deflected to "puedo ayudarte con reservas" without giving styling advice | (this run) |
| **R-36b** (context retention across criterion changes) | indecisa-cambia-criterio-tres-veces | Customer changed service / stylist / day; bot tracked all three without re-asking | (this run) |
| **NEW-G** (fallback when fully booked on the requested short window) | todos-ocupados-fecha-corta | Bot offered next available across all stylists instead of returning empty | (this run) |
| **FAQ scope** (no booking pressure on info_provided) | faq-precio-tinte, faq-horarios | Zero booking tool calls; clean info answer | (this run) |
| **PII protection on inbound spam** | spam-marketing-mensaje | Bot did not echo offer, did not leak customer data, deflected | (this run) |

Also incidentally observed: `services` has **no `price` column** (engram #6493). Bot answered `faq-precio-tinte` from prompt-side static info, not from DB. Document in Change I if a price column is ever added.

---

## 5. Regression Note

Skipped — comparison vs `20260609-0658/` and `20260609-0830/` not run this pass. Recommend running `tests/e2e/harness/diff.py` against `20260609-0830/` as the closest baseline before merging Change I.

---

## 6. Prioritized Recommendations for Change I

| Priority | Item | Files |
|----------|------|-------|
| **P0** | `book.py` service_id validator + R-rule | `agent/tools/book.py`, `agent/prompts/shared/critical_rules.md` |
| **P0** | Propagate `TEST_MODE_GCAL_SKIP` to agent container | `docker-compose.yml` |
| **P1** | Clarification rule for ambiguous input (emoji / empty / whitespace) | `agent/prompts/shared/critical_rules.md`, `agent/prompts/shared/booking_flow.md` |
| **P1** | Investigate turn-2 context-loss / input-echo loop | `agent/agent_factory.py:47-55`, `agent/middleware/summarize.py`, `agent/middleware/appointment_context.py` |
| **P2** | Duplicate-sentence artifact in opener | `agent/middleware/disclosure.py`, `agent/prompts/shared/identity.md` |
| **P2** | Runner SKILL.md flag fix | `skills/atrevete-qa-runner/SKILL.md` |
| **P2** | Retune `max_turns` for new-customer flows | `tests/e2e/harness/scenarios-v2.yaml` |
| **Deferred** | Multi-customer booking on behalf (NEW-F) | new state slot + `book_on_behalf_of` semantics |
| **Deferred** | `services.price` column + DB-grounded FAQ pricing | migration + `agent/services/` lookup |

---

## Notes on Methodology Gaps This Run

- Langfuse returned 401 → L2 fully skipped, L5 scored from turn text only. Restoring Langfuse auth before the next regression batch is the single biggest leverage point for audit quality.
- 4 Change H scenarios (own-appt lookup, reschedule, cancel-single, cancel-rebook) were **skipped** — they need the seeded-customer-with-history mechanism. Track as Change I+ blocker.
- 17 additional v2 scenarios remain unrun; recommend queuing for the next batch after Change I lands.
