# Hallucination Tolerance Architecture

**Change J: hallucination-tolerant-architecture-bundle**

## Core Principles

### (a) Every external-effecting tool validates args before mutation

Every tool that executes an INSERT or UPDATE against the database MUST validate all
foreign-key arguments against the source-of-truth before any write occurs. "Validation"
means an actual DB read — not a type-check, not a format check, not a prompt rule.

If any FK argument is invalid (service_id not in `services`, stylist_id not in `stylists`,
appointment_id not in `appointments`, or appointment owned by a different customer), the
tool MUST return a structured error and perform no mutation.

This is implemented via `agent/tools/_booking_validators.py` (Change I baseline, extended
by Change J).

### (b) Every response slot referencing catalog/memory/appointments is groundable post-hoc

The LLM is statistically likely to hallucinate service names, stylist names, or preferences
when they are absent from the injected context slots. The architecture defends against this
by scanning every assistant reply for tokens that appear to reference the catalog but are
not present in the current `<catalog>` slot.

Post-hoc groundedness scanning (Change J, `ResponseGroundednessMiddleware`) runs after
every LLM turn in LOG-ONLY mode. This provides an evidence baseline before any hard-block
is introduced.

---

## (c) Defended Surfaces Inventory

| Tool | Validator(s) | Guard type |
|------|-------------|-----------|
| `book` | `validate_service_ids_exist` | FK: service_ids in services table |
| `book` | `validate_stylist_id_exists` | FK: stylist_id in stylists table |
| `book` | `validate_slot_in_offered` | State-binding: start_iso must be in recently_offered_slots |
| `book` | `check_slot_availability` (DB) | Availability: slot still free at commit time |
| `update_booking` | `validate_service_ids_exist` | FK: service_ids in services table |
| `update_booking` | `validate_stylist_id_exists` | FK: stylist_id in stylists table |
| `update_booking` | `validate_slot_in_offered` | State-binding: slot_iso must be in recently_offered_slots |
| `update_booking` | `validate_booking_date` | Business rules: date legality (G1/G2/G3) |
| `manage_appointments` | `validate_appointment_belongs_to_customer` | IDOR: appointment owned by resolved customer |
| Response (all tools) | `ResponseGroundednessMiddleware` | Post-hoc: catalog token scan + price regex |

---

## (d) Future Tool Author Checklist

When adding a new tool that accepts arguments from the LLM and executes side effects,
follow this checklist before merging:

- [ ] **FK validation before mutation**: every UUID argument (service_id, stylist_id,
      appointment_id, etc.) must be validated against the DB with a SELECT before any
      INSERT/UPDATE. Use `validate_service_ids_exist`, `validate_stylist_id_exists`, or
      add a new validator following the `FKValidationResult` pattern in
      `agent/tools/_booking_validators.py`.

- [ ] **IDOR check when appointment_id is accepted**: if the tool accepts an
      `appointment_id` argument, call `validate_appointment_belongs_to_customer(session,
      appt_id, state.customer_id)` before any mutation. Return a generic "not found"
      error (no cross-customer data leak). Log WARNING when a mismatch is detected.

- [ ] **Slot-set validation when start_time is accepted**: if the tool accepts a
      `start_time` or `start_iso` argument for scheduling, call `validate_slot_in_offered(
      start_iso, stylist_id, state.recently_offered_slots)` before any DB write. On
      failure, return a structured error with `next_step=reoffer_slots` and instruct the
      LLM to re-call `check_availability` or `get_next_available_options`.

- [ ] **Server-side stamping for any audit timestamp**: timestamps that carry legal or
      audit significance (e.g., `policy_accepted_at`, `consent_at`) MUST be stamped by
      the server using `datetime.now(UTC)`. The LLM MUST NOT supply, influence, or
      override these values. Narrow the tool schema to accept a `bool` flag; the server
      stamps the timestamp internally.

- [ ] **Post-hoc groundedness logging for response content**: if the tool injects catalog
      tokens into the assistant reply or modifies the response content, ensure those
      tokens are either sourced from `<catalog>` (injected by `DynamicPromptMiddleware`)
      or explicitly logged via `ResponseGroundednessMiddleware`. No new bypass paths.

---

## Related files

- `agent/tools/_booking_validators.py` — validator SSOT
- `agent/middleware/response_groundedness.py` — post-hoc scan (Change J)
- `agent/middleware/availability_context.py` — produces `recently_offered_slots`
- `agent/state.py` — `recently_offered_slots` field
- `agent/prompts/shared/critical_rules.md` — R-40, R-41 (prompt-side complement)
