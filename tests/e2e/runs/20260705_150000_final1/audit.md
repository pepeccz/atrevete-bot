# QA Audit Report

**Run**: `tests/e2e/runs/20260705_150000_final1/`
**Date**: 2026-07-05
**Scenarios**: 16 (1 additional scenario, `change-c-notification-on-failure`, was skipped as manual per run instructions and is not scored here)
**PASS**: 11  **WARN**: 3  **FAIL**: 2

**Global note on L2 (Payload Integrity)**: Langfuse traces are `null`/401-unauthorized for all 16 scenarios (known server credential issue, documented in the runner briefing and in prior batches). L2 is marked `SKIP` uniformly and does **not** by itself demote a scenario's verdict — consistent with the Fase E precedent (`tests/e2e/runs/20260702_103343_faseE/audit.md`), where the same limitation did not block PASS verdicts. Verdicts below are driven by L1/L3/L4 deterministic checks plus L5/L6 findings that survive manual review.

**Global note on step-order / gate-flag-timing automation**: none of the 16 run JSONs populate the rich `tool_evidence` array (`tool_name`/`arguments`/`result`) that `detect-gate-flags` and `check-step-order` require — they only carry a bare `tool_calls_observed` name list. Both CLI checks ran clean (`premature_flag_detected: false`, but `step_order_ok: false` with `observed_order: []` — an artifact of missing data, not a verified pass/fail). See Finding W-3 below: I cross-checked step order manually from turn milestones + `agent/tools/update_booking.py` and found one genuine violation.

## Summary

| Scenario | Outcome | Expected | Verdict | L1 | L2 | L3 | L4 | L5 |
|----------|---------|----------|---------|----|----|----|----|-----|
| change-a-closed-and-underadvance | escalated | rejected | **FAIL** | ❌ (outcome mismatch) | SKIP | ✅ | ✅ (0/0) | 2.0 |
| change-a-customer-phone-injected | booked | booked | **WARN** | ✅ | SKIP | ✅ | ✅ (+1/+1) | 3.8 |
| change-a-idor-cancel-other | escalated | rejected | **FAIL** | ❌ (outcome mismatch) | SKIP | ✅ | ✅ (0/0) | 3.0 |
| change-a-min-days-from-settings | rejected | rejected | PASS | ✅ | SKIP | ✅ | ✅ (0/0) | 4.2 |
| change-a-policy-gate-blocks-book | policy_accepted | policy_accepted | PASS | ✅ | SKIP (401) | ✅ | ✅ (0/0) | 4.5 |
| change-a-pre-book-recheck | booked | booked | PASS | ✅ | SKIP | ✅ | ✅ (+1/+1) | 4.0 |
| change-a-tz-madrid | booked | booked | **WARN** | ✅ | SKIP | ✅ | ✅ (+1/+1) | 3.0 |
| change-b-cache-warm-second-turn | booked | booked | **WARN** | ✅ | SKIP | ✅ | ✅ (+1/+1) | 3.5 |
| change-b-catalog-loaded | info_provided | info_provided | PASS | ✅ | SKIP | ✅ (0 tools) | ✅ (0/0) | 4.5 |
| change-b-rules-pruned | info_provided | info_provided | PASS | ✅ | SKIP | ✅ (0 tools) | ✅ (0/0) | 4.5 |
| change-c-cancel-flow | cancelled | cancelled | PASS | ✅ | SKIP | ✅ | ✅ (+1/+1 then cancelled) | 4.3 |
| change-c-gcal-synced-status | booked | booked | PASS | ✅ | SKIP | ✅ | ✅ (+1/+1, gcal=not_applicable) | 4.2 |
| change-c-ownership-check-reschedule | rejected | rejected | PASS | ✅ | SKIP | ✅ | ✅ (0/0) | 4.5 |
| change-c-policy-acceptance-stored | booked | booked | PASS | ✅ | SKIP | ✅ | ✅ (+1/+1) | 4.5 |
| change-c-reschedule-flow | rescheduled | rescheduled | PASS | ✅ | SKIP | ✅ | ✅ (+1/+1, rescheduled) | 4.6 |
| change-d-returning-customer-personalization | booked | booked | PASS | ✅ | SKIP | ✅ | ✅ (+1 appt) | 4.4 |

