# Spec: qa-final

## Requirements

### MUST

- **R1**: `conftest.py` MUST import `QATestingContext` (not `TestingContext`) from `tests.e2e.harness.context_manager`
- **R2**: `conftest.py` `testing_context` fixture MUST return `QATestingContext` (type annotation and runtime)
- **R3**: `.atl/qa-testing-context.md` MUST exist and be parseable by `TestingContextManager._extract_frontmatter()`
- **R4**: Context file MUST define exactly 4 personas: `new_client`, `returning_client`, `frustrated_client`, `indecisive_client`
- **R5**: Context file MUST define exactly 4 flows: `booking_complete`, `returning_client`, `escalation`, `indecision`
- **R6**: Each flow MUST reference a valid `persona_id` from the personas section
- **R7**: Each flow MUST have at least 3 steps with `turn`, `mode`, `user`, and `expect` fields
- **R8**: `pytest tests/e2e/test_conversation_e2e.py --collect-only` MUST collect all 4 tests without errors

### SHOULD

- **R9**: Persona descriptions SHOULD match realistic beauty salon customer archetypes
- **R10**: Flow step `user` messages SHOULD be in Spanish (production language)
- **R11**: `expect.response_contains` markers SHOULD be achievable by the current agent pipeline

### WONT

- **R12**: This spec does NOT cover agent behavioral correctness — only infrastructure readiness
- **R13**: This spec does NOT require all 4 E2E tests to PASS — only that they RUN

## Scenarios

### Scenario: Import fix resolves correctly

```gherkin
Given conftest.py imports QATestingContext from tests.e2e.harness.context_manager
When Python loads the tests/e2e/conftest.py module
Then no ImportError is raised
And the testing_context fixture returns an instance of QATestingContext
```

### Scenario: Context file loads successfully

```gherkin
Given .atl/qa-testing-context.md exists with JSON frontmatter
When TestingContextManager(root_path=Path.cwd()).load_context() is called
Then a QATestingContext is returned
And context.personas has exactly 4 entries
And context.flows has exactly 4 entries
And each flow's persona_id exists in context.personas
```

### Scenario: booking_complete flow is well-formed

```gherkin
Given the context file defines flow "booking_complete"
Then flow.persona_id == "new_client"
And flow has >= 3 steps
And each step has keys: turn, mode, user, expect
And step user messages are in Spanish
```

### Scenario: returning_client flow is well-formed

```gherkin
Given the context file defines flow "returning_client"
Then flow.persona_id == "returning_client"
And flow has >= 3 steps
```

### Scenario: escalation flow is well-formed

```gherkin
Given the context file defines flow "escalation"
Then flow.persona_id == "frustrated_client"
And flow has >= 3 steps
And flow.expected_outcome contains "escalation_triggered"
```

### Scenario: indecision flow is well-formed

```gherkin
Given the context file defines flow "indecision"
Then flow.persona_id == "indecisive_client"
And flow has >= 3 steps
```

### Scenario: Test collection succeeds

```gherkin
Given Bug A (import) and Bug B (missing file) are both fixed
When pytest tests/e2e/test_conversation_e2e.py --collect-only is run
Then 4 tests are collected
And no errors appear in collection output
```

### Scenario: E2E execution produces per-flow report

```gherkin
Given all infrastructure fixes are applied
And the agent pipeline is running (Redis + agent consumer)
When pytest tests/e2e/test_conversation_e2e.py -v is executed
Then each of the 4 tests produces a result (PASS, FAIL, or ERROR)
And test output is captured for the delivery report
```

## Acceptance Criteria

- [ ] `python -c "from tests.e2e.conftest import testing_context"` succeeds
- [ ] `TestingContextManager` loads `.atl/qa-testing-context.md` returning 4 personas, 4 flows
- [ ] `pytest tests/e2e/test_conversation_e2e.py --collect-only` collects 4 items, 0 errors
- [ ] `pytest tests/e2e/test_conversation_e2e.py -v` executes all 4 flows (PASS or FAIL, not ERROR)
