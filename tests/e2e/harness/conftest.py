"""pytest configuration for tests/e2e/harness/ pure-unit tests.

The parent tests/e2e/conftest.py defines an autouse async fixture
``cleanup_after_test`` that requires a live Redis connection. The harness
directory also contains pure unit tests (test_scenarios_schema.py,
test_assert_audience_disambiguation.py) that are PURE — they do not touch
Redis or the database.

This local conftest overrides the Redis-dependent autouse fixtures so that
pure harness unit tests can run without a live Redis instance. Tests in
sub-directories that DO need Redis are not affected (they can override back).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest


@pytest.fixture(autouse=True)
async def cleanup_after_test() -> AsyncGenerator[None, None]:  # type: ignore[override]
    """No-op override of the parent e2e cleanup fixture.

    Pure harness unit tests (YAML schema validation, helper logic tests) do not
    create any Redis state and do not need cleanup. The parent fixture is
    overridden here so pytest does not attempt a Redis ping during setup.
    """
    yield


@pytest.fixture
async def state_reset() -> Any:  # type: ignore[override]
    """No-op override — harness unit tests do not use state_reset."""
    return None
