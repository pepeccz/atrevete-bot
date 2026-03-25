# Design: p0-booking-fix — Two P0 Blockers

## Technical Approach

Two independent fixes targeting booking flow reliability. Fix 1 ensures the DB has all 6 salon stylists seeded correctly. Fix 2 ensures `extract_customer_fields()` increments the circuit-breaker counter on "customer not found" responses so the agent switches from `action='get'` to `action='create'` instead of looping.

**Current state after codebase investigation**: Both fixes are ALREADY implemented in the codebase.

## Architecture Decisions

### Decision: Slug-based idempotent seeding (Fix 1)

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Match by `name` | Names can change, collisions with common names | ❌ Rejected |
| Match by `slug` (URL-safe stable ID) | Requires slug column; names can be updated independently | ✅ Chosen |
| Match by UUID | UUIDs are random, can't be known at seed time | ❌ Rejected |

**Rationale**: `slug` is a unique indexed column on `Stylist`. It provides a human-readable stable identity key that survives name changes. The seed function reconciles (upsert) on slug: updates `name`/`category`/`is_active` if the row exists, creates if not. `google_calendar_id` is intentionally left untouched — it's assigned via admin panel OAuth flow.

### Decision: Check `exists == False` before `error` (Fix 2)

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Check `exists is False` after error check | "Not found" has no `error` key, works but semantically wrong ordering | ❌ Current proposal |
| Check `exists is False` before error check | Explicit early return, clear precedence | ✅ Implemented |
| Merge into error check (`if error or not exists`) | Loses distinction between server error vs not-found | ❌ Rejected |

**Rationale**: `manage_customer(action='get')` returns `{"exists": False, ...}` when the phone isn't found. This is NOT an error — it's a valid response that means "customer doesn't exist yet." Without incrementing `manage_customer_failure_count`, the circuit breaker never fires and the agent can loop indefinitely re-issuing `action='get'`.

## Data Flow

### Fix 1: Seed Reconciliation

```
STYLISTS_DATA (6 entries)
    │
    ▼ for each entry
┌──────────────────────────┐
│ SELECT * FROM stylists   │
│ WHERE slug = :slug       │
└──────────┬───────────────┘
           │
     ┌─────┴─────┐
     │ exists?   │
     ├─── yes ───┤──→ UPDATE name, category, is_active
     └─── no  ───┘──→ INSERT new row (google_calendar_id=None)
```

### Fix 2: extract_customer_fields Decision Tree

```
extract_customer_fields(result, ctx)
    │
    ├─ result has "error"?
    │   └─ yes → failure_count++ → return (error path)
    │
    ├─ result["exists"] is False?
    │   └─ yes → failure_count++ → return (not-found path)
    │
    └─ extract id, first_name → reset counters → return (success path)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `database/seeds/stylists.py` | **Already done** | 6 stylists (Ana, Ana Maria, Marta, Pilar, Rosa, Victor) with slug-based upsert |
| `agent/modes/tool_extractors.py` | **Already done** | `exists is False` check at line 619, before success extraction |

## Interfaces / Contracts

### Seed data shape (existing)

```python
{
    "name": str,           # Display name
    "slug": str,           # Stable identity key (unique)
    "category": ServiceCategory,  # HAIRDRESSING | AESTHETICS
    "is_active": bool,     # Active in booking system
    # google_calendar_id intentionally absent — set via admin OAuth
}
```

### extract_customer_fields contract (existing)

```python
def extract_customer_fields(result: dict, ctx: BookingContext) -> None:
    # Mutates ctx in-place. Three paths:
    # 1. error  → failure_count++
    # 2. exists=False → failure_count++
    # 3. success → set customer_id, customer_name, reset counters
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `extract_customer_fields` with `exists=False` | `test_customer_not_found` in `tests/unit/test_tool_extractors.py` — **exists** (line 671) |
| Unit | Seed data completeness | Verify `STYLISTS_DATA` has 6 entries with correct slugs |
| Unit | Failure counter increment on not-found | Assert `ctx.manage_customer_failure_count == 1` after not-found |
| Integration | Seed idempotency | Run `seed_stylists()` twice, verify no duplicates |

## Migration / Rollout

No migration required. Seed script is idempotent — safe to re-run. The `extract_customer_fields` fix is a pure function change with no schema impact.

## Open Questions

- [x] ~~Are all 6 stylists seeded?~~ → Yes, verified in `database/seeds/stylists.py`
- [x] ~~Is the `exists=False` check implemented?~~ → Yes, verified at `tool_extractors.py:619-626`
- [ ] The task description mentions 5 new stylists with placeholder UUID `google_calendar_id` values — the actual implementation correctly leaves `google_calendar_id=None` (assigned via admin OAuth). The task description appears outdated.
