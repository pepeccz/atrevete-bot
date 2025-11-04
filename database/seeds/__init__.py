"""
Seed data orchestration module.

Provides seed_all() function to execute all seed scripts in dependency order.
Can be run standalone: python -m database.seeds
"""

import asyncio

# from database.seeds.packs import seed_packs  # Removed - packs functionality eliminated
from database.seeds.policies import seed_policies
from database.seeds.services import seed_services
from database.seeds.stylists import seed_stylists


async def seed_all() -> None:
    """
    Execute all seed scripts in dependency order.

    Order:
    1. stylists (Story 1.3a) - independent
    2. services (Story 1.3b) - independent
    3. policies (Story 1.3b) - independent

    Note: packs removed (functionality eliminated)
    """
    print("Starting database seeding...")
    print("-" * 50)

    await seed_stylists()
    await seed_services()
    # await seed_packs()  # Removed - packs functionality eliminated
    await seed_policies()

    print("-" * 50)
    print("✓ Database seeding complete!")


if __name__ == "__main__":
    asyncio.run(seed_all())
