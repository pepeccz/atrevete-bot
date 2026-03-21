# Design: Fix Booking Confirmation Bug

## Technical Approach

Four targeted surgical edits across 4 files. No schema changes, no new dependencies. Each fix
addresses a single broken invariant in the booking pipeline. The approach is defensive-by-default:
enforce correctness at the last possible checkpoint rather than relying on upstream paths to always
run correctly.

---

## Architecture Decisions

| # | Decision | Choice | Rejected | Rationale |
|---|----------|--------|----------|-----------|
| 1 | Where to ensure `customer_id` | Defensive guard in `_handle_completed` | Move creation to GREETING; enforce in `_handle_customer_name` | `_handle_completed` is the single mandatory exit point before `book()` is called. GREETING is only reached on first interaction — returning clients routed directly to BOOKING would still be broken. `_handle_customer_name` is skipped when `customer_name` is already in state. |
| 2 | Where to increment `error_count` | In each mode handler after `book()` fails | In `_run_agentic_loop` in `base.py` | `_run_agentic_loop` handles LLM/tool errors generically. Only booking failures should drive escalation. Incrementing in `_handle_completed` keeps the counter semantically correct and avoids false escalations from transient LLM errors. |
| 3 | How to preserve step on error | Merge current `mode_context` with `last_error` into error return | Reset `mode_context` on failure; return bare `CONFIRMATION` step | `_finalize_mode_context` currently sets `booking_step=CONFIRMATION` but does not preserve the collected slot/service/stylist data. Without preservation, `_determine_step` regresses the user to an earlier step because the data looks incomplete. |
| 4 | How to fix the prompt contradiction | Remove offending line from `confirmation.md`; filter `first_name` from `build_step_context` | Only update `critical_rules.md`; only filter at loader level | The contradiction requires fixing both the instruction source and the data leak. Removing the line closes the gap at the prompt level. Filtering `first_name` from `build_step_context` (line 309) closes the data leak. Note: `customer_name` is already not injected (line 265); `first_name` in `mode_context` IS injected and is the actual leak vector. |

---

## Data Flow

### Bug #1/#2 — Before (customer_id null path)

```
new user → preprocess → pending_whatsapp_name set, customer_id=None
         → router → BOOKING (intent="book")
         → _handle_completed
               customer_id = state.get("customer_id") or ""  # → ""
               book.ainvoke(customer_id="")
               UUID("") → ValueError → error_text set
         → LLM generates error response
         → user stuck, no booking created
```

### Bug #1/#2 — After (defensive guard)

```
new user → preprocess → pending_whatsapp_name set, customer_id=None
         → router → BOOKING (intent="book")
         → _handle_completed
               customer_id = state.get("customer_id") or ""  # → ""
               [NEW] if not customer_id:
                   resolved_name = first_name or pending_whatsapp_name or "Cliente"
                   customer_id = await _create_customer_if_needed(state, resolved_name)
                   if customer_id: updates["customer_id"] = customer_id
               book.ainvoke(customer_id=valid_uuid)  # ✓ succeeds
         → appointment created
```

### Bug #3 — error_count flow

```
Before: book() fails → error_text set → error response returned
        router_node checks error_count → always 0 → escalation never fires

After:  book() fails → error_text set
        [NEW] updates["error_count"] = state.get("error_count", 0) + 1
        → error response returned
        router_node checks error_count ≥ 3 → escalates ✓
```

### Bug #4 — mode_context on error

```
Before: error_text set → _finalize_mode_context(mode_context, CONFIRMATION, COMPLETED)
        → {"booking_step": "confirmation"}  # slot/service data LOST
        → next turn: _determine_step sees incomplete data → regresses

After:  error_text set →
        [NEW] {"booking_step": "confirmation", **current mode_context, "last_error": error_text}
        → next turn: _determine_step sees complete data → stays at confirmation ✓
```

### Bug #5 — name leak flow

