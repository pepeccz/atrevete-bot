# QA Baseline — Atrévete Bot live pipeline

- **Run**: `20260617_144938`
- **Target**: live deploy `pepe@server` (commit `5a23a5f`), agent `TEST_MODE_GCAL_SKIP=true`, `MESSAGE_BATCH_WINDOW_SECONDS=3`
- **Scenarios**: 14 automated (1 `manual` skipped), persona-driven against the real agent, DB-reconciled against Postgres ground truth.

## Verdict matrix (outcome + backend reconciliation)

| # | Scenario | Expected | Conversational | DB ground truth | Verdict |
|---|----------|----------|----------------|-----------------|---------|
| 1 | idor-cancel-other | rejected | rejected (+escalate) | no appt touched | ✅ PASS |
| 2 | policy-gate-blocks-book | policy_accepted | policy gated before book | no customer/policy row persisted | ⚠️ see F3 |
| 3 | **pre-book-recheck** | booked | "booked" (skipped availability) | **NO customer, NO appt** | ❌ **FAIL — hallucinated booking (F1)** |
| 4 | tz-madrid | booked | stuck @ policy gate | no appt | ⚠️ scenario turn-budget (F2) |
| 5 | min-days-from-settings | rejected | rejected (3-day min) | no appt | ✅ PASS |
| 6 | customer-phone-injected | booked | booked, availability shown | confirmed 26-jun 10:00 Harolyn | ✅ PASS |
| 7 | cache-warm-second-turn | booked | stuck @ policy gate | no appt | ⚠️ turn-budget + no cache speedup (F2/F5) |
| 8 | catalog-loaded | escalated | info-provided (real catalog) | n/a | ⚠️ expectation wrong (F4) |
| 9 | rules-pruned | escalated | escalated, no rule-code leak | n/a | ✅ PASS |
| 10 | gcal-synced-status | booked | booked, availability shown | confirmed 20-jun 11:00 Rosa, gcal=not_applicable | ✅ PASS |
| 11 | cancel-flow | cancelled | book→cancel | status=cancelled | ✅ PASS |
| 12 | reschedule-flow | rescheduled | book→reschedule | moved to 24-jun (Wed), confirmed | ✅ PASS |
| 13 | policy-acceptance-stored | policy_accepted | policy+book | policy_accepted_at set, appt confirmed | ✅ PASS |
| 14 | ownership-check-reschedule | rejected | rejected (+escalate) | no appt touched | ✅ PASS (classification nuance, F4) |

**8 clean PASS, 1 critical FAIL, 5 with caveats.** Backend reconciliation confirmed 5 real appointments persisted exactly as the bot claimed (date/time/stylist/status all matched) — and 1 case where the bot claimed a booking that does NOT exist.

---

## Findings

### F1 — CRITICAL: hallucinated booking confirmation (bot bug)
When the customer gives a concrete day + "cualquier estilista" and the bot **skips the availability-presentation / slot-selection step**, it sends a fully specified confirmation ("Te he confirmado la cita martes 23 junio 10:00 con Marta") **without calling the `book` tool**. Agent logs for conv `eb9b9641` confirm: correct phone `+34999000003`, checkpoint persisted, NO book tool fired, and **no appointment row exists**. Reproduced twice (pilot + scenario 3). Contrast: every run that presented availability first (6/10/14) booked for real.
- **Impact**: customer is told their appointment exists when it does not. Directly violates the "if it says X, X must have happened" contract.
- **Likely root cause area**: booking-flow prompt / tool-calling discipline in `agent/prompts/shared/booking_flow.md` + `agent/tools/book.py` gating — the model is allowed to emit a confirmation without a tool round-trip when it auto-selects a slot.
- **Next step**: force the flow to require a `book` tool result before any confirmation language; add a guard that a "confirmada" message cannot be emitted without a persisted appointment id.

### F2 — Scenario turn-budgets are unrealistic for new customers (scenario-design gap)
`tz-madrid` (max 6) and `cache-warm` (max 4) both ran out of turns AT the policy gate, classified `stuck` despite correct bot behaviour. New-customer booking needs: disclose → identify → present availability → policy gate → name → confirm ≈ 7-9 turns. Budgets must be raised or these scenarios will always false-fail.

### F3 — Policy acceptance not persisted without a booking
Scenario 2 accepted the policy but no `customer` row / `policy_accepted_at` was persisted (only scenario 14, which booked, stored it). A returning customer who accepted but didn't book would be re-gated. Confirm whether this is intended.

### F4 — Rigid outcome expectations vs. acceptable bot behaviour
- `catalog-loaded` expects `escalated` but the bot correctly answers the catalog inline (real items, no hallucination) — the expectation looks wrong.
- Both IDOR scenarios `escalate` after refusing rather than emitting a bare `rejected` — functionally safe; the enum/auditor should treat "refuse-then-escalate" as a valid rejection.

### F5 — No cache warm-up observed
`cache-warm` turns were a flat 11-14s band; no second-turn acceleration. Either the cache isn't warming or latency is dominated by the LLM. Needs instrumentation, not conversational inference.

---

## Confirmed HARNESS gaps (for the extension phase)
- **H1 — tool_evidence always empty**: the harness never captures tool calls. L3 (booking-flow-step validation) is non-functional. Today the only way to verify "se respetan todos los pasos" is DB ground truth + transcript reading.
- **H2 — `state` returns has_checkpoint:false even when a checkpoint WAS persisted**: the state-capture reads the wrong thread_id/key. L2/state inspection non-functional.
- **H3 — no service-type/audience assertion**: stylist↔service matching looked correct (manicura→Rosa, tinte→Harolyn) but nothing asserts it deterministically.
- **H4 — no multi-message burst scenario**, and the helper forces `MESSAGE_BATCH_WINDOW_SECONDS=0` in-process (mooted here because the agent container batches at 3s, but no scenario exercises it).
- **H5 — no customer-memory / returning-customer seeding**.

## What's strong today
- Security/IDOR boundary: solid (×2).
- Real bookings persist exactly as claimed; cancel & reschedule mutate the right rows; `gcal_sync_status=not_applicable` honoured (no real GCal touched).
- Castellano discipline (no voseo), AI disclosure, policy gate, and service↔stylist domain matching all held across runs.
