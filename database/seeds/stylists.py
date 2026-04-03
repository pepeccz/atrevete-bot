"""
Seed script for stylists table.

Populates the database with stylists using slug as the stable identity key.
Google Calendar IDs are assigned via the admin panel OAuth flow — not by this script.

Canonical stylist roster (5 active professionals):
  Peluquería: Marta, Pilar, Victor, Harolyn
  Estética: Rosa
"""

import asyncio
from typing import Any

from sqlalchemy import select

from database.connection import AsyncSessionLocal
from database.models import ServiceCategory, Stylist

# Stylist seed data — identity fields only.
# google_calendar_id is intentionally absent: it is assigned exclusively via
# the admin panel's OAuth-backed calendar picker (PUT /api/admin/stylists/{id}/calendar).
STYLISTS_DATA: list[dict[str, Any]] = [
    {
        "name": "Marta",
        "slug": "marta",
        "category": ServiceCategory.HAIRDRESSING,
        "is_active": True,
    },
    {
        "name": "Pilar",
        "slug": "pilar",
        "category": ServiceCategory.HAIRDRESSING,
        "is_active": True,
    },
    {
        "name": "Victor",
        "slug": "victor",
        "category": ServiceCategory.HAIRDRESSING,
        "is_active": True,
    },
    {
        "name": "Harolyn",
        "slug": "harolyn",
        "category": ServiceCategory.HAIRDRESSING,
        "is_active": True,
    },
    {
        "name": "Rosa",
        "slug": "rosa",
        "category": ServiceCategory.AESTHETICS,
        "is_active": True,
    },
]


async def seed_stylists() -> None:
    """
    Seed the stylists table with stylists defined in STYLISTS_DATA.

    Reconciles by slug (stable identity key). For each entry:
    - If a row with that slug already exists: update name, category, is_active.
      The google_calendar_id column is intentionally left untouched.
    - If no row exists: create a new row with google_calendar_id=None.

    This function is fully idempotent — running it multiple times produces the same result.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            for stylist_data in STYLISTS_DATA:
                result = await session.execute(
                    select(Stylist).where(Stylist.slug == stylist_data["slug"])
                )
                existing_stylist = result.scalar_one_or_none()

                category_value = (
                    stylist_data["category"].value
                    if hasattr(stylist_data["category"], "value")
                    else str(stylist_data["category"])
                )

                if existing_stylist is not None:
                    # Update identity fields only — NEVER touch google_calendar_id
                    existing_stylist.name = stylist_data["name"]
                    existing_stylist.category = stylist_data["category"]
                    existing_stylist.is_active = stylist_data["is_active"]
                    print(f"✓ Updated stylist: {stylist_data['name']} ({category_value})")
                else:
                    # Create new row — google_calendar_id starts as None
                    stylist = Stylist(
                        name=stylist_data["name"],
                        slug=stylist_data["slug"],
                        category=stylist_data["category"],
                        is_active=stylist_data["is_active"],
                        google_calendar_id=None,
                    )
                    session.add(stylist)
                    print(f"✓ Created stylist: {stylist_data['name']} ({category_value})")

        await session.commit()
        print(f"\n✓ Seeding complete! Total stylists in seed data: {len(STYLISTS_DATA)}")


if __name__ == "__main__":
    print("Seeding stylists table...")
    print("=" * 60)
    asyncio.run(seed_stylists())
