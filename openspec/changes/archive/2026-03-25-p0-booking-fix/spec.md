# p0-booking-fix — Specification

## Purpose

Fix two P0 blockers that prevent QA from running end-to-end: missing stylist seed data and an uncaught `exists=False` path in `extract_customer_fields`.

---

## Fix 1 — DB Seeding: 5 Canonical Stylists

### Requirement: STYLISTS_DATA must contain all 5 active stylists

`STYLISTS_DATA` in `database/seeds/stylists.py` MUST define exactly 5 stylist entries:

| name   | specialties                    | is_active |
|--------|-------------------------------|-----------|
| Lucía  | corte, color                  | True      |
| Carmen | corte, peinado                | True      |
| Ana    | color, mechas                 | True      |
| Sofía  | peinado, tratamientos         | True      |
| Elena  | corte, mechas, color          | True      |

Each entry MUST include: `name`, `google_calendar_id` (placeholder UUID string), `is_active=True`, `specialties` list.

### Requirement: Seed function MUST be idempotent

The seed function MUST check whether a stylist with the same `name` already exists before inserting. It MUST NOT create duplicate rows on re-run.

#### Scenario: First-time seed

- GIVEN the `stylists` table is empty
- WHEN the seed function is called
- THEN 5 stylist rows are inserted
- AND each row has `is_active=True` and at least one specialty

#### Scenario: Re-run does not duplicate

- GIVEN all 5 stylists already exist in the database
- WHEN the seed function is called again
- THEN no new rows are inserted
- AND the function completes without error

#### Scenario: Partial seed (some stylists present)

- GIVEN 2 of the 5 stylists exist in the database
- WHEN the seed function is called
- THEN only the 3 missing stylists are inserted
- AND the 2 existing rows are unchanged

#### Scenario: QA state_reset calls seed

- GIVEN `state_reset.py` invokes the seed function before a test run
- WHEN the database is empty
- THEN all 5 stylists are available for booking queries
- AND availability tool can return results for each stylist

---

## Fix 2 — extract_customer_fields: Handle exists=False

### Requirement: exists=False path MUST increment failure count

When `manage_customer` returns `{"exists": False, ...}` (no `"error"` key), `extract_customer_fields` MUST increment `manage_customer_failure_count` and MUST NOT attempt to extract `customer_id`.

### Requirement: exists=True path MUST extract customer_id

When `manage_customer` returns `{"exists": True, "customer_id": "...", ...}`, `extract_customer_fields` MUST extract `customer_id` from the result.

### Requirement: error path MUST NOT regress

When `manage_customer` returns `{"error": "..."}`, `extract_customer_fields` MUST increment `manage_customer_failure_count` (existing behavior — unchanged).

#### Scenario: Customer does not exist (exists=False)

- GIVEN `manage_customer` returns `{"exists": False, "phone": "+5491100000000", "message": "..."}`
- WHEN `extract_customer_fields` processes the result
- THEN `manage_customer_failure_count` is incremented by 1
- AND `customer_id` is NOT set in state

#### Scenario: Customer exists (exists=True)

- GIVEN `manage_customer` returns `{"exists": True, "customer_id": "uuid-abc", "name": "Test"}`
- WHEN `extract_customer_fields` processes the result
- THEN `customer_id` is extracted and stored in state
- AND `manage_customer_failure_count` is NOT incremented

#### Scenario: Tool returns error key

- GIVEN `manage_customer` returns `{"error": "DB timeout"}`
- WHEN `extract_customer_fields` processes the result
- THEN `manage_customer_failure_count` is incremented by 1
- AND `customer_id` is NOT set in state

#### Scenario: Existing passing tests do not regress

- GIVEN the existing unit test suite for `extract_customer_fields`
- WHEN the fix is applied
- THEN all previously passing tests continue to pass

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| 1 | `STYLISTS_DATA` defines exactly 5 stylists with the canonical names and specialties |
| 2 | Seed function is idempotent: running twice does not produce duplicate rows |
| 3 | `state_reset.py` leaves 5 stylists in the DB after each QA reset |
| 4 | `extract_customer_fields` increments `failure_count` when `exists=False` |
| 5 | `extract_customer_fields` extracts `customer_id` when `exists=True` |
| 6 | `extract_customer_fields` increments `failure_count` when `error` key is present |
| 7 | All existing unit tests pass after the fix |
