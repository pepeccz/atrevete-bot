"""
Seed script for blocking_events table.

Creates 4 representative blocking events to exercise all BlockingEventType values:
  1. VACATION — Marta, 7-day span starting next Monday
  2. BREAK    — Pilar, single recurring-series-style daily 14:00–15:00 break (4 occurrences)
  3. MEETING  — Victor, single 1-hour block next Tuesday morning
  4. PERSONAL — Harolyn, single 30-minute block next Friday afternoon

Idempotent: each row is skipped when (stylist_id, start_time) already exists.
Pattern mirrors database/seeds/holidays.py.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from database.connection import AsyncSessionLocal
from database.models import BlockingEvent, BlockingEventType, Stylist

MADRID_TZ = ZoneInfo("Europe/Madrid")


def _next_weekday(weekday: int, from_date: date | None = None) -> date:
    """Return the next occurrence of *weekday* (0=Mon, 6=Sun) on or after *from_date*."""
    base = from_date or date.today()
    days_ahead = (weekday - base.weekday()) % 7
    return base + timedelta(days=days_ahead or 7)


def _madrid_dt(d: date, hour: int, minute: int = 0) -> datetime:
    """Build a timezone-aware datetime in Europe/Madrid for the given date/time."""
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=MADRID_TZ)


def _build_seed_rows(stylists: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Compute seed rows relative to today so the dates are always 'in the future'
    and re-running the seed on a different day still produces valid data.

    Returns a list of dicts that map to BlockingEvent fields.
    """
    next_monday = _next_weekday(0)  # Monday
    next_tuesday = _next_weekday(1)  # Tuesday
    next_friday = _next_weekday(4)  # Friday

    rows: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # 1. VACATION — Marta: 7-day span Mon–Sun
    # ------------------------------------------------------------------ #
    marta_id = stylists.get("marta")
    if marta_id:
        for delta in range(7):
            day = next_monday + timedelta(days=delta)
            rows.append(
                {
                    "stylist_id": marta_id,
                    "title": "Vacaciones",
                    "description": "Vacaciones anuales de Marta",
                    "start_time": _madrid_dt(day, 9),
                    "end_time": _madrid_dt(day, 21),
                    "event_type": BlockingEventType.VACATION,
                }
            )

    # ------------------------------------------------------------------ #
    # 2. BREAK — Pilar: 4 x weekly Mon–Fri 14:00–15:00
    #    Stored as individual non-recurring blocking events (seed only,
    #    not linked to a recurring_series) to keep the seed simple.
    # ------------------------------------------------------------------ #
    pilar_id = stylists.get("pilar")
    if pilar_id:
        for week_offset in range(4):
            for day_offset in range(5):  # Mon=0 … Fri=4
                day = next_monday + timedelta(weeks=week_offset, days=day_offset)
                rows.append(
                    {
                        "stylist_id": pilar_id,
                        "title": "Descanso almuerzo",
                        "description": "Pausa para comer",
                        "start_time": _madrid_dt(day, 14),
                        "end_time": _madrid_dt(day, 15),
                        "event_type": BlockingEventType.BREAK,
                    }
                )

    # ------------------------------------------------------------------ #
    # 3. MEETING — Victor: single 1h block next Tuesday 09:00–10:00
    # ------------------------------------------------------------------ #
    victor_id = stylists.get("victor")
    if victor_id:
        rows.append(
            {
                "stylist_id": victor_id,
                "title": "Reunión de equipo",
                "description": "Reunión semanal de coordinación",
                "start_time": _madrid_dt(next_tuesday, 9),
                "end_time": _madrid_dt(next_tuesday, 10),
                "event_type": BlockingEventType.MEETING,
            }
        )

    # ------------------------------------------------------------------ #
    # 4. PERSONAL — Harolyn: single 30min block next Friday 16:00–16:30
    # ------------------------------------------------------------------ #
    harolyn_id = stylists.get("harolyn")
    if harolyn_id:
        rows.append(
            {
                "stylist_id": harolyn_id,
                "title": "Asunto personal",
                "description": None,
                "start_time": _madrid_dt(next_friday, 16),
                "end_time": _madrid_dt(next_friday, 16, 30),
                "event_type": BlockingEventType.PERSONAL,
            }
        )

    return rows


async def seed_blocking_events() -> None:
    """
    Seed the blocking_events table with representative rows.

    Idempotent: uses (stylist_id, start_time) as the natural key to avoid
    duplicate inserts.  Re-running the script on the same day is safe.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Resolve stylist ids by slug
            stylist_result = await session.execute(
                select(Stylist).where(Stylist.slug.in_(["marta", "pilar", "victor", "harolyn"]))
            )
            stylists_by_slug: dict[str, Any] = {
                s.slug: s.id for s in stylist_result.scalars().all()
            }

            if not stylists_by_slug:
                print("⚠ No stylists found — run seed_stylists first.")
                return

            seed_rows = _build_seed_rows(stylists_by_slug)

            created_count = 0
            skipped_count = 0

            for row in seed_rows:
                # Idempotency guard: skip if (stylist_id, start_time) already exists
                existing_result = await session.execute(
                    select(BlockingEvent).where(
                        BlockingEvent.stylist_id == row["stylist_id"],
                        BlockingEvent.start_time == row["start_time"],
                    )
                )
                if existing_result.scalar_one_or_none() is not None:
                    skipped_count += 1
                    continue

                event = BlockingEvent(
                    stylist_id=row["stylist_id"],
                    title=row["title"],
                    description=row["description"],
                    start_time=row["start_time"],
                    end_time=row["end_time"],
                    event_type=row["event_type"],
                )
                session.add(event)
                created_count += 1
                print(
                    f"  + Created: {row['event_type'].value} for {row['start_time'].date()} ({row['title']})"
                )

        await session.commit()
        print("\n✓ Blocking events seeding complete!")
        print(f"  Created: {created_count}")
        print(f"  Skipped: {skipped_count} (already exist)")
        print(f"  Total rows attempted: {len(seed_rows)}")


async def clear_blocking_events() -> None:
    """Remove all seed blocking events. Use with caution."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(select(BlockingEvent))
            events = result.scalars().all()
            count = len(events)
            for ev in events:
                await session.delete(ev)

        await session.commit()
        print(f"✓ Cleared {count} blocking events from database")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--clear":
        print("Clearing blocking_events table...")
        print("=" * 60)
        asyncio.run(clear_blocking_events())
    else:
        print("Seeding blocking_events table...")
        print("=" * 60)
        asyncio.run(seed_blocking_events())
