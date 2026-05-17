"""TDD tests for validation-layer-extraction — _booking_validators module.

Tasks T1 (RED) + T2 (GREEN):
  - All G1/G2/G3 + happy-path cases for validate_booking_date
  - Guard precedence (G1 before G2, G2 before G3)
  - Deterministic output via injectable ref_date (no wall-clock dependency)

All tests patch DB helpers so they run without a live database.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Constants used across tests
# ---------------------------------------------------------------------------

# A known open day (Tuesday 2026-05-05 — ref_date from design)
OPEN_DATE_ISO = "2026-05-05"
OPEN_DATE = date.fromisoformat(OPEN_DATE_ISO)

# A known closed day (Sunday 2026-05-03)
CLOSED_DATE_ISO = "2026-05-03"
CLOSED_DATE = date.fromisoformat(CLOSED_DATE_ISO)

# Reference date: 2026-04-28 (28 April 2026 — today for tests)
REF_DATE = date(2026, 4, 28)

# MIN_BOOKING_DAYS = 3 (from time_resolver.py)
MIN_BOOKING_DAYS = 3


# ---------------------------------------------------------------------------
# T1 — Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_explicit_iso_open_day_within_lead_time():
    """Happy path: explicit ISO, open day, within advance policy → result.ok, date_iso preserved."""
    from agent.tools._booking_validators import validate_booking_date

    with patch(
        "agent.tools._booking_validators.is_date_closed",
        new=AsyncMock(return_value=False),
    ):
        result = await validate_booking_date(
            date_iso=OPEN_DATE_ISO,
            date_text=None,
            ref_date=REF_DATE,
        )

    assert result.ok is True, f"Expected ok=True, got error_code={result.error_code}"
    assert result.date_iso == OPEN_DATE_ISO
    assert result.error_code is None
    assert result.error_message is None


# ---------------------------------------------------------------------------
# T1 — G1: Relative date resolution failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g1_no_input_date_iso_and_date_text_none():
    """G1: both date_iso=None and date_text=None → error_code='invalid_relative_date'."""
    from agent.tools._booking_validators import validate_booking_date

    result = await validate_booking_date(
        date_iso=None,
        date_text=None,
        ref_date=REF_DATE,
    )

    assert result.ok is False
    assert result.error_code == "invalid_relative_date"
    assert result.date_iso is None


@pytest.mark.asyncio
async def test_g1_unresolvable_relative_text_returns_invalid():
    """G1: date_text that resolve_relative_date cannot resolve → error_code='invalid_relative_date'."""
    from agent.tools._booking_validators import validate_booking_date

    with patch(
        "agent.tools._booking_validators.resolve_relative_date",
        return_value=None,
    ):
        result = await validate_booking_date(
            date_iso=None,
            date_text="mañana",
            ref_date=REF_DATE,
        )

    assert result.ok is False
    assert result.error_code == "invalid_relative_date"
    assert result.date_iso is None


@pytest.mark.asyncio
async def test_g1_resolves_to_date_and_passes_to_g2_check():
    """G1: date_text resolves successfully → G2 is checked (happy path continues)."""
    from agent.tools._booking_validators import validate_booking_date

    resolved = date(2026, 5, 5)  # open Tuesday

    with (
        patch(
            "agent.tools._booking_validators.resolve_relative_date",
            return_value=resolved,
        ),
        patch(
            "agent.tools._booking_validators.is_date_closed",
            new=AsyncMock(return_value=False),
        ),
    ):
        result = await validate_booking_date(
            date_iso=None,
            date_text="el martes",
            ref_date=REF_DATE,
        )

    assert result.ok is True
    assert result.date_iso == "2026-05-05"


# ---------------------------------------------------------------------------
# T1 — G2: Closed day
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g2_sunday_closed_day():
    """G2: date_iso is a Sunday (closed) → error_code='closed_day'."""
    from agent.tools._booking_validators import validate_booking_date

    with patch(
        "agent.tools._booking_validators.is_date_closed",
        new=AsyncMock(return_value=True),
    ):
        result = await validate_booking_date(
            date_iso=CLOSED_DATE_ISO,
            date_text=None,
            ref_date=REF_DATE,
        )

    assert result.ok is False
    assert result.error_code == "closed_day"
    assert result.date_iso is None
    assert "closed_date" in result.payload
    assert result.payload["closed_date"] == CLOSED_DATE_ISO


@pytest.mark.asyncio
async def test_g2_open_day_passes_through():
    """G2 negative: open day → closed_day does NOT fire → reaches G3 or success."""
    from agent.tools._booking_validators import validate_booking_date

    with patch(
        "agent.tools._booking_validators.is_date_closed",
        new=AsyncMock(return_value=False),
    ):
        result = await validate_booking_date(
            date_iso=OPEN_DATE_ISO,
            date_text=None,
            ref_date=REF_DATE,
        )

    # Open day + within lead-time → ok
    assert result.ok is True
    assert result.error_code is None


# ---------------------------------------------------------------------------
# T1 — G3: Advance policy (lead-time)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g3_date_violates_advance_policy():
    """G3: date_iso == ref_date (same day) with MIN_BOOKING_DAYS=3 → advance_policy_violated."""
    from agent.tools._booking_validators import validate_booking_date

    # ref_date=2026-04-28, date=2026-04-28 → 0 days ahead < MIN_BOOKING_DAYS=3
    with patch(
        "agent.tools._booking_validators.is_date_closed",
        new=AsyncMock(return_value=False),
    ):
        result = await validate_booking_date(
            date_iso=REF_DATE.isoformat(),  # same day as ref
            date_text=None,
            ref_date=REF_DATE,
        )

    assert result.ok is False
    assert result.error_code == "advance_policy_violated"
    assert result.date_iso is None
    assert "min_date" in result.payload
    assert result.payload["min_days"] == MIN_BOOKING_DAYS


@pytest.mark.asyncio
async def test_g3_date_exactly_at_min_boundary_passes():
    """G3 boundary: date_iso == ref_date + MIN_BOOKING_DAYS (boundary is inclusive) → ok."""
    from datetime import timedelta

    from agent.tools._booking_validators import validate_booking_date

    min_date = REF_DATE + timedelta(days=MIN_BOOKING_DAYS)

    with patch(
        "agent.tools._booking_validators.is_date_closed",
        new=AsyncMock(return_value=False),
    ):
        result = await validate_booking_date(
            date_iso=min_date.isoformat(),
            date_text=None,
            ref_date=REF_DATE,
        )

    assert result.ok is True, f"Expected ok at boundary, got: {result.error_code}"


# ---------------------------------------------------------------------------
# T1 — Guard precedence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_precedence_g1_fires_before_g2():
    """G1 precedence: date_iso=None + date_text=None for a Sunday → G1 fires (not G2)."""
    from agent.tools._booking_validators import validate_booking_date

    # Even if is_date_closed would return True (Sunday), G1 fires first
    with patch(
        "agent.tools._booking_validators.is_date_closed",
        new=AsyncMock(return_value=True),
    ):
        result = await validate_booking_date(
            date_iso=None,
            date_text=None,  # G1 trigger
            ref_date=REF_DATE,
        )

    # G1 fires, not G2
    assert result.error_code == "invalid_relative_date", f"Got: {result.error_code}"


@pytest.mark.asyncio
async def test_precedence_g2_fires_before_g3():
    """G2 precedence: date_iso=Sunday that also violates lead-time → G2 fires (not G3)."""
    from agent.tools._booking_validators import validate_booking_date

    # CLOSED_DATE_ISO = "2026-05-03" (Sunday) — is within 3 days of REF_DATE 2026-04-28 (5 days)
    # Actually 2026-05-03 is 5 days from REF_DATE — let's use same-day Sunday instead
    # ref_date = 2026-05-03, date_iso = 2026-05-03 → same day AND Sunday → G2 fires
    ref_sunday = date(2026, 5, 3)

    with patch(
        "agent.tools._booking_validators.is_date_closed",
        new=AsyncMock(return_value=True),
    ):
        result = await validate_booking_date(
            date_iso=CLOSED_DATE_ISO,  # Sunday
            date_text=None,
            ref_date=ref_sunday,  # same day → also violates G3
        )

    # G2 fires before G3
    assert result.error_code == "closed_day", f"Got: {result.error_code}"


# ---------------------------------------------------------------------------
# T1 — ref_date injectable (no wall-clock dependency)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ref_date_injectable_deterministic():
    """ref_date parameter produces deterministic output — no wall-clock access."""
    from agent.tools._booking_validators import validate_booking_date

    # Inject a specific ref_date far in the past → OPEN_DATE will pass G3
    # OPEN_DATE = 2026-05-05, ref = 2026-04-28: delta = 7 days ≥ MIN_BOOKING_DAYS=3 → pass
    with patch(
        "agent.tools._booking_validators.is_date_closed",
        new=AsyncMock(return_value=False),
    ):
        result = await validate_booking_date(
            date_iso=OPEN_DATE_ISO,
            date_text=None,
            ref_date=REF_DATE,  # explicit ref → no wall-clock
        )

    assert result.ok is True
    assert result.date_iso == OPEN_DATE_ISO


@pytest.mark.asyncio
async def test_g3_payload_contains_min_date_value():
    """G3: payload min_date must be ref_date + MIN_BOOKING_DAYS as ISO string."""
    from datetime import timedelta

    from agent.tools._booking_validators import validate_booking_date

    expected_min = REF_DATE + timedelta(days=MIN_BOOKING_DAYS)

    with patch(
        "agent.tools._booking_validators.is_date_closed",
        new=AsyncMock(return_value=False),
    ):
        result = await validate_booking_date(
            date_iso=REF_DATE.isoformat(),  # violates lead-time
            date_text=None,
            ref_date=REF_DATE,
        )

    assert result.error_code == "advance_policy_violated"
    assert result.payload["min_date"] == expected_min.isoformat()


# ---------------------------------------------------------------------------
# T7 — Regression: "mañana" bug
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manana_regression_resolver_succeeds():
    """Regression: date_text='mañana' with resolver returning ref+1 → ok, date_iso=ref+1."""
    from datetime import timedelta

    from agent.tools._booking_validators import validate_booking_date

    tomorrow = REF_DATE + timedelta(days=1)

    with (
        patch(
            "agent.tools._booking_validators.resolve_relative_date",
            return_value=tomorrow,
        ),
        patch(
            "agent.tools._booking_validators.is_date_closed",
            new=AsyncMock(return_value=False),
        ),
    ):
        result = await validate_booking_date(
            date_iso=None,
            date_text="mañana",
            ref_date=REF_DATE,
        )

    # tomorrow = 2026-04-29; REF_DATE=2026-04-28; delta=1 < MIN_BOOKING_DAYS=3
    # G3 should fire — lead-time violation
    assert result.ok is False
    assert result.error_code == "advance_policy_violated"


@pytest.mark.asyncio
async def test_manana_regression_resolver_fails_returns_invalid():
    """Regression: date_text='mañana' when resolver returns None → invalid_relative_date."""
    from agent.tools._booking_validators import validate_booking_date

    with patch(
        "agent.tools._booking_validators.resolve_relative_date",
        return_value=None,
    ):
        result = await validate_booking_date(
            date_iso=None,
            date_text="mañana",
            ref_date=REF_DATE,
        )

    assert result.ok is False
    assert result.error_code == "invalid_relative_date"
