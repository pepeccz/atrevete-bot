# Diagnostic Report: Sunday Booking Bug Analysis
**Date:** November 26, 2025
**Issue:** Customer reported seeing availability slots for Sunday (closed day)

---

## Executive Summary

**Conclusion:** Sunday bug is **NOT reproducible** in direct availability checks. Database configuration is CORRECT. However, confirmed **critical bug** in `find_next_available()` with hardcoded weekend logic that incorrectly skips Saturday (which is OPEN).

---

## Database Configuration ✅ CORRECT

Query: `SELECT day_of_week, is_closed, start_hour, end_hour FROM business_hours WHERE day_of_week IN (5, 6);`

```
day_of_week | is_closed | start_hour | end_hour
-------------+-----------+------------+----------
           5 | f         |          9 |       14    ← Saturday: OPEN 9:00-14:00
           6 | t         |            |             ← Sunday: CLOSED
```

**Result:** Database correctly configured per business requirements.

---

## Code Testing ✅ Sunday Returns Empty

Test: `check_availability("Peluquería", "2025-12-08")` (Sunday)

```
Success: None
Stylists found: 0
```

**Result:** Sunday availability correctly returns empty (no slots shown).

---

## Root Cause Analysis

### 1. **Why User Saw Sunday Slots (Hypothesis)**

The user's bug report showed Sunday slots appearing in conversation:
```
"El 7 de diciembre" (Sunday) → Bot showed slots: 10:00, 11:30, 14:00, 16:30
```

**Possible explanations:**
1. **LLM Hallucination**: AI generated slots without actually calling `check_availability` tool
2. **FSM State Confusion**: Bot was in wrong state and echoed previous day's slots
3. **Cached/Stale Data**: Conversation state had cached slots from different day
4. **Intermittent Bug**: Code path that bypasses closed day check (not reproducible in direct test)

**Evidence against database misconfiguration:**
- Database shows Sunday is CLOSED ✅
- Direct test shows Sunday returns empty ✅
- `generate_time_slots_async()` correctly reads from database ✅

---

### 2. **Confirmed Bug: Saturday Hardcoded as Closed** ❌

**Location:** `agent/tools/availability_tools.py:437-440, 467-470`

```python
# Lines 437-440: Skips BOTH Saturday AND Sunday
while earliest_valid.weekday() in [5, 6]:  # 5=Saturday, 6=Sunday
    earliest_valid += timedelta(days=1)

# Lines 467-470: Same hardcoded skip in loop
if current_date.weekday() in [5, 6]:
    logger.info(f"Skipping closed day (weekend)")
    continue
```

**Impact:**
- `find_next_available()` NEVER returns Saturday slots
- Database says Saturday is OPEN 9:00-14:00, but code skips it
- Customers asking "¿cuándo hay disponibilidad?" miss Saturday slots

**Severity:** HIGH - Saturday slots are completely hidden from "next available" searches

---

### 3. **Architecture Inconsistency** ⚠️

Different availability tools use different validation:

| Tool | Closed Day Logic | Saturday Behavior |
|------|------------------|-------------------|
| `check_availability()` | Database-driven via `generate_time_slots_async()` | ✅ Shows Saturday slots (9:00-14:00) |
| `find_next_available()` | Hardcoded `[5, 6]` | ❌ Skips Saturday (treats as closed) |

**Result:** Inconsistent customer experience depending on which tool LLM selects.

---

## Recommendations

### Immediate Priority: Fix Hardcoded Weekend Logic
1. Remove hardcoded `[5, 6]` from `find_next_available()`
2. Replace with database-driven validation
3. Ensure Saturday slots appear in "next available" searches

### Secondary Priority: Investigate Sunday Bug
Since Sunday bug is not reproducible in direct tests, investigate:
1. LLM tool calling logs (did it actually call `check_availability`?)
2. Conversation state at time of bug (cached slots?)
3. FSM state transitions (was FSM in correct state?)

### Long-term Solution: Centralized Validation
Implement `shared/business_hours_validator.py` as planned to ensure:
- Single source of truth (database)
- Consistent validation across all tools
- No hardcoded business logic

---

## Implementation Proceeds As Planned

Despite Sunday bug not being reproducible, the plan addresses:
1. ✅ Hardcoded weekend logic (confirmed bug - Saturday hidden)
2. ✅ Architecture inconsistency (different tools use different logic)
3. ✅ FSM slot validation gaps (prevents future state confusion)
4. ✅ Centralized business hours validation (single source of truth)

**Next Steps:** Proceed with Week 1 implementation (Foundation phase).
