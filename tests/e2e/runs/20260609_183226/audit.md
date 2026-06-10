# V4 QA Audit — Post-Change I Verification

**Run timestamp**: 20260609_183226
**Scenarios executed**: 7
**Baseline**: V3 (Change I delivered the P0 fixes)

---

## Executive Summary

V4 confirms that **Change I's P0 fixes hold in production**: the `service_id` FK validator
prevents UUID hallucination, `gcal_sync_status=not_applicable` is honored when
`TEST_MODE_GCAL_SKIP=true` propagates correctly via `env_file`, and R-39 (input gate
for non-procesable messages) fires on emoji-only turn 1. No V3 P0 regressions detected.

Three new polish-tier issues surfaced (R-39 wording leaks category enumeration; policy
re-ask loop during long impatient flows; cancel-con-razon scenario expectation
miscalibrated against the 48h policy). 2/7 runners misdiagnosed local containers
instead of the SSH server — a discipline/skill-doc bug, not a bot bug. These are all
bundled into **Change L (post-V4 polish bundle)**. The multi-customer split gap
(NEW-F) remains deferred to **Change M** pending Pilar business input.

---

## V4 vs V3 Regression Diff

| Issue (V3 obs) | V3 State | V4 State | Verdict |
|---|---|---|---|
| #6505 service_id UUID hallucination | P0 broken | **FIXED** — validator rejects fakes | HOLD |
| #6508 TEST_MODE_GCAL_SKIP not propagated | P0 broken | **FIXED** — env_file wired | HOLD |
| #6502 emoji category inference | broken | **FIXED** — R-39 gate fires | HOLD (wording polish needed) |
| #6500 duplicate sentence turn 1 | open | not re-detected in V4 (detector exists but not integrated) | UNKNOWN |
| #6503 turn-2 user input loop | open | deferred to Change K | DEFER |
| #6506 multi-customer split | open | reproduced again (multi-cita-pareja) | DEFER → Change M |

**No P0 regressions.** Change I delivered.

---

## Per-Scenario Verdict Table

| Scenario | Outcome | Bugs | Verdict | Notes |
|---|---|---|---|---|
| multi-cita-pareja | partial_completed | 0 | WARN | Change I fixes verified; NEW-F multi-customer gap persists |
| mensaje-no-procesable-emoji-solo | stuck | 0 | WARN | R-39 fired but enumerated 4 categories — should be open question |
| indecisa-cambia-criterio-tres-veces | BLOCKED | — | BLOCKED | Runner checked local stack instead of SSH server |
| faq-atienden-hombres | timeout | 0 | BLOCKED | Runner checked local stack instead of SSH server |
| cancel-con-razon | escalated | 0 | TECH-FAIL / BOT-OK | Bot correctly applied 48h policy + empathetic escalation; scenario expectation miscalibrated |
| impaciente-multiples-mensajes | booked | 2 | PASS w/ findings | Batching 3msgs/601ms→1 reply works; **policy re-ask loop** at turn 11 |
| laconica-todo-una-linea | booked | 0 | PASS | 4-slot one-shot extraction worked perfectly |

**Tally**: 2 PASS, 2 WARN, 1 TECH-FAIL (bot-correct), 2 BLOCKED.

---

## Critical Confirmation: Change I P0 Fixes Are Live

1. **service_id FK validator** (`agent/tools/_booking_validators.py`)
   - multi-cita-pareja turn N: bot did NOT generate a fake UUID; resolved real
     `service_id` from catalog before invoking `book`. No 4xx from DB FK.
2. **GCal env propagation** (`docker-compose.yml` env_file)
   - All bookings in V4 wrote `gcal_sync_status='not_applicable'` to `appointments`.
     No GCal API calls attempted. Sandbox isolation intact.
3. **R-39 input gate** (`agent/prompts/shared/critical_rules.md`)
   - Emoji-only turn 1 short-circuited to clarification request instead of inferring
     "depilación" or other category. Gate firing confirmed.

