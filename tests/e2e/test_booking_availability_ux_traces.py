"""Offline QA trace assertions for booking availability UX regressions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.e2e.qa_booking_run import analyze_booking_trace, analyze_empty_day_trace


@pytest.fixture(autouse=True)
def qa_test_environment() -> None:
    """Override the live e2e env fixture; these tests are offline trace checks."""


@pytest.fixture
def redis_client() -> None:
    """Override live Redis dependency from tests/e2e/conftest.py."""


@pytest.fixture
def binary_redis_client() -> None:
    """Override live Redis dependency from tests/e2e/conftest.py."""


@pytest.fixture
def redis_harness() -> None:
    """Override live Redis harness dependency from tests/e2e/conftest.py."""


@pytest.fixture
def state_reset() -> None:
    """Override live cleanup dependency from tests/e2e/conftest.py."""


@pytest.fixture(autouse=True)
def cleanup_after_test() -> None:
    """Disable Redis cleanup for offline trace tests."""


def _load_traces() -> dict:
    path = Path(__file__).with_name("booking_availability_ux_traces.json")
    return json.loads(path.read_text(encoding="utf-8"))


def test_early_slot_reveal_trace_shows_slots_before_name_or_notes():
    traces = _load_traces()
    result = analyze_booking_trace(traces["early_slot_reveal"]["trace"])

    assert result["first_slot_turn"] == 3
    assert result["first_name_or_notes_turn"] == 4
    assert result["slots_before_name_or_notes"] is True


def test_named_stylist_empty_day_trace_requires_consent_before_alternatives():
    traces = _load_traces()
    result = analyze_empty_day_trace(
        traces["empty_day_named_stylist_requires_consent"]["trace"],
        requires_consent=True,
    )

    assert result["first_consent_turn"] == 1
    assert result["first_alternative_turn"] == 2
    assert result["passes"] is True


def test_any_stylist_empty_day_trace_allows_immediate_bounded_alternatives():
    traces = _load_traces()
    result = analyze_empty_day_trace(
        traces["empty_day_any_stylist_can_offer_alternatives_immediately"]["trace"],
        requires_consent=False,
    )

    assert result["first_consent_turn"] is None
    assert result["first_alternative_turn"] == 1
    assert result["passes"] is True
