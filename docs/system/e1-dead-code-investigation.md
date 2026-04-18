# E1 Dead-Code Investigation Report

> Performed: 2026-04-18  
> Branch: `feat/architecture-migration-e1`  
> HEAD at time of investigation: `7221d61`  
> Investigator: SDD apply agent (e1-scaffolding, batch C7)  
> Method: `git grep` static import scan + git-log activity check

---

## Summary

E1 investigation found **zero confirmed-dead candidates**. All 7 candidates initially flagged by the audit remain active — either with live runtime importers or with enough test coverage and indirect usage to make blind deletion high-risk.

**Net E1 deletions: 0 files.**

---

## Investigation Method

For each candidate:

1. **Static import scan** — `git grep -n "from <module>\|import <module>"` across all `*.py` files.
2. **Git activity check** — `git log --since="60 days ago" -- <path>` to confirm recent activity.
3. **Deletion threshold** — DELETE only if `static_importers == 0` AND `runtime_refs == 0` AND `no_recent_activity_60d`. Otherwise: KEEP.

---

## Per-Candidate Findings

### 1. `agent/fsm/models.py`

**Verdict: KEEP — active dependency**

Static importers found:

| File | Line | Symbol |
|------|------|--------|
| `agent/fsm/__init__.py` | 23 | package re-export |
| `agent/modes/confirmation_reply_node.py` | 7 | `IntentType` |
| `agent/routing/intent_router.py` | 21 | `Intent, IntentType` |
| `agent/services/cancellation_service.py` | 600 | `IntentType` (lazy) |
| `agent/services/confirmation_service.py` | 35 | `IntentType` |
| `tests/unit/test_confirmation_reply_node.py` | 6 | `IntentType` |
| `tests/unit/test_confirmation_service.py` | 24 | `IntentType` |
| `tests/unit/test_intent_router.py` | 19 | `BookingState, Intent, IntentType` |

**Conclusion**: Heavily used across routing, confirmation, and cancellation. The audit that labeled it "legacy v5.x deprecated" was wrong — the FSM model types are still the canonical intent type system. Do NOT delete in E1. Scheduled path is `DELETE | E1` in `06-current-vs-target.md`; that row must be corrected to reflect live usage.

---

### 2. `agent/prompts/legacy/` (5 `.md` files)

**Verdict: KEEP — active runtime path**

Static importers found:

| File | Line | What |
|------|------|------|
| `agent/prompts/__init__.py` | 34 | `load_maite_system_prompt()` definition |
| `agent/prompts/__init__.py` | 44 | `Path(__file__).parent / "legacy" / "maite_system_prompt.md"` (runtime file read) |
| `agent/prompts/__init__.py` | 201 | exported in `__all__` |

The function `load_maite_system_prompt()` is called by `agent/graphs/conversation_flow.py:21` at graph build time. The legacy markdown files are loaded at runtime, not imported; the `__init__.py` builds the prompt string by reading `legacy/maite_system_prompt.md` directly from disk.

`06-current-vs-target.md` row `agent/prompts/legacy/ | DELETE | E1` is stale. The directory is live. Correction: change phase to E4 and action to DELETE-after-mode-migration (when BookingCapability replaces the current graph in E2 and the legacy system prompt is superseded).

---

### 3. `agent/batching/message_batcher.py`

**Verdict: KEEP — main entry point dependency**

Static importers found:

| File | Line | Symbol |
|------|------|--------|
| `agent/batching/__init__.py` | 8 | package re-export |
| `agent/main.py` | 13 | `MessageBatcher` |
| `tests/unit/test_batcher_dedup.py` | 11 | `MessageBatcher` |

`agent/main.py` is the Redis Streams consumer entry point. `MessageBatcher` is instantiated there and drives the deduplication loop. Zero ambiguity — actively used at runtime. The audit label "INVESTIGAR: si no hay callers → DELETE" from `06-current-vs-target.md` is now resolved: there ARE callers. Update action to `KEEP` or defer to E4 for a potential MOVE to `infra/workers/batching.py`.

---

### 4. `agent/resilience/*` (3 files)

**Files**: `agent/resilience/error_classifier.py`, `agent/resilience/fallback_chain.py`, `agent/resilience/retry_strategy.py`

**Verdict: KEEP — deferred to E4 (see deferred tasks below)**

Static importers from OUTSIDE the package:

- Zero production callers found via grep. The modules import each other internally (within `agent/resilience/`) but no file outside the package imports them.
- Heavy test coverage: `tests/unit/test_error_classifier.py` has 700+ lines of assertions.

**Why not DELETE in E1**: The absence of production callers does NOT confirm the modules are dead. Circuit breaker semantics may be wired indirectly (e.g., via middleware that references them at runtime but not statically). Deleting 3 tested modules without a runtime trace is high-risk. The safe action is to document this as an E4 task with explicit runtime tracing requirement before deletion.

**E4 task logged** — see deferred tasks section below.

---

### 5. `agent/validators/slot_validator.py` + `agent/validators/transaction_validators.py`

**Verdict: KEEP — active dependency**

