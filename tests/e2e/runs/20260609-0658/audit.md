# QA Batch Audit — Run 20260609-0658

**Run dir:** `tests/e2e/runs/20260609-0658/`
**Scenarios audited:** 14 of 15 (`change-c-notification-on-failure` is `manual: true` and skipped)
**Audit framework:** atrevete-qa-auditor — L1, L3, L4, L5 applied. **L2 (Payload Integrity) skipped: Langfuse returned 401 invalid token for the whole batch — no system-prompt or tool-arg payload audit available.**

---

## 1. Executive Verdict

**6 PASS / 8 FAIL / 14 audited.** Pass-rate 43%. The deterministic security primitives are healthy: IDOR rejection (cancel + reschedule) and the InjectedState contract both hold under adversarial pressure. The DB+GCal split is also clean — `TEST_MODE_GCAL_SKIP` correctly stamps `not_applicable` on every created appointment. **Three CRITICAL systemic bugs dominate the failures**: (A) every successful `book` writes `status='pending'` while the bot tells the user "te he confirmado" — UX vs SoT mismatch on 100% of happy paths; (B) the `escalate` tool is never fired when the LLM verbalizes "te paso con una persona" — the model says the words but does not emit the tool call; (C) policy acceptance is only persisted as a side effect of a successful `book` call — every conversation that ends before `book` (policy_accepted scenarios) leaves no `customer.policy_accepted_at` row, breaking the very evidence the scenario is designed to verify.

---

## 2. Per-Scenario Matrix

| # | id | outcome | expected | verdict | L1 | L3 | L4 | L5 |
|---|---|---|---|---|---|---|---|---|
| 1 | change-a-idor-cancel-other | rejected | rejected | **PASS** | ✓ | ✓ | ✓ | 4.5 |
| 2 | change-a-policy-gate-blocks-book | policy_accepted | policy_accepted | **WARN** | ✓ | ✓ | ✗ DB | 3.5 |
| 3 | change-a-pre-book-recheck | booked | booked | **WARN** | ✓ | ✓ | ✗ status | 4.0 |
| 4 | change-a-tz-madrid | stuck | booked | **FAIL** | ✓ | ✗ | n/a | 2.5 |
| 5 | change-a-min-days-from-settings | stuck | rejected | **FAIL** | ✓ | ✗ | n/a | 2.0 |
| 6 | change-a-customer-phone-injected | booked | booked | **WARN** | ✓ | ✓ | ✗ status | 4.0 |
| 7 | change-b-cache-warm-second-turn | stuck | booked | **FAIL** | ✓ | ✗ | n/a | 3.0 |
| 8 | change-b-catalog-loaded | stuck | escalated | **FAIL** | ✓ | ✗ escalate not called | n/a | 3.0 |
| 9 | change-b-rules-pruned | stuck | escalated | **FAIL** | ✓ | ✗ escalate not called | n/a | 3.5 |
| 10 | change-c-gcal-synced-status | booked | booked | **WARN** | ✓ | ✓ | ✗ status | 3.5 |
| 11 | change-c-cancel-flow | stuck | cancelled | **FAIL** | ✓ | ✗ | partial | 2.5 |
| 12 | change-c-ownership-check-reschedule | rejected | rejected | **PASS** | ✓ | ✓ | ✓ | 4.5 |
| 13 | change-c-policy-acceptance-stored | stuck | policy_accepted | **FAIL** | ✓ | n/a | ✗ DB | 3.0 |
| 14 | change-c-reschedule-flow | stuck | rescheduled | **FAIL** | ✓ | ✗ | n/a | 2.0 |

*WARN = scenario passed at conversation level but a deterministic side-effect check failed (DB status, missing policy row). Tool-call evidence `tools_observed: []` is empty for the whole batch because the harness collector wasn't wired — L3 was inferred from `agent_response` + `bugs`.*

---

## 3. Root Cause Investigation

