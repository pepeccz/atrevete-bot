# QA Audit Report — V6 Batch

**Run**: `tests/e2e/runs/20260610_100123/`
**Date**: 2026-06-10
**Deploy under test**: post-Change L, commit `008d8b84`
**Scenarios**: 8
**PASS**: 0  **WARN**: 1  **FAIL**: 7
**Baseline**: V4 `tests/e2e/runs/20260609_183226/` (diff: `diff.md`). Cross-refs: V3 `20260609_171708/`, V5 adversarial `20260609_233246/`.

> Headline: **one latent P0 (`Customer.name` AttributeError in CustomerResolveMiddleware) explains 3 of 7 FAILs and the entire "R-41 regression" narrative.** It is NOT a Change L regression — it has been broken since the create_agent rewrite (commit `291946cc`) and was masked by fail-open exception handling. Every returning customer, in QA *and production*, is currently treated as a brand-new customer.

---

## Summary

| Scenario | Outcome | Expected | Verdict | L1 | L2 | L3 | L4 | L5 |
|----------|---------|----------|---------|----|----|----|----|-----|
| mensaje-no-procesable-emoji-solo | stuck | stuck | **WARN** | ✅ | ⏭ no traces | ✅ | ✅ | 4.0 |
| cancel-con-razon | stuck | cancelled | **FAIL** | ✅ | ⏭ | ❌ | ❌ | 2.0 |
| cancel-fuera-48h | escalated | escalated | **FAIL** | ✅ | ⏭ | ❌ | ❌ | 2.5 |
| laconica-todo-una-linea | stuck | booked | **FAIL** | ✅ | ⏭ | ❌ | ❌ | 3.5 |
| multi-cita-pareja | stuck | multi_completed | **FAIL** | ✅ | ⏭ | ❌ | ❌ | 2.5 |
| impaciente-multiples-mensajes | stuck | booked | **FAIL** | ✅ | ⏭ | ❌ | ❌ | 3.0 |
| cliente-leal-lo-de-siempre | stuck | booked | **FAIL** | ✅ | ⏭ | ❌ | ❌ | 2.5 |
| confundida-pide-aclaracion | stuck | booked | **FAIL** | ✅ | ⏭ | ❌ | ❌ | 4.5 |

Notes:
- L1 passes everywhere: no tracebacks, no JSON leaks, no empty responses, valid outcome enum values.
- `detect-repeats` run on all 8 files: **0 turns with repeated sentences** (Change I + L5 fix holding).
- **No voseo** in any of the 67 bot turns (`rg "tenés|hacé|podés|sabés|querés|vení|decime|contame"` → 0 hits). Castellano compliance: clean.
- No stylist hallucinations: bot only named Harolyn, Marta, Pilar, Victor — matches live `stylists` table (Harolyn, Marta, Pilar, Rosa, Victor). Bot correctly rejected "Carmen" twice. **Note**: the auditor SKILL.md roster ("Lucía, Carmen, Ana, Sofía, Elena") is stale — see Harness Fixes.
- L2 skipped batch-wide: `langfuse_trace_path: null` in all runs (Langfuse client not initialized on server: `No Langfuse client with public key pk-lf-72e4… has been initialized`, agent log 08:04:52).
- L4 DB verification executed against the live sandbox DB (psql via ssh): seeded appointments for `+34999000023` (2026-06-15) and `+34999000045` (2026-06-11) both still `confirmed`; **0 rows in `escalations`** for the run window; **0 rows in `customer_consents`** for `+34999%` phones; `gcal_sync_status='not_applicable'` on all seeded rows (GCAL skip active).

---

## Findings

### CRITICAL

#### C1 — `CustomerResolveMiddleware` never resolves existing customers: `'Customer' object has no attribute 'name'` (P0, production-affecting, latent since create_agent rewrite)

**Evidence (server agent logs, 24 occurrences during this run):**

```
WARNING agent.middleware.customer_resolve — Customer lookup failed for phone +34999000023: 'Customer' object has no attribute 'name'
WARNING agent.middleware.customer_resolve — Customer lookup failed for phone +34999000045: 'Customer' object has no attribute 'name'
WARNING agent.middleware.customer_resolve — Customer lookup failed for phone +34999000033: 'Customer' object has no attribute 'name'
```

**Root cause**: `agent/middleware/customer_resolve.py:107` builds the lookup dict with `"name": customer.name`, but the `Customer` model (`database/models.py:262-278`) has only `first_name` / `last_name` — there is no `name` column and no `@property name`. The `AttributeError` is swallowed by the broad fail-open `except` at `customer_resolve.py:114-116`, which logs a WARNING and returns `None` — so the middleware behaves exactly as if the customer does not exist.