**Conclusion**: V4 is a green baseline for the P0 layer.

---

## New Findings → Change L Scope

### L1 — R-39 wording leak (P2)
**Symptom**: bot replies to emoji-only message with "podés contarme si querés
agendar un corte, color, depilación o tratamiento?" — enumerating four categories.
**Expected**: pure open question ("¿qué servicio te interesa?") so the bot doesn't
prime the user with category options.
**Fix**: tighten R-39 example block in `critical_rules.md`; forbid category
enumeration in the clarification reply.

### L2 — Policy re-ask loop (P1)
**Symptom**: in `impaciente-multiples-mensajes` turn 11, bot asked the customer to
accept the privacy policy a second time after already receiving acceptance earlier
in the same conversation.
**Hypothesis**: `policy_accepted_at` write happens after the LLM has already drafted
the second policy-ask turn; race window between middleware state read and DB write.
**Fix**: gate policy re-ask on `customer_consents` table presence, not on
state-cached `policy_accepted_at`. Or: invalidate the cached state slot once the
consent row is written within the same turn.

### L3 — cancel-con-razon scenario calibration (P2)
**Symptom**: scenario expected `outcome=cancelled` but bot correctly applied the
48h policy and escalated (because the seed appointment was inside the 48h window).
**Fix**: either change seed to schedule the appointment > 48h in the future and
expect `outcome=cancelled`, OR add a sibling scenario `cancel-fuera-48h` with the
> 48h seed and keep this one as the inside-48h escalation case. Recommend latter:
two distinct flows are useful regression coverage.

### L4 — Runner SKILL.md hardening (P1)
**Symptom**: 2/7 runners (indecisa, faq-atienden-hombres) diagnosed against the
local docker stack instead of the SSH `pepe@server` deploy, producing BLOCKED runs.
**Fixes**:
- Add explicit "**SERVER ONLY — ignore local containers**" warning at top of
  `skills/atrevete-qa-runner/SKILL.md`.
- Fix the `--phone` / `--name` → `--customer-phone` / `--persona-name` CLI flag
  drift in the runner CLI examples.
- Document `qa_turn_helper`'s `MESSAGE_BATCH_WINDOW_SECONDS=0` quirk (it disables
  batching for runner mode; without it, multi-message turns get merged on prod
  defaults and the runner mis-times responses).

### L5 — Duplicate-sentence detector integration (P3)
The detector built in Change I5 is not yet integrated into the V4 audit pipeline.
Wire it into `atrevete-qa-auditor` so future audits flag #6500-class regressions
automatically.

### Deferred → Change M
- **NEW-F multi-customer split** (#6506): requires business decision from Pilar on
  whether to split parent/companion into two `customers` rows or model as a single
  appointment with `companion_name`. Out of scope for L.

---

## Runner Discipline Issue

**2/7 runners (indecisa-cambia-criterio-tres-veces, faq-atienden-hombres) checked
local docker containers instead of the SSH server**, producing BLOCKED outcomes
not attributable to the bot.

This is the second time this drift surfaces (V3 had a similar single instance).
The L4 SKILL.md hardening above addresses root cause. Until that lands, orchestrators
spawning runner subagents should prepend the prompt with: "Deploy lives at
pepe@server:/home/pepe/Proyectos/atrevete-bot. NEVER inspect local containers."

---

## Recommendations

1. Ship **Change L** (L1-L5) as a single post-V4 polish bundle. No DB migration.
   Restart api+agent + rebuild admin-panel only for L1 (prompt) and L2 (middleware).
2. Re-run the 2 BLOCKED scenarios after L4 SKILL.md hardening lands.
3. File Change M backlog stub for NEW-F (multi-customer) once Pilar input arrives.
4. Adopt the I5 duplicate-sentence detector in the auditor before V5.
