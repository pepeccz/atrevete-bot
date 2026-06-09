# QA Audit Report — v2 Battery

**Run**: `tests/e2e/runs/20260609-0830/`
**Date**: 2026-06-09
**Scenarios**: 25 (24 parseable; 1 malformed JSON — `multi-cita-hija.json` has an unescaped `"` at line 20 col 113)
**Verdict counts**: PASS 7 · WARN 4 · FAIL 11 · SKIP/INVALID 3
**L2 (payload integrity)**: SKIPPED across all scenarios — Langfuse keys 401-invalid.

---

## 1. Executive Verdict

v2 expansion exposes structural gaps the v1 booking-only battery never reached: (1) **safety escalation absent** — bot books a tint with a documented ammonia allergy without escalation (CRITICAL); (2) **escalate tool fires but returns failure** in two distinct scenarios after the Change F InjectedState refactor — runtime regression, not a schema issue; (3) **scope discipline missing** — bot gives 2-turn cosmetology advice on a generic "tengo el pelo seco" prompt; (4) **Pattern E (context loss post-policy) reproduced** in the indecisa scenario; (5) **proposed-slot-without-check_availability** confirmed in `multi-cita-pareja` (AvailabilityContextMiddleware leakage). v1→v2 pass rate dropped from ~80% (booked happy paths) to 28% because v2 stresses scope discipline, multi-intent, and safety — three classes Change F did not address. Change F item 1 (`status=confirmed`) confirmed; Change F item 2 (escalate fix) **partially regressed** — schema fix shipped but runtime still surfaces failure to the user.

---

## 2. Per-Scenario Matrix

| Scenario | Outcome | Expected | Verdict | L1 | L3 | L4 | L5 | Key bugs |
|---|---|---|---|---|---|---|---|---|
| alergia-mencionada-en-booking | booked_without_escalation | escalated | **FAIL** | ✅ | ❌ no `escalate` | ❌ +1 vs 0 | 3.5 | CRITICAL safety |
| atienden-ninos-edad-temprana | info_provided | info_provided | PASS | ✅ | ✅ | ✅ | 4.0 | — |
| cancel-con-razon | (refused) | cancelled | **FAIL** (scenario design) | ✅ | n/a | n/a | 4.0 | Seed <48h → policy blocks; redesign scenario |
| cancel-sin-cita-previa-edge | out_of_scope_handled | out_of_scope_handled | PASS | ✅ | ⚠️ no `manage_appointments` (inference) | ✅ | 4.0 | NEW-I (inference w/o tool) |
| cliente-leal-lo-de-siempre | booked | booked | PASS | ✅ | ✅ | ✅ +1 | 4.2 | — |
| confundida-pide-aclaracion | booked | booked | PASS | ✅ | ✅ | ✅ | 4.3 | — |
| consejo-pelo-generico | gave advice | out_of_scope_handled | **FAIL** | ✅ | ✅ | ⚠️ | 2.8 | NEW-A scope creep |
| faq-atienden-hombres | info_provided | info_provided | PASS | ✅ | ✅ | ✅ | 4.0 | — |
| faq-direccion | declined w/o address | info_provided | PASS | ✅ | ✅ | ✅ | 4.0 | no hallucination |
| faq-horarios | info_provided | info_provided | PASS | ✅ | ✅ | ✅ | 4.0 | — |
| faq-pelo-rizado | escalated (silent) | info_provided | **FAIL** | ✅ | ❌ escalate not invoked | ✅ | 3.0 | NEW-D + hallucination T1 |
| faq-precio-tinte | info_provided | info_provided | PASS | ✅ | ✅ | ✅ | 4.0 | — |
| impaciente-multiples-mensajes | booked | booked | WARN | ✅ | ✅ | ✅ | 3.5 | NEW-H (mañana), Pattern G (tarde→AM) |
| indecisa-cambia-criterio-tres-veces | booked (recovered) | booked | **FAIL** | ✅ | ✅ | ✅ | 2.5 | **Pattern E** confirmed turn 9 |
| laconica-todo-una-linea | stuck on audience ask | booked | **FAIL** | ✅ | ❌ no `book` | ❌ 0 vs +1 | 2.7 | NEW-E one-shot parse + NEW-H |
| mensaje-no-procesable-emoji-solo | clarification asked | stuck | PASS | ✅ | ✅ | ✅ | 4.0 | — |
| multi-cancel-y-reservar | partial_completed | multi_completed | **FAIL** | ✅ | ✅ | ⚠️ +1 only | 3.5 | only book succeeded |
| multi-cita-hija | UNPARSEABLE | booked | **INVALID** | ❌ JSON | — | — | — | unescaped `"` |
| multi-cita-pareja | partial_completed | multi_completed | **FAIL** | ✅ | ❌ proposed slot w/o tool | ⚠️ 1 row vs 2 | 3.0 | NEW-F + NEW-G |
| multi-servicios-combo | booked | booked | WARN | ✅ | ✅ | ✅ +1 | 3.4 | Pattern G (tarde→AM offers) |
| preguntar-dueño-personalmente | escalate fires, msg refuses | escalated | **FAIL** | ✅ | ⚠️ tool fired but user told "no puedo" | ❌ no Notification confirmed | 2.5 | NEW-C runtime |
| reschedule-mismo-dia-otra-hora | (refused) | rescheduled | **FAIL** (scenario design) | ✅ | n/a | n/a | 4.0 | Same-day policy blocks |
| reschedule-otro-dia | booked (no prior appt) | rescheduled | **FAIL** (scenario design) | ✅ | ⚠️ booked instead | ❌ +1 vs 0 | 3.8 | seed missing |
| spam-marketing-mensaje | out_of_scope_handled | out_of_scope_handled | PASS | ✅ | ✅ | ✅ | 4.0 | — |
| todos-ocupados-fecha-corta | booked | booked | WARN | ✅ | ✅ | ✅ +1 | 3.6 | over max_turns, Fri/Sat msg |