```
Before: build_step_context injects mode_context["first_name"]  (line 309)
        confirmation.md says "Puedes usar el nombre de la clienta"
        LLM sees both → uses name in response → Rule #6 violated

After:  build_step_context skips "first_name" key (filtered)
        confirmation.md line 11 removed
        LLM receives no name data → cannot use it ✓
```

---

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `agent/modes/booking_mode.py` | Modify | Add defensive `customer_id` guard + `error_count` increment + `mode_context` preservation in `_handle_completed` |
| `agent/prompts/loader.py` | Modify | Filter `first_name` key from `mode_context` in `build_step_context` (line 309 area) |
| `agent/prompts/modes/booking/confirmation.md` | Modify | Remove line 11: "Puedes usar el nombre de la clienta solo si ya existe en el estado." |

> `agent/modes/base.py` — No changes required. `error_count` increment belongs in the booking handler, not the generic loop.

---

## Interfaces / Contracts

### `_handle_completed` — modified return on error path

```python
# booking_mode.py — error branch (lines ~1309-1326)
# BEFORE
return {
    **self._response_updates(state, result.response_text),
    "mode_context": self._finalize_mode_context(
        mode_context,
        BookingSubstep.CONFIRMATION,
        BookingSubstep.COMPLETED,
    ),
    "last_node": "booking",
    "user_message": None,
}

# AFTER
return {
    **self._response_updates(state, result.response_text),
    "mode_context": {
        **mode_context,                        # preserve all collected data
        "booking_step": BookingSubstep.CONFIRMATION.value,
        "last_error": error_text,              # surface error for LLM context
    },
    "error_count": state.get("error_count", 0) + 1,   # drive escalation
    "last_node": "booking",
    "user_message": None,
}
```

### Defensive `customer_id` guard — new block in `_handle_completed`

```python
# Insert after line 1280: customer_id = state.get("customer_id") or ""
if not customer_id:
    resolved_name = (
        first_name
        or state.get("pending_whatsapp_name")
        or state.get("customer_first_name")
        or "Cliente"
    )
    new_id = await self._create_customer_if_needed(state, resolved_name)
    if new_id:
        customer_id = new_id
        updates: dict[str, Any] = {"customer_id": customer_id}
    else:
        self.logger.error("_handle_completed: could not resolve customer_id, booking will fail")
```

### `build_step_context` — filter `first_name`

```python
# loader.py — replace lines 309-310
# BEFORE
if mode_context.get("first_name"):
    collected_data.append(f"Nombre para la reserva: {mode_context['first_name']}")

# AFTER  (remove entirely — first_name must not reach LLM)
```

---

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `_handle_completed` with `customer_id=None` and valid `pending_whatsapp_name` → booking succeeds | Mock `_create_customer_if_needed`, assert it is called and `customer_id` is set before `book.ainvoke` |
| Unit | `error_count` increments on booking failure | Assert state update contains `error_count = prev + 1` |
| Unit | `mode_context` preserved on error (booking_step stays CONFIRMATION, all data intact) | Assert mode_context keys after error path |
| Unit | `build_step_context` does NOT include `first_name` | Pass mode_context with `first_name` set; assert output string does not contain it |
| Unit | `confirmation.md` does not contain name-permission line | Grep / string match on file content |
| Integration | Full booking flow from new WhatsApp user to appointment created | Use existing mock fixtures; assert `appointment_created=True` in final state |

---

## Migration / Rollout

No migration required. Changes are confined to Python logic and one markdown file.
No database schema changes. No Redis key format changes. Rollback: `git revert <commit>`.

---

## Open Questions

- [ ] Should `last_error` in `mode_context` be shown to the LLM via a dedicated substep prompt overlay, or is the generic `error` substep prompt sufficient? (Current design uses existing `error` step — acceptable for now.)
- [ ] If `_create_customer_if_needed` returns `None` (no phone, or DB failure), should the booking be aborted with an escalation trigger instead of letting `book()` fail with an empty `customer_id`? (Current design logs an error and continues — `book()` will fail and escalation will eventually trigger via `error_count`.)
