# Delta Spec: fix-booking-confirmation-bug

**Change**: fix-booking-confirmation-bug  
**Status**: Ready for tasks  
**Files affected**: 4

---

## file: `agent/modes/booking_mode.py`

### Change 1: Defensive customer creation in `_handle_completed`

**Location**: `_handle_completed`, line 1280

**Current Behavior**:
- `customer_id = state.get("customer_id") or ""` — defaults to empty string when unset
- `book()` receives empty string → `UUID("")` raises `ValueError` → booking fails

**New Behavior**:
The system MUST check `customer_id` before calling `book()`. If `customer_id` is empty or None, the system MUST call `_create_customer_if_needed()` using the resolved name from `pending_whatsapp_name` or `customer_first_name`. If customer creation also fails (no phone, tool error), the system MUST return an error response and MUST NOT call `book()`.

**Requirements**:
- The system MUST be idempotent: `_create_customer_if_needed()` already short-circuits if `customer_id` exists in state — no change needed there.
- The system MUST preserve all slot data (stylist, service, time) when creation fails.
- The system SHOULD use `pending_whatsapp_name` as primary name fallback, then `customer_first_name`, then `"Cliente"` as last resort.

#### Scenario 1 — New client, name available
- GIVEN `customer_id` is None in state
- AND `pending_whatsapp_name = "María"` is set
- WHEN `_handle_completed` runs
- THEN `_create_customer_if_needed("María")` is called
- AND `customer_id` is set from the result
- AND `book()` is called with the new `customer_id`

#### Scenario 2 — Returning client, `customer_id` already set
- GIVEN `customer_id = "uuid-123"` is set in state
- WHEN `_handle_completed` runs
- THEN `_create_customer_if_needed` is NOT called
- AND `book()` is called with `"uuid-123"` directly

#### Scenario 3 — No phone, customer creation impossible
- GIVEN `customer_id` is None
- AND `customer_phone` is empty
- WHEN `_handle_completed` runs
- THEN `_create_customer_if_needed` returns None
- AND `book()` is NOT called
- AND an error response is returned to the user

---

### Change 2: `mode_context` preservation on booking error

**Location**: `_handle_completed` error block, lines 1317–1326

**Current Behavior**:
- On error, `_finalize_mode_context(mode_context, CONFIRMATION, COMPLETED)` is called
- This resets `booking_step` to `CONFIRMATION` but does NOT carry forward slot data
- On next turn `_determine_step` may regress to an earlier step because data looks incomplete

**New Behavior**:
The system MUST include the full current `mode_context` in the error return dict, merged with a `last_error` field. The system MUST set `booking_step` to `CONFIRMATION` explicitly. The system MUST NOT clear `selected_slot`, `stylist_id`, `service_name`, or `stylist_name`.

#### Scenario 1 — Error at confirmation, user retries
- GIVEN user is at `confirmation` step with all slots filled
- WHEN `book()` fails (e.g., customer creation error)
- THEN `mode_context` in state still contains `selected_slot`, `stylist_id`, `service_name`
- AND `mode_context["booking_step"]` = `"confirmation"`
- AND `mode_context["last_error"]` contains the error description
- AND on next user message, the bot stays at `confirmation` step

#### Scenario 2 — Error with stale context hint
- GIVEN `last_error` is set in `mode_context`
- WHEN `_build_layered_messages` runs for the next turn
- THEN the LLM receives the error context and can explain what happened to the user

---

## file: `agent/modes/base.py`

### Change 3: `error_count` increment on agentic loop failure

**Location**: `_run_agentic_loop`, end of exception handler, line 353–357

**Current Behavior**:
- `_run_agentic_loop` catches exceptions and returns `AgenticLoopResult(error=str(exc))`
- `error_count` in `ConversationState` is never mutated anywhere in the codebase
- The router escalation guard (`error_count >= 3`) never triggers