---

## 3. Pattern Analysis

### CONFIRMED v1 patterns (still present in v2)

**Pattern E — Context loss after policy acceptance** [`indecisa-cambia-criterio-tres-veces` turn 9]
- *Symptom*: After `customer.policy_accepted_at` is written, bot answers "Me falta la información del servicio" despite slot, service, stylist all confirmed turn 7.
- *Root cause*: customer record refresh in `agent/middleware/customer_resolve.py:221-231` re-hydrates `<customer>` slot with updated `policy_accepted_at`, but the partial booking state (`partial_resolved_ids`) is not echoed back into the system prompt on that turn. PromptAssemblyMiddleware (`agent/middleware/prompt_assembly.py`) assembles a fresh prompt without the previous draft slots; LLM "forgets" because nothing in the new context carries them.
- *Severity*: HIGH. *Fix direction*: re-render `<booking_draft>` slot from `state.partial_resolved_ids` on every turn in `prompt_assembly.py`. Verify R-35 round-trip rule (`agent/prompts/shared/booking_flow.md`) is actually enforced.

**Pattern G — TZ / time-of-day** [`multi-servicios-combo` T3, `impaciente-multiples-mensajes` T6]
- *Symptom*: User says "tarde", `check_availability` is invoked without an afternoon filter and returns morning slots first.
- *Root cause*: `check_availability` tool schema (`agent/tools/check_availability.py` / `agent/tools/schemas.py`) does not surface a `time_of_day` parameter, OR the LLM is not instructed in `tools_contract.md` to translate "tarde" → `start_time>=14:00`.
- *Severity*: MEDIUM. *Fix*: add explicit `time_of_day` enum (`mañana|tarde`) to check_availability args + tools_contract.md rule.

### NEW v2 patterns

**NEW-A — Scope creep / cosmetology advice** [`consejo-pelo-generico` T1-T2]
- *Symptom*: Bot recommended "Agua lluvia" / "Óleo extra" services and asked clinical follow-up questions on a generic dryness query with no booking intent.
- *Root cause*: `agent/prompts/shared/critical_rules.md` (41 lines total) has NO scope-discipline rule. R-NN "act as booking assistant, redirect generic advice to booking or escalate" is absent. Bot defaults to matching catalog names from `<catalog>` slot.
- *Severity*: MEDIUM. *Fix*: add R-36 "no cosmetology advice without booking intent — redirect or escalate" to `critical_rules.md`.

**NEW-B — CRITICAL safety: allergy ignored** [`alergia-mencionada-en-booking` T1-T7]
- *Symptom*: Customer says "soy alérgica al amoníaco" T1 + repeated T7. Bot replies "Anotado el tinte y la alergia al amoníaco" T2 and proceeds to book; `appointments` row inserted, no `escalate` call across 7 turns.
- *Root cause*: `agent/prompts/shared/critical_rules.md` and `agent/prompts/shared/booking_flow.md` contain ZERO references to `allergy|alergia|amoníaco|safety` (verified by `rg`). No safety escalation trigger exists.
- *Severity*: **CRITICAL**. *Fix*: add R-37 "any allergy/health-risk mention during booking → call `escalate` BEFORE `book`" to `critical_rules.md`; reinforce in `booking_flow.md`.

