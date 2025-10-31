#!/usr/bin/env python3
"""
Script to update stylist data in the database.

This script:
1. Shows current stylists in DB
2. Deactivates all existing stylists
3. Creates/updates the 6 new stylists with correct Google Calendar IDs
4. Shows final state
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, update
from database.connection import get_async_session
from database.models import Stylist, ServiceCategory


# New stylist data with real Google Calendar IDs
NEW_STYLISTS = [
    {
        "name": "Victor",
        "category": ServiceCategory.HAIRDRESSING,
        "calendar_id": "02ac48c0a2b9ed4e3b82b48ff92c951c2369519401c88ace2f14e024f57b59d1@group.calendar.google.com",
    },
    {
        "name": "Ana",
        "category": ServiceCategory.HAIRDRESSING,
        "calendar_id": "740ac1de72d7343d38e7c29e21f88da2654c805d3918710b24e491bce3effd34@group.calendar.google.com",
    },
    {
        "name": "Marta",
        "category": ServiceCategory.HAIRDRESSING,
        "calendar_id": "4824b0be9f7479672cf08e305c18ff87b607c2ea7f2fc7c3e2641f2e07671062@group.calendar.google.com",
    },
    {
        "name": "Ana Maria",
        "category": ServiceCategory.HAIRDRESSING,
        "calendar_id": "97124a0d577423f6efc3d8f72a253ed987178f31c8f138395a99817200e75883@group.calendar.google.com",
    },
    {
        "name": "Pilar",
        "category": ServiceCategory.HAIRDRESSING,
        "calendar_id": "3b266f75917395ff0cfe7ed47703a5f9c8a8a14a8f680882693df6da80122c39@group.calendar.google.com",
    },
    {
        "name": "Rosa",
        "category": ServiceCategory.AESTHETICS,
        "calendar_id": "2eda3449b5832c981f72fc4c3cee8eac296868ea889aba41e507c7cb550cef4b@group.calendar.google.com",
    },
]


def print_table_header():
    """Print table header for stylist display."""
    print("\n" + "=" * 120)
    print(f"{'ID':<38} | {'Name':<15} | {'Category':<15} | {'Active':<8} | {'Calendar ID':<40}")
    print("=" * 120)


def print_stylist_row(stylist):
    """Print a single stylist row."""
    calendar_id_short = stylist.google_calendar_id[:40] + "..." if len(stylist.google_calendar_id) > 40 else stylist.google_calendar_id
    print(
        f"{str(stylist.id):<38} | "
        f"{stylist.name:<15} | "
        f"{stylist.category.value:<15} | "
        f"{'✅' if stylist.is_active else '❌':<8} | "
        f"{calendar_id_short}"
    )


async def show_current_stylists(session):
    """Display current stylists in database."""
    print("\n📋 CURRENT STYLISTS IN DATABASE:")
    print_table_header()

    stmt = select(Stylist).order_by(Stylist.name)
    result = await session.execute(stmt)
    stylists = result.scalars().all()

    if not stylists:
        print("(No stylists found)")
    else:
        for stylist in stylists:
            print_stylist_row(stylist)

    print("=" * 120)
    print(f"\nTotal: {len(stylists)} stylists")


async def deactivate_all_stylists(session):
    """Deactivate all existing stylists."""
    print("\n🔄 Deactivating all existing stylists...")

    stmt = update(Stylist).values(is_active=False)
    result = await session.execute(stmt)
    await session.commit()

    print(f"✅ Deactivated {result.rowcount} stylists")


async def create_or_update_stylist(session, name: str, category: ServiceCategory, calendar_id: str):
    """Create or update a single stylist."""
    # Check if stylist exists by name
    stmt = select(Stylist).where(Stylist.name == name)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        # Update existing stylist
        existing.category = category
        existing.google_calendar_id = calendar_id
        existing.is_active = True
        print(f"   ✏️  Updated: {name}")
    else:
        # Create new stylist
        new_stylist = Stylist(
            name=name,
            category=category,
            google_calendar_id=calendar_id,
            is_active=True,
        )
        session.add(new_stylist)
        print(f"   ➕ Created: {name}")

    await session.commit()


async def create_new_stylists(session):
    """Create or update all new stylists."""
    print("\n📝 Creating/Updating new stylists...")

    for stylist_data in NEW_STYLISTS:
        await create_or_update_stylist(
            session,
            name=stylist_data["name"],
            category=stylist_data["category"],
            calendar_id=stylist_data["calendar_id"],
        )

    print(f"✅ Processed {len(NEW_STYLISTS)} stylists")


async def main():
    """Main execution function."""
    print("=" * 120)
    print("🔧 STYLIST DATABASE UPDATE TOOL")
    print("=" * 120)
    print("\nThis script will:")
    print("  1. Show current stylists")
    print("  2. Deactivate all existing stylists")
    print("  3. Create/update 6 new stylists with real Google Calendar IDs")
    print("  4. Show final state")
    print("\n⚠️  WARNING: This will deactivate all current stylists!")
    print("=" * 120)

    # Confirmation prompt
    response = input("\n❓ Do you want to proceed? (yes/no): ").strip().lower()
    if response not in ["yes", "y"]:
        print("\n❌ Operation cancelled by user.")
        return

    try:
        async for session in get_async_session():
            # Step 1: Show current state
            await show_current_stylists(session)

            # Step 2: Deactivate all
            await deactivate_all_stylists(session)

            # Step 3: Create new stylists
            await create_new_stylists(session)

            # Step 4: Show final state
            print("\n" + "=" * 120)
            print("✅ UPDATE COMPLETE!")
            await show_current_stylists(session)

            print("\n" + "=" * 120)
            print("📊 SUMMARY:")
            print("=" * 120)
            print("   • All old stylists deactivated (is_active=False)")
            print("   • 6 new stylists created/updated with real Google Calendar IDs")
            print("   • Category breakdown:")
            print("     - Hairdressing: 5 stylists (Victor, Ana, Marta, Ana Maria, Pilar)")
            print("     - Aesthetics: 1 stylist (Rosa)")
            print("\n✅ Database is ready for availability testing!")
            print("=" * 120)

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
