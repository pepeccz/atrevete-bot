# Proposal: Stylist Selection State Resolution Bug

## Intent

The booking FSM is stuck 100% of the time at `stylist_selection` when the user picks "any stylist", "first available", or "no preference". The LLM answers verbally as if the selection was made, but `_advance_step()` waits for `mode_context["stylist_id"]` which is never set — because `_handle_stylist_selection()` has no Python-side resolver. Every flexible-stylist booking fails silently at confirmation. Additionally, the `GreetingMode` name-leak filter misses partial-name leaks (e.g. `"Hola, María"` passes when stored value is `"María García"`).

## Scope

### In Scope
- Add deterministic resolver in `_handle_stylist_selection()` for: `cualquiera`, `sin preferencia`, `primer horario`, numeric choice (1, 2, 3…), and stylist name match
- Preserve structured `soonest_any_slot` payload (stylist_id + slot) in `_prefetch_stylist_options()` alongside display string
- Strengthen `GreetingMode` name-leak filter from exact full-string to partial-name / token match

### Out of Scope
- New LangChain tools (no "select stylist" tool)
- New schema fields in BookingState
- FSM structural refactor
- Slot pre-locking at stylist-selection step (slot choice stays in `slot_selection`)

## Approach

1. **`_prefetch_stylist_options()` (line 475)** — store `soonest_any_slot` as structured dict `{stylist_id, stylist_name, slot_start, slot_end}`, keep display string alongside
2. **`_handle_stylist_selection()` (line 1006)** — before calling LLM: parse user reply for "no preference" intent or numeric/name pick; resolve to `stylist_id` + `stylist_name`; write into `mode_context`; then call `_advance_step()`
3. **`_resolve_stylist_selection()` (new helper)** — extract resolution logic into a pure function for clarity and testability
4. **`greeting_mode.py:189`** — change leak filter to check each token of the stored name individually (first name / last name substring)

## Affected Areas

| File | Lines | Change |
|------|-------|--------|
| `agent/modes/booking_mode.py` | 475 | Store structured `soonest_any_slot` dict |
| `agent/modes/booking_mode.py` | 1006 | Add pre-LLM stylist resolution |
| `agent/modes/booking_mode.py` | 1461 | No change needed once 1006 is fixed |
| `agent/modes/booking_mode.py` | new | Add `_resolve_stylist_selection()` helper |
| `agent/modes/greeting_mode.py` | 189 | Token-based partial-name leak filter |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Resolution heuristics miss edge-case phrasing | Med | Cover: `cualquier`, `no importa`, `el que sea`, ordinals; log unresolved cases |
| Structured prefetch changes break display rendering | Low | Keep display string field unchanged; add new `soonest_any_slot_data` key |
| Name-filter over-triggers on common words | Low | Only check name tokens ≥ 4 chars; case-normalize |

## Rollback Plan

All changes are in two files. Revert `agent/modes/booking_mode.py` and `agent/modes/greeting_mode.py` to HEAD. No DB schema changes, no migration needed.

## Dependencies

- None. Fully self-contained in agent layer.

## Success Criteria

- [ ] User replies `cualquiera` → `stylist_id` is set in `mode_context` before LLM call
- [ ] User replies with stylist name or number → correct `stylist_id` resolved
- [ ] `_advance_step()` moves to `slot_selection` without being stuck
- [ ] `soonest_any_slot` preserves structured data (stylist_id, slot_start)
- [ ] `"Hola, María"` is blocked when stored name is `"María García"`
- [ ] No regression on single-stylist or explicit-stylist-name bookings
