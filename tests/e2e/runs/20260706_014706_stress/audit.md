# Stress Batch Audit — 20260706_014706_stress

8 novel stress scenarios against the live deploy (pepe@server), designed to cover ground the standard 15-scenario suite does not: multi-appointment conversations, reschedule chains, family bookings, ambiguous confirmations, self-overlap, out-of-catalog + escalation, and memory-driven personalization.

**Verdict: 5 PASS / 3 FAIL.** Core booking machinery (draft isolation, in-place reschedule, policy gate, ownership checks, memory personalization) is solid. The failures cluster in one theme: **the agent acts — or claims to have acted — without grounding** (phantom confirmation, silent disambiguation-free confirm, premature escalation).

## Summary

| Scenario | Outcome | Verdict | Headline |
|---|---|---|---|
| stress-multi-cita-secuencial | multi_completed | PASS | Clean 2nd draft, policy asked once, zone disambiguation correct |
| stress-agenda-familiar | escalated | **FAIL** | P1: escalated on turn 1 for a 2-person booking R-44 explicitly covers |
| stress-reagenda-cadena | cancelled | PASS | 1 row mutated in place; medium bug: `cancellation_reason` NULL |
| stress-cliente-caotico | booked | PASS | Strike-escalation fix VALIDATED live; final intent matched exactly |
| stress-conflicto-solapamiento | partial_completed | **FAIL** | CRITICAL: phantom confirmation — "queda todo listo" with zero tool calls |
| stress-confirmacion-ambigua | double-confirmed | **FAIL** | CRITICAL: silent confirm of wrong appointment; both ended confirmed |
| stress-fuera-catalogo-escalacion | booked | PASS | Honest decline, real escalation row, clean return to booking |
| stress-memoria-cliente-recurrente | booked | PASS | "Lo de siempre" resolved from memory, still confirmed before booking |

## Findings (ranked)

### F1 — CRITICAL: phantom booking confirmation (unbacked success claim)
`stress-conflicto-solapamiento`, turns 17–18. Customer accepted the 14:30 alternative for a pedicure; bot replied "Perfecto, te lo dejo a las 14:30 … Queda todo listo" with **no tool call in either turn**. The pedicure does not exist in DB. Server-side defenses (book() overlap rejection) held; the failure is purely the LLM asserting success without evidence. This is the FINAL-1 `unbacked_slots` pattern (31% of runs) escalated to its worst form: unbacked *booking confirmation*.
**Expected behavior**: on acceptance, call `update_booking`/`book`; confirm only after tool success.
**Fix direction**: deterministic guard, not prompt-only — a post-model check (middleware) that blocks/repairs replies matching booking-confirmation language when no `book`/`manage_appointments` success occurred in the same turn. Prompt rule alone has already proven insufficient for this pattern class.

### F2 — CRITICAL: ambiguous confirm intent binds to wrong appointment, no disambiguation gate
`stress-confirmacion-ambigua`. With two PENDING appointments, "quiero confirmar mi cita" silently confirmed the later, last-referenced one (no question asked). The clarifying question fired one turn late and then confirmed the *other* one too — final state: **both confirmed**, neither turn showed a proper 2-item disambiguation list.
**Expected behavior**: `count(pending) > 1` + bare "mi cita" intent → list both with dates/services, ask which, act on exactly one.
**Fix direction**: tool-level precondition in `manage_appointments` confirm action (return `disambiguation_required` with candidates when the target is not explicitly identified and >1 pending exists). Deterministic, testable, prompt-independent.

### F3 — HIGH: premature escalation on 2-person family booking
`stress-agenda-familiar`, turn 1. "Corte para mí y para mi hija de 8 años, mejor seguidas" → `escalate(reason="manual_request")` with zero availability checks or questions. R-44 (`critical_rules.md:72`) + `booking_flow.md:118-120` document exactly this case (worked example: "niño + marido") as a sequential single-person flow. `Corte de Niña` (child_female) is active in catalog.
**Contrast**: the wedding/6-people request in `stress-fuera-catalogo-escalacion` SHOULD escalate and did. The boundary "large group → human; ≤2 people → sequential flow" is miscalibrated toward escalation.
**Fix direction**: constrain the `escalate` docstring (`escalation_tools.py:42-63`) — it is currently vague enough to be an easy exit; add an explicit negative example (2-person family booking) mirroring the R-44 positive example.

