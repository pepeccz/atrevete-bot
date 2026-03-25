# Proposal: p0-booking-fix

**Priority**: P0 — Booking flow completely broken in QA

## Intent

Two independent bugs combine to make end-to-end booking untestable:

1. **QA harness never seeds stylists.** `state_reset.py` cleans DB state before each run but assumes stylists already exist. After a fresh DB or full reset, no stylists are available — booking flows fail immediately with zero candidates.
2. **`extract_customer_fields` silently swallows `exists=False`.** When `manage_customer(action='get')` returns `{"exists": False, ...}` (no `"error"` key), the extractor falls through without incrementing `manage_customer_failure_count`. The circuit breaker never triggers and the agent loops indefinitely re-issuing `get` instead of switching to `create`.

Both must be fixed together: even with stylists present, the customer-lookup loop blocks every new-customer booking.

## Scope

### In Scope

- Add stylist seeding to `state_reset.py` (call `seed_stylists()` during QA reset)
- Handle `exists=False` branch in `extract_customer_fields` — increment failure counter and return early
- Unit test for the `exists=False` path
- Verify existing `STYLISTS_DATA` contains the canonical roster

### Out of Scope

- Changing the canonical stylist list (names, slugs, categories)
- Refactoring `state_reset.py` beyond adding the seed call
- Modifying `manage_customer` tool return shape
- Other QA harness improvements

## Approach

**Blocker 1 — Stylist seeding in QA harness:**
- Import and call `seed_stylists()` from `database/seeds/stylists.py` inside `StateResetHarness.reset_conversation_state()` (or a new `ensure_stylists()` method).
- `seed_stylists()` is already idempotent (upserts by slug) — safe to call on every reset.

**Blocker 2 — `exists=False` handling:**
- Add a guard after the `error` check in `extract_customer_fields`: if `result.get("exists") is False`, increment `ctx.manage_customer_failure_count` and return.
- This lets the circuit breaker gate fire, which transitions the agent to ask for the customer's name and use `action='create'` instead.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `tests/e2e/harness/state_reset.py` | Modified | Add stylist seeding during QA reset |
| `agent/modes/tool_extractors.py` | Modified | Handle `exists=False` in `extract_customer_fields` |
| `tests/unit/test_tool_extractors.py` | Modified | Add test for `exists=False` → failure counter increment |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `seed_stylists()` adds latency to QA reset | Low | Idempotent upsert is fast; 6 rows only |
| Incrementing failure count on `exists=False` changes retry semantics | Low | This is the intended behavior — circuit breaker should fire |

## Rollback Plan

Both changes are additive:
- Blocker 1: Remove the `seed_stylists()` call from `state_reset.py`.
- Blocker 2: Remove the `exists=False` guard block — reverts to silent fall-through.

No migrations, no schema changes, no external API changes.

## Dependencies

- `database/seeds/stylists.py` must contain the canonical roster (already does: Ana, Ana Maria, Marta, Pilar, Rosa, Victor).

## Success Criteria

- [ ] QA harness `reset_conversation_state()` leaves DB with all 6 canonical stylists present
- [ ] `extract_customer_fields({"exists": False, ...})` increments `manage_customer_failure_count`
- [ ] Unit test covers the `exists=False` path and asserts counter increment
- [ ] Full booking QA flow (new customer) completes without infinite loop
