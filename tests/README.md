# Test Suite Documentation

This directory contains the comprehensive test suite for the Atrévete Bot project.

## Directory Structure

```
tests/
├── README.md                    # This file
├── conftest.py                  # Shared pytest fixtures
├── unit/                        # Unit tests (isolated, fast)
│   ├── test_slot_validator.py  # SlotValidator unit tests
│   ├── test_booking_fsm.py     # FSM unit tests
│   └── ...
├── integration/                 # Integration tests (multiple components)
│   ├── test_booking_flow_complete.py  # Complete booking flow
│   ├── test_booking_e2e.py            # End-to-end scenarios
│   ├── test_fsm_llm_integration.py    # FSM + LLM integration
│   └── scenarios/               # Specific scenario tests
│       ├── test_duration_enrichment.py
│       ├── test_closed_day_slot_validation.py
│       └── ...
└── mocks/                       # Shared mock objects
    └── ...
```

## Test Categories

### Unit Tests (`tests/unit/`)
**Purpose**: Test individual functions/classes in isolation

**Characteristics:**
- Fast execution (< 1ms per test)
- No external dependencies (DB, Redis, APIs)
- Heavy use of mocks
- 100% coverage target for validators

**Example:**
```python
# tests/unit/test_slot_validator.py
async def test_validate_complete_valid_slot():
    """Test that a valid slot passes all validations."""
    validator = SlotValidator()
    slot = {"start_time": "2025-12-01T10:00:00+01:00", "duration_minutes": 60}
    result = await validator.validate_complete(slot)
    assert result.valid is True
```

### Integration Tests (`tests/integration/`)
**Purpose**: Test component interactions

**Characteristics:**
- Moderate execution time (< 100ms per test)
- May use real DB/Redis in CI
- Tests 2-3 components together
- 70%+ coverage target

**Example:**
```python
# tests/integration/test_booking_flow_complete.py
async def test_happy_path_single_service():
    """Test complete booking flow: IDLE → BOOKED."""
    fsm = BookingFSM("test-conv")
    # Test all transitions with real FSM logic
    ...
```

### Scenario Tests (`tests/integration/scenarios/`)
**Purpose**: Test specific user scenarios end-to-end

**Characteristics:**
- Realistic user flows
- Multiple components involved
- Edge case validation
- 90%+ coverage target for critical flows

**Example:**
```python
# tests/integration/scenarios/test_duration_enrichment.py
async def test_multiple_services_duration_summed():
    """Test that selecting multiple services sums durations correctly."""
    # Simulates user selecting Corte + Barba
    ...
```

## Running Tests

### Run All Tests
```bash
# Using helper script (recommended)
./scripts/run-tests-with-coverage.sh

# Using pytest directly
pytest
```

### Run Specific Test Categories
```bash
# Unit tests only
./scripts/run-tests-with-coverage.sh unit
pytest tests/unit/

# Integration tests only
./scripts/run-tests-with-coverage.sh integration
pytest tests/integration/

# Scenario tests only
./scripts/run-tests-with-coverage.sh scenarios
pytest tests/integration/scenarios/
```

### Run Specific Test File
```bash
pytest tests/unit/test_slot_validator.py -v
```

### Run Specific Test Function
```bash
pytest tests/unit/test_slot_validator.py::test_validate_complete_valid_slot -v
```

### Run with Coverage Report
```bash
pytest --cov=agent --cov=shared --cov=database \
       --cov-report=html \
       --cov-report=term-missing
```

## Coverage Requirements

### Minimum Coverage Targets
- **Overall**: 85% (enforced in CI)
- **Unit tests**: 100% for validators
- **Integration tests**: 70% for FSM and agent
- **End-to-end tests**: 90% for booking flow

### Excluded from Coverage
- `*/tests/*` - Test code itself
- `*/migrations/*` - Database migrations
- `*/__pycache__/*` - Python cache
- `*/venv/*` - Virtual environments

### Viewing Coverage Reports

After running tests with coverage:

```bash
# Open HTML report
firefox htmlcov/index.html
# or
xdg-open htmlcov/index.html

# View terminal report
cat coverage.txt
```

## Test Markers

Tests can be marked with pytest markers:

```python
@pytest.mark.unit         # Unit test
@pytest.mark.integration  # Integration test
@pytest.mark.e2e          # End-to-end test
@pytest.mark.slow         # Slow-running test (> 1s)
```

### Run Tests by Marker
```bash
# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Skip slow tests
pytest -m "not slow"
```

## Writing New Tests

### Best Practices

1. **Test Naming**: Use descriptive names
   ```python
   # Good
   async def test_slot_on_closed_day_rejected()

   # Bad
   async def test_slot_validation()
   ```

2. **Docstrings**: Explain what and why
   ```python
   async def test_duration_calculated_on_slot_selection():
       """
       Test that duration is calculated after SELECT_SLOT transition.

       Validates:
       - calculate_service_durations() is called
       - slot.duration_minutes is updated with real value
       """
   ```

3. **Arrange-Act-Assert Pattern**
   ```python
   async def test_example():
       # Arrange: Set up test data
       fsm = BookingFSM("test")
       intent = Intent(type=IntentType.START_BOOKING)

       # Act: Execute the code under test
       result = await fsm.transition(intent)

       # Assert: Verify results
       assert result.success is True
   ```

4. **Use Fixtures**: DRY principles
   ```python
   @pytest.fixture
   def valid_slot():
       return {"start_time": "...", "duration_minutes": 60}

   async def test_with_fixture(valid_slot):
       result = await validator.validate(valid_slot)
       assert result.valid
   ```

