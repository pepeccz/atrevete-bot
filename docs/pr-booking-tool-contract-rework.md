# PR: booking-tool-contract-rework

> **Delete this file after merge.**

## Summary

- Introduces `update_booking` (slot collector), a closed `NextStep` vocabulary, and richer `ToolResponse` (adds `collected`, `missing` fields) to replace the brittle multi-step booking prompt logic.
- Hardened `check_availability` (advance-policy guard, stylist/date pre-conditions) and `book` (confirmation gate, incomplete-slot guard) return structured `next_step` values the LLM narrates directly.
- Rewrote `booking_flow.md` to 6 content lines (tool-driven narration), removed hardcoded advance-policy from `catalog_builder.py`, and added VCR infra + 5 canonical scenario tests (skipped pending cassette recording on server).

---

## R-IDs Satisfied

| ID | Requirement | Status |
|----|-------------|--------|
| R1 | `ToolResponse` has `collected` and `missing` fields | ✅ |
| R2 | `update_booking` slot-collector matrix | ✅ |
| R3 | `update_booking` audience disambiguation | ✅ |
| R4 | `check_availability` advance-policy guard | ✅ |
| R5 | `check_availability` date pre-condition guard | ✅ |
| R6 | `check_availability` stylist pre-condition guard | ✅ |
| R7 | `book` confirmation gate (`confirmed` parameter) | ✅ |
| R8 | `book` incomplete-slot guard | ✅ |
| R9 | `NextStep` 12-value closed Literal | ✅ |
| R10 | No imperative verb in `NextStep` values | ✅ |
| R11 | `booking_flow.md` ≤10 lines, no numbered steps | ✅ |
| R12 | VCR infra (`pytest-recording`, `conftest.py`, cassette dir) | ✅ |
| R13 | 5 canonical VCR scenarios written | ✅ (skipped — cassettes pending) |
| R14 | No hardcoded advance policy in `catalog_builder.py` | ✅ |
| R15 | No `USE_CAPABILITY_BOOKING` feature flags in `agent/` | ✅ |
| R16 | `AgentState` shape unchanged (snapshot test) | ✅ |
| R17 | Middleware stack unchanged (snapshot test) | ✅ |
| R18 | Black + ruff clean; mypy no new errors; docs updated | ✅ |
| R19 | Inline comment per `NextStep` value in source + lint test | ✅ |

---

## Files Added

| Path | Purpose |
|------|---------|
| `agent/tools/next_steps.py` | `NextStep` Literal + `NEXT_STEP_PAYLOAD_CONTRACT` |
| `agent/tools/update_booking.py` | Slot-collector tool |
| `agent/tools/_booking_helpers.py` | `_resolve_audience_variants`, `_resolve_stylist`, `_compute_first_valid_date`, `_resolve_service_ids` |
| `tests/unit/tools/test_tool_response_schema.py` | R1 |
| `tests/unit/tools/test_next_steps_vocabulary.py` | R9, R10, R19 |
| `tests/unit/tools/test_update_booking.py` | R2 |
| `tests/unit/tools/test_update_booking_audience.py` | R3 |
| `tests/unit/tools/test_check_availability.py` | R4–R6 |
| `tests/unit/tools/test_book.py` | R7, R8 |
| `tests/unit/test_no_feature_flags.py` | R15 |
| `tests/unit/state/test_agent_state_schema.py` | R16 |
| `tests/unit/agent/test_middleware_stack.py` | R17 |
| `tests/integration/conftest.py` | VCR config fixture |
| `tests/integration/test_vcr_infra.py` | R12 smoke |
| `tests/integration/test_booking_real_llm.py` | R13 (5 scenarios, skipped) |
| `tests/integration/cassettes/booking/.gitkeep` | Cassette dir |
| `tests/integration/cassettes/README.md` | Refresh policy |
| `scripts/refresh_booking_cassettes.sh` | Manual cassette re-record entry point |
| `tests/unit/test_prompts/test_booking_flow_prompt.py` | R11 |
| `tests/unit/test_prompts/test_catalog_builder.py` | R14 |

## Files Modified

| Path | Change |
|------|--------|
| `agent/tools/schemas.py` | Added `collected`, `missing`; tightened `next_step: NextStep \| None` |
| `agent/tools/check_availability.py` | Pre-condition guards + `first_valid_date` payload |
| `agent/tools/book.py` | `confirmed: bool` gate + incomplete-slot guard |
| `agent/agent_factory.py` | Registered `update_booking` in `AGENT_TOOLS` (5→6 tools) |
| `agent/prompts/shared/booking_flow.md` | Rewritten to 6-line narration contract |
| `agent/prompts/catalog_builder.py` | Advance policy injected from DB, not hardcoded |
| `requirements.txt` | Added `pytest-recording>=0.13` |
| `agent/AGENTS.md` | Updated tool count (4→5), added `update_booking` to tools table |

---

## Test Plan (server-side, post-merge)

- [ ] SSH to `pepe@server`, `cd /home/pepe/Proyectos/atrevete-bot`
- [ ] `git pull origin master` (after merge)
- [ ] `docker compose restart agent`
- [ ] Verify agent starts: `docker compose logs --tail 50 agent | grep -v DEBUG`
- [ ] Run smoke test: `curl -X POST http://localhost:8000/healthz`
- [ ] Record cassettes:
  ```bash
  OPENROUTER_API_KEY=<real_key> ./scripts/refresh_booking_cassettes.sh
  ```
- [ ] Commit cassettes: `git add tests/integration/cassettes/booking/ && git commit -m "chore(test): record S1-S5 booking cassettes"`
- [ ] Remove skip marker from `tests/integration/test_booking_real_llm.py` (`pytestmark = pytest.mark.skip(...)`)
- [ ] Run integration suite: `DATABASE_URL=... ./venv/bin/pytest tests/integration/test_booking_real_llm.py -v`
- [ ] All 5 scenarios pass

---

## Rollback Plan

```bash
ssh pepe@server
cd /home/pepe/Proyectos/atrevete-bot
git fetch origin
git revert <merge_sha>
git push origin master
docker compose restart agent
```

No DB migration to undo. No feature flags to flip. No checkpoint flush required (stateless tool contract). In-flight risk window: <2 min revert window; create_agent recovers from tool-call shape mismatch via error ToolMessage.

Post-revert smoke:
```bash
docker compose logs --tail 50 agent | grep -E "ERROR|tool.response"
curl -X POST http://localhost:8000/healthz
```

---

## Known Follow-ups

1. **Cassette recording** — must be done on server with real `OPENROUTER_API_KEY` and live DB. See test plan above.
2. **Remove skip marker** — after cassettes are recorded and committed (separate commit).
3. **`scripts/refresh_booking_cassettes.sh`** — verify the script exits 0 after cassette re-record on server.
