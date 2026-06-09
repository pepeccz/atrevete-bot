"""Tests for the _slot_today rendering in DynamicPromptMiddleware.

Covers:
  A-1: slot present in assembled prompt (fecha, dia_semana, tz; NOT hora_local)
  A-2: slot is first in SLOT_REGISTRY
  A-3: UTC→CEST conversion (UTC+2 summer) — date and day name only
  A-4: DST winter CET (UTC+1) — date only

Note: hora_local was removed from <today> in F3 (quick-wins-bundle) to enable
prefix cache reuse across turns within the same calendar day.

All tests inject a fixed datetime — no datetime.now() in test body.
"""

from __future__ import annotations

from datetime import UTC, datetime


def _render_today(now_utc: datetime) -> str:
    """Helper: call _slot_today with an injected datetime and return the rendered string."""
    from agent.middleware.dynamic_prompt import _slot_today

    return _slot_today(now_utc)


class TestSlotTodayContent:
    def test_a1_slot_present_in_rendered_string(self):
        """Scenario A-1: rendered output contains <today> block with required fields.

        hora_local is intentionally absent (removed in F3 for prefix cache stability).
        """
        now_utc = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)
        result = _render_today(now_utc)

        assert "<today>" in result
        assert "</today>" in result
        assert "fecha:" in result
        assert "dia_semana:" in result
        assert "hora_local:" not in result  # removed in F3 for prefix cache stability
        assert "tz: Europe/Madrid" in result

    def test_a3_utc_to_cest_conversion(self):
        """Scenario A-3: 12:00 UTC maps to 2026-04-27 (CEST date is same day)."""
        now_utc = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)
        result = _render_today(now_utc)

        assert "fecha: 2026-04-27" in result
        assert "dia_semana: lunes" in result
        assert "hora_local" not in result  # removed in F3
        assert "tz: Europe/Madrid" in result

    def test_a4_dst_winter_cet(self):
        """Scenario A-4: 11:00 UTC in winter maps to 2026-01-05 (CET date is same day)."""
        now_utc = datetime(2026, 1, 5, 11, 0, 0, tzinfo=UTC)
        result = _render_today(now_utc)

        assert "fecha: 2026-01-05" in result
        assert "hora_local" not in result  # removed in F3
        assert "tz: Europe/Madrid" in result

    def test_weekday_name_is_lowercase(self):
        """Weekday name must be lowercase Spanish."""
        now_utc = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)
        result = _render_today(now_utc)
        # lunes is Monday (weekday 0)
        assert "dia_semana: lunes" in result

    def test_tuesday_weekday(self):
        now_utc = datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)  # Tuesday
        result = _render_today(now_utc)
        assert "dia_semana: martes" in result

    def test_format_no_trailing_whitespace(self):
        now_utc = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)
        result = _render_today(now_utc)
        for line in result.splitlines():
            assert line == line.rstrip(), f"Trailing whitespace in: {line!r}"


class TestSlotTodayOrdering:
    def test_a2_today_slot_is_first_in_slot_registry(self):
        """Scenario A-2: _slot_today must be first in SLOT_REGISTRY."""
        from agent.state import SLOT_REGISTRY

        assert SLOT_REGISTRY[0] == "_slot_today", (
            f"_slot_today must be first in SLOT_REGISTRY, got {SLOT_REGISTRY[0]!r}"
        )
