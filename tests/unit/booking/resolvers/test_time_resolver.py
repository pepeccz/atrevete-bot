"""Tests for resolve_relative_date — all 13 spec scenarios + phrase families.

All tests use fixed today = date(2026, 4, 27) which is a lunes (Monday).
No datetime.now() calls in test body — resolver is pure with injected today.
"""

from __future__ import annotations

from datetime import date

import pytest


TODAY = date(2026, 4, 27)  # lunes (Monday)


@pytest.fixture
def resolve():
    from agent.booking.resolvers.time_resolver import resolve_relative_date

    return resolve_relative_date


class TestSimplePhrases:
    def test_b1_hoy(self, resolve):
        """Scenario B-1: hoy → today."""
        assert resolve("hoy", TODAY) == TODAY

    def test_b2_manana(self, resolve):
        """Scenario B-2: mañana → today + 1."""
        assert resolve("mañana", TODAY) == date(2026, 4, 28)

    def test_b3_pasado_manana(self, resolve):
        """Scenario B-3: pasado mañana → today + 2."""
        assert resolve("pasado mañana", TODAY) == date(2026, 4, 29)

    def test_hoy_case_insensitive(self, resolve):
        assert resolve("Hoy", TODAY) == TODAY

    def test_manana_without_accent(self, resolve):
        """Unaccented mañana should NOT resolve (only canonical forms)."""
        # 'manana' without accent is not a Spanish word — expect None
        result = resolve("manana", TODAY)
        assert result is None


class TestProximoWeekday:
    def test_b4_proximo_weekday(self, resolve):
        """Scenario B-4: el próximo miércoles from Monday → Wednesday same week."""
        # today is lunes (0), miércoles is (2) → date(2026, 4, 29)
        assert resolve("el próximo miércoles", TODAY) == date(2026, 4, 29)

    def test_proximo_without_el(self, resolve):
        assert resolve("próximo lunes", TODAY) == date(2026, 5, 4)

    def test_proximo_lunes_from_lunes(self, resolve):
        """próximo lunes from a Monday → next Monday (not today)."""
        assert resolve("próximo lunes", TODAY) == date(2026, 5, 4)


class TestQueVieneWeekday:
    def test_b5_weekday_que_viene_strictly_next_week(self, resolve):
        """Scenario B-5: el miércoles que viene → Wednesday of following week (≥ today+7)."""
        # today is lunes 2026-04-27; miércoles que viene → 2026-05-06
        assert resolve("el miércoles que viene", TODAY) == date(2026, 5, 6)

    def test_lunes_que_viene(self, resolve):
        """lunes que viene from Monday → following Monday (today+7)."""
        assert resolve("lunes que viene", TODAY) == date(2026, 5, 4)


class TestBareWeekday:
    def test_b6_bare_weekday_miercoles(self, resolve):
        """Scenario B-6: el miércoles from Monday → next Wednesday."""
        assert resolve("el miércoles", TODAY) == date(2026, 4, 29)

    def test_b7_bare_weekday_same_day_next_week(self, resolve):
        """Scenario B-7: el lunes from Monday → following Monday (never today)."""
        assert resolve("el lunes", TODAY) == date(2026, 5, 4)

    def test_bare_weekday_no_article(self, resolve):
        assert resolve("miércoles", TODAY) == date(2026, 4, 29)

    def test_bare_weekday_unaccented_miercoles(self, resolve):
        """Unaccented miercoles should still resolve."""
        assert resolve("miercoles", TODAY) == date(2026, 4, 29)

    def test_bare_weekday_unaccented_sabado(self, resolve):
        assert resolve("sabado", TODAY) == date(2026, 5, 2)


class TestDayOfMonth:
    def test_b8_el_n_current_month(self, resolve):
        """Scenario B-8: el 30 from April 27 → April 30 (still in month)."""
        assert resolve("el 30", TODAY) == date(2026, 4, 30)

    def test_b9_el_n_already_passed_next_month(self, resolve):
        """Scenario B-9: el 5 from April 27 → May 5 (passed in April)."""
        assert resolve("el 5", TODAY) == date(2026, 5, 5)

    def test_el_27_today_goes_to_next_month(self, resolve):
        """el 27 when today is the 27th → next occurrence (May 27)."""
        assert resolve("el 27", TODAY) == date(2026, 5, 27)


class TestDayOfMonthWithMonthName:
    def test_b10_el_n_de_mes_future(self, resolve):
        """Scenario B-10: el 5 de mayo → May 5 2026."""
        assert resolve("el 5 de mayo", TODAY) == date(2026, 5, 5)

    def test_b11_el_n_de_mes_already_passed_next_year(self, resolve):
        """Scenario B-11: el 3 de enero already passed → January 3 2027."""
        assert resolve("el 3 de enero", TODAY) == date(2027, 1, 3)

    def test_month_name_case_insensitive(self, resolve):
        assert resolve("el 5 de Mayo", TODAY) == date(2026, 5, 5)


class TestAmbiguousAndUnrecognized:
    def test_b12_la_semana_que_viene_returns_none(self, resolve):
        """Scenario B-12: week reference without weekday → None."""
        assert resolve("la semana que viene", TODAY) is None

    def test_b13_unrecognized_returns_none_no_exception(self, resolve):
        """Scenario B-13: unrecognized text → None, no exception."""
        result = resolve("algún día", TODAY)
        assert result is None

    def test_empty_string_returns_none(self, resolve):
        assert resolve("", TODAY) is None

    def test_vague_phrase_returns_none(self, resolve):
        assert resolve("en unos días", TODAY) is None

    def test_never_raises_on_any_string(self, resolve):
        """B4: must never raise exceptions."""
        for phrase in ["!!!", "123abc", "el fin de semana", "mañana lunes"]:
            result = resolve(phrase, TODAY)
            assert result is None or isinstance(result, date)