### F4 — HIGH (compounding): escalations carry no context
`escalations.issue_summary` is empty on a real escalation row. The human receives a handoff with no written reason. Compounds F3: over-escalation + context-free escalations = silent workload dump on staff.
**Fix direction**: make `escalate` require a summary argument populated from conversation context; stamp it into the row.

### F5 — MEDIUM: self-service cancellation never stamps `cancellation_reason`
`manage_appointments_tool.py:606-612` hardcodes `reason=None` for the general cancel action → row cancelled with NULL reason, violating the documented marker taxonomy (`customer_declined` vs `operator_cancelled` vs `auto_cancelled_no_confirmation`). Breaks the analytics the AUTO_CANCEL rollout depends on. One-line fix + test.

### F6 — MEDIUM (systemic): "not listening" — redundant re-asks
Three independent instances in one batch:
1. Manicura variant re-asked verbatim after "la simple" (fuera-catalogo).
2. Audience re-asked after service pivot — draft audience resets on service change (cliente-caotico).
3. Manicura variant + audience re-asked despite being established earlier in-conversation (confirmacion-ambigua).
Pattern: disambiguation answers given colloquially or established context are dropped when the draft mutates. Friction, not blockage — but it is the top perceived-quality issue for real users.

### F7 — LOW: soft-cancel gets a pleasant non-answer
"Mejor lo dejamos por ahora… ya escribiré" → bot neither cancelled nor surfaced the still-active appointment. Expected: state the active appointment and ask the binary question ("¿te la cancelo o te la guardo?").

### F8 — LOW: date-NLU edge cases
- "el sábado que viene" → +12 days instead of nearest Saturday (+5).
- "jueves 10" (contradictory: Thursday was the 9th) → resolved to Friday the 10th without flagging the mismatch. Expected: notice contradiction, clarify.

### Non-issues verified during audit
- **Prices NULL for all 77 services**: intentional — R-40 (`critical_rules.md:64`) forbids numeric prices until the catalog exposes them; bot complied verbatim in live runs.
- `qa_turn_helper state` consent-vs-DB mismatch: known Fase E artifact (engram #7335).
- Langfuse 401 batch-wide: known credential regeneration pending (obs #7491); all L2 trace checks skipped.

## Validated strengths (expected == actual)
- Strike-escalation fix (`_rejection_strikes.py:42`) holds under 3 service pivots + 2 date reversals.
- Draft isolation between sequential bookings in one conversation; policy asked exactly once (DB fallback in `book.py:416-456` works as designed).
- Reschedule chain: single row mutated in place, availability re-checked before each move, correct dates echoed.
- Memory personalization: "lo de siempre" → correct service + stylist from seeded history, with confirmation before booking and no invented "usual time".
- Ownership/IDOR: all manage_appointments calls scoped to the resolved customer.
- Honest out-of-catalog decline, no hallucinated prices; wedding request escalated correctly.

## Harness debt observed (not agent bugs)
1. **Parallel-batch cleanup hazard**: one runner ran global `cleanup.py` mid-batch (deleted 93 Redis checkpoints while 5 runs were in flight). Rule for future batches: runners use `state_reset.py` scoped to their own phone; global cleanup is orchestrator-only, after the batch.
2. Server `venv/` is broken/empty; runners had to use `.venv/` or system python3 with `REDIS_URL`/`DATABASE_URL` overridden to localhost. Should be provisioned properly.
3. `state_reset.py` returned `"clean": false` after a fully successful cleanup — criteria miscalibrated.
4. `state_reset.py` has no escalations cleanup path (one tagged sandbox row remains: `80087fc9`).
5. Two runners exceeded the 15-turn hard cap (16, 18) to capture anomalies — cap policy vs anomaly-capture needs a documented exception rule.

## Recommended fix order
1. F1 phantom-confirmation guard (deterministic middleware check) — trust-destroying bug class.
2. F2 disambiguation precondition in manage_appointments confirm — data-corrupting (wrong appointment confirmed).
3. F3+F4 together: escalate docstring constraint + mandatory issue_summary — one PR, same file.
4. F5 cancellation_reason one-liner.
5. F6 draft-context retention on service change (needs design: preserve audience/variant answers across `update_booking` service pivots).
