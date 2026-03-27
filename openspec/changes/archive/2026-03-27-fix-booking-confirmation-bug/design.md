# Design: Fix Booking Confirmation Bug

## Technical Approach

Five surgical edits across 4 existing files + 1 new test file. No schema changes, no new dependencies. The fix targets the LLM-driven agentic architecture: `_pre_tool_call` (hard gate before `book()`), `_build_response` (exit serializer), `BookingContext` (slot data-bag), and the test layer. All changes follow the existing patterns: `ToolCallRejection` for gate logic, `ctx.to_mode_context()` for serialization, `tool_extractors.py` for failure tracking.

---

## Architecture Decisions

| # | Decision | Choice | Rejected | Rationale |
|---|----------|--------|----------|-----------|
| 1 | Where to auto-create customer | `_pre_tool_call` (line 709 gate), before `NO_CUSTOMER_ID` rejection | `_build_response`; `handle()` pre-resolvers | `_pre_tool_call` is the last-resort gate before `book()` runs. Pre-resolvers run early but the LLM may not call `manage_customer` at all. `_build_response` runs after the agentic loop — too late. |
| 2 | How to call DB for customer creation | Import & call `_create_customer` from `customer_tools.py` directly (internal function) | Invoke `manage_customer` tool via `tool.ainvoke()` | Direct call avoids tool schema overhead, JSON string parsing, and the tool dedup cache. `_create_customer(phone, data)` is a clean async function that returns a dict. Idempotent: call `_get_customer` first. |
| 3 | Where to increment `error_count` | `_build_response`, when `book_failure_count > 0` AND `not ctx._booking_completed` | In `_run_agentic_loop` (base.py) | Only booking failures should drive escalation. `_run_agentic_loop` handles generic LLM/tool errors — incrementing there causes false escalations from transient parse errors. |
| 4 | How to detect "booking failure" | Read `ctx.book_failure_count` after `apply_all_tool_results` runs | Check `AgenticLoopResult.error` field | `book_failure_count` is already incremented by `extract_booking_result` in `tool_extractors.py` (line 743). Checking it post-extraction avoids duplicating failure-detection logic. `result.error` is for LLM-level errors, not tool failures. |
| 5 | How to fix the broken test | Redirect to `booking.md` (single flat file) | Delete the test; create `booking/confirmation.md` | No subdirectory exists. Creating one contradicts the architecture (single monolithic prompt per mode). Redirecting is minimal and tests the actual file. |

---

## Data Flow

### GAP 1 — `_pre_tool_call` customer creation

```
_pre_tool_call("book", args)
  │
  ├─ ctx.customer_id set? ─── YES → skip, proceed to other gates
  │
  └─ NO → _create_customer_if_needed(ctx, state)
           │
           ├─ phone = state["customer_phone"]
           │  name = ctx.customer_name or state["pending_whatsapp_name"]
           │         or state["customer_first_name"] or "Cliente"
           │
           ├─ _get_customer(phone) → exists? → use existing ID
           │                       → not found? → _create_customer(phone, {first_name, ...})
           │
           ├─ SUCCESS → ctx.customer_id = uuid → proceed to other gates
           └─ FAIL → return ToolCallRejection(NO_CUSTOMER_ID)
```

### GAP 3 — `error_count` flow through `_build_response`

```
handle() → _run_agentic_loop → apply_all_tool_results
                                   │ (increments ctx.book_failure_count on failure)
         → _build_response
              │
              ├─ ctx._booking_completed? → NO changes to error_count
              │
              └─ NOT completed AND ctx.book_failure_count > prev_count?
                    → updates["error_count"] = state.get("error_count", 0) + 1
                    → router_node reads error_count >= 3 → ESCALATION
```

---

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `agent/modes/booking_mode.py` | Modify | (1) Add `_create_customer_if_needed` coroutine. (2) In `_pre_tool_call`, call it before `NO_CUSTOMER_ID` rejection. (3) In `_build_response`, snapshot `book_failure_count` at entry, compare after `apply_all_tool_results`, increment `error_count` if increased AND not success. (4) Set `ctx.last_error` on failure path. |
| `agent/modes/booking_context.py` | Modify | Add `last_error: str | None = None` field. Add to `reset_transient()`. |
| `tests/unit/test_prompt_loader.py` | Modify | Redirect `TestConfirmationMdNoNamePermission` to read `agent/prompts/modes/booking.md`. Assert no `"Puedes usar el nombre de la clienta"`. Assert contains `"Modo RESERVA"` (core instruction). |
| `tests/integration/test_booking_new_user.py` | Create | Integration test: state with `pending_whatsapp_name`, `customer_id=None`, `customer_phone` set → `BookingMode.handle()` → assert `customer_id` populated, no crash. Mock `_create_customer`/`_get_customer` and `book` tool at DB layer. |

