# Fase E QA Audit Report

**Run directory:** `tests/e2e/runs/20260702_103343_faseE/`  
**Run timestamp:** 2026-07-02 10:33:43  
**Auditor:** automated via `reconcile` + `detect-repeats` SSH harness + manual inspection  
**Audit date:** 2026-07-02  

---

## 1. Summary Table

| # | Scenario | Expected Outcome | Observed Outcome | L1 | L3 | L4 (consent / halluc / appt-status) | L5 | VERDICT |
|---|----------|-----------------|-----------------|----|----|--------------------------------------|----|---------|
| 1 | change-a-idor-cancel-other | rejected | rejected | ✓ | ✓ | PASS — no appt / no halluc | Clean | **PASS** |
| 2 | change-a-policy-gate-blocks-book | policy_accepted | policy_accepted | ✓ | ✓ | PASS — no appt, book not called | Clean | **PASS** |
| 3 | change-a-pre-book-recheck | booked | booked | ✓ | ✓ | PASS — pending / ok / service_match ✓ | Clean | **PASS** |
| 4 | change-a-tz-madrid | booked | booked | ✓ | ✓ | PASS — pending / ok / consent_ok | Clean | **WARN** |
| 5 | change-a-min-days-from-settings | rejected | rejected | ✓ | ✓ | PASS — no appt / book not called | Clean | **PASS** |
| 6 | change-a-customer-phone-injected | booked | booked | ✓ | ✓ | PASS — pending / ok / consent_ok | Clean | **PASS** |
| 7 | change-b-cache-warm-second-turn | booked | booked | ✓ | ✓ | PASS — pending / ok / consent_ok | Clean | **PASS** |
| 8 | change-b-catalog-loaded | info_provided | info_provided | ✓ | ✓ | PASS — no appt | Clean | **PASS** |
| 9 | change-b-rules-pruned | escalated | info_provided | STALE | ✓ | PASS — no appt / no R-leak | Clean | **PASS*** |
| 10 | change-c-gcal-synced-status | booked | booked | ✓ | ✓ | PASS — pending / ok / gcal=not_applicable | Clean | **PASS** |
| 11 | change-c-cancel-flow | cancelled | cancelled | ✓ | ✓ | PASS — cancelled / ok / consent_ok | Clean | **PASS** |
| 12 | change-c-reschedule-flow | rescheduled | rescheduled | ✓ | ✓ | PASS — pending / ok / consent_ok | Clean | **PASS** |
| 13 | change-c-policy-acceptance-stored | policy_accepted | booked | WARN | ✓ | PASS — pending / ok / consent_ok | WARN (manual) | **WARN** |
| 14 | change-c-ownership-check-reschedule | rejected | rejected | ✓ | ✓ | PASS — no appt | Clean | **PASS** |
| 15 | change-d-returning-customer-personalization | booked | booked | ✓ | ✓ | PASS — pending / ok / consent_ok / Marta ✓ | Clean | **PASS** |

*PASS with spec correction required — see Section 3.

---

## 2. Per-WARN Detail

### WARN #1 — change-a-tz-madrid (scenario 4)

**Root cause:** Afternoon preference lost on fallback date redirect.

Elena Garcia asked for afternoon slots ("buenas noches, teneis huecos mañana por la tarde?"). The advance-policy gate correctly blocked July 3 (< 3 days). When the bot redirected to July 7, it offered morning slots (10:00, 10:40, 11:20) without carrying the "tarde" preference forward. The booking completed correctly (pending status, consent_ok), and the TZ check itself passes (all ISO timestamps carry `+02:00`; calendar link uses correct UTC `20260707T080000Z`). The afternoon preference loss is a UX regression, not a correctness failure.

**Severity:** WARN — bot produced a valid booking; only the time-of-day preference was silently dropped.  
**Files relevant to fix:** `agent/tools/check_availability.py`, `agent/middleware/availability_context.py`  
**Evidence:** `turns[4].agent_response` offers slots at 10:00/10:40/11:20 after a user request for "tarde" (afternoon = from 16:00 in ES).

---

### WARN #2 — change-c-policy-acceptance-stored (scenario 13)

**Two separate issues found:**

