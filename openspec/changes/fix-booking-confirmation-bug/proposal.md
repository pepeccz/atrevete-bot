# Proposal: Fix Booking Confirmation Bug

## Intent

100% of new WhatsApp clients cannot complete a booking. The booking flow fails at confirmation
because `customer_id` is never created when the agent skips the `customer_name` FSM step
(which happens whenever `pending_whatsapp_name` is already in state). Secondary bugs compound
the failure: escalation never triggers (broken `error_count`), users regress to earlier steps
on errors, and the agent violates its own critical rule by mentioning client names aloud.

**Business impact**: Zero successful bookings for first-time clients until this is fixed.

## Scope

### In Scope
- Defensive customer creation in `_handle_completed` (primary fix for null `customer_id`)
- `error_count` increment on booking failures (enables auto-escalation at threshold 3)
- `mode_context` preservation on errors (prevents step regression)
- Remove name-permission line from `confirmation.md` (resolves Rule #6 contradiction)
- Filter `customer_name` from LLM context in `loader.py`

### Out of Scope
- Refactoring the `GreetingMode` customer creation path
- Changes to `booking_tools.py` validation logic
- Admin panel or API changes
- Performance optimizations
- Any new booking features

## Approach

**Primary fix — defensive customer creation in `_handle_completed`:**
At the moment of booking, if `customer_id` is missing, create the customer inline using
`pending_whatsapp_name` or `customer_first_name` as fallback. This is the safest single point
of enforcement regardless of which FSM path led here.

**Error tracking — increment in node, not in `_run_agentic_loop`:**
After any booking failure in `_handle_completed`, add `error_count + 1` to the state updates.
The existing `router_node` escalation guard already checks this value — it just never gets set.

**Step regression — preserve `mode_context` on error:**
Instead of returning bare `CONFIRMATION` state on failure, merge the current `mode_context`
into the error updates. The LLM can retry confirmation with full context intact.

**Prompt contradiction — two-line fix:**
Remove the offending permission line from `confirmation.md` and filter `customer_name` out of
the context dict before it reaches the LLM in `loader.py`.

## Affected Areas

| File | Impact | Description |
|------|--------|-------------|
| `agent/modes/booking_mode.py` | Modified | Defensive `customer_id` creation in `_handle_completed`; preserve `mode_context` on error |
| `agent/modes/base.py` | Modified | Increment `error_count` on agentic loop failures |
| `agent/prompts/modes/booking/confirmation.md` | Modified | Remove line permitting customer name usage |
| `agent/prompts/loader.py` | Modified | Filter `customer_name` from mode_context before LLM injection |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Duplicate customer creation (created in GREETING + again in `_handle_completed`) | Low | `_create_customer_if_needed` already checks if customer exists via phone lookup |
| `customer_name` filter breaks legitimate context fields | Low | Only `customer_name` key is filtered; all other keys pass through |
| `error_count` increment triggers false escalation on transient errors | Low | Threshold is 3; transient errors are rare; escalation is recoverable |
| Step preservation keeps stale slot data after a real conflict error | Med | `last_error` field in `mode_context` lets LLM explain what happened |

## Rollback Plan

All changes are isolated to 4 files with no schema migrations required.

1. `git revert <commit>` rolls back all 4 files atomically
2. No database changes — no data rollback needed
3. Redis checkpoint keys are conversation-scoped — existing sessions auto-expire

## Dependencies

- None. All fixes are self-contained within the agent layer.
- Existing `_create_customer_if_needed()` method is reused as-is.

## Success Criteria

- [ ] A new WhatsApp client can complete a booking end-to-end without errors
- [ ] `customer_id` is never empty string or None when `book()` is called
- [ ] After 3 consecutive failures, conversation escalates to human agent
- [ ] A user who hits an error at `confirmation` stays at `confirmation` on next turn
- [ ] Agent responses in confirmation step contain no client name references
- [ ] All existing unit tests pass (no regressions)