**Blast radius** (all confirmed in this run):
1. `customer_id` never enters state → `manage_appointments` cancel path returns `CUSTOMER_ID_REQUIRED` ("No pude verificar tu identidad", `agent/tools/manage_appointments_tool.py:144-152`) → **self-service cancellation/reschedule is broken for ALL existing customers** (scenarios 2, 3).
2. `read_customer_memories()` is only called after a successful lookup (`customer_resolve.py:214-219`) → **customer_memories never injected** → the entire R-41 "lo de siempre" grounding is dead (scenario 7, Pattern D). This is NOT a prompt regression.
3. Policy status unknown → phone-only `<customer>` block → **policy gate re-fires for customers who already accepted** (scenario 7: Raquel Cordero, DB row verified: `policy_accepted_at=2025-08-14`, `policy_version='1.0'` == server `POLICY_VERSION`).
4. Customer name unknown → **bot re-asks name from customers it has in the DB** (scenarios 3, 7).

**Regression status**: introduced in `291946cc` (create_agent rewrite); present in V3/V4/V5. V3's cliente-leal "PASS" was a false pass (it booked, but as an anonymous new customer; the V3 audit did not check memory grounding). The V6 runner verdict "R-41 regression" is a misattribution — R-41 never worked post-rewrite.

**Fix** (Change N, ~3 lines + test):
```python
# customer_resolve.py:107
"name": f"{customer.first_name} {customer.last_name or ''}".strip(),
```
Plus: (a) unit test that `_lookup_customer` returns a non-None dict for a seeded customer (this would have caught it on day 1); (b) consider logging at ERROR with a counter metric — a fail-open WARNING hid a P0 for multiple deploys.

---

#### C2 — Escalation silent failure: tool claims success, no DB record, bot locks itself (architecture defect; sandbox-triggered crash, real failure mode)

**Evidence**: server logs 08:06:45 (conv `1e4e4f66…` = cancel-con-razon) and 08:08:19 (conv `389a06a0…` = cancel-fuera-48h):

```
ERROR agent.services.escalation_service — Cannot initialize escalation client: invalid literal for int() with base 10: '389a06a0-…'
ERROR agent.tools.escalation_tools — escalate: escalation failed at step unknown step
```

DB verified: **0 rows in `escalations`** despite the run outcome `escalated` and the bot telling the customer "Te paso con alguien del salón ahora mismo."

**Root cause chain**:
1. `agent/services/escalation_service.py:284-291` — `conv_id_int = int(conversation_id)` fails for UUID conv ids, and the function **returns early BEFORE S5 (DB escalation record)**. The Chatwoot client init is fused to the DB record: if Chatwoot can't be reached/parsed, no escalation evidence is persisted anywhere.
2. `agent/tools/escalation_tools.py:70-75` — on `result.success=False` the tool returns the *soft* string "Estoy intentando transferirte a un agente. Por favor, espera un momento…". Nothing tells the LLM the escalation FAILED, so the LLM paraphrases it as success ("ya he escalado este caso").
3. `escalation_tools.py:46` docstring — "After calling this tool, stop responding to booking requests for this conversation" — combined with (2), the bot enters a **phantom post-escalation lock**: cancel-con-razon turns 2-3, the bot refuses a legitimate >48h self-service cancellation because it believes a human (who will never come) owns the conversation.

The `int()` crash itself is sandbox-triggered (harness uses UUID4 conv ids; production Chatwoot uses integers — see Sandbox Artifacts). The **silent-failure mode is a real production defect regardless**: any Chatwoot outage/4xx today produces the same "claimed escalation, no record, locked bot" behavior. Violates the Change J principle that tool failures must be loud.

**Fix** (Change N):
- Decouple S5: write the `escalations` DB row + admin `Notification` even when the Chatwoot client fails (move S5 before/independent of client init).
- Tool contract: on `result.success=False`, return a machine-readable failure (`ESCALATION_FAILED: no human was notified. Tell the customer to call the salon at <phone>; do NOT claim the handoff happened`) and do NOT apply the stop-responding instruction.
- Scope the docstring lock to `result.success=True`.

---

#### C3 — Booking-rejection dead loops: no deterministic recovery, no escalation cap (scenarios 4, 5; Pattern C)

