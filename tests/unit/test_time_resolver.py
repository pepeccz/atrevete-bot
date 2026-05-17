"""Unit tests for agent/booking/resolvers/time_resolver.py.

All tests inject `today` explicitly — no clock access in tests.

TDD: tasks 1.1 (RED) — 7 new cases for REQ-P3-1 through REQ-P3-4.
"""

from datetime import date

from agent.booking.resolvers.time_resolver import resolve_relative_date

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Reference "today" for tests: Monday 2026-04-27
TODAY = date(2026, 4, 27)


# ---------------------------------------------------------------------------
# Existing regression tests (must stay green after regex extension)
# ---------------------------------------------------------------------------


def test_mañana():
    assert resolve_relative_date("mañana", TODAY) == date(2026, 4, 28)


def test_pasado_mañana():
    assert resolve_relative_date("pasado mañana", TODAY) == date(2026, 4, 29)


def test_que_viene_without_filler_still_works():
    """REQ-P3-3 regression: 'el viernes que viene' still works after regex extension.

    min_delta=7: target = today+7 = 2026-05-04 (Mon); next Friday >= that = 2026-05-08.
    'que viene' semantics = strictly next-week occurrence.
    """
    result = resolve_relative_date("el viernes que viene", TODAY)
    assert result == date(2026, 5, 8)


def test_proximo_prepositional_still_works():
    """Regression: 'el próximo viernes' unchanged by new sibling regex."""
    result = resolve_relative_date("el próximo viernes", TODAY)
    assert result == date(2026, 5, 1)


def test_bare_weekday_still_works():
    """Regression: 'el viernes' resolves to this week's Friday (min_delta=1)."""
    result = resolve_relative_date("el viernes", TODAY)
    assert result == date(2026, 5, 1)


# ---------------------------------------------------------------------------
# Task 1.1 RED — NEW cases (must fail before task 1.2 implementation)
# ---------------------------------------------------------------------------


def test_que_viene_with_de_la_semana_filler():
    """REQ-P3-1: 'el viernes de la semana que viene' → Friday of next calendar week.

    Today = Monday 2026-04-27.
    min_delta=7 → target = 2026-05-04 (Mon); next Friday >= that = 2026-05-08.
    Same result as plain 'viernes que viene' — the 'de la semana' filler is transparent.
    """
    result = resolve_relative_date("el viernes de la semana que viene", TODAY)
    assert result == date(2026, 5, 8)


def test_que_viene_with_de_la_semana_filler_no_article():
    """REQ-P3-1 variant: 'viernes de la semana que viene' (no article)."""
    result = resolve_relative_date("viernes de la semana que viene", TODAY)
    assert result == date(2026, 5, 8)


def test_proximo_post_positioned():
    """REQ-P3-2: 'viernes próximo' → next Friday (min_delta=1, same semantics as pre-positioned)."""
    # Today Mon 2026-04-27 → next Friday 2026-05-01
    result = resolve_relative_date("viernes próximo", TODAY)
    assert result == date(2026, 5, 1)


def test_proximo_post_positioned_no_accent_no_article():
    """REQ-P3-2 variant: 'viernes proximo' (no accent, no article)."""
    result = resolve_relative_date("viernes proximo", TODAY)
    assert result == date(2026, 5, 1)


def test_de_la_semana_alone_returns_none():
    """REQ-P3-3 negative: 'el viernes de la semana' without 'que viene' → None."""
    result = resolve_relative_date("el viernes de la semana", TODAY)
    assert result is None


def test_proximo_alone_returns_none():
    """REQ-P3-3 negative: 'próximo' alone (no weekday) → None."""
    result = resolve_relative_date("próximo", TODAY)
    assert result is None


def test_post_positioned_does_not_match_bare_weekday():
    """REQ-P3-3 negative: plain 'viernes' is NOT captured by the new post-positioned regex.

    It should still resolve via the bare-weekday branch (not the new sibling).
    The date result must be identical (next Friday), confirming no regression.
    """
    result = resolve_relative_date("viernes", TODAY)
    assert result == date(2026, 5, 1)
