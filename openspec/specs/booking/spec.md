# Spec: Booking Mode — Customer Creation & Error Tracking

**Domain**: booking
**Source change**: fix-booking-confirmation-bug
**Archived**: 2026-03-27
**Architecture**: LLM-driven mode-based (v6.0) — BookingContext + _pre_tool_call + _build_response

---

## Requirement 1 — Inline customer creation for new WhatsApp users

**File**: `agent/modes/booking_mode.py`
**Location**: `_pre_tool_call`, before `NO_CUSTOMER_ID` rejection gate

The system MUST attempt silent customer creation when `ctx.customer_id` is `None` but `pending_whatsapp_name` and `customer_phone` are both available in state, before returning a `ToolCallRejection`. A new coroutine `_create_customer_if_needed(ctx, state)` SHALL perform the creation. If creation succeeds, it MUST inject the returned UUID into `ctx.customer_id` and allow the `book()` call to proceed. If creation fails (phone missing, tool error), the existing `NO_CUSTOMER_ID` rejection MUST be returned unchanged.

### Scenario 1.1 — New WhatsApp user, creation succeeds

- GIVEN `ctx.customer_id` is `None`
- AND `state["pending_whatsapp_name"]` = `"María"` and `state["customer_phone"]` is set
- WHEN `_pre_tool_call` runs for a `book()` call
- THEN `_create_customer_if_needed` is awaited and customer is created via `manage_customer`
- AND `ctx.customer_id` is set to the returned UUID
- AND the `book()` call proceeds without rejection

### Scenario 1.2 — Returning customer, customer_id already set

- GIVEN `ctx.customer_id` = `"uuid-123"`
- WHEN `_pre_tool_call` runs for a `book()` call
- THEN `_create_customer_if_needed` is NOT called
- AND `book()` proceeds with `"uuid-123"`

### Scenario 1.3 — New WhatsApp user, no phone available

- GIVEN `ctx.customer_id` is `None`
- AND `state["customer_phone"]` is empty or absent
- WHEN `_pre_tool_call` runs for a `book()` call
- THEN `_create_customer_if_needed` returns `None`
- AND `ToolCallRejection(NO_CUSTOMER_ID)` is returned (existing behavior preserved)
- AND `book()` is NOT called

---

## Requirement 2 — `last_error` field in `BookingContext`

**File**: `agent/modes/booking_context.py`, `agent/modes/booking_mode.py`
**Location**: `BookingContext` dataclass + `_build_response` error path

`BookingContext` MUST expose a `last_error: str | None = None` field (default `None`). When `book()` raises an exception or the tool returns an error result, the calling code MUST set `ctx.last_error = str(e)` before calling `_build_response`. `BookingContext.to_mode_context()` MUST include `last_error` in its output. On the next turn, the LLM MUST receive `last_error` in its context so it can explain what happened.

### Scenario 2.1 — `book()` fails, error preserved across turns

- GIVEN user is at the confirmation step with all slots filled
- WHEN `book()` raises an exception
- THEN `ctx.last_error` is set to the exception string
- AND `_build_response` serializes it into `mode_context["last_error"]`
- AND on the next turn the LLM context contains the error description

### Scenario 2.2 — Successful booking clears `last_error`

- GIVEN a prior turn had `ctx.last_error` set
- WHEN `book()` succeeds on the next attempt
- THEN `ctx.last_error` is `None`
- AND `mode_context["last_error"]` is absent or `None`

---

## Requirement 3 — `error_count` incremented on booking failure

**File**: `agent/modes/booking_mode.py`
**Location**: `_build_response`, after the booking result check

`conversation_flow.py` reads `error_count` for auto-escalation (`>= 3`), but nothing incremented it prior to this fix. When `book()` returns a failure (not `ctx._booking_completed`), `_build_response` MUST add `"error_count": state.get("error_count", 0) + 1` to the returned state update dict. On success it MUST NOT change `error_count`.

### Scenario 3.1 — Booking failure increments error_count

- GIVEN `state["error_count"]` = `1`
- WHEN `book()` fails and `ctx._booking_completed` is `False`
- THEN the returned state update dict contains `"error_count": 2`

### Scenario 3.2 — Three consecutive failures trigger auto-escalation

- GIVEN `state["error_count"]` = `2`
- WHEN a booking failure increments it to `3`
- THEN on the next `router_node` execution `error_count >= 3` is `True`
- AND the conversation transitions to ESCALATION mode

### Scenario 3.3 — Successful booking does not change error_count

- GIVEN `state["error_count"]` = `1`
- WHEN `book()` succeeds (`ctx._booking_completed = True`)
- THEN the returned state update dict does NOT contain `"error_count"`

---

## Requirement 4 — Test suite targets real prompt file paths

**File**: `tests/unit/test_prompt_loader.py`
**Location**: `TestBookingMdNoNamePermission` class (formerly `TestConfirmationMdNoNamePermission`)

The test suite MUST reference the actual prompt file `agent/prompts/modes/booking.md` (not a non-existent `booking/confirmation.md` subdirectory). The test MUST assert that `booking.md` does NOT contain `"Puedes usar el nombre de la clienta"` and MUST assert it contains core booking instructions.

### Scenario 4.1 — booking.md does not grant name-use permission

- GIVEN `agent/prompts/modes/booking.md` is read
- WHEN its content is checked
- THEN it does NOT contain `"Puedes usar el nombre de la clienta"`

### Scenario 4.2 — Redirected test targets the correct file

- GIVEN the test class `TestBookingMdNoNamePermission` is run
- WHEN it executes
- THEN it reads `agent/prompts/modes/booking.md` (not a `booking/` subdirectory)
- AND the test passes without `FileNotFoundError`

---

## Requirement 5 — Integration test coverage for new WhatsApp user booking

**File**: `tests/integration/test_booking_new_user.py`
**Location**: New file

There MUST be integration tests that exercise `BookingMode.handle()` end-to-end with `pending_whatsapp_name` set and `customer_id=None`.

### Scenario 5.1 — End-to-end: new WhatsApp user completes booking

- GIVEN `state["customer_id"]` is `None`
- AND `state["pending_whatsapp_name"]` = `"Lucía"`
- AND `state["customer_phone"]` = `"+34600000001"`
- WHEN `BookingMode.handle()` is called and the LLM invokes `book()`
- THEN `_create_customer_if_needed` silently creates the customer
- AND the booking succeeds without the LLM being required to call `manage_customer` first
- AND the returned state update contains a non-empty `mode_context`

### Scenario 5.2 — End-to-end: new WhatsApp user, no phone → graceful error

- GIVEN `state["customer_id"]` is `None`
- AND `state["pending_whatsapp_name"]` = `"Lucía"`
- AND `state["customer_phone"]` is absent
- WHEN `BookingMode.handle()` is called and the LLM invokes `book()`
- THEN the `book()` call is rejected with `NO_CUSTOMER_ID`
- AND the LLM receives an instruction to call `manage_customer` first
- AND `state["error_count"]` is NOT incremented (rejection, not a failure)

---

## Out of Scope

- Changes to `greeting_mode.py`, `general_mode.py`, or `escalation_mode.py`
- Google Calendar sync or notification logic
- Admin panel or API route changes
- Any prompt content changes beyond the test redirection in Requirement 4
