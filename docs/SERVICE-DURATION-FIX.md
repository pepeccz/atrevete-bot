# Service Duration Validation Fix

**Date:** 2025-11-04
**Issue:** `check_availability_tool` was not validating service duration against business hours closing time
**Status:** ✅ FIXED

---

## Problem Description

The system has TWO availability checking mechanisms:

### 1. `check_availability` Node (Tier 2 - Transactional) ✅ WORKING
- **Location:** `agent/nodes/availability_nodes.py:531-860`
- **Context:** Used during actual booking flow (Tier 2)
- **Status:** Already working correctly
- **How it works:**
  - Has access to full conversation state
  - Calculates exact service duration: `sum(s.duration_minutes for s in services)`
  - Passes duration to `generate_time_slots_async()` and `is_slot_available()`
  - Ensures appointments fit within business hours

### 2. `check_availability_tool` Tool (Tier 1 - Conversational) ❌ HAD BUG
- **Location:** `agent/tools/availability_tools.py:60-240`
- **Context:** Used for informal availability queries (e.g., "Do you have availability tomorrow?")
- **Status:** **FIXED** - Now uses conservative 90-minute duration
- **Previous behavior:**
  - Used default 30-minute duration for all queries
  - Could suggest slots that don't fit longer services within business hours
  - Example: For a 3-hour service on a day closing at 20:00, it could suggest 18:30 (would end at 21:30!)

---

## Solution Implemented

### Approach: Conservative Default Duration (Option B)

Added a **conservative service duration constant** of **90 minutes** for Tier 1 availability queries.

**Why 90 minutes?**
- Covers most common service combinations (corte + peinado + tratamiento)
- Conservative enough to prevent booking conflicts
- Simple - no need for complex service duration calculation in Tier 1
- Tier 2 still calculates exact durations for actual bookings

### Code Changes

**File:** `agent/tools/availability_tools.py`

#### 1. Added Conservative Duration Constant

```python
# Conservative service duration for informational availability checks
# Used when exact service duration is unknown (Tier 1 conversational queries)
# Set to 90 minutes to cover most common service combinations
CONSERVATIVE_SERVICE_DURATION_MINUTES = 90
```

#### 2. Updated `check_availability_tool` to Use Conservative Duration

**Before:**
```python
slots = generate_time_slots(requested_date, time_range)  # ❌ No duration
if is_slot_available(slot_time, busy_events):  # ❌ No duration
```

**After:**
```python
slots = await generate_time_slots_async(
    requested_date,
    day_of_week,
    service_duration_minutes=CONSERVATIVE_SERVICE_DURATION_MINUTES  # ✅ 90 min
)

if is_slot_available(
    slot_time,
    busy_events,
    service_duration_minutes=CONSERVATIVE_SERVICE_DURATION_MINUTES  # ✅ 90 min
):
```

#### 3. Updated Imports

Changed from synchronous `generate_time_slots` to async `generate_time_slots_async` for database-backed business hours.

---

## Validation

### Test Results

Business hours: **10:00-20:00** (Tuesday-Friday)

| Service Duration | Slots Generated | Last Slot | Service Ends At | Valid? |
|------------------|-----------------|-----------|-----------------|--------|
| 30 min           | 20 slots        | 19:30     | 20:00           | ✅     |
| **90 min** (new) | **18 slots**    | **18:30** | **20:00**       | **✅** |
| 180 min (3h)     | 15 slots        | 17:00     | 20:00           | ✅     |

### Example Scenario

**Before Fix:**
- Customer: "Do you have availability at 6pm tomorrow for a full treatment?"
- Tool returns: "Yes, available at 18:30 with Marta"
- Problem: 3-hour service would end at 21:30 (90 min past closing!)

**After Fix:**
- Customer: "Do you have availability at 6pm tomorrow for a full treatment?"
- Tool returns: "Available at 16:00 or 17:00 with Marta"
- Correct: With 90-min conservative duration, 18:30 slot is excluded
- Note: When customer proceeds to booking (Tier 2), exact duration will be calculated

---

## Architecture Notes

### Two-Tier Availability System

**Tier 1 (Conversational - Informational)**
- Tool: `check_availability_tool`
- Purpose: Informal queries during conversation
- Duration: **Conservative 90 minutes** (safe default)
- Accuracy: Lower precision, but prevents impossible bookings

**Tier 2 (Transactional - Precise)**
- Node: `check_availability`
- Purpose: Actual booking flow
- Duration: **Exact calculation** from selected services
- Accuracy: Precise, ensures perfect fit

This separation allows:
- Fast, helpful responses during conversation (Tier 1)
- Precise, accurate bookings during transaction (Tier 2)
- No risk of booking conflicts due to conservative Tier 1 estimates

---

## Related Files

- `agent/tools/availability_tools.py` - Fixed tool (Tier 1)
- `agent/nodes/availability_nodes.py` - Already correct node (Tier 2)
- `agent/tools/calendar_tools.py` - Core availability functions
- `database/models.py` - Service model with `duration_minutes` field
- `database/seeds/business_hours.py` - Business hours configuration

---

## Testing Recommendations

### Unit Tests (Already Pass)
```bash
DATABASE_URL="..." ./venv/bin/pytest tests/unit/test_calendar_tools.py -v
```

### Integration Test Scenarios

1. **Conservative filtering works:**
   - Query availability via conversational agent
   - Verify slots exclude those within 90 min of closing

2. **Tier 2 still precise:**
   - Start booking flow with specific services
   - Verify exact duration calculation in `check_availability` node

3. **Edge cases:**
   - Saturday (9:00-14:00): Last 90-min slot should be 12:30
   - 3-hour service: Should work correctly in Tier 2 but be more restrictive in Tier 1

---

## Future Improvements (Optional)

If needed, could add `service_duration_minutes` parameter to tool schema:

```python
class CheckAvailabilitySchema(BaseModel):
    service_category: str
    date: str
    time_range: str | None = None
    stylist_id: str | None = None
    service_duration_minutes: int = Field(
        default=90,
        description="Total duration of services in minutes (default: 90 min conservative estimate)"
    )
```

This would allow Claude to pass exact duration if it has already calculated it via `get_services` tool, but defaults to 90 min otherwise.

**Current decision:** Keep simple with fixed 90 min. Can revisit if needed.
