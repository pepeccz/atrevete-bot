"""
Seed script for holidays table.

Populates the database with Spanish national holidays and
Community of Madrid regional holidays for 2025.

These dates represent salon-wide closures where no bookings are allowed.
"""

import asyncio
from datetime import date
from typing import Any

from sqlalchemy import select

from database.connection import AsyncSessionLocal
from database.models import Holiday

# Spanish holidays for 2025 (National + Community of Madrid)
# Source: BOE + Comunidad de Madrid official calendar
HOLIDAYS_2025: list[dict[str, Any]] = [
    # National Holidays (Festivos Nacionales)
    {"date": date(2025, 1, 1), "name": "Año Nuevo"},
    {"date": date(2025, 1, 6), "name": "Día de Reyes / Epifanía"},
    {"date": date(2025, 4, 17), "name": "Jueves Santo"},
    {"date": date(2025, 4, 18), "name": "Viernes Santo"},
    {"date": date(2025, 5, 1), "name": "Día del Trabajador"},
    {"date": date(2025, 8, 15), "name": "Asunción de la Virgen"},
    {"date": date(2025, 10, 12), "name": "Fiesta Nacional de España"},
    {"date": date(2025, 11, 1), "name": "Día de Todos los Santos"},
    {"date": date(2025, 12, 6), "name": "Día de la Constitución"},
    {"date": date(2025, 12, 8), "name": "Inmaculada Concepción"},
    {"date": date(2025, 12, 25), "name": "Navidad"},

    # Community of Madrid Regional Holidays (Festivos Comunidad de Madrid)
    {"date": date(2025, 5, 2), "name": "Día de la Comunidad de Madrid"},

    # Optional local holidays (can be customized per salon)
    # These are commonly observed by businesses even if not official:
    {"date": date(2025, 12, 24), "name": "Nochebuena"},
    {"date": date(2025, 12, 31), "name": "Nochevieja"},
]

# Add 2026 holidays for future planning
HOLIDAYS_2026: list[dict[str, Any]] = [
    # National Holidays (Festivos Nacionales)
    {"date": date(2026, 1, 1), "name": "Año Nuevo"},
    {"date": date(2026, 1, 6), "name": "Día de Reyes / Epifanía"},
    {"date": date(2026, 4, 2), "name": "Jueves Santo"},
    {"date": date(2026, 4, 3), "name": "Viernes Santo"},
    {"date": date(2026, 5, 1), "name": "Día del Trabajador"},
    {"date": date(2026, 8, 15), "name": "Asunción de la Virgen"},
    {"date": date(2026, 10, 12), "name": "Fiesta Nacional de España"},
    {"date": date(2026, 11, 1), "name": "Día de Todos los Santos"},  # Falls on Sunday
    {"date": date(2026, 11, 2), "name": "Día de Todos los Santos (trasladado)"},  # Moved to Monday
    {"date": date(2026, 12, 6), "name": "Día de la Constitución"},  # Falls on Sunday
    {"date": date(2026, 12, 7), "name": "Día de la Constitución (trasladado)"},  # Moved to Monday
    {"date": date(2026, 12, 8), "name": "Inmaculada Concepción"},
    {"date": date(2026, 12, 25), "name": "Navidad"},

    # Community of Madrid Regional Holidays
    {"date": date(2026, 5, 2), "name": "Día de la Comunidad de Madrid"},  # Falls on Saturday

    # Optional local holidays
    {"date": date(2026, 12, 24), "name": "Nochebuena"},
    {"date": date(2026, 12, 31), "name": "Nochevieja"},
]

# Combine all holidays
ALL_HOLIDAYS = HOLIDAYS_2025 + HOLIDAYS_2026


async def seed_holidays() -> None:
    """
    Seed the holidays table with Spanish holidays.

    Checks if each holiday already exists before inserting.
    Uses UPSERT logic to update existing entries or create new ones.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            created_count = 0
            updated_count = 0
            skipped_count = 0

            for holiday_data in ALL_HOLIDAYS:
                # Check if holiday for this date already exists
                result = await session.execute(
                    select(Holiday).where(Holiday.date == holiday_data["date"])
                )
                existing_holiday = result.scalar_one_or_none()

                if existing_holiday is None:
                    # Create new holiday entry
                    holiday = Holiday(
                        date=holiday_data["date"],
                        name=holiday_data["name"],
                        is_all_day=True,
                    )
                    session.add(holiday)
                    created_count += 1
                    print(f"✓ Created: {holiday_data['date']} - {holiday_data['name']}")
                else:
                    # Update existing holiday name if different
                    if existing_holiday.name != holiday_data["name"]:
                        existing_holiday.name = holiday_data["name"]
                        updated_count += 1
                        print(f"⊙ Updated: {holiday_data['date']} - {holiday_data['name']}")
                    else:
                        skipped_count += 1
                        print(f"- Skipped: {holiday_data['date']} - {holiday_data['name']} (already exists)")

        # Commit all changes
        await session.commit()
        print(f"\n✓ Seeding complete!")
        print(f"  Created: {created_count} holidays")
        print(f"  Updated: {updated_count} holidays")
        print(f"  Skipped: {skipped_count} holidays (already exist)")
        print(f"  Total in DB: {created_count + updated_count + skipped_count} holidays")


async def clear_holidays() -> None:
    """
    Clear all holidays from the database.
    Use with caution - this removes all holiday data.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(select(Holiday))
            holidays = result.scalars().all()
            count = len(holidays)

            for holiday in holidays:
                await session.delete(holiday)

        await session.commit()
        print(f"✓ Cleared {count} holidays from database")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--clear":
        print("Clearing holidays table...")
        print("=" * 60)
        asyncio.run(clear_holidays())
    else:
        print("Seeding holidays table...")
        print("=" * 60)
        asyncio.run(seed_holidays())
