"""
Seed data script for policies table.

Populates business rules and FAQ policies using UPSERT logic.
Can be run standalone: python -m database.seeds.policies
"""

import asyncio

from sqlalchemy.dialects.postgresql import insert

from database.connection import get_async_session
from database.models import Policy

# Business rule policies
BUSINESS_RULES = [
    {
        "key": "cancellation_threshold_hours",
        "value": {
            "threshold_hours": 24,
            "description": "Minimum hours before appointment to allow cancellation without penalty",
        },
        "description": "Cancellation threshold for appointments",
    },
    {
        "key": "advance_payment_percentage",
        "value": {
            "payment_percentage": 20,
            "description": "Percentage of total price required as anticipo for services requiring advance payment",
        },
        "description": "Advance payment percentage for bookings",
    },
    {
        "key": "provisional_timeout_standard",
        "value": {
            "timeout_minutes": 30,
            "description": "Minutes to hold provisional booking before expiration (standard bookings)",
        },
        "description": "Provisional booking timeout for standard bookings",
    },
    {
        "key": "provisional_timeout_same_day",
        "value": {
            "timeout_minutes": 10,
            "description": "Minutes to hold provisional booking before expiration (same-day bookings)",
        },
        "description": "Provisional booking timeout for same-day bookings",
    },
    {
        "key": "reminder_advance_hours",
        "value": {
            "advance_hours": 48,
            "description": "Hours before appointment to send reminder notification",
        },
        "description": "Reminder notification advance time",
    },
]

# FAQ policies
FAQ_POLICIES = [
    {
        "key": "faq_parking",
        "value": {
            "question": "¿Dónde puedo aparcar?",
            "answer": "Tenemos parking gratuito en la calle trasera del salón",
            "keywords": ["parking", "aparcar", "coche"],
        },
        "description": "FAQ: Parking information",
    },
    {
        "key": "faq_location",
        "value": {
            "question": "¿Dónde están ubicados?",
            "answer": "Estamos en C/ Olivar 2.  28100, Alcobendas (Madrid). Enlace a google maps: https://maps.app.goo.gl/iXWaUFVVzJbavboEA",
            "keywords": ["ubicación", "dirección", "dónde"],
        },
        "description": "FAQ: Salon location",
    },
]


async def seed_policies() -> None:
    """
    Seed policies table with business rules and FAQs.

    Uses UPSERT logic (INSERT ON CONFLICT UPDATE) to avoid duplicates.
    """
    all_policies = BUSINESS_RULES + FAQ_POLICIES

    async for session in get_async_session():
        for policy_data in all_policies:
            # Use PostgreSQL UPSERT: INSERT ... ON CONFLICT (key) DO UPDATE
            stmt = insert(Policy).values(
                key=policy_data["key"],
                value=policy_data["value"],
                description=policy_data.get("description"),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["key"],
                set_={
                    "value": stmt.excluded.value,
                    "description": stmt.excluded.description,
                },
            )
            await session.execute(stmt)

        await session.commit()

    print(f"✓ Seeded {len(all_policies)} policies ({len(BUSINESS_RULES)} business rules + {len(FAQ_POLICIES)} FAQs)")


if __name__ == "__main__":
    asyncio.run(seed_policies())