**Evidence**: multi-cita-pareja turns 6-12 — two full cycles of fabricate-UUID → `update_booking` FK rejection (`UUIDs no válidos o inactivos`, `agent/tools/update_booking.py:343-356`) → apology → user agrees to redo → same failure. 12 turns consumed, `escalate` never called. laconica-todo-una-linea turn 8 — `book` rejected by the guard chain (server log `tool.response.rejected` for `book` at 08:09:28/08:10:07; most plausible guard: `pre_book_validation_required`, `agent/tools/book.py:221-229`, since the only `check_availability` call was the turn-2 *list* query, never the slot-specific `slot_time=…` validation) → bot honestly reports "se me ha quedado atascada la reserva" but max_turns hits before recovery.

The validators are working as designed (no hallucinated booking reached the DB — Change J holding at the data layer). The gap is **above** the validators: when a tool rejects, the prompt contract relies on the LLM to self-correct, and the LLM instead asks the user for permission to retry, producing user-visible limbo.

**Fix** (Change N):
- Add a consecutive-rejection counter to state (incremented by `book`/`update_booking` rejected responses). At N=2 for the *same* next_step, return `next_step="escalation_required"` from the tool itself, forcing R7 (`critical_rules.md:7`) to fire deterministically.
- Prompt rule: after `pre_book_validation_required`, the model MUST call `check_availability(slot_time=…)` and then `book` again in the SAME turn — never ask the user for permission to retry an internal step.
- For the fabricated-UUID case: the rejection payload should include the valid resolved IDs (or instruct re-calling with `services` names only and `partial_resolved_ids` per R-35) so the model has a concrete recovery path.

---

#### C4 — "fiebre" triggers immediate safety escalation on a routine cancellation (scenario 2)

**Evidence**: cancel-con-razon turn 1 — appointment 5 days out, user says "estoy con fiebre, prefiero cancelarla" → bot escalates immediately, `manage_appointments` never called, then C2's phantom lock makes turns 2-3 unrecoverable.

**Root cause**: R-37 (`agent/prompts/shared/critical_rules.md:44-48`) defines the safety gate for **chemical-service booking** with trigger set {alergia, embarazo, medicación, …} — "fiebre" is not in the set and cancellation is not in scope. The LLM is over-generalizing R-37 to "any illness mention anywhere". There is no negative rule scoping it.

**Fix** (Change N, prompt-only): add explicit negative scope to R-37: *illness/fever given as a reason to CANCEL or RESCHEDULE is NOT a safety trigger — proceed with `manage_appointments` normally and wish them a quick recovery.* 

---

### WARNING

