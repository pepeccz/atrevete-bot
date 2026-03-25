# Proposal: qa-final

**Priority**: P0 — delivery gate

## Intent

The E2E test suite (`tests/e2e/test_conversation_e2e.py`) cannot run at all due to two infrastructure bugs. Until these are fixed, we cannot validate the 4 core conversational flows before client delivery. This change fixes both bugs and executes the validation gate.

## Scope

### In Scope

- Fix broken import in `tests/e2e/conftest.py` (`TestingContext` → `QATestingContext`)
- Create missing `.atl/qa-testing-context.md` with 4 personas and 4 flows
- Execute `pytest tests/e2e/test_conversation_e2e.py -v` and report per-flow PASS/FAIL

### Out of Scope

- Modifying agent logic, mode nodes, or tool implementations
- Changing the QA harness infrastructure (`redis_harness.py`, `state_reset.py`)
- Adding new test scenarios beyond the 4 existing flows
- Performance tuning or latency optimization

## Approach

**Bug A — Import mismatch:** The class was renamed from `TestingContext` to `QATestingContext` in `context_manager.py` (to avoid pytest collection warnings), but `conftest.py` still imports the old name. One-line fix: update the import and type annotation.

**Bug B — Missing context file:** `TestingContextManager` loads `.atl/qa-testing-context.md` which doesn't exist. Create the file using JSON-in-frontmatter format (as required by `_extract_frontmatter`), defining the 4 personas and 4 flows that `test_conversation_e2e.py` expects: `booking_complete`, `returning_client`, `escalation`, `indecision`.

**Validation:** Run the 4 E2E flows against the live Redis-backed agent pipeline and capture results.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `tests/e2e/conftest.py` | Modified | Fix import: `TestingContext` → `QATestingContext` |
| `.atl/qa-testing-context.md` | New | QA context file with 4 personas + 4 flows |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| E2E flows fail due to agent bugs (not infra) | Medium | This change only fixes infra; agent bugs are separate findings |
| Context file format doesn't match parser | Low | Format derived directly from `_extract_frontmatter` source code |
| `.atl/` directory doesn't exist | Low | Create it as part of the change |

## Rollback Plan

- Revert the import line in `conftest.py` to `TestingContext`
- Delete `.atl/qa-testing-context.md`
- No schema changes, no migrations, no external API changes

## Dependencies

- Live Redis + agent pipeline must be running for E2E execution (sub-task 2)
- `database/seeds/stylists.py` seeding must be in place (from prior p0-booking-fix change)

## Success Criteria

- [ ] `from tests.e2e.harness.context_manager import QATestingContext` resolves without `ImportError`
- [ ] `TestingContextManager(root_path=Path.cwd()).load_context()` returns a `QATestingContext` with 4 personas and 4 flows
- [ ] `pytest tests/e2e/test_conversation_e2e.py -v` runs all 4 tests without `ImportError` or `FileNotFoundError`
- [ ] Per-flow PASS/FAIL results captured and reported