5. **Mock at Boundaries**: Don't mock business logic
   ```python
   # Good: Mock external dependency
   with patch("agent.fsm.booking_fsm.SlotValidator") as mock:
       mock.validate_complete.return_value = MagicMock(valid=True)

   # Bad: Mock internal logic
   with patch.object(fsm, 'transition'):  # Don't do this!
   ```

## Mocking Patterns

### Mock Database Session
```python
with patch("agent.fsm.booking_fsm.get_async_session") as mock_session_ctx:
    mock_session = MagicMock()
    mock_service = MagicMock()
    mock_service.duration_minutes = 60

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_service
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_session_ctx.return_value.__aenter__.return_value = mock_session
```

### Mock Async Function
```python
with patch("module.async_function", new_callable=AsyncMock) as mock_fn:
    mock_fn.return_value = {"result": "success"}
    result = await async_function()
```

### Mock SlotValidator
```python
with patch("agent.fsm.booking_fsm.SlotValidator") as mock_validator:
    mock_validation = MagicMock()
    mock_validation.valid = True
    mock_validation.error_code = None
    mock_validator.validate_complete = AsyncMock(return_value=mock_validation)
```

## Troubleshooting

### Tests Fail with "No module named X"
**Solution**: Install dev dependencies
```bash
pip install -r requirements.txt
```

### Tests Fail with Database Connection Error
**Solution**: Ensure Docker services are running
```bash
docker-compose up -d postgres redis
```

### Coverage Below 85%
**Solution**: Check which files need more tests
```bash
# Generate coverage report
pytest --cov=agent --cov-report=term-missing:skip-covered

# Identify gaps
grep -A 5 "TOTAL" coverage.txt
```

### Slow Tests
**Solution**: Run only fast tests
```bash
pytest -m "not slow"
```

## CI/CD Integration

Tests run automatically on:
- Every push to `master` branch
- Every pull request

### CI Requirements
- All tests must pass
- Coverage must be ≥ 85%
- No linting errors (ruff)
- No type errors (mypy)

### View CI Results
- GitHub Actions tab in repository
- Coverage report artifact (retained 30 days)
- PR comment with coverage diff

## Async Mocking Patterns

Python's `MagicMock` does NOT support `await`. Use `AsyncMock` (Python 3.8+) for
any `async def` target, async context manager, or coroutine attribute.

### Pattern 1 — Replace MagicMock with AsyncMock for async callables

**BEFORE (broken — TypeError: object MagicMock is not awaitable):**
```python
from unittest.mock import MagicMock
mock_session = MagicMock()
result = await mock_session.execute(stmt)  # raises TypeError
```

**AFTER (correct):**
```python
from unittest.mock import AsyncMock
mock_session = AsyncMock()
result = await mock_session.execute(stmt)  # works
```

### Pattern 2 — Set concrete return_value to avoid numeric comparison failures

**BEFORE (broken — MagicMock vs int comparison is always True but misleading):**
```python
session = MagicMock()
session.commit = MagicMock()          # not awaitable
session.execute = MagicMock()         # not awaitable
```

**AFTER (correct):**
```python
from unittest.mock import AsyncMock, MagicMock
session = MagicMock()
session.add = MagicMock()                              # sync — fine
session.commit = AsyncMock()                           # async
session.execute = AsyncMock(return_value=mock_result)  # async, typed return
```

For numeric comparisons, always set a concrete `return_value`:
```python
mock_result = MagicMock()
mock_result.scalar_one_or_none.return_value = 42      # concrete int, not MagicMock
session.execute = AsyncMock(return_value=mock_result)
count = await session.execute(stmt)
assert count.scalar_one_or_none() == 42               # passes
```

### Pattern 3 — mocker.patch.object with new=AsyncMock

**BEFORE (broken — patches async method with a synchronous MagicMock):**
```python
mocker.patch.object(MyService, "fetch_data")
```

**AFTER (correct):**
```python
from unittest.mock import AsyncMock
mocker.patch.object(MyService, "fetch_data", new=AsyncMock(return_value={"ok": True}))
```

With context manager form:
```python
from unittest.mock import AsyncMock, patch
with patch("module.path.fetch_data", new_callable=AsyncMock) as mock_fetch:
    mock_fetch.return_value = {"key": "value"}
    result = await service.do_something()
    mock_fetch.assert_awaited_once()
```

## Rate Limiting

Rate limiting is **disabled globally** in tests (conftest sets `RATE_LIMITING_ENABLED=false`).

Tests that assert 429 behaviour must:
1. Re-enable: `monkeypatch.setenv("RATE_LIMITING_ENABLED", "true")`
2. Clear cache: `from shared.config import get_settings; get_settings.cache_clear()`
3. Mark with: `@pytest.mark.rate_limit_required`

## Stripe Stub

A full in-memory Stripe stub lives in `conftest.py` under `sys.modules["stripe"]`.
Available: `Invoice`, `InvoiceItem`, `PaymentMethod`, `Subscription`, `Customer`,
`Charge`, `Refund`, `Event`, `Webhook`, `SetupIntent`, `PaymentIntent`, `TaxRate`,
`checkout.Session`, `error.StripeError`, `error.InvalidRequestError`.

## Additional Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Coverage.py Documentation](https://coverage.readthedocs.io/)
- [Testing Strategy](../docs/TESTING-STRATEGY.md)
- [Plan Progress](../docs/PLAN-PROGRESS.md)

---

**Last Updated**: 2025-11-27
**Maintainer**: Claude Code
