# Tasks: Fix Booking Confirmation Bug

## Phase 1: Prompt Fixes (no logic deps)

- [ ] 1.1 `agent/prompts/modes/booking/confirmation.md` — Remove line 11: `- Puedes usar el nombre de la clienta solo si ya existe en el estado.`
- [ ] 1.2 `agent/prompts/loader.py` — Remove lines 309-310 that inject `first_name` into `build_step_context()` collected data

## Phase 2: Core Logic — booking_mode.py

- [ ] 2.1 `agent/modes/booking_mode.py` — After `customer_id = state.get("customer_id") or ""` (line ~1280), add defensive guard: resolve name from `first_name → pending_whatsapp_name → customer_first_name → "Cliente"`, call `_create_customer_if_needed`, set `customer_id` and `updates["customer_id"]` if resolved
- [ ] 2.2 `agent/modes/booking_mode.py` — In `_handle_completed` error branch (lines ~1317-1326): replace `_finalize_mode_context(...)` call with inline dict `{**mode_context, "booking_step": CONFIRMATION.value, "last_error": error_text}`
- [ ] 2.3 `agent/modes/booking_mode.py` — In same error return dict: add `"error_count": state.get("error_count", 0) + 1`

## Phase 3: Unit Tests

- [ ] 3.1 `tests/unit/test_booking_mode.py` — Test Scenario: `customer_id=None`, `pending_whatsapp_name="María"` → `_create_customer_if_needed` called, `book()` called with returned UUID
- [ ] 3.2 `tests/unit/test_booking_mode.py` — Test Scenario: `customer_id="uuid-123"` already set → `_create_customer_if_needed` NOT called, `book()` called directly with `"uuid-123"`
- [ ] 3.3 `tests/unit/test_booking_mode.py` — Test Scenario: `customer_id=None`, `customer_phone=""` → `_create_customer_if_needed` returns None, `book()` NOT called, error response returned
- [ ] 3.4 `tests/unit/test_booking_mode.py` — Test: booking failure increments `error_count` → assert `state_update["error_count"] == prev + 1`
- [ ] 3.5 `tests/unit/test_booking_mode.py` — Test: booking failure preserves `mode_context` → assert `mode_context["booking_step"] == "confirmation"`, `mode_context["selected_slot"]` intact, `mode_context["last_error"]` set
- [ ] 3.6 `tests/unit/test_loader.py` — Test: `build_step_context()` with `mode_context["first_name"]="María"` → returned string does NOT contain `"Nombre para la reserva: María"`
- [ ] 3.7 `tests/unit/test_prompts.py` (or grep check) — Assert `confirmation.md` does not contain `"Puedes usar el nombre de la clienta"`

## Phase 4: Integration Test

- [ ] 4.1 `tests/integration/test_booking_flow.py` — E2E: new WhatsApp user (no `customer_id` in state, `pending_whatsapp_name` set) completes full booking → assert `appointment_created=True` in final state and no `ValueError` raised