---

## Interfaces / Contracts

### `_create_customer_if_needed` — new coroutine

```python
async def _create_customer_if_needed(
    self,
    ctx: BookingContext,
    state: ConversationState,
) -> str | None:
    """Try to create customer from state data. Returns UUID or None."""
    if ctx.customer_id:
        return ctx.customer_id  # Idempotent

    phone = state.get("customer_phone")
    if not phone:
        return None

    name = (
        ctx.customer_name
        or state.get("pending_whatsapp_name")
        or state.get("customer_first_name")
        or "Cliente"
    )

    # Try get-first (idempotent — customer may exist from a prior session)
    from agent.tools.customer_tools import _get_customer, _create_customer
    result = await _get_customer(phone)
    if result.get("id"):
        return result["id"]

    # Create
    parts = name.split(" ", 1)
    result = await _create_customer(phone, {
        "first_name": parts[0],
        "last_name": parts[1] if len(parts) > 1 else "",
    })
    return result.get("id")  # None if error
```

### `BookingContext.last_error` — new field

```python
# In BookingContext dataclass, under "Failure tracking" group:
last_error: str | None = None

# In reset_transient():
self.last_error = None
```

### `_build_response` — error_count increment

```python
# At top of _build_response, before any processing:
prev_book_failures = ctx.book_failure_count

# ... (existing code runs: name redaction, disclosure, etc.) ...

# After building `updates` dict, before return:
if not ctx._booking_completed and ctx.book_failure_count > prev_book_failures:
    ctx.last_error = str(result.tool_results.get("book", [{}])[-1])
    updates["error_count"] = state.get("error_count", 0) + 1
```

> **Note**: `book_failure_count` is incremented by `apply_all_tool_results` → `extract_booking_result` (line 743 of `tool_extractors.py`) BEFORE `_build_response` is called (line 391 → 414 in `booking_mode.py`). So comparing `prev` vs current is reliable.

**Correction**: `apply_all_tool_results` runs at line 391, `_build_response` at line 414. But `prev_book_failures` must be captured BEFORE `apply_all_tool_results`. Move the snapshot to `handle()` at line ~390:

```python
# In handle(), before apply_all_tool_results:
prev_book_failures = ctx.book_failure_count
apply_all_tool_results(result.tool_results, ctx)
# ... (existing post-processing) ...
return self._build_response(state, ctx, result, prev_book_failures)
```

`_build_response` gains an optional `prev_book_failures: int = 0` parameter.

---

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `_create_customer_if_needed` returns UUID on success, None on failure | Mock `_get_customer`/`_create_customer` from `customer_tools`. Test idempotency (already set), get-existing, create-new, no-phone paths. |
| Unit | `_pre_tool_call` with `customer_id=None` → calls `_create_customer_if_needed` → allows `book()` | Use existing `_make_mode()` + `BookingContext` pattern from `test_booking_guards.py`. Patch `_create_customer_if_needed`. |
| Unit | `_build_response` increments `error_count` when `book_failure_count` increased | Mock `AgenticLoopResult` with failed booking, assert `updates["error_count"]`. |
| Unit | `_build_response` does NOT increment `error_count` on success | Assert `"error_count"` not in returned dict when `_booking_completed=True`. |
| Unit | `BookingContext.last_error` serialized and cleared | `to_mode_context()` includes `last_error`, `reset_transient()` clears it. |
| Unit | `TestConfirmationMdNoNamePermission` reads `booking.md`, not `booking/confirmation.md` | Direct file-read assertion. |
| Integration | New WhatsApp user → `BookingMode.handle()` → booking succeeds | Mock LLM (returns `book()` tool call), mock `_get_customer`/`_create_customer` at DB layer, mock `book` tool. Assert `customer_id` populated and `appointment_created=True`. Follow `test_booking_guards.py` mock pattern. |

---

## Migration / Rollout

No migration required. All changes are Python logic + 1 new test file. No DB schema, no Redis key, no prompt content changes. Rollback: `git revert <commit>`.

---

## Open Questions

- [x] ~~Where to snapshot `prev_book_failures`~~ — Resolved: in `handle()` before `apply_all_tool_results`, passed to `_build_response` as parameter.
- [ ] Should `_create_customer_if_needed` also set `ctx.customer_name` if it was None? (Recommend yes — the name is needed for the confirmation summary, and we already have it from the fallback chain.)