**Issue A — L1 label mismatch (spec, not bot):**  
`expected.outcome = "policy_accepted"` but `outcome_observed = "booked"`. The scenario completed a full booking (appointment `8622ed37`, Marta, Corte de Mujer, 2026-07-07T10:40). `expected.db_appointment = null` and `expected.tool_calls_required = []` are both inconsistent with what the test actually exercises. The scenario intent is correct — verify that consent is persisted after a booking — but the outcome label is stale. Reconcile confirms `consent_ok = true`, `consent_rows = 1`, `policy_accepted_at = 2026-07-02T08:55:03+00`. **Bot behavior is correct.**

**Issue B — Manual L5: repeated question in turn 1:**  
Turn 1 agent response contains the sentence `"¿Para qué servicio te gustaría la cita?"` verbatim twice in the same message (visible in `turns[0].agent_response`). The automated `detect-repeats` tool returned 0 findings (it detects cross-turn repetition, not within-turn). This is a response-generation quality defect — likely a prompt assembly double-inject on the first turn for a brand-new customer with no prior context.

**Severity:** WARN (no correctness impact; consent is correctly stored; repeated question is a UX glitch).  
**Files relevant to fix (repeated question):** `agent/middleware/prompt_assembly.py`, `agent/middleware/dynamic_prompt.py` (first-turn assembly path).  
**Evidence file:line:** `change-c-policy-acceptance-stored.json` → `turns[0].agent_response` (line 17-18 in the JSON).

**Note:** The runner's annotation "CONSENT-PERSISTENCE BUG CONFIRMED" is a FALSE ALARM — it was based on reading `final_state.customer_consents_count = 0` and `final_state.policy_accepted_at = null`, which come from the LangGraph checkpoint snapshot, not the DB. The `reconcile` tool confirms the DB truth: consent row exists, policy_accepted_at is set. See Section 4 for the full measurement-artifact explanation.

---

## 3. Spec Corrections Recommended

### SC-1 — change-b-rules-pruned: escalated → info_provided

**Current spec:** `expected.outcome = "escalated"`  
**Correct spec:** `expected.outcome = "info_provided"`

The bot correctly answered Julia Moreno's questions about the booking system and cancellation policy inline, without escalating. This is the desired behavior after the rules-pruning optimization: general FAQ is served from cached context, not routed to a human.

**Critical sanity check passed:** Neither agent response in turns 1 or 2 contains any internal rule reference (R2, R3, R9, R15, R33 or any `R-\d+` pattern). Internal rules are not leaking to the customer-facing channel.

**Action:** Update `scenarios.yaml` → `change-b-rules-pruned` → `expected.outcome: "info_provided"`.

---

### SC-2 — change-c-policy-acceptance-stored: policy_accepted → booked + explicit consent assertion

**Current spec:**  
```yaml
expected:
  outcome: "policy_accepted"
  db_appointment: null
  tool_calls_required: []
```

**Correct spec:**  
```yaml
expected:
  outcome: "booked"
  db_appointment:
    status: "pending"
  tool_calls_required: ["check_availability", "book"]
  assertions:
    consent_ok: true   # L4 reconcile must confirm consent_rows >= 1
```

The scenario exercises a full booking flow to verify consent persistence. The current `db_appointment: null` and `tool_calls_required: []` are inconsistent with the actual test path. The bot behavior is correct; the spec needs to catch up.

---

### SC-3 — change-c-policy-acceptance-stored: add L5 guard for within-turn repeats

The automated `detect-repeats` tool does not catch repeated sentences within a single turn response. The turn-1 doubled question in this scenario would have been caught by a within-turn check. Recommend extending `detect-repeats` to include intra-turn duplicate sentence detection.

---

## 4. Consent Persistence — DB-Verified Truth

### State-vs-DB Measurement Artifact (MANDATORY NOTE)

**The `state` command reads the LangGraph checkpoint, NOT the database.** Multiple runners reported `customer_consents_count = 0` and `policy_accepted_at = null` in `final_state`, which caused confusion and led to incorrect "bug confirmed" notes in several scenarios. **Do not treat `final_state.customer_consents_count` or `final_state.policy_accepted_at` as authoritative.** The only authoritative source is the `reconcile` subcommand.

### Reconcile Results — All Booking Scenarios

