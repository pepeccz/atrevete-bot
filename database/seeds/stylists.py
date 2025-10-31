"""
Seed script for stylists table.

Populates the database with 6 stylists with real Google Calendar IDs:
- Victor (Hairdressing)
- Ana (Hairdressing)
- Marta (Hairdressing)
- Ana Maria (Hairdressing)
- Pilar (Hairdressing)
- Rosa (Aesthetics)
"""

import asyncio
from typing import Any

from sqlalchemy import select

from database.connection import AsyncSessionLocal
from database.models import ServiceCategory, Stylist

# Stylist seed data with real Google Calendar IDs
STYLISTS_DATA: list[dict[str, Any]] = [
    {
        "name": "Victor",
        "category": ServiceCategory.HAIRDRESSING,
        "google_calendar_id": "02ac48c0a2b9ed4e3b82b48ff92c951c2369519401c88ace2f14e024f57b59d1@group.calendar.google.com",
        "is_active": True,
        "metadata_": {},
    },
    {
        "name": "Ana",
        "category": ServiceCategory.HAIRDRESSING,
        "google_calendar_id": "740ac1de72d7343d38e7c29e21f88da2654c805d3918710b24e491bce3effd34@group.calendar.google.com",
        "is_active": True,
        "metadata_": {},
    },
    {
        "name": "Marta",
        "category": ServiceCategory.HAIRDRESSING,
        "google_calendar_id": "4824b0be9f7479672cf08e305c18ff87b607c2ea7f2fc7c3e2641f2e07671062@group.calendar.google.com",
        "is_active": True,
        "metadata_": {},
    },
    {
        "name": "Ana Maria",
        "category": ServiceCategory.HAIRDRESSING,
        "google_calendar_id": "97124a0d577423f6efc3d8f72a253ed987178f31c8f138395a99817200e75883@group.calendar.google.com",
        "is_active": True,
        "metadata_": {},
    },
    {
        "name": "Pilar",
        "category": ServiceCategory.HAIRDRESSING,
        "google_calendar_id": "3b266f75917395ff0cfe7ed47703a5f9c8a8a14a8f680882693df6da80122c39@group.calendar.google.com",
        "is_active": True,
        "metadata_": {},
    },
    {
        "name": "Rosa",
        "category": ServiceCategory.AESTHETICS,
        "google_calendar_id": "2eda3449b5832c981f72fc4c3cee8eac296868ea889aba41e507c7cb550cef4b@group.calendar.google.com",
        "is_active": True,
        "metadata_": {},
    },
]


async def seed_stylists() -> None:
    """
    Seed the stylists table with 6 stylists.

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