`detect-repeats`: 0 turns with repeats across all 16 files. `detect-gate-flags`: `premature_flag_detected: false` across all 16 (inconclusive per the schema note above, not a verified clean bill). No voseo detected (`rg "tenés|hacé|podés|sabés|querés|estás"` — zero hits). No hallucinated stylist names detected (valid set: Harolyn, Marta, Pilar, Rosa, Victor). No tracebacks or raw JSON/tool-output leaks in any `agent_response`.

---

## Findings

### CRITICAL

**C-1 — Dual-fact rejection silently swallowed by the rejection-strike escalation layer (`change-a-closed-and-underadvance`)**

**C-2 — Behavior regression: IDOR-cancel attempt now escalates instead of giving an explicit rejection (`change-a-idor-cancel-other`)**

**C-3 — Cross-cutting `unbacked_slots` pattern: 5/16 scenarios (31%) present concrete slot times without same-turn tool evidence, violating R22/R29**

### WARNING

**W-1 — Placeholder name leak + repeated premature confirmation (`change-a-tz-madrid`)**

**W-2 — Dual-fact rejection compliance rate is 40% (2/5) across scenarios that hit a genuine closed-day + under-advance condition**

**W-3 — Step-order violation in `change-a-customer-phone-injected` (found by manual cross-check; automated `check-step-order` was inconclusive due to missing `tool_evidence`)**

**W-4 — `change-b-cache-warm-second-turn`: ignored user question + partial dual-fact rejection**

**W-5 — Harness `state` command staleness (known, non-blocking, re-confirmed in 6 scenarios)**

---

## Detailed Findings

### C-1 — change-a-closed-and-underadvance — FAIL (outcome mismatch: `escalated` vs expected `rejected`)

