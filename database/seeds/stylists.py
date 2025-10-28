"""
Seed script for stylists table.

Populates the database with 5 stylists:
- Pilar (Hairdressing)
- Marta (Both - Hairdressing + Aesthetics)
- Rosa (Aesthetics)
- Harol (Hairdressing)
- Víctor (Hairdressing)
"""

import asyncio
from typing import Any

from sqlalchemy import select

from database.connection import AsyncSessionLocal
from database.models import ServiceCategory, Stylist

# Stylist seed data
STYLISTS_DATA: list[dict[str, Any]] = [
    {
        "name": "Pilar",
        "category": ServiceCategory.HAIRDRESSING,
        "google_calendar_id": "pilar@atrevete.com",
        "is_active": True,
        "metadata_": {},
    },
    {
        "name": "Marta",
        "category": ServiceCategory.BOTH,
        "google_calendar_id": "marta@atrevete.com",
        "is_active": True,
        "metadata_": {},
    },
    {
        "name": "Rosa",
        "category": ServiceCategory.AESTHETICS,
        "google_calendar_id": "rosa@atrevete.com",
        "is_active": True,
        "metadata_": {},
    },
    {
        "name": "Harol",
        "category": ServiceCategory.HAIRDRESSING,
        "google_calendar_id": "harol@atrevete.com",
        "is_active": True,
        "metadata_": {},
    },
    {
        "name": "Víctor",
        "category": ServiceCategory.HAIRDRESSING,
        "google_calendar_id": "victor@atrevete.com",
        "is_active": True,
        "metadata_": {},
    },
]


async def seed_stylists() -> None:
    """
    Seed the stylists table with 5 stylists.

    Checks if each stylist already exists by google_calendar_id before inserting.
    Uses UPSERT logic to avoid duplicate entries.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            for stylist_data in STYLISTS_DATA:
                # Check if stylist already exists
                result = await session.execute(
                    select(Stylist).where(
                        Stylist.google_calendar_id == stylist_data["google_calendar_id"]
                    )
                )
                existing_stylist = result.scalar_one_or_none()

                if existing_stylist is None:
                    # Create new stylist
                    stylist = Stylist(**stylist_data)
                    session.add(stylist)
                    category_value = stylist_data['category'].value if hasattr(stylist_data['category'], 'value') else str(stylist_data['category'])
                    print(
                        f"✓ Created stylist: {stylist_data['name']} ({category_value})"
                    )
                else:
                    category_value = stylist_data['category'].value if hasattr(stylist_data['category'], 'value') else str(stylist_data['category'])
                    print(
                        f"⊙ Stylist already exists: {stylist_data['name']} ({category_value})"
                    )

        # Commit all changes
        await session.commit()
        print(f"\n✓ Seeding complete! Total stylists in database: {len(STYLISTS_DATA)}")


if __name__ == "__main__":
    print("Seeding stylists table...")
    print("=" * 60)
    asyncio.run(seed_stylists())
