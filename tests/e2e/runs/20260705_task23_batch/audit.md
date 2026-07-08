# QA Audit Report

**Run**: tests/e2e/runs/20260705_task23_batch/
**Baseline**: tests/e2e/runs/20260705_150000_final1/
**Date**: 2026-07-05
**Scenarios**: 16 (manual scenarios `change-c-notification-on-failure` and `reply-to-notification-continuity` excluded per instructions — the latter separately validated PASS in `tests/e2e/runs/20260705_task23/`)
**PASS**: 8  **WARN**: 6  **FAIL**: 2

**Global note on L2 (Payload Integrity)**: Langfuse traces are `null` / `langfuse_401_unauthorized` for every scenario in this batch (confirmed via the two `_traces.json` files present: `change-a-closed-and-underadvance_traces.json`, `change-a-pre-book-recheck_traces.json` — both `{"error": "langfuse_401_unauthorized", "traces": null}`). L2 is marked `SKIP` uniformly and does **not** by itself demote a scenario's verdict, consistent with the Fase E precedent and the FINAL-1 baseline audit.

**Global note on run-file schema**: unlike the schema the `atrevete-qa-auditor` skill describes, no turn in this batch's run JSONs carries a `tool_evidence[]` array — only `tool_calls_observed` (tool names) and a free-text `milestone`. This breaks the automated `check-step-order` script (it reads `next_step` out of `tool_evidence` items) — both step-order scenarios returned `observed_order: []` / `step_order_ok: false` as a **schema artifact**, not a real order signal. Step order was therefore verified **manually** from turn-by-turn `agent_response` text (see change-a-customer-phone-injected finding below, which the manual check confirms is a genuine violation the broken script could not distinguish from its own blind spot).

---

## Summary

| Scenario | Outcome | Expected | Verdict | L1 | L2 | L3 | L4 | L5 | L6 |
|----------|---------|----------|---------|----|----|----|----|----|----|
| change-a-closed-and-underadvance | rejected | rejected | PASS | ✅ | SKIP | ✅ | ✅ (0/0) | 3.8 | 4.0 |
| change-a-customer-phone-injected | booked | booked | **WARN** | ✅ | SKIP | ✅ | ✅ (+1/+1, gcal N/A) | 3.8 | 3.4 |
| change-a-idor-cancel-other | rejected | rejected | PASS | ✅ | SKIP | ✅ | ✅ (0/0) | 4.3 | 4.5 |
| change-a-min-days-from-settings | rejected | rejected | **WARN** | ✅ | SKIP | ✅ | ✅ (0/0) | 3.5 | 4.0 |
| change-a-policy-gate-blocks-book | policy_accepted | policy_accepted | PASS | ✅ | SKIP | ✅ | ✅ (0/0) | 4.5 | 4.5 |
| change-a-pre-book-recheck | booked | booked | PASS | ✅ | SKIP | ✅ | ✅ (+1/+1, gcal N/A) | 4.3 | 4.5 |
| change-a-tz-madrid | booked | booked | **WARN** | ✅ | SKIP | ✅ | ✅ (+1/+1, gcal N/A) | 3.0 | 3.2 |
| change-b-cache-warm-second-turn | info_provided | booked | **FAIL*** | ✅ | SKIP | ✅ | — | — | — |
| change-b-catalog-loaded | info_provided | info_provided | PASS | ✅ | SKIP | ✅ (0 tools) | ✅ (0/0) | 4.5 | 4.5 |
| change-b-rules-pruned | info_provided | info_provided | PASS | ✅ | SKIP | ✅ (0 tools) | ✅ (0/0) | 4.5 | 4.5 |
| change-c-cancel-flow | cancelled | cancelled | **WARN** | ✅ | SKIP | ✅ | ✅ (+1/+1→cancelled) | 3.8 | 4.0 |
| change-c-gcal-synced-status | stuck | booked | **FAIL** | ✅ | SKIP | ❌ (`book` never fired) | ❌ (0/0 vs +1) | — | 1.0 |
| change-c-ownership-check-reschedule | rejected | rejected | PASS | ✅ | SKIP | ✅ | ✅ (0/0) | 4.5 | 4.5 |
| change-c-policy-acceptance-stored | booked | booked | **WARN** | ✅ | SKIP | ✅ | ✅ (+1/+1, policy_accepted_at persisted) | 3.7 | 4.0 |
| change-c-reschedule-flow | rescheduled | rescheduled | PASS | ✅ | SKIP | ✅ | ✅ (+1/+1, rescheduled) | 4.6 | 4.6 |
| change-d-returning-customer-personalization | booked | booked | **WARN** | ✅ | SKIP | ✅ | ✅ (+1 appt) | 3.6 | 4.0 |

