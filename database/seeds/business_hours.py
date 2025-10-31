"""
Seed script for business_hours table.

Populates the database with the salon's operating hours:
- Monday: CLOSED
- Tuesday-Friday: 10:00 - 20:00
- Saturday: 9:00 - 14:00
- Sunday: CLOSED
"""

import asyncio
from typing import Any

from sqlalchemy import select

from database.connection import AsyncSessionLocal
from database.models import BusinessHours

# Business hours seed data
# Day of week: 0=Monday, 1=Tuesday, ..., 6=Sunday
BUSINESS_HOURS_DATA: list[dict[str, Any]] = [
    # Monday - CLOSED
    {
        "day_of_week": 0,
        "is_closed": True,
        "start_hour": None,
        "start_minute": 0,
        "end_hour": None,
        "end_minute": 0,
    },
    # Tuesday - 10:00 to 20:00
    {
        "day_of_week": 1,
        "is_closed": False,
        "start_hour": 10,
        "start_minute": 0,
        "end_hour": 20,
        "end_minute": 0,
    },
    # Wednesday - 10:00 to 20:00
    {
        "day_of_week": 2,
        "is_closed": False,
        "start_hour": 10,
        "start_minute": 0,
        "end_hour": 20,
        "end_minute": 0,
    },
    # Thursday - 10:00 to 20:00
    {
        "day_of_week": 3,
        "is_closed": False,
        "start_hour": 10,
        "start_minute": 0,
        "end_hour": 20,
        "end_minute": 0,
    },
    # Friday - 10:00 to 20:00
    {
        "day_of_week": 4,
        "is_closed": False,
        "start_hour": 10,
        "start_minute": 0,
        "end_hour": 20,
        "end_minute": 0,
    },
    # Saturday - 9:00 to 14:00
    {
        "day_of_week": 5,
        "is_closed": False,
        "start_hour": 9,
        "start_minute": 0,
        "end_hour": 14,
        "end_minute": 0,
    },
    # Sunday - CLOSED
    {
        "day_of_week": 6,
        "is_closed": True,
        "start_hour": None,
        "start_minute": 0,
        "end_hour": None,
        "end_minute": 0,
    },
]


async def seed_business_hours() -> None:
    """
    Seed the business_hours table with salon operating hours.

    Checks if each day's hours already exist before inserting.
    Uses UPSERT logic to update existing entries or create new ones.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            created_count = 0
            updated_count = 0

            for hours_data in BUSINESS_HOURS_DATA:
                # Check if hours for this day already exist
                result = await session.execute(
                    select(BusinessHours).where(
                        BusinessHours.day_of_week == hours_data["day_of_week"]
                    )
                )
                existing_hours = result.scalar_one_or_none()

                day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                day_name = day_names[hours_data["day_of_week"]]

                if existing_hours is None:
                    # Create new business hours entry
                    business_hours = BusinessHours(**hours_data)
                    session.add(business_hours)
                    created_count += 1

                    if hours_data["is_closed"]:
                        print(f"✓ Created: {day_name} - CLOSED")
                    else:
                        print(
                            f"✓ Created: {day_name} - "
                            f"{hours_data['start_hour']:02d}:{hours_data['start_minute']:02d} to "
                            f"{hours_data['end_hour']:02d}:{hours_data['end_minute']:02d}"
                        )
                else:
                    # Update existing hours
                    existing_hours.is_closed = hours_data["is_closed"]
                    existing_hours.start_hour = hours_data["start_hour"]
                    existing_hours.start_minute = hours_data["start_minute"]
                    existing_hours.end_hour = hours_data["end_hour"]
                    existing_hours.end_minute = hours_data["end_minute"]
                    updated_count += 1

                    if hours_data["is_closed"]:
                        print(f"⊙ Updated: {day_name} - CLOSED")
                    else:
                        print(
                            f"⊙ Updated: {day_name} - "
                            f"{hours_data['start_hour']:02d}:{hours_data['start_minute']:02d} to "
                            f"{hours_data['end_hour']:02d}:{hours_data['end_minute']:02d}"
                        )

        # Commit all changes
        await session.commit()
        print(f"\n✓ Seeding complete!")
        print(f"  Created: {created_count} entries")
        print(f"  Updated: {updated_count} entries")
        print(f"  Total: {len(BUSINESS_HOURS_DATA)} days configured")


if __name__ == "__main__":
    print("Seeding business_hours table...")
    print("=" * 60)
    asyncio.run(seed_business_hours())
