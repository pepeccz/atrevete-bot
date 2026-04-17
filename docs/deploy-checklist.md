# Deploy Checklist — Atrévete Bot

This document tracks manual post-deploy steps that cannot be automated as runtime tests.

---

## Measured-Gate: Booking Negation Resolver

**Covers**: R5, S9 (booking-flow-architectural-map change)

After deploying the booking negation resolver (commit C2 of booking-flow-architectural-map),
a human operator OR CI script MUST persist a measured-gate memory to Engram.

This is NOT a runtime test. A passing test suite does NOT satisfy R5 — the memory MUST
be created at deploy time.

### When to Run

Immediately after the first production deploy that includes `shared/negation_phrases.py`
and the pre-loop hook in `agent/modes/booking_mode.py`.

### Step: Persist Measured-Gate Memory

Run the following Python snippet (e.g. via `python3 -c "..."` on the deploy server, or
as a one-off CI job):

```python
# Paste this into a Python REPL or run as a script after deploy.
# Replace {deploy_date} with today's date in YYYY-MM-DD format.

from datetime import date, timedelta

deploy_date = date.today().isoformat()          # e.g. "2026-04-17"
review_date = (date.today() + timedelta(days=14)).isoformat()

# Engram mem_save call (use the MCP engram tool or the engram Python client):
# mem_save(
#     title=f"Measured-gate: booking negation resolver {deploy_date}",
#     type="reminder",
#     scope="project",
#     project="atrevete-bot",
#     topic_key=f"measured-gate/booking-negation-resolver-{deploy_date}",
#     content={
#         "deploy_date": deploy_date,
#         "review_date": review_date,
#         "aggregation_query": (
#             "grep '\"message\":\"booking.negation_resolver\"' agent.log "
#             "| jq -s 'group_by(.matched) | map({matched: .[0].matched, count: length})'"
#         ),
#         "thresholds": {
#             "match_rate_ok": 0.97,
#             "escalate_if": "no_match_rate + user_retry_rate > 0.03",
#         },
#         "escalation_path": "Q1-hybrid Haiku classifier (pre-loop LLM fallback)",
#     }
# )
```

### Log Aggregation Query

After `review_date`, run this on the deploy server to compute match rates:

```bash
docker logs atrevete-agent 2>&1 \
  | grep '"message":"booking.negation_resolver"' \
  | jq -s 'group_by(.matched) | map({matched: .[0].matched, count: length})'
```

For `user_retry_rate`: look for conversations where a second "nada más"-adjacent
utterance appears within 2 turns of a `matched=false` record (indicates the user
had to repeat themselves).

### Decision Thresholds

| Metric | Threshold | Action |
|--------|-----------|--------|
| `match_rate` | ≥ 0.97 | Resolver is permanent — close the gate memory |
| `no_match_rate + user_retry_rate` | > 0.03 | Escalate to Q1-hybrid Haiku classifier |

### Escalation Path

If thresholds are not met: implement `agent/modes/_negation_classifier.py` as a
pre-loop Haiku LLM fallback. Wire into `booking_mode.py` after `is_negation()` returns
`False`. Surface area: 1 new file + 1 call-site change (isolated by design).

---

## Checklist Template

Use this for each deploy that touches the booking flow:

- [ ] `shared/negation_phrases.py` deployed and importable
- [ ] Pre-loop hook active in `agent/modes/booking_mode.py`
- [ ] `booking.negation_resolver` log entries visible in production logs
- [ ] Measured-gate memory persisted to Engram (`measured-gate/booking-negation-resolver-{date}`)
- [ ] Review calendar entry created for `review_date` (+14 days)