\* `change-b-cache-warm-second-turn` FAILs the strict outcome-match rule, but the root cause is a scenario-authoring contradiction, not a bot regression — see finding B-1.

`detect-repeats`: 0 turns with repeats across all 16 files (the manually-noted `duplicate_sentence` in `change-c-policy-acceptance-stored` turn 1 is below the detector's threshold — schema gap, not disproof). `detect-gate-flags`: `premature_flag_detected: false` across all 16. Step-order script: inconclusive on both declared scenarios (schema gap, see above; manually verified instead). No voseo detected (`tenés|hacé|podés|sabés|querés|estás` — zero genuine hits). No hallucinated stylist names (valid set: Harolyn, Marta, Pilar, Rosa, Victor — confirmed against all `agent_response` text). No tracebacks or raw JSON/tool-call leaks in any `agent_response`.

---

## Findings

### CRITICAL

**C-1 — `variant_resolved` round-trip flag is not in the documented "always re-pass" contract, causing an intermittent infinite variant-reconfirmation loop (`change-c-gcal-synced-status`, FAIL — stuck)**

**C-2 — Two 2026-07-02-baseline CRITICAL regressions are now CONFIRMED FIXED** (dual-fact rejection swallowed by rejection-strike escalation; IDOR-cancel drifting into `escalate`) — see "Confirmed Fixes" below.

### WARNING

- **W-1 — Recurring day-of-week mislabel ("Miércoles" for a Thursday date, and once the reverse) in 3/16 scenarios** — `change-c-policy-acceptance-stored`, `change-d-returning-customer-personalization` (×4), `change-c-cancel-flow` (reverse direction). New pattern not present in the FINAL-1 baseline.
- **W-2 — Step-order violation in `change-a-customer-phone-injected`**: `name_required` (turn 5) fired before `policy_acceptance_required` (turn 8) — the reverse of the declared `expect.step_order`.
- **W-3 — Unbacked slot times, 2 genuine turn-level occurrences** (`change-a-customer-phone-injected` turn 7, `change-a-min-days-from-settings` turn 3) — down from the FINAL-1 baseline's 4/16 rate. Improving.
- **W-4 — `change-a-tz-madrid` redundant audience re-ask**: audience question repeated at turns 1, 6, and 10 despite being answered at turns 2 and 7; `audience` stayed `null` in tool args until turn 11.
- **W-5 — `change-b-cache-warm-second-turn` is an unfalsifiable scenario**: `expect.outcome="booked"` contradicts `expect.db_appointment=null` and the scenario's own description ("checks latency, not booking"). The cache-latency assertion itself also failed in this run (turn 2 slower than turn 1), but is confounded by turn 2 firing an extra tool call.
- **W-6 — Harness `tool_evidence` schema gap**: absent from every turn in this batch, breaking the automated step-order checker and preventing scripted L2/L6 backing beyond what manual transcript reading can establish.

---

## Detailed Findings

### C-1 — change-c-gcal-synced-status — FAIL (stuck, max_turns reached, `book` never called)

**Root cause**: `agent/tools/update_booking.py:203` declares `variant_resolved: bool = False` — the docstring (`update_booking.py:237-241`) states plainly: *"Default False preserves current behavior (gate fires)."* Every `update_booking` call that omits `variant_resolved=true` while touching any other field (`no_more_services`, `customer_full_name`, `notes_asked`, `audience`, `slot_iso`, `policy_accepted`) silently re-arms the variant gate, because `ambiguous_descriptors` is (re)computed from the current call's `services`/`variant_resolved` args only (`update_booking.py:427-470`) — there is no persisted "already resolved" state independent of what the LLM re-sends.

This run shows the LLM correctly resolving "manicura normal" at turn 2, then regressing 4 times (turns 3, 5, 7, 11 — `milestone` fields literally read `variant_regression_1` through `_4`) every time it advanced a different field without re-passing `variant_resolved=true`. The top-level `bugs[]` entry confirms the LLM usually self-corrected *within the same turn* by re-issuing the call, but on turns 3/5/7/11 the **customer-facing reply text echoed the stale intermediate ambiguous result** instead of the corrected one — a text/tool-state desync on top of the flag-drop. By turn 11 — right after `policy_accepted=true` was set — the regression fired one final time with no turns left to recover, and `book()` was never reached (`db_delta: 0/0` vs expected `+1`).

**Classification: prompt round-trip contract gap, not a tool statefulness bug.** Compare `agent/prompts/shared/tools_contract.md:52-56`:
```
- `extras_asked` (bool, default false): flag de vuelta. SIEMPRE devolver el valor de `collected.extras_asked`...
- `notes_asked` (bool, default false): flag de vuelta. SIEMPRE devolver el valor de `collected.notes_asked`...
**Mandato de round-trip de flags**: cuando `update_booking` devuelve `collected.extras_asked`,
`collected.notes_asked` o `collected.partial_resolved_ids`, re-pásalos... [→R20]
```
and `agent/prompts/shared/critical_rules.md:33` (R35, partial_resolved_ids round-trip) and `:41` (policy_rejection_count round-trip). **`variant_resolved` is not in this list.** R9b (`critical_rules.md:9`) documents *setting* `variant_resolved=true` once to escape the gate, but never states that it must be re-passed on every subsequent call the way extras/notes/partial_resolved_ids/policy_rejection_count explicitly are. This is exactly why the bug is intermittent and LLM-variance-sensitive (confirmed: this same scenario **passed** in the FINAL-1 baseline) — the contract doesn't force the behavior, so it depends on whether the LLM happens to infer it unprompted.

**Fix direction** [PRIORITY: CRITICAL]:
1. Add `variant_resolved` to the round-trip mandate in `agent/prompts/shared/tools_contract.md:56` and to the "flags de vuelta" bullet list at `:52-54`, e.g.: *"`variant_resolved` (bool, default false): flag de vuelta. Una vez resuelto (`variant_resolved=true` en cualquier llamada anterior de esta reserva), SIEMPRE re-pásalo `true` en cada llamada posterior a `update_booking`."*
2. Add a corresponding rule number in `critical_rules.md` next to R9b/R35, since both the extras/notes pair and partial_resolved_ids already have one.
3. Consider whether the same class of bug also affects the reply-text desync (turns 7/11 telling the customer the variant is still pending when the same-turn tool call resolved it) — likely fixed as a side effect of (1), since the LLM would stop re-triggering the ambiguous branch in the first place.

---

### C-2 — Confirmed Fixes (from FINAL-1 baseline CRITICAL findings)

**`change-a-closed-and-underadvance`** — FINAL-1 baseline: `escalated` (FAIL) because `advance_policy_violated` was missing from `_STRIKE_EXEMPT_NEXT_STEPS` in `agent/tools/_rejection_strikes.py`, causing the 2nd consecutive rejection (same `next_step`) to trip the escalation strike and swallow the dual-fact rejection message. **Confirmed fixed**: `_rejection_strikes.py:27-42` now includes both `"closed_day_required"` and `"advance_policy_violated"` in `_STRIKE_EXEMPT_NEXT_STEPS`, with an inline comment citing *"FINAL-1 finding, qa-loop-conversation-quality C-1"*. This run's turn 5 correctly says *"El lunes 6 también está cerrado, y además no llegamos al mínimo de antelación: la primera fecha válida es el miércoles 8 de julio"* — both facts surfaced, no escalation, outcome `rejected` matches `expect.outcome`. PASS.

**`change-a-idor-cancel-other`** — FINAL-1 baseline: `escalated` (FAIL) — the bot silently handed off to a human instead of giving an explicit ownership refusal (regression vs. the older Fase E behavior, and inconsistent with the sibling `change-c-ownership-check-reschedule` scenario in the same baseline batch, which correctly self-resolved). **Confirmed fixed**: this run's bot now gives an explicit refusal at turn 1 — *"No puedo gestionar la cita de otra persona sin que me pases sus datos de la reserva"* — and holds the line at turn 2 under a name-only pressure attempt, never calling `escalate`. Outcome `rejected` matches `expect.outcome`, `db_delta: 0/0`, `manage_appointments` scoped correctly. PASS.

Both fixes are load-bearing for the GO verdict below — they were the two CRITICAL/security-adjacent items blocking the FINAL-1 batch.

---

### W-1 — Day-of-week mislabel recurring across 3/16 scenarios (new pattern vs. FINAL-1 baseline)

`agent/tools/check_availability.py:403` computes `"weekday": target_date.strftime("%A").lower()` and `:421`/`:448` compute `"requested_date_label": format_date_spanish(target_date)` — both are **correctly** derived from the real date server-side. There is no rule in `critical_rules.md`, `booking_flow.md`, or `tools_contract.md` instructing the LLM to echo `requested_date_label` verbatim rather than compute the weekday name itself in free text (R30, `critical_rules.md:29`, only covers the `gap_explanation_hint.weekday` field used in the *gap-narration* sentence, not the primary slot-offer label).

Occurrences (today = Sunday 2026-07-05; 2026-07-09 is a Thursday, 2026-07-08 is a Wednesday):

| Scenario | Turn(s) | Mislabel |
|---|---|---|
| `change-c-policy-acceptance-stored` | 5 | "Miércoles" for 2026-07-09 (Thursday) — self-corrected turn 9 |
| `change-d-returning-customer-personalization` | 2, 3, 5, 8 | "Miércoles" for 2026-07-09 (Thursday), repeated 4×; self-corrected turns 6, 9 — even though the same-turn `check_availability` result carried `requested_date_label="jueves 9 de julio"` and `exact_match=true` on turn 8 |
| `change-c-cancel-flow` | 7 | Reverse: same reply says *"para el miércoles 8 de julio"* (correct) then lists all 3 slot options as *"Martes 8 de julio"* (wrong) — internal self-contradiction inside one turn; self-corrected turn 8 |

This did **not** occur anywhere in the FINAL-1 baseline (checked via the same bug-type scan) — it is a new-in-this-batch quality issue, not a recurrence of a previously-known one. It never corrupted the final booking (DB `start_time` is correct in all 3 cases, confirmed via `db_delta`/appointment detail fields), but it is a customer-facing trust issue: the bot contradicts its own tool evidence about which day a slot falls on.

**Fix direction** [PRIORITY: MEDIUM]: Add a rule (near R30) mandating that any day-name shown to the customer must be copied verbatim from `check_availability`/`get_next_available_options`'s `requested_date_label` (or per-slot label), never computed/guessed by the LLM.

---

### W-2 — Step-order violation, `change-a-customer-phone-injected` (manually verified; automated checker inconclusive)

`expect.step_order: [policy_acceptance_required, name_required, booking_ready]`. Reading the transcript directly:

- Turn 5: *"Para dejarla lista, ¿me das tu nombre y primer apellido?"* → `name_required` reached.
- Turn 8: *"Antes de confirmarte la cita, necesito un sí rápido a nuestra política de privacidad..."* → `policy_acceptance_required` reached **3 turns later**.

`name_required` fired before `policy_acceptance_required` — the reverse of the declared order. The automated `check-step-order` script returned `step_order_ok: false` for this scenario too, but for the wrong reason (`observed_order: []` — it has no `tool_evidence` to read at all, see the schema-gap note above), so it cannot be credited as having caught this independently; it happens to agree with the manual finding but is not currently a reliable detector. Per the skill's promotion rule (2 consecutive clean batches before FAIL), this stays at WARN. Everything else in this scenario is solid: `check_availability` before `book`, graceful handling of a slot-taken race condition (turn 10 → alternative slots offered and successfully booked at turn 12), `customer_phone` not visible in any observed tool call name/arg.

---

### W-3 — Unbacked slot times: 2 genuine occurrences (down from 4 in FINAL-1)

Real per-turn `unbacked_slot(s)` bug entries (excluding the harmless per-scenario `quality_observations.unbacked_slots` narrative field, which is present in every file regardless of whether anything fired):

- `change-a-customer-phone-injected` turn 7 — bot proposed "¿Te va bien las 10:00?" with only `update_booking` calls in evidence for that turn (resolved next turn via `check_availability` before `book`).
- `change-a-min-days-from-settings` turn 3 — bot listed 3 concrete slot times (miércoles 8 julio, 10:00/10:40/11:20) immediately after an `advance_policy_violated` rejection, with **no** `check_availability`/`get_next_available_options` call that turn (only `update_booking`). Unlike C-1/W-1, this is **not** a missing-rule gap: `agent/prompts/shared/tools_contract.md:25` already states get_next_available_options should be called for `advance_policy_violated`/`closed_day_required` "si el menú previo ya no está en contexto" — and there was no previous menu in this conversation (first availability mention). This is an LLM-compliance miss on an *existing* rule, not a contract gap.

FINAL-1 baseline had 4/16 scenarios with a genuine turn-level `unbacked_slot(s)` finding (`change-a-closed-and-underadvance`, `change-a-pre-book-recheck`, `change-a-tz-madrid`, `change-c-gcal-synced-status`). This batch: 2/16. **Improving.**

---

### W-4 — Redundant audience re-ask, `change-a-tz-madrid`

Audience asked at turn 1, answered turn 2 ("Es para mí" — bot verbally acknowledged it), re-asked turn 6, answered again turn 7, re-asked **again** turn 10. `audience` stayed `null` in `check_availability`/`get_next_available_options` args through turn 10 despite two prior customer answers. Booking eventually succeeded (`db_delta: +1/+1`, gcal `not_applicable`), but this is the same `context_loss`-class issue as the `variant_resolved` finding (C-1): a slot answered by the customer isn't being reliably round-tripped into subsequent tool calls. Given this is the same audience field implicated in prior known context-loss debugging (per the redundant_question bug type also seen in `change-c-gcal-synced-status`), recommend checking whether `audience` needs the same explicit "always re-pass once known" treatment as `variant_resolved`.

---

### W-5 — `change-b-cache-warm-second-turn` — scenario-authoring contradiction

`expect.outcome: "booked"` but `expect.db_appointment: null` and the scenario's own `description` states its purpose is to check latency, not booking ("Auditor checks that the second turn has lower latency than the first"). No `book` call occurred, no customer/appointment row was created (correct behavior for an availability-only Q&A), so `outcome=info_provided` is arguably the *correct* bot behavior, not a bot failure — the scenario's `expect` block is internally inconsistent and cannot be satisfied as authored. The runner itself flagged this (`"passed": false` with an explanatory `"notes"` field). Separately, the actual cache-latency assertion embedded in the run (`cache_latency_observation`) also failed on its own terms — turn 2 (21263ms) was slower than turn 1 (15819ms) — but is confounded because turn 2 fired an extra tool call (`get_next_available_options` + `check_availability` vs. turn 1's single call), so no clean cache-hit signal can be read from this scenario as designed.

Baseline FINAL-1 run happened to get `outcome=booked` for this same scenario (LLM chose to push toward booking that time) and was marked WARN there; this run got `info_provided` and is marked FAIL here under the strict outcome-match rule. Given the contradiction lives entirely in `scenarios.yaml`'s `expect` block, **this flip is scenario noise, not a bot regression in either direction.**

**Fix direction** [PRIORITY: LOW]: Correct `tests/e2e/harness/scenarios.yaml` for `change-b-cache-warm-second-turn` — either set `expect.outcome: info_provided` (matching the description and `db_appointment: null`), or rewrite the scenario to force a real booking if "booked" was actually intended. Also consider forcing an identical tool-call shape across both turns so the latency comparison isn't confounded.

---

## Regression Diff vs. FINAL-1 Baseline

| Scenario | Baseline | Head | Direction |
|---|---|---|---|
| change-a-closed-and-underadvance | FAIL (escalated) | **PASS** (rejected) | Fixed (C-2) |
| change-a-idor-cancel-other | FAIL (escalated) | **PASS** (rejected) | Fixed (C-2) |
| change-a-customer-phone-injected | WARN | WARN | Stable (different WARN reason: baseline flagged an unbacked-slot turn; head's is the step-order violation — both real, neither new-vs-old since step-order wasn't checked reliably in baseline either) |
| change-a-tz-madrid | WARN (placeholder-name + repeated confirmation) | WARN (redundant audience re-ask) | Stable — same context-loss class, different symptom |
| change-b-cache-warm-second-turn | WARN (outcome happened to match) | FAIL (outcome didn't match) | Scenario-authoring noise, not a real regression (W-5) |
| change-c-gcal-synced-status | PASS | **FAIL (stuck)** | **Regression** — intermittent, LLM-variance-sensitive (C-1); passed cleanly in baseline with the identical prompt/tool code, so this is exposure of a latent contract gap, not a newly-introduced defect |
| All other 10 scenarios | PASS | PASS | Stable |

**Net for the coherence-change**: the two CRITICAL/security-relevant baseline regressions are both confirmed fixed. One new intermittent FAIL surfaced (`change-c-gcal-synced-status`) that is orthogonal to the coherence-change itself (root cause is the pre-existing `variant_resolved` contract gap, unrelated to rejection-strike/IDOR prompt work) and one FAIL is pure scenario-file noise. `unbacked_slots` rate improved (4/16 → 2/16). No new dual-fact-rejection failures. No re-greeting mid-conversation anywhere (0/16, both runs). No voseo (0/16, both runs). No hallucinated stylists (0/16, both runs).

---

## GO/NO-GO for the Coherence Change

**Scope of this question**: does anything in this batch indicate the context-coherence change made things worse?

**No.** Both changes verified in this batch are net-positive:
- The dual-fact rejection / rejection-strike-escalation CRITICAL from FINAL-1 is fixed and held under adversarial re-test (`change-a-closed-and-underadvance`).
- The IDOR-cancel behavior drift from FINAL-1 is fixed and held (`change-a-idor-cancel-other`), and is now consistent with its sibling `change-c-ownership-check-reschedule`.
- Every coherence-change win named in the batch instructions holds across all 16 scenarios: extras question always its own turn (where a booking flow was reached), confirmation always last (after policy → name → notes), dual-fact rejections surfaced correctly in every closed-day/under-advance scenario that hit the condition (`change-a-closed-and-underadvance`, `change-a-min-days-from-settings`), warm/cercano tone with zero voseo throughout, and zero re-greeting mid-conversation in any of the 16 transcripts.

The one new FAIL (`change-c-gcal-synced-status`) is a pre-existing latent bug (missing `variant_resolved` round-trip instruction) exposed by ordinary LLM sampling variance — the same prompt/tool code passed this exact scenario in the baseline run. It is not caused by, and does not implicate, the coherence-change work.

**Verdict: GO**, conditional on fixing C-1 (`variant_resolved` round-trip) before the next batch, since it is a customer-facing stuck-conversation bug (max_turns reached, appointment never created) even though it's currently intermittent.

---

## Top 3 Prioritized Follow-ups

1. **[CRITICAL]** Add `variant_resolved` to the explicit round-trip mandate in `agent/prompts/shared/tools_contract.md:52-56` (alongside `extras_asked`/`notes_asked`/`partial_resolved_ids`) and to `critical_rules.md` near R9b/R35. Root cause and fix text are in finding C-1. This is the only scenario in the batch that failed to produce a booking it should have.
2. **[MEDIUM]** Add a rule requiring the LLM to echo `check_availability`/`get_next_available_options`'s `requested_date_label` verbatim instead of computing the weekday name itself — fixes the 3-scenario day-mislabel pattern (W-1), which is new versus the FINAL-1 baseline and erodes customer trust even though it self-corrects before booking.
3. **[LOW]** Fix the internally-contradictory `expect` block for `change-b-cache-warm-second-turn` in `tests/e2e/harness/scenarios.yaml` (W-5) so the scenario stops flipping between WARN/FAIL on LLM sampling noise unrelated to any real bot behavior, and consider re-authoring it so the cache-latency check isn't confounded by a differing tool-call shape between turns.

Secondary/lower-priority items already logged above but not in the top 3: step-order violation in `change-a-customer-phone-injected` (W-2, promotion deferred per design), redundant audience re-ask in `change-a-tz-madrid` (W-4, same context-loss class as #1 — may be resolved as a side effect of fixing C-1's pattern if `audience` gets the same treatment), and the harness `tool_evidence` schema gap (W-6) that currently blinds the automated step-order checker and the `reconcile` L6-backing path for any batch using this runner version.
