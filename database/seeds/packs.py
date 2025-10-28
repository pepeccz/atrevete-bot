"""
Seed data script for packs table.

Populates sample packs from PRD scenarios.
Can be run standalone: python -m database.seeds.packs
"""

import asyncio
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from database.connection import get_async_session
from database.models import Pack, Service

# Sample pack from PRD Scenario 5
SAMPLE_PACKS = [
    {
        "name": "Mechas + Corte",
        "service_names": ["MECHAS", "Corte de pelo"],  # Service names to look up
        "duration_minutes": 180,
        "price_euros": Decimal("80.00"),
        "description": "Pack ahorro: Mechas + Corte por solo €80 (ahorra €5)",
    },
]


async def seed_packs() -> None:
    """
    Seed packs table with sample packs.

    Queries service IDs by name, then creates packs with included_service_ids array.
    Uses UPSERT logic (check by name before inserting) to avoid duplicates.
    """
    async for session in get_async_session():
        seeded_count = 0

        for pack_data in SAMPLE_PACKS:
            # Check if pack already exists by name
            stmt = select(Pack).where(Pack.name == pack_data["name"])
            result = await session.execute(stmt)
            existing_pack = result.scalar_one_or_none()

            if existing_pack is not None:
                continue

            # Look up service IDs by name
            service_ids: list[UUID] = []
            service_names_raw = pack_data.get("service_names", [])
            service_names: list[str] = service_names_raw if isinstance(service_names_raw, list) else []
            for service_name in service_names:
                stmt_select_id = select(Service.id).where(Service.name == service_name)
                result_service = await session.execute(stmt_select_id)
                service_id = result_service.scalar_one_or_none()

                if service_id is None:
                    print(f"⚠ Warning: Service '{service_name}' not found, skipping pack '{pack_data['name']}'")
                    break

                service_ids.append(service_id)

            # Only create pack if all services were found
            if len(service_ids) == len(service_names):
                pack = Pack(
                    name=pack_data["name"],
                    included_service_ids=service_ids,
                    duration_minutes=pack_data["duration_minutes"],
                    price_euros=pack_data["price_euros"],
                    description=pack_data.get("description"),
                )
                session.add(pack)
                seeded_count += 1

        await session.commit()

    print(f"✓ Seeded {seeded_count} packs (skipped {len(SAMPLE_PACKS) - seeded_count} existing or incomplete)")


if __name__ == "__main__":
    asyncio.run(seed_packs())
