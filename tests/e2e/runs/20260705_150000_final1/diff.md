| Scenario | Base outcome | Head outcome | Δ bugs | Δ tools | Δ DB | Verdict |
|----------|-------------|-------------|--------|---------|------|---------|
| change-a-closed-and-underadvance | missing | escalated | +3 | 0 | = | REGRESSED |
| change-a-customer-phone-injected | booked | booked | +1 | 0 | customer_count_delta=1, appt_count_delta=1 | DEGRADED |
| change-a-idor-cancel-other | rejected | escalated | 0 | 0 | = | REGRESSED |
| change-a-min-days-from-settings | rejected | rejected | 0 | 0 | = | OK |
| change-a-policy-gate-blocks-book | policy_accepted | policy_accepted | 0 | 0 | = | OK |
| change-a-pre-book-recheck | booked | booked | +2 | 0 | customer_count_delta=1, appt_count_delta=1 | DEGRADED |
| change-a-tz-madrid | booked | booked | +3 | 0 | customer_count_delta=1, appt_count_delta=1 | DEGRADED |
| change-b-cache-warm-second-turn | booked | booked | +2 | 0 | customer_count_delta=1, appt_count_delta=1 | DEGRADED |
| change-b-catalog-loaded | info_provided | info_provided | 0 | 0 | = | OK |
| change-b-rules-pruned | info_provided | info_provided | 0 | 0 | = | OK |
| change-c-cancel-flow | cancelled | cancelled | 0 | 0 | customer_count_delta=1, appt_count_delta=1 | OK |
| change-c-gcal-synced-status | booked | booked | +1 | 0 | customer_count_delta=1, appt_count_delta=1 | DEGRADED |
| change-c-ownership-check-reschedule | rejected | rejected | 0 | 0 | = | OK |
| change-c-policy-acceptance-stored | booked | booked | 0 | 0 | customer_count_delta=1, appt_count_delta=1 | OK |
| change-c-reschedule-flow | rescheduled | rescheduled | 0 | 0 | customer_count_delta=1, appt_count_delta=1 | OK |
| change-d-returning-customer-personalization | booked | booked | 0 | 0 | appt_count_delta=1 | OK |
