"""
Unit tests for compute_is_paused() truth table.

4-case truth table (ADR-2 / spec R1):
  case 1: paused_at=None                      → False (bot active, never paused)
  case 2: paused_at set, resumed_at=None       → True  (paused, no resume yet)
  case 3: resumed_at >= paused_at              → False (resumed after pause)
  case 4: resumed_at < paused_at              → True  (re-paused after resume)

F7 requirement: cases 3 and 4 MUST seed both timestamps DIRECTLY — do NOT call
resume().  resume() NULLs paused_at, so the resumed_at < paused_at branch
(re-pause-after-resume) is only physically reachable via direct seeding.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from database.models import compute_is_paused


class TestComputeIsPaused:
    """Truth table for compute_is_paused()."""

    def test_case1_paused_at_none_returns_false(self) -> None:
        """Case 1: paused_at=None, resumed_at=None → bot is active → False."""
        assert compute_is_paused(paused_at=None, resumed_at=None) is False

    def test_case1b_paused_at_none_resumed_at_set_returns_false(self) -> None:
        """Case 1b: paused_at=None even with a resumed_at → False (paused_at is the gate)."""
        now = datetime.now(tz=UTC)
        assert compute_is_paused(paused_at=None, resumed_at=now) is False

    def test_case2_paused_at_set_resumed_none_returns_true(self) -> None:
        """Case 2: paused_at set + resumed_at=None → bot is paused → True."""
        now = datetime.now(tz=UTC)
        assert compute_is_paused(paused_at=now, resumed_at=None) is True

    def test_case3_resumed_at_after_paused_at_returns_false(self) -> None:
        """Case 3: resumed_at > paused_at → bot was resumed → False.

        Seeds both timestamps DIRECTLY (F7 — never routes through resume()).
        """
        paused = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        resumed = paused + timedelta(hours=1)
        assert compute_is_paused(paused_at=paused, resumed_at=resumed) is False

    def test_case3b_resumed_at_equal_paused_at_returns_false(self) -> None:
        """Case 3b: resumed_at == paused_at → treated as resumed → False."""
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        assert compute_is_paused(paused_at=ts, resumed_at=ts) is False

    def test_case4_resumed_at_before_paused_at_returns_true(self) -> None:
        """Case 4: resumed_at < paused_at → re-paused after resume → True.

        Seeds both timestamps DIRECTLY (F7 — this branch is only reachable via
        direct seeding; resume() NULLs paused_at, never leaves resumed_at < paused_at).
        """
        resumed = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        paused = resumed + timedelta(hours=1)  # re-paused AFTER resume
        assert compute_is_paused(paused_at=paused, resumed_at=resumed) is True
