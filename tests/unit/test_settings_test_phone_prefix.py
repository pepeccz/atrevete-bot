"""Unit tests for QA harness Settings fields (AS2, AS3).

Covers:
- TEST_MODE_GCAL_SKIP defaults to False
- TEST_PHONE_PREFIX defaults to "+34999"
"""

from __future__ import annotations

import pytest


def test_test_mode_gcal_skip_default_false() -> None:
    """AS2: TEST_MODE_GCAL_SKIP must default to False (safe prod default)."""
    # Import inside test to avoid caching from other test runs
    from shared.config import Settings

    s = Settings()
    assert s.TEST_MODE_GCAL_SKIP is False


def test_test_phone_prefix_default() -> None:
    """AS3: TEST_PHONE_PREFIX must default to '+34999'."""
    from shared.config import Settings

    s = Settings()
    assert s.TEST_PHONE_PREFIX == "+34999"


def test_test_mode_gcal_skip_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEST_MODE_GCAL_SKIP can be set to True via environment variable."""
    monkeypatch.setenv("TEST_MODE_GCAL_SKIP", "true")
    from shared.config import Settings

    s = Settings()
    assert s.TEST_MODE_GCAL_SKIP is True


def test_test_phone_prefix_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEST_PHONE_PREFIX can be overridden via environment variable."""
    monkeypatch.setenv("TEST_PHONE_PREFIX", "+34888")
    from shared.config import Settings

    s = Settings()
    assert s.TEST_PHONE_PREFIX == "+34888"