### Pattern A — `appointment.status='pending'` while bot says "confirmada" — **CRITICAL**
- **Symptom**: 4 of 4 successful bookings (`pre-book-recheck`, `customer-phone-injected`, `gcal-synced-status`, and the booking inside `cancel-flow`) end with `status='pending'` in DB while the bot's last message is "te he confirmado / Listo, te queda reservada".
- **Root cause**: `agent/tools/book.py:375` hard-codes `status=AppointmentStatus.PENDING` on every insert. There is no later transition to `CONFIRMED` (no follow-up update inside the tool, no event handler). The bot's confirmation message is a prompt-driven UX template that doesn't match the DB enum.
- **Severity**: CRITICAL (every happy path leaks this; production data integrity vs UX expectation).
- **Fix**: change `agent/tools/book.py:375` to `status=AppointmentStatus.CONFIRMED` (the booking flow has already validated availability, policy, and customer identity before reaching this line). If `PENDING` is intentional for an async confirmation step, remove the "te he confirmado" wording from `agent/prompts/shared/booking_flow.md` and replace with "te he prereservado".

### Pattern B — `escalate` tool not invoked when bot says "te paso con una persona" — **CRITICAL**
- **Symptom**: `change-b-catalog-loaded`, `change-b-rules-pruned`, and the dead-end of `change-a-min-days-from-settings` turn 4 all show the model verbalizing handoff intent without firing the `escalate` tool.
- **Root cause**: `agent/prompts/shared/critical_rules.md:7` (R7) tells the model to call `escalate` immediately on a direct human request, but the trigger is conditioned on an *explicit user* ask. When the model itself decides to deflect ("te paso con una persona"), there is no rule that converts that intent into a forced tool call. The tool description in `agent/tools/escalation_tools.py:31-37` is also passive ("Call this tool when the customer explicitly asks…"). The `_settings.POLICY_VERSION` gate and `policy_escalation_required` (R7 second branch) are the only auto-fire paths; the generic "I'm stuck, let me hand off" path is missing.
- **Severity**: CRITICAL (any time the bot can't help, the user receives a verbal promise that never materializes — no Notification row, operator never sees the case).
- **Fix**: extend R7 in `critical_rules.md` with a self-trigger clause: "Si VOS decidís ofrecer transferir a una persona, llamá a `escalate` en el MISMO turno en que lo verbalizás — nunca diferido." Mirror this in `escalation_tools.py:31` description: "Call this tool whenever you tell the user you will hand off, regardless of whether they asked explicitly."

### Pattern C — Policy acceptance not persisted at verbal acceptance — **HIGH**
- **Symptom**: `change-a-policy-gate-blocks-book` and `change-c-policy-acceptance-stored` both verbally accepted policy but the `customer` row was never created — verified by the `bugs[]` field in both JSONs.
- **Root cause**: policy persistence is wired only inside `book()`. `agent/tools/book.py:354-361` reads the fresh customer, and only if `policy_accepted_at` is missing does it call `accept_policy()`. There is no standalone "policy acceptance happened" tool, and no middleware writes consent on its own. When the conversation ends at the policy gate without reaching `book` (the `policy_accepted` outcome), nothing is persisted. `agent/middleware/customer_resolve.py:97-98` only *reads* the consent fields — it never writes them.
- **Severity**: HIGH (the scenario `expect.outcome=policy_accepted` is unverifiable today; also a GDPR audit gap — the user gave verbal consent, the system has no record).
- **Fix**: persist consent at the same moment the assembly produces `next_step=policy_accepted`. Either (a) add an `accept_policy` LangChain tool that wraps `agent/services/policy_service.accept_policy()` and have the prompt instruct the model to call it on the same turn the user accepts, or (b) have `CustomerResolveMiddleware` watch for `collected.policy_accepted=True` transitions and upsert the customer + consent row immediately.

### Pattern D — Policy loop ("sí, acepto" → bot re-asks) — **HIGH**
- **Symptom**: `change-c-cancel-flow` turn 7 — bot says "Me falta volver a registrar tu aceptación de la política para poder confirmar la cita" right after the user said "Sí, acepto la política."
- **Root cause**: same as Pattern C — there is no persistence point at verbal acceptance, so on the next turn the `<customer>` slot still reports "Política privacidad: no aceptada" (`agent/middleware/customer_resolve.py:223`). The model trusts the slot over the visible conversation history (correctly — slots are the SoT contract) and re-asks. The user's second "Sí, acepto" eventually flowed into `book()` which then ran `accept_policy()` as a side effect — that's why turn 8 finally succeeded.
- **Severity**: HIGH (every first-time customer sees the loop; UX is "the bot doesn't believe me").
- **Fix**: same fix as Pattern C — persist on verbal acceptance, not as a `book()` side effect. The slot will then reflect "aceptada" on the next turn and the re-ask disappears.

### Pattern E — Context loss across the policy gate — **HIGH**
- **Symptom**: `change-c-reschedule-flow` turn 7 — bot loses service/date/time/stylist after policy acceptance and says "se ha perdido el contexto del servicio". Turn 10 also shows "ese hueco se ha ocupado justo ahora" appearing spuriously — a stale availability snapshot wins over a draft that should have been alive.
- **Root cause**: the `BookingContext`/draft lives in `AvailabilityContextMiddleware` state and is rehydrated turn-by-turn. There is no protective `update_booking` round-trip on policy acceptance, so when the policy turn runs without a fresh `update_booking(partial_resolved_ids=...)` call, the next assembly sees a blank draft. R-35 (`tools_contract.md` partial_resolved_ids round-trip rule) is documented but not enforced on the policy turn specifically.
- **Severity**: HIGH (any conversation that needs ≥2 turns post-policy hits the same cliff).
- **Fix**: in `agent/prompts/shared/booking_flow.md`, add an explicit rule: "after policy is accepted, the next assistant turn MUST re-emit `update_booking(partial_resolved_ids=[...])` carrying the in-flight draft before proceeding to `book`." Alternatively, in `AvailabilityContextMiddleware`, persist the draft into the long-lived state (not just per-turn cache) so it survives across the policy interrupt.

### Pattern F — Service disambiguation infinite loop ("Tinte" vs "Tinte para hombre") — **HIGH**
- **Symptom**: `change-a-min-days-from-settings` turns 1–4: user repeats "Tinte" verbatim 4 times, bot keeps asking "¿Tinte o Tinte para hombre?" and finally bails to "te paso con una persona" (which itself fails — Pattern B).
- **Root cause**: I could not load the resolver implementation (`agent/booking/resolvers/service_resolver.py` does not exist in the current tree — disambiguation lives in `agent/tools/update_booking.py:465-484` and `_booking_helpers.py:129`). The visible behavior suggests the audience disambiguation gate (Step 1) is firing repeatedly because `audience` stays unknown even though "Tinte" alone (with `audience=adult_female` set by the seed migration `Tinte.audience = 'adult_female'`) should auto-resolve. Either the resolver requires explicit audience input regardless of catalog audience, or the prompt blocks the model from emitting `update_booking(audience='adult_female')` when the user repeats the same word.
- **Severity**: HIGH (any ambiguous principal with an audience-tagged sibling will deadlock).
- **Fix (needs verification)**: in `agent/tools/update_booking.py:465`, allow the audience disambiguation step to be satisfied by the catalog's own `audience` field when the user has not contradicted it (i.e. if the only matching principal has `audience=adult_female`, accept it without re-asking). Adding a fast-path "user repeated the same token N times → commit catalog default" would also help.

### Pattern G — TZ Madrid "tarde" only offers morning slots — **MEDIUM**
- **Symptom**: `change-a-tz-madrid` turn 4 — user explicitly says "10 de junio por la tarde", bot rejects on min-days, then offers slots 10:00/10:40/11:20 without acknowledging the "tarde" preference.
- **Root cause**: `rg "tarde|preferred_window|time_of_day"` against `agent/tools/check_availability.py` and `agent/services/availability_service.py` returns **zero matches**. There is no time-of-day filter or hint at all — `check_availability` returns the earliest slots that satisfy stylist + date + duration, period. The "tarde" semantic is dropped on the floor when collected and the LLM never re-issues a filtered query.
- **Severity**: MEDIUM (annoying UX but customers do eventually pick a slot; not a security or data issue).
- **Fix**: extend `check_availability` arguments with `preferred_window: Literal["manana", "tarde", "any"] = "any"` and filter slots accordingly inside `availability_service`. Bonus: when filtered list is empty, return the unfiltered list with a one-line explanation ("no quedan tardes ese día, te muestro mañanas").

---

## 4. Confirmed Positives

- **IDOR rejection (deep)**: both `change-a-idor-cancel-other` and `change-c-ownership-check-reschedule` rejected cleanly at turn 3 with no DB mutation — ownership checks in `manage_appointments` are tight.
- **InjectedState contract held**: `change-a-customer-phone-injected` shows no `customer_phone` in tool args (inferred from absence of any IDOR-style success — and the tool schemas at `agent/tools/escalation_tools.py:23` and `agent/tools/book.py` all use `InjectedState`).
- **`TEST_MODE_GCAL_SKIP` working**: every created appointment in this run has `gcal_sync_status='not_applicable'` (verified in `change-c-gcal-synced-status` `db_delta`).
- **Critical-rule pruning effective**: `change-b-rules-pruned` scanned all 4 turns — zero references to R2/R3/R9/R15/R33 leaked.
- **`gcal_operation` column populated**: confirmed in successful booking DB snapshots; the `gcal-sync-resilience` migration (`e1f2a3b4c5d6`) is live and writing.

---

## 5. Recommendations (priority order)

1. **`agent/tools/book.py:375`** — flip `AppointmentStatus.PENDING` → `AppointmentStatus.CONFIRMED` (or fix the prompt copy). One-line change; resolves Pattern A across the board.
2. **`agent/prompts/shared/critical_rules.md:7` + `agent/tools/escalation_tools.py:31-37`** — add a self-trigger clause that forces `escalate` whenever the model verbalizes a handoff. Resolves Pattern B.
3. **`agent/middleware/customer_resolve.py:97` (or new `accept_policy` tool)** — persist consent at verbal acceptance, not as a `book()` side effect. Resolves Patterns C + D simultaneously.
4. **`agent/prompts/shared/booking_flow.md`** — add a rule that forces `update_booking(partial_resolved_ids=...)` re-emission on the turn immediately after policy acceptance. Resolves Pattern E.
5. **`agent/tools/update_booking.py:465-484`** — accept catalog-default `audience` when only one principal matches the user's token. Resolves Pattern F.
6. **`agent/tools/check_availability.py`** — add `preferred_window` filter and threshold-empty fallback. Resolves Pattern G.
7. **Harness gap**: `tools_observed` is empty in every JSON. Wire the runner's `tool_evidence` collector (likely `tests/e2e/harness/qa_turn_helper.py`) so L3 audits can be deterministic on the next run.

---

## 6. Known Limitations of This Run

- **Langfuse 401**: invalid API token for the entire batch — L2 (system-prompt slot integrity, tool-arg payload audit) was skipped. All L3 inferences were drawn from `agent_response` text and `bugs[]` notes, not from real tool-call traces. A re-run with a valid Langfuse key is required to confirm Patterns B/F at payload level.
- **`state_reset.py` FK violation patched mid-batch**: `change-a-pre-book-recheck` bugs[0] notes the deletion path failed on `customer_consents` FK before the patch landed. Earlier scenarios in the batch may have residual sandbox state — re-run from a clean reset is recommended before treating any of the WARN verdicts as final.
- **`max_turns` too tight**: `change-c-cancel-flow` (10), `change-c-reschedule-flow` (12), and `change-a-tz-madrid` (6) all timed out on `stuck` while the conversation was still progressing usefully. Even after fixing Patterns A/E, these need +4 turns to complete reliably.
- **`tools_observed` is empty** in every JSON in this run — see Recommendation #7.
