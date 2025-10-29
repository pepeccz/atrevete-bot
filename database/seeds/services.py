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
    # Hairdressing Services
    {
        "name": "MECHAS",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 120,
        "price_euros": Decimal("60.00"),
        "requires_advance_payment": True,
        "description": "Mechas californianas o babylights",
    },
    {
        "name": "Corte de pelo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 60,
        "price_euros": Decimal("25.00"),
        "requires_advance_payment": False,
        "description": "Corte de pelo profesional con lavado incluido",
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
        "name": "OLEO PIGMENTO",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "price_euros": Decimal("34.00"),
        "requires_advance_payment": True,
        "description": "Coloración semi-permanente con aceites nutritivos que protege y da brillo intenso",
    },
    {
        "name": "BARRO",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "price_euros": Decimal("36.50"),
        "requires_advance_payment": True,
        "description": "Mascarilla purificante con minerales para eliminar impurezas",
    },
    {
        "name": "BARRO GOLD",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "price_euros": Decimal("48.00"),
        "requires_advance_payment": True,
        "description": "Tratamiento intensivo con minerales y nutrición profunda para cabellos exigentes",
    },
    {
        "name": "AGUA LLUVIA",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 25,
        "price_euros": Decimal("20.00"),
        "requires_advance_payment": True,
        "description": "Tratamiento con agua de lluvia para hidratar y revitalizar el cabello",
    },
    {
        "name": "PEINADO LARGO",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 45,
        "price_euros": Decimal("22.50"),
        "requires_advance_payment": True,
        "description": "Peinado profesional para cabello largo",
    },
    {
        "name": "CORTE CABALLERO",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "price_euros": Decimal("17.50"),
        "requires_advance_payment": True,
        "description": "Corte de pelo masculino profesional",
    },
    {
        "name": "Peinado",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "price_euros": Decimal("15.00"),
        "requires_advance_payment": False,
        "description": "Peinado profesional para todo tipo de cabello",
    },
    # Aesthetics Services
    {
        "name": "MANICURA PERMANENTE",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "price_euros": Decimal("25.00"),
        "requires_advance_payment": True,
        "description": "Manicura permanente de larga duración",
    },
    {
        "name": "BIOTERAPIA FACIAL",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "price_euros": Decimal("15.70"),
        "requires_advance_payment": True,
        "description": "Tratamiento de bioterapia facial para rejuvenecer la piel",
    },
    {
        "name": "Micropigmentación",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "price_euros": Decimal("150.00"),
        "requires_advance_payment": True,
        "description": "Micropigmentación de cejas con técnica pelo a pelo",
    },
    # Consultation Services (Free)
    {
        "name": "CONSULTA GRATUITA",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 15,
        "price_euros": Decimal("0.00"),
        "requires_advance_payment": False,
        "description": "Consulta gratuita de 15 minutos para asesoramiento sobre servicios de peluquería",
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
