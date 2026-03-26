"""
Unit tests — Notes field in GCal event descriptions.

Tests for T-11 + T-12 (notes-feature):
- push_appointment_to_gcal includes "Notas: {notes}" in description when notes are set
- push_appointment_to_gcal omits "Notas:" when notes are None or empty string
- Notes are truncated at 500 characters

Strategy: mock _get_stylist_calendar_id, _get_calendar_service, and
_update_appointment_gcal_id so the full push_appointment_to_gcal() function runs
through its description-building logic without hitting the network or DB.

asyncio_mode = "auto" (set in pyproject.toml) — no @pytest.mark.asyncio needed.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

MADRID_TZ = ZoneInfo("Europe/Madrid")


def _make_fake_start_time() -> datetime:
    return datetime(2026, 4, 1, 10, 0, tzinfo=MADRID_TZ)


def _make_mock_service() -> MagicMock:
    """Build a MagicMock that mimics the Google Calendar service API chain.

    Captures the event_body passed to events().insert().execute() so tests
    can inspect the description that was built.
    """
    mock_service = MagicMock()
    mock_event = {"id": "fake-gcal-event-id"}
    (mock_service.events.return_value.insert.return_value.execute.return_value) = mock_event
    return mock_service


def _captured_event_body(mock_service: MagicMock) -> dict:
    """Extract the event body that was passed to events().insert(body=...)."""
    insert_call = mock_service.events.return_value.insert
    call_kwargs = insert_call.call_args.kwargs
    return call_kwargs.get("body", {})


class TestGCalNotesDescription:
    """REQ-4: Notes included in GCal event description when present."""

    async def _call_push(self, notes) -> tuple[MagicMock, str | None]:
        """Helper: call push_appointment_to_gcal with the given notes.

        Returns (mock_service, description_string).
        """
        from agent.services.gcal_push_service import push_appointment_to_gcal

        mock_service = _make_mock_service()
        appt_id = uuid4()
        stylist_id = uuid4()
        calendar_id = "stylist-calendar@group.calendar.google.com"

        with (
            patch(
                "agent.services.gcal_push_service._get_stylist_calendar_id",
                new=AsyncMock(return_value=calendar_id),
            ),
            patch(
                "agent.services.gcal_push_service._get_calendar_service",
                new=AsyncMock(return_value=mock_service),
            ),
            patch(
                "agent.services.gcal_push_service._update_appointment_gcal_id",
                new=AsyncMock(),
            ),
            # run_in_executor must actually call the callable so the event body is built
            patch(
                "agent.services.gcal_push_service.asyncio.get_event_loop",
                return_value=_make_fake_event_loop(mock_service),
            ),
        ):
            await push_appointment_to_gcal(
                appointment_id=appt_id,
                stylist_id=stylist_id,
                customer_name="María García",
                service_names="Corte de Señora",
                start_time=_make_fake_start_time(),
                duration_minutes=60,
                status="pending",
                notes=notes,
            )

        event_body = _captured_event_body(mock_service)
        description = event_body.get("description", "")
        return mock_service, description

    def test_notes_in_description_when_present(self):
        """push_appointment_to_gcal with notes → 'Notas: {notes}' in description."""
        import asyncio

        _, description = asyncio.get_event_loop().run_until_complete(
            self._call_push(notes="alergia al polvo")
        )

        assert "Notas: alergia al polvo" in description

    def test_notes_absent_when_none(self):
        """push_appointment_to_gcal with notes=None → 'Notas:' NOT in description."""
        import asyncio

        _, description = asyncio.get_event_loop().run_until_complete(self._call_push(notes=None))

        assert "Notas:" not in description

    def test_notes_absent_when_empty_string(self):
        """push_appointment_to_gcal with notes='' → 'Notas:' NOT in description."""
        import asyncio

        _, description = asyncio.get_event_loop().run_until_complete(self._call_push(notes=""))

        assert "Notas:" not in description

    def test_notes_truncated_at_500_chars(self):
        """push_appointment_to_gcal with 600-char notes → description contains ≤500 chars of notes."""
        import asyncio

        long_notes = "x" * 600
        _, description = asyncio.get_event_loop().run_until_complete(
            self._call_push(notes=long_notes)
        )

        assert "Notas:" in description
        # Extract the notes line to check its length
        for line in description.split("\n"):
            if line.startswith("Notas:"):
                # "Notas: " is 7 chars; the rest is the truncated note
                notes_content = line[len("Notas: ") :]
                assert len(notes_content) <= 500, (
                    f"Notes content should be ≤500 chars but got {len(notes_content)}"
                )
                break
        else:
            pytest.fail("'Notas:' line not found in description")


def _make_fake_event_loop(mock_service: MagicMock):
    """Create a fake event loop whose run_in_executor actually calls the function.

    This is needed because push_appointment_to_gcal wraps the GCal API call in
    loop.run_in_executor(None, create_event), which would otherwise return a
    coroutine that never executes under our mock.
    """
    import asyncio

    class FakeLoop:
        async def run_in_executor(self, executor, fn):
            # Call the sync function directly (no thread pool) to capture event body
            return fn()

    return FakeLoop()
