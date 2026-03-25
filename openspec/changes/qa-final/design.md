# Design: qa-final

## Architecture Decisions

### AD1: Import fix — minimal change

**Decision**: Change one import line and one type annotation in `conftest.py`.

**Rationale**: The class `QATestingContext` already exists in `context_manager.py`. The old name `TestingContext` was renamed to avoid pytest collection warnings (classes starting with `Test` get collected). The fixture just needs to reference the new name.

**Change**:
```python
# conftest.py line 13 — before:
from tests.e2e.harness.context_manager import TestingContext, TestingContextManager

# after:
from tests.e2e.harness.context_manager import QATestingContext, TestingContextManager
```

```python
# conftest.py line 60 — before:
def testing_context() -> TestingContext:

# after:
def testing_context() -> QATestingContext:
```

### AD2: Context file format — JSON-in-frontmatter

**Decision**: Use the JSON-in-YAML-frontmatter format that `_extract_frontmatter()` already parses.

**Rationale**: The parser at `context_manager.py:166-174` expects:
1. File starts with `---\n`
2. Content between first `---\n` and `\n---\n` is extracted
3. That content is parsed as JSON via `json.loads()`

The file is a `.md` but the frontmatter is pure JSON (not YAML). Everything after the closing `---` is markdown documentation (ignored by the parser).

**Structure**:
```
---
{
  "version": "1.0",
  "personas": { ... 4 personas ... },
  "criteria": { ... optional quality levels ... },
  "flows": { ... 4 flows ... }
}
---

# QA Testing Context
(human-readable documentation)
```

### AD3: Persona-to-flow mapping

| Flow ID | Persona ID | Phone | Description |
|---------|-----------|-------|-------------|
| `booking_complete` | `new_client` | +34600000001 | New customer books a service end-to-end |
| `returning_client` | `returning_client` | +34600000002 | Known customer books again |
| `escalation` | `frustrated_client` | +34600000003 | Frustrated customer triggers escalation |
| `indecision` | `indecisive_client` | +34600000004 | Indecisive customer guided to a booking |

These mappings are derived from `test_conversation_e2e.py` which calls `testing_context.flows["booking_complete"]` etc., and from the persona descriptions in the task prompt.

### AD4: Flow step design

Each flow has 4-5 steps following the pattern the test harness expects:

```json
{
  "turn": 1,
  "mode": "GREETING",
  "user": "Hola, quiero pedir una cita",
  "expect": {
    "response_contains": ["bienvenid", "servicio"]
  }
}
```

- `turn`: Sequential integer (1-based)
- `mode`: Expected agent mode (GREETING, BOOKING, ESCALATION, GENERAL)
- `user`: Spanish user message sent via Redis
- `expect.response_contains`: Lowercase substrings checked against agent response

### AD5: Directory structure

```
.atl/
└── qa-testing-context.md    # NEW — JSON frontmatter + markdown docs

tests/e2e/
└── conftest.py              # MODIFIED — import fix (2 lines)
```

No new Python files. No schema changes. No migrations.

## E2E Execution Approach

Sub-task 2 runs `pytest tests/e2e/test_conversation_e2e.py -v` which:
1. Loads the `testing_context` fixture → `QATestingContext` with 4 flows
2. For each test, calls `_run_flow()` which injects messages via Redis and captures responses
3. Evaluates the conversation trace against level checks (L1 structure, L3 execution, L4 context)
4. Reports PASS/FAIL per assertion

**Prerequisite**: The agent pipeline (Redis consumer + API) must be running. This is a live integration test, not a mock.
