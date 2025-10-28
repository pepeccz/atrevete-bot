"""
Seed data script for services table.

Populates sample services from PRD scenarios.
Can be run standalone: python -m database.seeds.services
"""

import asyncio
from decimal import Decimal

from sqlalchemy import select

from database.connection import get_async_session
from database.models import Service, ServiceCategory

# Sample services from PRD scenarios
SAMPLE_SERVICES = [
    {
        "name": "Corte de pelo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 60,
        "price_euros": Decimal("25.00"),
        "requires_advance_payment": False,
        "description": "Corte de pelo profesional con lavado incluido",
    },
    {
        "name": "MECHAS",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 120,
        "price_euros": Decimal("60.00"),
        "requires_advance_payment": True,
        "description": "Mechas californianas o babylights",
    },
    {
        "name": "Corte + Color",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 90,
        "price_euros": Decimal("45.00"),
        "requires_advance_payment": True,
        "description": "Corte de pelo con coloración completa",
    },
    {
        "name": "Micropigmentación",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "price_euros": Decimal("150.00"),
        "requires_advance_payment": True,
        "description": "Micropigmentación de cejas con técnica pelo a pelo",
    },
    {
        "name": "Consulta estética",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "price_euros": Decimal("0.00"),
        "requires_advance_payment": False,
        "description": "Consulta estética gratuita para evaluar tratamientos",
    },
]


async def seed_services() -> None:
    """
    Seed services table with sample services.

    Uses UPSERT logic (check by name before inserting) to avoid duplicates.
    """
    async for session in get_async_session():
        seeded_count = 0

        for service_data in SAMPLE_SERVICES:
            # Check if service already exists by name
            stmt = select(Service).where(Service.name == service_data["name"])
            result = await session.execute(stmt)
            existing_service = result.scalar_one_or_none()

            if existing_service is None:
                # Create new service
                service = Service(**service_data)
                session.add(service)
                seeded_count += 1

        await session.commit()

    print(f"✓ Seeded {seeded_count} services (skipped {len(SAMPLE_SERVICES) - seeded_count} existing)")


if __name__ == "__main__":
    asyncio.run(seed_services())