- **W1 — Policy acceptance not persisted unless `book` succeeds** (laconica): `policy_gate_check.db_customer_consents_row=false` after explicit acceptance at turn 6; DB confirms 0 consent rows. Known Pattern C/D from the 2026-06-09 audit — acceptance persistence rides on the `book` transaction (`agent/tools/book.py:384-399`). If `book` never succeeds, consent evaporates. Re-rank: with C3 making book failures common, this is now user-visible (customers re-accept). Bundle with Change N or explicitly re-defer.
- **W2 — `tool.response.rejected` logs are blind**: emitted at INFO with reasons in `extra={…}` (`book.py:212`, `update_booking.py:345` et al.), but the JSON log formatter drops extras — server logs show only the bare message, no `conversation_id`, no `next_step`, no invalid IDs. Root-causing C3 required inference. Fix: include tool_name/next_step/conversation_id in the message string or make `shared/logging_config.py` serialize extras.
- **W3 — Audience re-ask despite explicit qualifier** (scenarios 1, 4, 6, 7; Pattern B): "Corte de mujer" / "Corte dama" / returning female customer all still get "¿Es para señora, caballero, niña, niño o bebé?". Mechanism: the LLM calls `update_booking` with `audience=None`, tool rejects `audience_required` (`update_booking.py:515-529`), bot re-asks. Note "Corte Dama" is the literal catalog service name and still re-asked (laconica turn 1). Fix is prompt-side (booking_flow.md Paso 2): map mujer/dama/señora→`audience="adult_female"` etc. BEFORE calling, and never re-ask a dimension present in the user's words. Optionally tool-side: strict-resolve fully-qualified names without the audience gate.
- **W4 — Date context loss + parse failure** (impaciente turns 3→6→7): "mañana por la tarde" (turn 3) dropped after the stylist step; then "11 de junio por la tarde" answered with "¿Me dices el día y el mes exactos?" — a clearly formatted date failed to parse twice, costing 3 turns. Likely same family as W3 (slot context not carried into the tool call); traces needed to confirm whether it's prompt or `check_availability` date parsing.
- **W5 — 17:00 request answered with morning slots, no explanation** (laconica turn 2): bot must acknowledge the requested time is unavailable before offering alternatives (UX review obs #6550 overlap).
- **W6 — Premature data collection** (confundida turns 6-8): name + notes collected before any availability shown; cost 2-3 turns and contributed to the max_turns exhaustion. booking_flow ordering rule needed: slots → selection → name/notes.
- **W7 — runner `policy_gate_skipped` in impaciente is NOT a defect** (verified): the gate fires at slot-confirmation/book time; the conversation died at name collection (turn 10), before any `book` attempt. The book-side gate (`book.py:384-399`) was never reached. Runner misread — no action on the bot; fix the runner's check to only assert the gate after a `book` attempt or slot-confirmation milestone.
- **W8 — tool_evidence missed a real tool call** (cancel-con-razon): server log proves `escalate` fired at 08:06:45 for conv `1e4e4f66…`, but all three turns have `tool_calls_observed: []`. Change H's "empty is definitive" contract is violated — the 3-tier evidence chain has a gap (likely: tool crashed → checkpoint write pattern differs). Harness fix.

### Verdict corrections vs runner self-reports

| Scenario | Runner said | Audit verdict |
|---|---|---|
| mensaje-no-procesable-emoji-solo | PASS | **WARN** (only because L2 unverifiable batch-wide; behavior is the best of the batch) |
| cancel-fuera-48h | "surface escalated" | **FAIL** — L3 (`manage_appointments` never called) + L4 (`escalated` outcome with 0 escalation rows = phantom) |
| impaciente | FAIL incl. policy_gate_skipped | **FAIL**, but drop the policy finding (W7) |
| cliente-leal | FAIL, 6 bugs | **FAIL**, but all 6 bugs collapse into C1 (single root cause) |

---

## Regression Diff vs V4 (`diff.md`)

| Scenario | V4 | V6 | Real status |
|---|---|---|---|
| laconica-todo-una-linea | booked | stuck | **TRUE REGRESSION** — book rejected by guard chain at final step (C3). V4 booked the same flow. Prime suspect: Change L tightening of pre-book/slot validation paths interacting with LLM retry behavior. |
| impaciente-multiples-mensajes | booked | stuck | **TRUE REGRESSION** — date context loss (W4) burned 3 turns; V4 completed within budget. |
| multi-cita-pareja | partial_completed | stuck | **DEGRADED** — V4 got one booking through; V6 got zero (FK-rejection loop, C3). Validator unchanged-correct; recovery worsened. |
| cancel-con-razon | escalated | stuck | Lateral — both wrong vs expected `cancelled`. V6 adds phantom-lock (C2). Underlying C1+C4 present in both. |
| mensaje-no-procesable-emoji-solo | stuck | stuck | Stable-good (expected stuck). +1 minor bug (W3 turn 3). |
| cancel-fuera-48h / cliente-leal / confundida | not in V4 | — | No baseline; not regressions. |
| faq-atienden-hombres | timeout (V4) | not run | Coverage gap — re-include in V7. |

---

## Sandbox Artifacts (do NOT treat as production bugs)

1. **Chatwoot 404s** (`chats.zonavix.com/...conversations/<uuid>/messages`): harness conv ids are UUID4; production uses integer Chatwoot ids. Outbound mirror fails on every turn — harmless to the run (responses captured via Redis), noisy in logs.
2. **`int(conversation_id)` escalation crash trigger**: same UUID-vs-int mismatch. The *crash* won't happen in production — but C2's silent-failure handling of that crash is a real defect (any Chatwoot failure reproduces it).
3. **OTel 401 span export noise** in agent logs (filtered out of this analysis).
4. **Slot races**: 8 parallel runners shared one sandbox calendar. confundida turn 11 ("se me ha quedado sin hueco ese turno justo al validar", 37s latency) is consistent with a race — and the bot handled it gracefully (good Change J behavior). **laconica's failure is NOT a slot race**: server logs show `book` `tool.response.rejected` (validator guard), not an availability conflict.
5. **Langfuse disabled on server** → L2 unverifiable batch-wide. Fix the server credentials before V7 or L2 stays dark.

---

## Cross-Scenario Pattern Analysis

- **A. Seeded-customer resolution (sc. 2, 3, 7)** → single code bug, C1. Not a seeding artifact: DB rows verified present and correct (Isabel Domínguez +…023, Nuria Castillo +…045, Raquel Cordero +…033 with 3 completed appointments and policy v1.0); phones flowed correctly through the harness (`Stream message received … phone=+34999000030/23/33/45` in logs); the middleware lookup itself crashes.
- **B. Disambiguation context loss (sc. 1, 4, 6, 7)** → W3 + W4. Prompt-contract gap, not middleware: the model under-fills `update_booking(audience=…)` / drops date into tool calls; the tool then "asks again" by contract.
- **C. No-recovery loops (sc. 2, 4, 5)** → C2 + C3. Architectural: rejected-tool recovery is entrusted entirely to the LLM with no deterministic cap or forced-escalation exit.
- **D. R-41 memory grounding (sc. 7)** → downstream of C1. The injection code (`_build_memory_lines`, `customer_resolve.py:119-163`) is correct but unreachable. Re-test after C1 fix before touching prompts.
- **E. max_turns calibration** → laconica 8→10, impaciente 10→12, confundida 12→14, cliente-leal 8→10. Keep emoji at 5 (expected stuck) and multi-cita at 12 (more turns won't fix a loop). cancel scenarios 3→5 to observe recovery behavior after fixes.

---

## Recommendations

### (i) Change N scope — bot fixes (bundle with UX review obs #6550)

1. **[P0] C1** — `customer_resolve.py:107` name fix + regression test + ERROR-level logging on lookup exceptions. Smallest possible diff, biggest impact: unblocks cancel flows, R-41 memories, policy-gate skip, name skip for ALL returning customers. Re-run scenarios 2/3/7 immediately after.
2. **[P0] C2** — escalation loud-failure: S5 DB record decoupled from Chatwoot client init; `ESCALATION_FAILED` tool message; lock instruction scoped to success.
3. **[P1] C3** — consecutive-rejection counter → forced `escalation_required` at 2 strikes; same-turn retry rule for `pre_book_validation_required`; recovery payload (valid IDs) in FK rejections.
4. **[P1] C4** — R-37 negative scope: illness as cancellation reason ≠ safety trigger (prompt-only).
5. **[P2] W3** — audience-qualifier mapping rule in booking_flow.md Paso 2 (+ glossary line: dama/señora/mujer → adult_female; caballero/hombre → adult_male).
6. **[P2] W5 + W6** — UX ordering rules (acknowledge unavailable requested time; slots before name/notes) — natural fit with obs #6550 items.
7. **[P2] W1** — persist policy consent at acceptance time (not only inside book), or explicitly re-defer with Pilar's sign-off.
8. **[P3] W2** — make tool rejection logs carry reason + conversation_id through the JSON formatter.

### (ii) Harness fixes

1. **W8** — tool_evidence gap: capture tool calls that error (cancel-con-razon's escalate was invisible to all 3 tiers). Add a test: crash a tool deliberately, assert evidence captured.
2. **Langfuse server credentials** — L2 has been SKIP for two consecutive batches; fix before V7.
3. **max_turns calibration** per Pattern E table.
4. **Runner policy-gate check** (W7): only assert the gate after a book attempt / slot-confirmation milestone.
5. **SKILL.md stylist roster stale**: update `skills/atrevete-qa-auditor/SKILL.md` Rule 8 to Harolyn, Marta, Pilar, Rosa, Victor (current `stylists` table) or make it query the DB.
6. **Re-include faq-atienden-hombres** (and the V4 set) in V7 for full coverage.
7. Consider integer conv-ids (or a Chatwoot stub) in the harness to stop masking/triggering the int() family of issues — keep ONE UUID scenario to keep testing the loud-failure path.

### (iii) Defer / needs-Pilar

1. **Change M** — multi-customer companion split (scenario 5's husband handling): known deferral, unchanged.
2. **W1 consent persistence timing** if not bundled in Change N — GDPR-adjacent, Pilar should rank it.
3. **POLICY_VERSION / re-gate UX copy** for genuinely outdated-version customers — behavior is correct post-C1, but the message wording for "versión obsoleta" re-acceptance should get Pilar's eyes.
4. **3-day minimum booking lead time** (`MIN_BOOKING_DAYS=3`) — laconica/impaciente both asked for "mañana" and were refused; correct per config, but worth confirming with Pilar that 3 days is the intended business rule (it cost both scenarios their first choice).

---

*Audit executed per `skills/atrevete-qa-auditor/SKILL.md`. Evidence: 8 run JSONs, `detect-repeats` on all files, `diff.py` V4→V6, server agent logs (24h window), live sandbox DB queries (customers / appointments / escalations / customer_consents / stylists).*