**New Behavior**:
`AgenticLoopResult` MUST carry a boolean field `increment_error_count` (default `False`). When `_run_agentic_loop` catches a terminal exception (outer `except` block), it MUST set `increment_error_count = True`. Callers (mode nodes) MUST check this field and, if True, add `error_count: state.get("error_count", 0) + 1` to their return dict.

#### Scenario 1 — LLM call fails, error_count increments
- GIVEN the LLM raises an exception inside `_run_agentic_loop`
- WHEN the exception is caught
- THEN `AgenticLoopResult.increment_error_count = True`
- AND the calling mode node adds `error_count + 1` to the state update

#### Scenario 2 — Tool call fails but LLM responds, no increment
- GIVEN a tool call inside the loop raises an exception (inner try/except, line 311–314)
- AND the LLM produces a final response anyway
- WHEN `_run_agentic_loop` returns
- THEN `increment_error_count = False`
- AND `error_count` is NOT changed

#### Scenario 3 — Three consecutive failures trigger escalation
- GIVEN `error_count = 2` in state
- WHEN a booking failure increments to `error_count = 3`
- THEN on next `router_node` run, the escalation guard fires
- AND conversation transitions to ESCALATION mode

---

## file: `agent/prompts/modes/booking/confirmation.md`

### Change 4: Remove name-permission line

**Location**: `confirmation.md`, line 11

**Current Behavior**:
```
- Puedes usar el nombre de la clienta solo si ya existe en el estado.
```
This contradicts `critical_rules.md` Rule #6: "NUNCA uses el nombre del cliente en ninguna respuesta."

**New Behavior**:
The system MUST NOT include any instruction that permits using the client's name in responses. Line 11 MUST be removed. No replacement text is needed.

**Requirements**:
- The file MUST NOT contain any reference to using or displaying `customer_name` or the client's name in responses.
- All other content (summary format, confirmation request, transition rules) MUST remain unchanged.

#### Scenario 1 — Confirmation step renders without name
- GIVEN the LLM is at `confirmation` step
- AND `first_name = "María"` is in `mode_context`
- WHEN the system prompt is assembled
- THEN the `confirmation.md` overlay contains no instruction to use the client's name
- AND the LLM response does NOT include the client's name (e.g., no "¡Genial, María!")

#### Scenario 2 — Existing allowed content preserved
- GIVEN `confirmation.md` is modified
- WHEN it is loaded
- THEN summary format, confirmation request phrasing, and transition rules are intact

---

## file: `agent/prompts/loader.py`

### Change 5: Filter `first_name` from LLM dynamic context

**Location**: `build_step_context()`, lines 309–310

**Current Behavior**:
```python
if mode_context.get("first_name"):
    collected_data.append(f"Nombre para la reserva: {mode_context['first_name']}")
```
The client's name is injected into the dynamic context `SystemMessage`, making it visible to the LLM. The LLM then uses it in responses, violating Rule #6.

**New Behavior**:
The system MUST NOT inject `first_name` (or any name-derived field) into the `build_step_context()` output. The block at lines 309–310 MUST be removed entirely. The comment at lines 265–266 already documents the intent ("Customer name is intentionally NOT injected") — the code MUST match this intent.

**Requirements**:
- `first_name` MUST NOT appear in the dynamic context string.
- All other `mode_context` fields (service, stylist, slot, notes, etc.) MUST continue to be injected as-is.
- No other filtering logic is needed; only the `first_name` block is removed.

#### Scenario 1 — Context built without name
- GIVEN `mode_context["first_name"] = "María"`
- WHEN `build_step_context()` runs
- THEN the returned string does NOT contain `"Nombre para la reserva: María"`
- AND all other collected data fields (service, slot, stylist) are present

#### Scenario 2 — Missing first_name has no effect
- GIVEN `mode_context` does not contain `first_name`
- WHEN `build_step_context()` runs
- THEN the function behaves identically to the current behavior (no change)

#### Scenario 3 — Rule #6 enforced end-to-end
- GIVEN a full booking confirmation flow
- WHEN the LLM generates the confirmation summary
- THEN the response contains service, stylist, date, and time — but NOT the client's name
