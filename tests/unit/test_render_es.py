"""Unit tests for agent/workers/notification_handlers/_render_es.py.

Covers sdd/context-coherence FIX 2: shared Madrid-TZ + Spanish date/time
rendering used by all 3 notification handlers (confirm_48h, reminder_24h,
final_warning), including a DST-edge case where a UTC timestamp crosses the
calendar date boundary once converted to Europe/Madrid local time.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agent.workers.notification_handlers._render_es import (
    MADRID_TZ,
    fecha_es,
    hora_es,
    to_madrid,
)


def test_to_madrid_converts_utc_to_madrid_winter_offset():
    # Winter (CET, UTC+1): no DST.
    dt_utc = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
    dt_madrid = to_madrid(dt_utc)

    assert dt_madrid.tzinfo is not None
    assert dt_madrid.utcoffset().total_seconds() == 3600  # +1h
    assert dt_madrid.hour == 11


def test_to_madrid_converts_utc_to_madrid_summer_offset():
    # Summer (CEST, UTC+2): DST active.
    dt_utc = datetime(2026, 7, 5, 10, 0, tzinfo=UTC)
    dt_madrid = to_madrid(dt_utc)

    assert dt_madrid.utcoffset().total_seconds() == 7200  # +2h
    assert dt_madrid.hour == 12


def test_to_madrid_returns_none_for_none_input():
    assert to_madrid(None) is None


def test_dst_edge_utc_timestamp_crosses_date_boundary_in_madrid_winter():
    """A late-evening UTC timestamp in winter (CET +1) rolls into the next
    calendar day once rendered in Madrid local time."""
    dt_utc = datetime(2026, 1, 15, 23, 30, tzinfo=UTC)  # 2026-01-15 23:30 UTC
    dt_madrid = to_madrid(dt_utc)

    assert dt_madrid.date().isoformat() == "2026-01-16"
    assert fecha_es(dt_madrid) == "viernes 16 de enero"
    assert hora_es(dt_madrid) == "00:30"


def test_dst_edge_utc_timestamp_crosses_date_boundary_in_madrid_summer():
    """A late-evening UTC timestamp in summer (CEST +2) rolls into the next
    calendar day once rendered in Madrid local time."""
    dt_utc = datetime(2026, 7, 5, 22, 30, tzinfo=UTC)  # 2026-07-05 22:30 UTC
    dt_madrid = to_madrid(dt_utc)

    assert dt_madrid.date().isoformat() == "2026-07-06"
    assert fecha_es(dt_madrid) == "lunes 6 de julio"
    assert hora_es(dt_madrid) == "00:30"


def test_fecha_es_includes_day_name_day_number_and_month_name():
    dt = datetime(2026, 7, 8, 9, 0, tzinfo=MADRID_TZ)
    assert fecha_es(dt) == "miércoles 8 de julio"


def test_hora_es_renders_hh_mm():
    dt = datetime(2026, 7, 8, 9, 5, tzinfo=MADRID_TZ)
    assert hora_es(dt) == "09:05"