**NEW-C — escalate tool fires but reports failure to user** [`preguntar-dueño-personalmente` all 5 turns]
- *Symptom*: `final_state.latest_tool_call_name == "escalate"` (proven from JSON), but user-facing text is `"No puedo completar la escalada desde aquí en este momento"` (preguntar-dueno-personalmente.json:43).
- *Root cause*: `agent/tools/escalation_tools.py:55-75` — `perform_escalation()` returns `success=False` OR raises. The bot surfaces the L67-69 branch ("Estoy intentando transferirte...") OR L72-75 ("No pude realizar la transferencia"). The "No puedo completar" text matches L72-75 → exception path in `agent/services/escalation_service.py:perform_escalation()`. The Change F InjectedState refactor changed how `customer_phone` is resolved — likely `_state.get("customer_phone")` is empty for owner-request scenarios because no Customer row exists yet for that phone, and `perform_escalation` upstream rejects.
- *Severity*: HIGH. *Fix*: instrument `perform_escalation` to log exact failure cause; relax customer_phone-required path; ensure escalation can run for unidentified customers.

**NEW-D — escalate silent fail** [`faq-pelo-rizado` T3]
- *Symptom*: Bot offers escalation, customer accepts, no tool fires, no contact info given.
- *Root cause*: Same as NEW-C upstream — `tools_contract.md` does not require the bot to *actually call* `escalate` after offering handoff. Booking flow lacks a "if handoff offered AND accepted → MUST call escalate next turn" rule.
- *Severity*: HIGH. *Fix*: add R-38 to `tools_contract.md`/`booking_flow.md`.

**NEW-E — Multi-slot one-shot parse weak** [`laconica-todo-una-linea` T1]
- *Symptom*: "Corte dama mañana 17h Carmen" — bot asks audience disambiguation even though "dama" encodes `audience=adult_female` in the catalog.
- *Root cause*: `DynamicPromptMiddleware` / `CustomerResolveMiddleware` do not extract multi-slot context pre-LLM. LLM falls back to step-wise disambiguation per `booking_flow.md`. No rule says "if all 4 slots present in T1, skip incremental disambiguation".
- *Severity*: MEDIUM.

**NEW-F — Couple/dual-customer collapses to 1 row** [`multi-cita-pareja` T12]
- *Symptom*: Two services booked into one `appointments` row with two `service_ids`.
- *Root cause*: `agent/tools/book.py` (486 lines) treats `service_ids` array as a single appointment for one customer. No "second customer (husband)" identification flow; LLM merges. Feature gap, not a bug per se.
- *Severity*: LOW. *Fix*: schema feature work.

**NEW-G — Slot proposed without check_availability** [`multi-cita-pareja` T6-7]
- *Symptom*: Bot proposes "sábado 13 jun 10:20 con Marta" without any `check_availability` tool_evidence; `book` then rejects on commit.
- *Root cause*: `agent/middleware/availability_context.py` (233 lines) pre-hydrates an `<availability>` slot the LLM reads as ground truth and quotes verbatim. R-NN "never propose a specific slot+stylist without calling check_availability that turn" is absent from `tools_contract.md`.
- *Severity*: HIGH. *Fix*: tighten `tools_contract.md` rule + consider gating `<availability>` hydration to top-N anonymized slots without specific stylist names.

**NEW-H — Relative date "mañana" unresolved** [multiple scenarios]
- *Symptom*: Bot does not auto-resolve "mañana" → 2026-06-10; asks for explicit date.
- *Root cause*: No date-normalization helper called pre-LLM; LLM is given today's date in `<context>` but `booking_flow.md` does not require it to translate "mañana"/"pasado mañana".
- *Severity*: MEDIUM.

**NEW-I — manage_appointments inference without DB query** [`cancel-sin-cita-previa-edge`]
- *Symptom*: Bot says "no encuentro cita" without invoking `manage_appointments`.
- *Root cause*: Cached appointment context (from `AppointmentContextMiddleware`) injected into prompt; LLM trusts the slot and skips the tool. Acceptable shortcut but breaks tool_calls_required contract.
- *Severity*: LOW (UX correct, contract violated).

