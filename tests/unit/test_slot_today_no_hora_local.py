"""Tests for _slot_today — hora_local must be absent (AS5, F3).

F3: Removing hora_local from <today> makes the slot byte-identical
    across turns within the same calendar day, enabling prefix cache reuse.
"""

from __future__ import annotations

from datetime import UTC, datetime


class TestSlotTodayNoHoraLocal:
    """AS5 — <today> slot must not contain hora_local."""

    def _call_slot_today(self, fixed_utc: datetime) -> str:
        from agent.middleware.dynamic_prompt import _slot_today

        return _slot_today(now_utc=fixed_utc)

    def test_hora_local_absent(self) -> None:
        """hora_local must not appear in the rendered slot."""
        fixed = datetime(2026, 6, 9, 10, 30, 0, tzinfo=UTC)
        slot = self._call_slot_today(fixed)
        assert "hora_local" not in slot, (
            f"hora_local must be removed from <today> slot to enable prefix cache. "
            f"Got: {slot!r}"
        )

    def test_fecha_present(self) -> None:
        """fecha must still be in the rendered slot."""
        fixed = datetime(2026, 6, 9, 10, 30, 0, tzinfo=UTC)
        slot = self._call_slot_today(fixed)
        assert "fecha:" in slot, f"fecha must be present in <today> slot. Got: {slot!r}"

    def test_dia_semana_present(self) -> None:
        """dia_semana must still be in the rendered slot."""
        fixed = datetime(2026, 6, 9, 10, 30, 0, tzinfo=UTC)
        slot = self._call_slot_today(fixed)
        assert "dia_semana:" in slot, (
            f"dia_semana must be present in <today> slot. Got: {slot!r}"
        )

    def test_tz_present(self) -> None:
        """tz must still be in the rendered slot."""
        fixed = datetime(2026, 6, 9, 10, 30, 0, tzinfo=UTC)
        slot = self._call_slot_today(fixed)
        assert "tz:" in slot, f"tz must be present in <today> slot. Got: {slot!r}"

    def test_slot_stable_across_calls_same_day(self) -> None:
        """Two calls at different times on the same day must produce identical output."""
        morning = datetime(2026, 6, 9, 8, 0, 0, tzinfo=UTC)
        evening = datetime(2026, 6, 9, 20, 0, 0, tzinfo=UTC)
        assert self._call_slot_today(morning) == self._call_slot_today(evening), (
            "Without hora_local, same-day calls must produce identical <today> slots "
            "to enable prefix cache reuse."
        )
