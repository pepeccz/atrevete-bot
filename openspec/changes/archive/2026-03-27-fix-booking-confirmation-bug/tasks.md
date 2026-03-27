# Tasks: Fix Booking Confirmation Bug

## Phase 1: Foundation — BookingContext data model

- [x] T-01 `agent/modes/booking_context.py` — Add `last_error: str | None = None` field to `BookingContext` dataclass, under the "Failure tracking" group (near `book_failure_count`). Add `self.last_error = None` to `reset_transient()`.
  - **AC**: `BookingContext().last_error` is `None`; `reset_transient()` clears it; `to_mode_context()` serializes it automatically (private-field filter does not strip it).

## Phase 2: Core logic — booking_mode.py

- [x] T-02 `agent/modes/booking_mode.py` — Add new coroutine `_create_customer_if_needed(self, ctx, state)` (see design.md interface). Returns UUID string or None. Calls `_get_customer(phone)` first (idempotent), then `_create_customer(phone, {...})`. Also sets `ctx.customer_name` if it was `None`.
  - **AC**: Given `customer_phone` set + `pending_whatsapp_name="María"` → returns UUID and sets `ctx.customer_id` + `ctx.customer_name`. Given no `customer_phone` → returns `None`.

- [x] T-03 `agent/modes/booking_mode.py` — In `_pre_tool_call`, before the `NO_CUSTOMER_ID` `ToolCallRejection` (line ~711): call `await self._create_customer_if_needed(ctx, state)`. If result is not None, set `ctx.customer_id = result` and `continue` past the rejection gate. If None, preserve existing rejection.
  - **AC**: Scenario 1.1 — `customer_id=None` + phone set → `book()` proceeds. Scenario 1.3 — `customer_id=None` + no phone → `ToolCallRejection(NO_CUSTOMER_ID)` returned unchanged.

- [x] T-04 `agent/modes/booking_mode.py` — In `handle()`, snapshot `prev_book_failures = ctx.book_failure_count` BEFORE the `apply_all_tool_results(result.tool_results, ctx)` call (line ~391). Pass it to `_build_response` as a new optional parameter: `_build_response(state, ctx, result, prev_book_failures=prev_book_failures)`.
  - **AC**: `handle()` compiles without error; `_build_response` signature updated.

- [x] T-05 `agent/modes/booking_mode.py` — In `_build_response`, add `prev_book_failures: int = 0` parameter. After building the `updates` dict, add: if `not ctx._booking_completed and ctx.book_failure_count > prev_book_failures` → set `ctx.last_error` from the last book tool result and add `updates["error_count"] = state.get("error_count", 0) + 1`.
  - **AC**: Scenario 3.1 — failure increments `error_count`. Scenario 3.3 — success does NOT add `error_count` to updates.

## Phase 3: Fix broken unit test

- [x] T-06 `tests/unit/test_prompt_loader.py` — Redirect class `TestConfirmationMdNoNamePermission` (line ~833): replace `booking/confirmation.md` path with `agent/prompts/modes/booking.md`. Update both test methods. `test_confirmation_md_does_not_contain_name_permission_line` asserts no `"Puedes usar el nombre de la clienta"`. `test_confirmation_md_retains_core_instructions` asserts `booking.md` contains core booking instruction (e.g. `"RESERVA"` or `"Modo RESERVA"`).
  - **AC**: Both tests pass; no `FileNotFoundError` raised.

## Phase 4: New unit tests

- [x] T-07 `tests/unit/test_booking_mode.py` (or `test_booking_guards.py`) — Unit test `_create_customer_if_needed`: (a) idempotent when `ctx.customer_id` already set; (b) uses existing customer when `_get_customer` returns a result; (c) creates new customer when `_get_customer` returns empty; (d) returns None when `customer_phone` absent. Mock `_get_customer` and `_create_customer` from `agent.tools.customer_tools`.
  - **AC**: 4 test scenarios pass; no real DB calls made.

- [x] T-08 `tests/unit/test_booking_mode.py` — Unit test `_pre_tool_call` with `customer_id=None`: patch `_create_customer_if_needed` to return UUID → assert `book()` gate is NOT rejected. Follow `_make_mode()` + `BookingContext` pattern from existing `test_booking_guards.py`.
  - **AC**: No `ToolCallRejection` returned; `ctx.customer_id` populated.

- [x] T-09 `tests/unit/test_booking_mode.py` — Unit test `_build_response` increments `error_count` on booking failure: mock `AgenticLoopResult` with a failed `book` tool result, set `ctx.book_failure_count = prev + 1`. Assert `updates["error_count"] == prev + 1`. Also test success path: assert `"error_count"` not in updates when `_booking_completed=True`.
  - **AC**: Scenario 3.1 and 3.3 pass.

- [x] T-10 `tests/unit/test_booking_mode.py` — Unit test `BookingContext.last_error`: `to_mode_context()` includes `last_error` when set; `reset_transient()` clears it to `None`.
  - **AC**: Serialization and reset verified.

## Phase 5: Integration test

- [x] T-11 `tests/integration/test_booking_new_user.py` (new file) — Integration test for Scenario 5.1: state with `customer_id=None`, `pending_whatsapp_name="Lucía"`, `customer_phone="+34600000001"` → call `BookingMode.handle()` with LLM mocked to return a `book()` tool call. Mock `_get_customer`/`_create_customer` at DB layer. Assert returned state has non-empty `mode_context` and `customer_id` populated. No `ValueError` raised.
  - **AC**: Test passes; `appointment_created=True` or booking proceeds past `NO_CUSTOMER_ID` gate.

- [x] T-12 `tests/integration/test_booking_new_user.py` — Integration test for Scenario 5.2: same setup but `customer_phone` absent. Assert the `book()` call is rejected (state contains LLM instruction to call `manage_customer` first). Assert `error_count` NOT incremented (rejection ≠ failure).
  - **AC**: No crash; `error_count` unchanged.

---

## Dependency Order

```
T-01 (BookingContext field)
  └─► T-02 (_create_customer_if_needed — reads ctx.customer_id)
        └─► T-03 (_pre_tool_call wiring)
              └─► T-08 (unit test for gate)
  └─► T-04 (snapshot prev_book_failures in handle())
        └─► T-05 (_build_response error_count + last_error)
              └─► T-09 (unit test _build_response)
              └─► T-10 (unit test last_error)
T-02 ──────────────────► T-07 (unit test _create_customer_if_needed)
T-06 (independent — redirect broken test)
T-03 + T-05 ───────────► T-11, T-12 (integration tests — require full wiring)
```
