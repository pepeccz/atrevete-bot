# Tasks: qa-final — E2E Validation Gate

## Phase 1: Fix broken test infrastructure

- [ ] T1: Fix import in `tests/e2e/conftest.py` line 13 — change `TestingContext` to `QATestingContext`. Update type annotation on line 60. **XS** — no deps
- [ ] T2: Create `.atl/` directory if it doesn't exist. **XS** — no deps
- [ ] T3: Create `.atl/qa-testing-context.md` with JSON frontmatter containing 4 personas (`new_client`, `returning_client`, `frustrated_client`, `indecisive_client`) and 4 flows (`booking_complete`, `returning_client`, `escalation`, `indecision`). Each flow has 4-5 steps with `turn`, `mode`, `user` (Spanish), and `expect` fields. **M** — depends on T2

## Phase 2: Verify infrastructure fix

- [ ] T4: Run `python -c "from tests.e2e.harness.context_manager import QATestingContext, TestingContextManager; from pathlib import Path; ctx = TestingContextManager(root_path=Path.cwd()).load_context(); print(len(ctx.personas), len(ctx.flows))"` — must print `4 4`. **XS** — depends on T1, T3
- [ ] T5: Run `pytest tests/e2e/test_conversation_e2e.py --collect-only` — must collect 4 items, 0 errors. **XS** — depends on T1, T3

## Phase 3: Execute E2E validation

- [ ] T6: Run `pytest tests/e2e/test_conversation_e2e.py -v` with live agent pipeline. Capture per-flow results. **S** — depends on T5, requires running services
- [ ] T7: Report PASS/FAIL for each flow: `booking_complete`, `returning_client`, `escalation`, `indecision`. **XS** — depends on T6

---

**Total tasks**: 7
**Complexity**: XS × 5, S × 1, M × 1
**Critical path**: T1 + T2 → T3 → T4/T5 → T6 → T7
**Parallel opportunities**: T1 and T2 can run in parallel; T4 and T5 can run in parallel
