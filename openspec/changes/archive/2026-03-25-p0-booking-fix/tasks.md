# Tasks: p0-booking-fix — Two P0 Blockers

## Phase 1: Fix 1 — DB Seeding (database/seeds/stylists.py)

- [ ] T1: Read `database/seeds/stylists.py` — understand `STYLISTS_DATA` dict schema and `run_seed()` signature. **XS**
- [ ] T2: Add 5 stylist dicts (Lucía, Carmen, Ana, Sofía, Elena) to `STYLISTS_DATA` with fields: `name`, `google_calendar_id` (placeholder UUID string), `is_active=True`, `specialties` (list). **S**
- [ ] T3: Make `run_seed()` idempotent — add `SELECT` by `name` before `INSERT`; skip if row exists. File: `database/seeds/stylists.py`. **S**
- [ ] T4: Verify `database/seeds/state_reset.py` calls `run_seed()` (or equivalent) — confirm call exists and is correct; add call if missing. **XS**

## Phase 2: Fix 2 — extract_customer_fields (agent/tools/tool_extractors.py)

- [ ] T5: Read `extract_customer_fields()` (~lines 605–613) in `agent/tools/tool_extractors.py` — map current branch logic. **XS**
- [ ] T6: Add `exists == False` branch **before** the error check in `extract_customer_fields()`: increment `failure_count`, do NOT set `customer_id`. **S**

## Phase 3: Testing

- [ ] T7: Write unit test in `tests/unit/` — call seed twice, assert stylist count stays at 6 (idempotent). Depends on T3. **S**
- [ ] T8: Write unit test — `manage_customer` returns `{exists: False, phone: "..."}` → `failure_count` increments by 1, `customer_id` NOT set. Depends on T6. **S**
- [ ] T9: Write unit test — `manage_customer` returns `{exists: True, customer_id: "uuid"}` → `customer_id` IS set, `failure_count` NOT incremented. Depends on T6. **S**

## Phase 4: Verification

- [ ] T10: Run `pytest tests/unit/` — all tests must pass. Depends on T7, T8, T9. **XS**
- [ ] T11: Run QA harness DB reset and confirm 5+ stylists present in DB. Depends on T3, T4. **XS**

---

**Total tasks**: 11  
**Complexity**: XS = read/verify only, S = focused implementation, no M/L tasks  
**Critical path**: T1 → T2 → T3 → T4 → T7 → T10 | T5 → T6 → T8 → T9 → T10
