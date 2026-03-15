"""
Unit tests for stylist seed script slug-based reconciliation.

Tests cover the Rev 2 seed behavior:
- google_calendar_id is NEVER set by the seed (admin-only assignment)
- Reconciliation uses slug as the stable identity key
- Running the seed multiple times is fully idempotent
- Existing google_calendar_id values are NEVER overwritten by the seed
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from uuid import uuid4

from database.models import ServiceCategory, Stylist
from database.seeds.stylists import STYLISTS_DATA, seed_stylists


# ============================================================================
# Helpers
# ============================================================================


def _make_existing_stylist(slug: str, name: str, category: ServiceCategory, calendar_id=None):
    """Build a MagicMock that quacks like a Stylist ORM row."""
    stylist = MagicMock(spec=Stylist)
    stylist.id = uuid4()
    stylist.slug = slug
    stylist.name = name
    stylist.category = category
    stylist.google_calendar_id = calendar_id
    stylist.is_active = True
    return stylist


# ============================================================================
# Task 5.1.1 — seed creates rows with correct slugs, no google_calendar_id set
# ============================================================================


@pytest.mark.asyncio
async def test_seed_creates_stylists_with_slug():
    """
    GIVEN an empty database
    WHEN seed_stylists() is executed
    THEN each stylist is created with its correct slug and google_calendar_id=None.
    """
    added_stylists: list[MagicMock] = []

    def capture_add(obj):
        added_stylists.append(obj)

    mock_session = AsyncMock()
    mock_session.add = MagicMock(side_effect=capture_add)
    mock_session.commit = AsyncMock()

    # Simulate: no existing stylist found for any slug → scalar_one_or_none returns None
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    # Patch the async context managers
    mock_begin_ctx = AsyncMock()
    mock_begin_ctx.__aenter__ = AsyncMock(return_value=None)
    mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin_ctx)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("database.seeds.stylists.AsyncSessionLocal", return_value=mock_session_ctx):
        await seed_stylists()

    # Verify the correct number of stylists were added
    assert len(added_stylists) == len(STYLISTS_DATA), (
        f"Expected {len(STYLISTS_DATA)} stylists added, got {len(added_stylists)}"
    )

    # Build a map from slug → added stylist for assertion
    slug_map = {s.slug: s for s in added_stylists}

    for seed_entry in STYLISTS_DATA:
        slug = seed_entry["slug"]
        assert slug in slug_map, f"Stylist with slug '{slug}' was not created"
        created = slug_map[slug]
        # google_calendar_id must be None — seed never assigns it
        assert created.google_calendar_id is None, (
            f"Stylist '{slug}' should have google_calendar_id=None, "
            f"got {created.google_calendar_id!r}"
        )
        assert created.name == seed_entry["name"], (
            f"Name mismatch for slug '{slug}'"
        )
        assert created.category == seed_entry["category"], (
            f"Category mismatch for slug '{slug}'"
        )


# ============================================================================
# Task 5.1.2 — running seed twice doesn't create duplicates (no calendar assigned)
# ============================================================================


@pytest.mark.asyncio
async def test_seed_is_idempotent_no_calendar():
    """
    GIVEN stylists already exist in the database with google_calendar_id=None
    WHEN seed_stylists() is executed again
    THEN no new rows are inserted; existing rows are updated in-place.
    """
    # Pre-build existing stylists matching STYLISTS_DATA exactly
    existing = {
        entry["slug"]: _make_existing_stylist(
            slug=entry["slug"],
            name=entry["name"],
            category=entry["category"],
            calendar_id=None,
        )
        for entry in STYLISTS_DATA
    }

    added_stylists: list = []

    def capture_add(obj):
        added_stylists.append(obj)

    mock_session = AsyncMock()
    mock_session.add = MagicMock(side_effect=capture_add)
    mock_session.commit = AsyncMock()

    def make_result(slug):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing[slug]
        return mock_result

    # Return the existing row for every slug lookup
    call_index = [0]

    async def fake_execute(stmt):
        entry = STYLISTS_DATA[call_index[0] % len(STYLISTS_DATA)]
        call_index[0] += 1
        return make_result(entry["slug"])

    mock_session.execute = fake_execute

    mock_begin_ctx = AsyncMock()
    mock_begin_ctx.__aenter__ = AsyncMock(return_value=None)
    mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin_ctx)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("database.seeds.stylists.AsyncSessionLocal", return_value=mock_session_ctx):
        await seed_stylists()

    # Nothing should be added (existing rows found for every slug)
    assert len(added_stylists) == 0, (
        f"Expected 0 new stylists (idempotent), got {len(added_stylists)}"
    )

    # Verify each existing row was mutated with name/category/is_active but NOT calendar
    for entry in STYLISTS_DATA:
        stylist = existing[entry["slug"]]
        assert stylist.name == entry["name"]
        assert stylist.category == entry["category"]
        assert stylist.is_active == entry["is_active"]
        # google_calendar_id must remain None — seed never assigns it
        assert stylist.google_calendar_id is None


# ============================================================================
# Task 5.1.3 — seed runs after calendar reassignment → calendar preserved
# ============================================================================


@pytest.mark.asyncio
async def test_seed_is_idempotent_after_calendar_reassignment():
    """
    GIVEN Victor already exists with google_calendar_id = "victor-cal-id"
    WHEN seed_stylists() is executed
    THEN Victor's google_calendar_id is STILL "victor-cal-id" after the seed.
    """
    # Build all existing stylists; Victor has a calendar assigned
    existing = {}
    for entry in STYLISTS_DATA:
        cal = "victor-cal-id" if entry["slug"] == "victor" else None
        existing[entry["slug"]] = _make_existing_stylist(
            slug=entry["slug"],
            name=entry["name"],
            category=entry["category"],
            calendar_id=cal,
        )

    added_stylists: list = []
    mock_session = AsyncMock()
    mock_session.add = MagicMock(side_effect=added_stylists.append)
    mock_session.commit = AsyncMock()

    call_index = [0]

    async def fake_execute(stmt):
        entry = STYLISTS_DATA[call_index[0] % len(STYLISTS_DATA)]
        call_index[0] += 1
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing[entry["slug"]]
        return mock_result

    mock_session.execute = fake_execute

    mock_begin_ctx = AsyncMock()
    mock_begin_ctx.__aenter__ = AsyncMock(return_value=None)
    mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin_ctx)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("database.seeds.stylists.AsyncSessionLocal", return_value=mock_session_ctx):
        await seed_stylists()

    # No new rows should be inserted
    assert len(added_stylists) == 0

    # Victor's calendar must survive the seed run
    victor = existing["victor"]
    assert victor.google_calendar_id == "victor-cal-id", (
        "Seed overwrote Victor's google_calendar_id — that is forbidden"
    )

    # All other stylists still have None (seed never assigned anything)
    for entry in STYLISTS_DATA:
        if entry["slug"] != "victor":
            assert existing[entry["slug"]].google_calendar_id is None


# ============================================================================
# Task 5.1.4 — seed must not touch google_calendar_id even when set
# ============================================================================


@pytest.mark.asyncio
async def test_seed_never_overwrites_calendar_id():
    """
    GIVEN ALL stylists already have google_calendar_id set to non-None values
    WHEN seed_stylists() is executed
    THEN every google_calendar_id is preserved exactly as-is.
    """
    original_calendars = {entry["slug"]: f"cal-{entry['slug']}@g.com" for entry in STYLISTS_DATA}
    existing = {
        entry["slug"]: _make_existing_stylist(
            slug=entry["slug"],
            name=entry["name"],
            category=entry["category"],
            calendar_id=original_calendars[entry["slug"]],
        )
        for entry in STYLISTS_DATA
    }

    added_stylists: list = []
    mock_session = AsyncMock()
    mock_session.add = MagicMock(side_effect=added_stylists.append)
    mock_session.commit = AsyncMock()

    call_index = [0]

    async def fake_execute(stmt):
        entry = STYLISTS_DATA[call_index[0] % len(STYLISTS_DATA)]
        call_index[0] += 1
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing[entry["slug"]]
        return mock_result

    mock_session.execute = fake_execute

    mock_begin_ctx = AsyncMock()
    mock_begin_ctx.__aenter__ = AsyncMock(return_value=None)
    mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin_ctx)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("database.seeds.stylists.AsyncSessionLocal", return_value=mock_session_ctx):
        await seed_stylists()

    # No new rows
    assert len(added_stylists) == 0

    # Every calendar must be unchanged
    for entry in STYLISTS_DATA:
        slug = entry["slug"]
        expected_cal = original_calendars[slug]
        actual_cal = existing[slug].google_calendar_id
        assert actual_cal == expected_cal, (
            f"Seed overwrote google_calendar_id for slug '{slug}': "
            f"expected {expected_cal!r}, got {actual_cal!r}"
        )