Static importers found:

| File | Line | Symbol |
|------|------|--------|
| `agent/modes/booking_mode.py` | 901 | `MINIMUM_DAYS` from `transaction_validators` |
| `agent/services/availability_service.py` | 525 | `MINIMUM_DAYS` |
| `agent/tools/availability_tools.py` | 41–42 | `validate_3_day_rule`, `MINIMUM_DAYS` |
| `agent/tools/manage_appointments_tool.py` | 397 | `validate_3_day_rule` |
| `agent/transactions/booking_transaction.py` | 28 | multiple validators |
| `agent/validators/__init__.py` | 13 | package re-export |
| `agent/validators/slot_validator.py` | 19 | internal cross-import |
| `tests/unit/test_slot_validator.py` | 6 | `SlotValidator` |
| `tests/unit/test_transaction_validators.py` | 2 | — |
| `tests/unit/test_category_validation.py` | 13 | `validate_category_consistency` |

Deeply integrated across availability, booking, and appointment management. The audit label "INVESTIGAR" is resolved: these validators are load-bearing. Not deletable in E1 or E4; eventual target is `cores/availability/` in E2.

---

### 6. `shared/email_service.py`

**Verdict: KEEP — active billing path**

Static importers found:

| File | Line | Symbol |
|------|------|--------|
| `api/services/billing_service.py` | 21 | `EmailService` |
| `api/services/billing_service.py` | 38 | `self.email_service = EmailService()` |
| `api/services/billing_service.py` | 251 | `await self.email_service.send_invoice_email(...)` |

The `06-current-vs-target.md` row marks this `DELETE? | E1` — the question mark is now answered: NOT deletable. `BillingService` instantiates it and calls `send_invoice_email` in the invoice-paid flow. Removing it would break the billing path silently.

Update row action to `MOVE → infra/email/` in E4, when billing is extracted to `cores/billing/`.

---

### 7. `api/services/stripe_service.py`

**Verdict: KEEP — active billing path**

Static importers found:

| File | Line | Symbol |
|------|------|--------|
| `api/services/billing_service.py` | 20 | `StripeService` |
| `api/routes/billing.py` | 34 | `StripeService` |
| `api/routes/billing.py` | 271, 299, 329, 330, 337, 362, 363, 387 | instantiated + used across 4 routes |

The `06-current-vs-target.md` row marks this `DELETE? | E1` — also resolved: NOT deletable. It powers `/billing/setup-session`, `/billing/sepa-status`, and SEPA/tax-id management routes that are live in production. 

Update row action to `MOVE → cores/billing/` or `infra/billing/` in E4.

---

## Corrections Required in `06-current-vs-target.md`

The following rows need action corrections based on this investigation. These corrections are applied in commit C8 alongside the architecture doc update:

| Row | Current action | Corrected action | Corrected phase |
|-----|----------------|------------------|-----------------|
| `agent/fsm/models.py` | `DELETE \| E1` | `DELETE` (only after E4 cleanup replaces FSM types) | E4 |
| `agent/prompts/legacy/` | `DELETE \| E1` | `DELETE` (only after E2 moves BookingCapability + loader supersedes) | E4 |
| `agent/batching/message_batcher.py` | `INVESTIGAR → DELETE \| E1` | `KEEP or MOVE → infra/workers/batching.py` | E4 |
| `agent/resilience/error_classifier.py` | `INVESTIGAR → DELETE \| E1` | `INVESTIGATE with runtime trace` | E4 |
| `agent/resilience/fallback_chain.py` | `INVESTIGAR \| E1` | `INVESTIGATE with runtime trace` | E4 |
| `agent/resilience/retry_strategy.py` | `INVESTIGAR \| E1` | `INVESTIGATE with runtime trace` | E4 |
| `agent/validators/slot_validator.py` | `INVESTIGAR \| E1` | `MOVE → cores/availability/` | E2 |
| `agent/validators/transaction_validators.py` | `INVESTIGAR \| E1` | `MOVE → cores/availability/` | E2 |
| `shared/email_service.py` | `DELETE? \| E1` | `MOVE → infra/email/` | E4 |
| `api/services/stripe_service.py` | `DELETE? \| E1` | `MOVE → cores/billing/ or infra/billing/` | E4 |

---

## Deferred Tasks (E4)

The following task is added to `docs/system/07-migration-plan.md` under Phase E4:

> **E4 deferred: Investigate and delete `agent/resilience/*` if confirmed dead.**  
> Conditions for deletion: (1) zero static importers outside the package, (2) zero runtime trace (add temporary logging to confirm zero invocations in production over 7 days), (3) no middleware or dependency-injection that instantiates these classes indirectly. If conditions met: delete in a single commit with a detailed justification comment. If conditions not met: MOVE to `infra/resilience/` and wire into production use.

---

## References

- `docs/system/06-current-vs-target.md` — mapping rows updated in commit C8
- `docs/system/07-migration-plan.md` — E4 deferred task added in commit C8
- Design artifact: engram #4094, section 3 (dead-code investigation protocol)
- Spec: R18