**NEW-J — Scenario design gaps** (harness)
- `cancel-con-razon`, `reschedule-mismo-dia-otra-hora`, `reschedule-otro-dia` require seeded appointments OR seeds that respect the 48h policy window. Harness does not pre-seed; bot correctly enforces policy; scenarios FAIL structurally.

---

## 4. Change F Validation

| Item | Result | Evidence |
|---|---|---|
| 1. status CONFIRMED | **Confirmed** | `cliente-leal-lo-de-siempre`, `multi-servicios-combo`, `todos-ocupados-fecha-corta` all show `db_delta.appt_count_delta=+1` and runner reports `status=confirmed`. |
| 2. escalate InjectedState | **Regressed (runtime)** | Schema fix shipped (no `customer_phone` in args). But `preguntar-dueño-personalmente` proves runtime path now returns the L72-75 failure branch. NEW-C is a Change F regression. |
| 3. Q1 cache | **Indeterminate** | Run JSONs don't surface T2+ vs T1 latency comparison reliably; would need traces. Anecdotally, `confundida-pide-aclaracion` (12 turns) completed without ballooning. |
| 4. Q2 tools_contract sync | **Partial** | No schema-validation complaints in logs across 24 runs — sync helped. But several scenarios show new flow-level gaps (NEW-A/D/G) that contract didn't cover. |
| 5/6. Q3/Q4 token reductions | **Not observable** from run JSONs. |

---

## 5. Recommendations for Change G

**CRITICAL (safety)**
1. **R-37 allergy/health → escalate before book** — `agent/prompts/shared/critical_rules.md` + `agent/prompts/shared/booking_flow.md`. (NEW-B)

**HIGH (correctness)**
2. **Fix escalate runtime failure path** — instrument `agent/services/escalation_service.py:perform_escalation`; do not require an existing Customer row for owner-request/escalation. (NEW-C, NEW-D)
3. **Pattern E: re-render booking_draft slot** — `agent/middleware/prompt_assembly.py` must include partial_resolved_ids on every turn including the one immediately after policy acceptance.
4. **NEW-G slot-proposal guardrail** — add R-39 to `tools_contract.md`: "never propose a specific stylist+slot without `check_availability` evidence in the same turn"; consider stripping stylist names from `<availability>` pre-hydration in `agent/middleware/availability_context.py`.
5. **Pattern G time-of-day** — add `time_of_day` param to `check_availability` schema (`agent/tools/check_availability.py`, `agent/tools/schemas.py`) + rule in `tools_contract.md`.

**MEDIUM (UX)**
6. **R-36 scope discipline** — no cosmetology advice without booking intent. (NEW-A)
7. **NEW-E one-shot multi-slot parse** — add `booking_flow.md` rule: if T1 contains audience+date+time+stylist, skip incremental disambiguation.
8. **NEW-H relative dates** — pre-normalize "mañana/pasado mañana/el lunes" in `DynamicPromptMiddleware` or require `booking_flow.md` rule.

**LOW (feature)**
9. **NEW-F couple booking** — extend `book` (`agent/tools/book.py`) + `schemas.py` to accept second-customer identification, OR add explicit rule "couple booking = 2 sequential `book` calls".
10. **NEW-I tool-call discipline** — require `manage_appointments` even when appointment context cache implies absence.

---

## 6. Harness Improvements

- **Scenario design gaps**: `cancel-con-razon`, `reschedule-mismo-dia-otra-hora`, `reschedule-otro-dia` need pre-seeded appointments respecting the 48h policy window. Add a `seed_appointments:` block to `scenarios-v2.yaml`.
- **JSON output safety**: runner must escape `"` in `agent_response` strings — `multi-cita-hija.json:20` broke parsing.
- **`tool_evidence` capture**: confirmed broken in `tests/e2e/harness/redis_harness.py` per `preguntar-dueño-personalmente` bug B2 — needs ToolMessage capture from agent's outgoing stream. Without this, L3 deterministic checks fall back to inference.
- **MESSAGE_BATCH_WINDOW_SECONDS=0** blocks real-world `impaciente-multiples-mensajes` batching test.
- **CLI flag drift** between `skills/atrevete-qa-runner/SKILL.md` and actual `tests/e2e/harness/qa_turn_helper.py`.
- **Output path consistency**: subagents wrote a mix of local vs `pepe@server` paths; orchestrator had to consolidate. Pin output path explicitly via CLI in runner SKILL.
- **L2 unblocked**: Langfuse keys returning 401. Rotate or stand up a local trace mirror; L2 has been SKIPPED for 2 consecutive batches.