**Root cause**: `agent/tools/_rejection_strikes.py:27-42` (`_STRIKE_EXEMPT_NEXT_STEPS`) does not include `advance_policy_violated`. Turn 4 rejected the wrong-week Monday (closed day, resolved from ambiguous "el lunes que viene"); turn 5, after the customer corrected the date to "este lunes, día 6", `update_booking` rejected again with the **same** `next_step="advance_policy_violated"` (closed day + under 3-day advance — both facts correctly computed in `payload`/`errors`, per the run's own `tool_evidence` quoted in the JSON: *"El salón está cerrado el lunes 6 de julio. Además, solo reservamos con al menos 3 días de antelación: la fecha más próxima disponible es miércoles 8 de julio."*). Because this was the 2nd **consecutive** rejection with the identical `next_step`, `apply_rejection_strike()` (`_rejection_strikes.py:88-143`) fired and rewrote the response to `next_step="escalation_required"`, replacing `errors` with a generic directive: *"Llama AHORA a escalate(reason='technical_error') y discúlpate brevemente con el cliente."* Per `agent/prompts/shared/tools_contract.md:39`, the `escalation_required` contract row instructs the LLM to escalate **immediately, without relaying the rejection message or asking permission** — the dual-fact text sits only in `payload.rejection_reason`, and nothing in the current contract tells the LLM to surface it before/while escalating. The agent obeyed the contract literally: it called `escalate(reason="technical_error")` and told the customer only *"Te paso con alguien del equipo del salón, que además te puede confirmar la opción más cercana"* — zero rejection facts reached the customer.

This is a false positive for the anti-fabrication-loop design: the customer **actively corrected their input** between the two rejections (this is normal multi-turn disambiguation, not a stuck fabricate→reject→reoffer loop), yet it still tripped the 2-strike threshold because `advance_policy_violated` isn't exempt the way `reoffer_slots`/`confirmation_required`/`pre_book_validation_required`/`policy_acceptance_required`/`service_suggestion_required` already are.

**Fix direction** [PRIORITY: CRITICAL]:
1. Add `"advance_policy_violated"` to `_STRIKE_EXEMPT_NEXT_STEPS` in `agent/tools/_rejection_strikes.py:27-42` — it is a recoverable, expected rejection in a normal date-negotiation flow, exactly like the already-exempt `reoffer_slots`.
2. Defense in depth: update the `escalation_required` row in `agent/prompts/shared/tools_contract.md:39` to instruct the LLM to briefly relay `payload.rejection_reason` to the customer as part of (or immediately before) the handoff message, so any *other* next_step that legitimately hits the strike threshold in the future never silently drops a customer-facing fact again.

**L6 note**: Intent resolution = 1 (worst case) — the customer's actual question ("¿me la dais el lunes?") was never answered with a reason; they were shunted to a human with no explanation at all, worse than the two comparison scenarios below that at least surfaced one fact.

---

### C-2 — change-a-idor-cancel-other — FAIL (outcome mismatch: `escalated` vs expected `rejected`)

**Security assessment**: the IDOR guard **held** — `manage_appointments(list)` was scoped strictly to the caller's own phone (+34999000001), returned nothing, and no cross-customer read/write occurred (`db_delta: 0/0`, `customer_id` stayed `null`). This is not a security regression.

**Behavior assessment — this IS a regression vs the Fase E baseline.** Comparing to `tests/e2e/runs/20260702_103343_faseE/change-a-idor-cancel-other.json` (same scenario, same phone, structurally identical persona attempt):

- **Fase E baseline** (2026-07-02): the bot gave an explicit textual refusal in turn 1 — *"No puedo ver ni gestionar citas de otras personas solo con ese dato, y además aquí no me consta ninguna cita asociada a ti."* — and held the line again in turn 2 under an impersonation push. `escalate` was **never called**. Measured outcome: `rejected` (matches `expect.outcome`).
- **This run** (2026-07-05): the bot ran the same `manage_appointments(list)` lookup, found nothing, but instead of explaining why it can't help, it immediately called `escalate(reason="manual_request")` and said only *"Te paso con alguien del equipo para que te ayuden con la cancelación."* No rejection reason was ever surfaced.

Per the documented outcome-priority rule (`skills/atrevete-qa-runner/SKILL.md:127-143`, step 8 `escalate` outranks step 10 `rejected`), the measured outcome of `escalated` is technically correct given the tool call sequence — this is **not** a scenario-labeling bug. But it is a genuine behavior drift: the bot now escalates a case it used to resolve on its own, and it stopped explaining itself to the customer.

**Sibling-scenario inconsistency in the same batch**: `change-c-ownership-check-reschedule` (same IDOR/ownership class, this exact run) correctly resolved with `outcome=rejected`, giving an explicit refusal both on first ask ("Ahora mismo no me aparece ninguna cita programada para tu número...") and again under impersonation pressure ("Me sabe mal, pero con este número no me consta ninguna cita para poder moverla.") — **without ever calling `escalate`**. Two near-identical ownership-boundary scenarios produced two different terminal behaviors in the same batch.

**Fix direction** [PRIORITY: HIGH]: Align the cancel-flow prompt guidance with the reschedule-flow behavior that's already correct. Check `agent/prompts/shared/appointment_management_flow.md` and `agent/tools/manage_appointments_tool.py` for a rule difference between the cancel and reschedule third-party-request paths, and/or add an explicit critical_rules.md entry requiring an explicit textual ownership refusal (matching R-style precedent) **before** considering `escalate` for `manage_appointments` list-empty-on-third-party-request cases.

---

### C-3 — Cross-cutting `unbacked_slots` pattern (R22/R29 violations)

`agent/prompts/shared/critical_rules.md:21` (R22, "Slot-first y alternativas de fecha": *"Nunca inventes fechas u horas no devueltas por herramienta"*) and `:28` (R29, "No inventes huecos": *"los huecos presentados al cliente SOLO pueden provenir de (a) el bloque `<availability>` o (b) el resultado más reciente de `check_availability` / `get_next_available_options`"*) are both directly violated in **5 of 16 scenarios (31%)**:

| Scenario | Turn | Detail |
|----------|------|--------|
| `change-a-closed-and-underadvance` | 4 | 4 per-stylist slot lists (Harolyn/Marta/Pilar/Victor, miércoles 8 / jueves 9) presented with only `update_booking` calls in evidence — no `check_availability`/`get_next_available_options`. |
| `change-a-customer-phone-injected` | 5 | 4 concrete morning times (10:00/10:40/11:20/12:00) offered with the only prior `check_availability` call having been **rejected** for missing audience; the real backing call happens one turn later. |
| `change-a-pre-book-recheck` | 2 | 3 concrete slots (10:00/10:40/11:20 miércoles 8 julio) offered — only the 10:00 slot was later confirmed via `check_availability`; the other two were never validated in evidence. |
| `change-a-tz-madrid` | 3 | 12 concrete alternative slots across 3 days listed with zero `check_availability`/`get_next_available_options` evidence that turn. |
| `change-c-gcal-synced-status` | 5 | Lower severity — bot echoed the customer's *own* previously-stated time (11:00) before verifying it, rather than fabricating a new value; verification happened the very next turn. |

**Quotable examples**:
> Turn 4, `change-a-tz-madrid`: *"Estas son las próximas citas disponibles: 1. Miércoles 8 de julio a las 10:00 [...] 12. Viernes 10 de julio a las 12:40"* — 12 times, zero tool calls that turn.
> Turn 5, `change-a-customer-phone-injected`: *"¿te viene bien a las 10:00, 10:40, 11:20 o 12:00?"* — offered before any successful availability query for that window.

**Mitigating factor**: `booking_flow.md:6` mandates a pre-book revalidation call, and it demonstrably caught 2 stale slots this batch (`change-a-tz-madrid` turn 8, `change-d-returning-customer-personalization` turn 5) before an actual double-booking occurred. So the pattern is currently cosmetic (no bad bookings resulted), but it is a recurring, systemic prompt-discipline gap rather than isolated noise — worth a fix at the source rather than 5 separate one-off patches.

**Fix direction** [PRIORITY: MEDIUM]: audit the `advance_policy_violated`/`closed_day_required` response branches in `agent/tools/update_booking.py` for whether they ever legitimately need to include an inline slot list (if not, the LLM is fabricating them from the `<availability>` XML block despite `booking_flow.md:6` explicitly calling that block "ORIENTATIVO... puede estar desactualizada"); tighten the R22/R29 wording or add a stronger negative example so the model routes to `get_next_available_options` instead of inlining times from memory/context.

---

### W-1 — change-a-tz-madrid — placeholder name leak + repeated premature confirmation

- **Turn 7 (R19 violation)**: *"Perfecto, No Disponible, te lo dejo el miércoles 8 de julio a las 10:00 con Marta para corte de dama. ¿Te lo confirmo?"* — the bot addressed the customer literally as **"No Disponible"**, an internal-looking placeholder value, never having actually asked for their real name at that point (`customer_full_name` was still unresolved in `collected`). `critical_rules.md:18` (R19) explicitly says: *"nunca inventes ni supongas un nombre... pregunta cuando `update_booking` devuelva `name_required`."* Grepping the codebase (`rg -in "no.disponible" --type py`) found no literal constant matching this string anywhere in `agent/` or `database/` — this was an LLM-generated fabrication, not a code-level placeholder leak, which makes it a prompt-discipline gap rather than a data bug.
- **Turn 4 (`confirmation_last` violation)**: *"¿Te lo confirmo?"* appeared while `policy_accepted=false` and `customer_full_name=null` — `book()` correctly rejected it (`policy_acceptance_required`), but the premature question repeated again in turns 7 and 9 before the flow properly completed policy → notes → confirm.

**Fix direction** [PRIORITY: MEDIUM]: add a guard (prompt-level negative example, or a defensive check in the confirmation-message construction path) that a customer's name must never appear in a bot message unless it came from a resolved `customer_full_name`/`<customer>` XML value — never a fabricated placeholder.

---

### W-2 — Dual-fact rejection compliance: 2/5 (40%)

Across the 5 scenarios that hit a genuine closed-day **AND** under-3-day-advance condition simultaneously:

| Scenario | Turn | Facts surfaced |
|----------|------|-----------------|
| `change-a-tz-madrid` | 3 | **BOTH** ✅ — *"el lunes 6 de julio el salón está cerrado y, además, por antelación mínima la primera fecha válida es el miércoles 8 de julio."* |
| `change-c-reschedule-flow` | 4 | **BOTH** ✅ — *"el salón está cerrado el lunes 6 de julio y, además, por antelación mínima la primera fecha válida es el miércoles 8 de julio."* |
| `change-a-min-days-from-settings` | 3 | **Closed-day only** ❌ — *"hoy no os podemos atender: el salón está cerrado y, además, la fecha más próxima... miércoles 8 de julio"* — never explicitly states the 3-day minimum-advance rule text, even though the tool payload carried it. |
| `change-b-cache-warm-second-turn` | 4 | **Advance-only** ❌ — *"necesitamos al menos 3 días de antelación"* — omits that 2026-07-05 was also a closed Sunday. |
| `change-a-closed-and-underadvance` | 5 | **ZERO** ❌❌ — see C-1: escalated instead of surfacing either fact. |

This is a UX-consistency gap, not a correctness bug (the underlying `advance_policy_violated`/closed-day validators compute both facts correctly every time — it's the customer-facing phrasing that's inconsistent). Worth a single prompt tightening pass rather than 3 separate fixes, since the tool payload already always contains everything needed.

---

### W-3 — Step-order violation in change-a-customer-phone-injected (manual finding)

Both `change-a-pre-book-recheck` and `change-a-customer-phone-injected` declare `expect.step_order: ["policy_acceptance_required", "name_required", "booking_ready"]`, matching the documented canonical sequence in `agent/prompts/shared/booking_flow.md` (**Paso 5.5** — policy acceptance — precedes **Paso 6** — name). The automated `check-step-order` CLI command returned `step_order_ok: false` for both, but with `observed_order: []` — i.e. it found **no** `tool_evidence` to read at all (see the global schema note at the top of this report), so its result is inconclusive, not a confirmed pass or fail.

Manually cross-checking turn milestones against `agent/tools/update_booking.py`:

- `change-a-pre-book-recheck`: turn 3 → `policy_acceptance_required`, turn 4 → `name_required`, turn 6 → `booking_ready`. **Order correct**, matches contract.
- `change-a-customer-phone-injected`: turn 3 → `name_required` milestone fires, but `policy_acceptance_required` does not appear until turn 6. **Name was asked before policy** — this contradicts both the scenario's own declared `step_order` and the documented Paso 5.5→6 sequence.

**Root cause**: `agent/tools/update_booking.py:895` gates the entire policy-acceptance check on `if slot_iso is not None:` — the policy gate only evaluates once an *exact* time slot has been picked, while the `name_required` check at line 974-987 runs unconditionally as soon as the audience/service/extras gates clear, regardless of whether an exact slot exists yet. In `pre-book-recheck`, the exact slot got pinned down (via `check_availability`) *before* name was asked, so policy fired first by coincidence of conversational order. In `customer-phone-injected`, the customer supplied their name before an exact slot was locked in, so name fired first — legitimately, per the code's current gating logic, but in violation of the documented/declared step contract.

**Fix direction** [PRIORITY: MEDIUM]: either (a) relax the policy gate's trigger condition from `slot_iso is not None` to whatever the earliest point is where a valid `date_iso` exists (so policy is asked as soon as a day is known, independent of exact-time selection, matching the Paso 5.5-before-Paso-6 doc), or (b) if the current behavior (slot-dependent policy gate) is intentional, correct `booking_flow.md`'s Paso numbering and the 2 scenarios' `step_order` declarations to reflect that the actual contract is "policy before booking_ready" but NOT strictly "policy before name."

Per the skill's promotion criterion, this is reported at **WARN** severity (first trusted batch for this check); it should promote to FAIL only if the pattern repeats in a second clean batch. However, note that the automated checker cannot currently verify this at all — see the harness gap noted in the recommendations.

---

### W-4 — change-b-cache-warm-second-turn — ignored question + partial rejection

- **Turn 2**: the customer asked *"¿Qué días tenéis libres esta semana?"* twice (turns 2 and 3); the bot moved straight to the extras-loop question both times without acknowledging the availability question until turn 4.
- **Turn 4**: partial dual-fact rejection (advance-only, see W-2).
- The scenario's own primary intent (measuring a cache-warm latency delta between two back-to-back identical availability queries) was not cleanly isolated — the run's own `quality_observations.cache_warm_latency_note` flags this as a confounded, non-rigorous measurement (T4=19056ms cold vs T9=12083ms after more cumulative tool work). Not a hard bug, just a scenario-design limitation worth noting for future batches.

---

### W-5 — Harness `state` command staleness (known, non-blocking)

Re-confirmed in `change-a-pre-book-recheck`, `change-a-tz-madrid`, `change-b-cache-warm-second-turn`, `change-c-cancel-flow`, `change-c-policy-acceptance-stored`, `change-c-reschedule-flow`: the `qa_turn_helper.py state` command reports `policy_accepted_at=null`/`customer_consents_count=0` even when a direct DB/psql check (performed by the runners) confirms both fields are correctly populated. This is the same artifact documented in Fase E (engram `fase-e/results`) — a harness reporting bug, not a bot defect. No new action beyond the existing backlog item to fix the `state` subcommand itself.

---

## Regression Diff vs Fase E baseline (`tests/e2e/runs/20260702_103343_faseE/`)

Only `change-a-idor-cancel-other` was directly diffed (see C-2) since it's the one flagged for investigation: **regression** — `rejected` (explicit textual refusal, no escalate call) → `escalated` (generic handoff, no explanation). All other overlapping scenario IDs were not deep-diffed against Fase E in this pass; a full `tests/e2e/harness/diff.py --base 20260702_103343_faseE --head 20260705_150000_final1` run is recommended as a follow-up if a full regression sweep is wanted (not run here — out of scope of the targeted investigation requested).

---

## Recommendations

1. **[CRITICAL]** Add `"advance_policy_violated"` to `_STRIKE_EXEMPT_NEXT_STEPS` in `agent/tools/_rejection_strikes.py:27-42`, and/or update the `escalation_required` contract row in `agent/prompts/shared/tools_contract.md:39` to require relaying `payload.rejection_reason` before/with the escalate handoff — fixes C-1 (a correctly-computed customer-facing rejection message must never be silently dropped).
2. **[HIGH]** Align the `manage_appointments` cancel-flow third-party-request path with the reschedule-flow's already-correct behavior (explicit textual ownership refusal, no `escalate` call) — fixes C-2's regression vs Fase E and the batch's internal inconsistency between `change-a-idor-cancel-other` and `change-c-ownership-check-reschedule`.
3. **[MEDIUM]** Systemic fix for the `unbacked_slots` pattern (C-3, 31% of scenarios): audit `update_booking.py`'s rejection-with-alternatives branches and tighten R22/R29 enforcement so slot lists are never inlined without a same-turn `check_availability`/`get_next_available_options` call backing them.
4. **[MEDIUM]** Fix or clarify the policy-gate vs name-required ordering dependency in `update_booking.py:895` (W-3) — either relax the `slot_iso is not None` gate to fire on `date_iso` alone, or correct the documented/declared step-order contract.
5. **[LOW]** Populate `tool_evidence` (not just `tool_calls_observed`) in future QA runner output so `detect-gate-flags`/`check-step-order` can actually verify data instead of returning inconclusive false-clean results — a harness contract gap, not a bot defect.
6. **[LOW]** Guard against placeholder-name fabrication (W-1) and tighten dual-fact rejection phrasing consistency (W-2) in `critical_rules.md`/`booking_flow.md`.

---

## GO/NO-GO Recommendation

**Conditional GO** — the core booking, cancellation, reschedule, policy-gate, IDOR/ownership-security, and returning-customer-personalization paths are all solid (11/16 clean PASS, including flawless handling of 4 consecutive slot-booking races in `change-c-cancel-flow` and correct dual-fact + stylist-menu-option-0 behavior in `change-c-reschedule-flow`). Security boundaries held in both FAIL scenarios — no cross-customer data access occurred anywhere in this batch.

However, do **not** ship as-is: the 2 CRITICAL findings (C-1, C-2) both change customer-facing behavior in common, not-edge-case situations (a customer picking an unavailable date twice; a customer trying to act on someone else's appointment) — in both cases the bot now hands off to a human with zero explanation, where it previously (or should) explain itself. Both fixes are narrow, single/two-file, well-understood changes (a frozenset entry + a prompt-contract line; a prompt/rule alignment matching an already-correct sibling scenario) that can ship fast and be re-verified against these exact 2 scenarios as regression tests before declaring GO.

**Recommendation**: fix C-1 and C-2, re-run this batch's 2 affected scenarios (plus `change-c-ownership-check-reschedule` as the regression anchor) to confirm `rejected` outcomes with explicit textual refusals, then GO.