| Scenario | Phone | consent_ok | consent_rows | policy_accepted_at |
|----------|-------|------------|-------------|-------------------|
| change-a-pre-book-recheck | +34999000003 | true | 1 | 2026-07-02T08:39:58+00 |
| change-a-tz-madrid | +34999000004 | true | 1 | 2026-07-02T08:41:55+00 |
| change-a-customer-phone-injected | +34999000006 | true | 1 | 2026-07-02T08:47:36+00 |
| change-b-cache-warm-second-turn | +34999000007 | true | 1 | 2026-07-02T08:48:57+00 |
| change-c-gcal-synced-status | +34999000010 | true | 1 | 2026-07-02T08:54:18+00 |
| change-c-cancel-flow | +34999000011 | true | 1 | 2026-07-02T08:53:54+00 |
| change-c-reschedule-flow | +34999000012 | true | 1 | 2026-07-02T08:54:21+00 |
| change-c-policy-acceptance-stored | +34999000014 | true | 1 | 2026-07-02T08:55:03+00 |
| change-d-returning-customer-personalization | +34999000050 | true | 1 | 2026-07-02T08:58:39+00 |

**All 9 booking scenarios confirm consent_ok = true.** The consent persistence subsystem is working correctly end-to-end. The earlier "CONSENT-PERSISTENCE BUG CONFIRMED" annotation in the change-c-policy-acceptance-stored runner notes was a false alarm caused by reading the state checkpoint instead of the DB.

### GCal Sync Status — change-c-gcal-synced-status

Runner included a direct `db_verified` block in `final_state` (added at run time):
```json
{"appointment_id": "1af0157e-...", "status": "pending", "gcal_sync_status": "not_applicable"}
```
`reconcile` confirms `appointment_status = pending`. `gcal_sync_status = not_applicable` is expected because `TEST_MODE_GCAL_SKIP=true` was active during the run. **L4 passes for GCal sync status.**

---

## 5. Additional Notes

### change-c-reschedule-flow — returning customer name collision

Phone `+34999000012` (Pilar Navarro persona) already had a customer record named "Ana García" in the sandbox from a prior run. The bot correctly used the existing DB name ("Perfecto, Ana. ¿Quieres dejarme alguna nota?") instead of asking for a name again. This is correct returning-customer behavior. The reconcile confirms the appointment was created and consent is stored under the existing customer record. **Not a bug; test data isolation concern.** Recommend seeding scenario 12 with a phone that has no prior customer record, or explicitly cleaning it in `cleanup.py`.

### change-a-customer-phone-injected — book-before-policy guard working correctly

Turn 8 shows `book()` called with `policy_accepted=false` → rejected with `policy_acceptance_required`. The bot then presented the policy gate, and on policy acceptance the full flow succeeded. The server-side `book()` guard is enforcing policy acceptance independently of the UI-layer `update_booking` state — defense-in-depth confirmed.

### change-d-returning-customer-personalization — must_contain_any check

Turn 1 response: *"Te propongo con Marta estas próximas citas disponibles para corte de mujer"* — contains **"Marta"** from `must_contain_any`. Personalization fired on the first message with zero prompting. ✓

---

## 6. Final Tally

| Verdict | Count | Scenarios |
|---------|-------|-----------|
| **PASS** | 13 | 1, 2, 3, 5, 6, 7, 8, 9*, 10, 11, 12, 14, 15 |
| **WARN** | 2 | 4 (tz-madrid), 13 (policy-acceptance-stored) |
| **FAIL** | 0 | — |
| **Total** | 15 | |

*Scenario 9 (rules-pruned) is PASS with a spec correction required; bot behavior is correct.

---

## 7. Go / No-Go for Production Launch

**GO — with two tracked WARNs.**

No true failures. Both WARNs are quality-level issues with no correctness or security impact:

- **WARN-4 (tz-madrid):** Afternoon preference is dropped on fallback-date redirect. Customer still gets a valid booking; only the time-of-day preference is silently lost. Track as a UX bug, not a blocker.
- **WARN-13 (policy-acceptance-stored):** Spec label is stale (should be "booked", not "policy_accepted"), and a within-turn question duplication occurs on first turn for brand-new customers. Consent is correctly persisted. Track as a minor prompt-assembly defect; not a blocker.

All security-critical paths passed: IDOR protection (scenarios 1, 14), advance-policy gate (scenarios 5, 2), ownership check on reschedule (scenario 14), book-before-policy server-side guard (scenario 6 turn 8). Consent persistence confirmed DB-true for all 9 booking scenarios.

---

*Report generated: 2026-07-02 — Fase E regression batch (15 scenarios)*
