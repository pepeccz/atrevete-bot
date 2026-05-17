#!/usr/bin/env python3
"""
Script to reconcile stylist data in the database.

Google Calendar IDs are assigned via the admin panel OAuth flow — not by this script.

This script:
1. Shows current stylists in DB
2. Deactivates stylists whose slug is NOT in the canonical list
3. Upserts each canonical stylist by slug (name, category, is_active)
4. Shows final state
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from database.connection import get_async_session
from database.models import ServiceCategory, Stylist
from database.seeds.stylists import STYLISTS_DATA  # single source of truth

# Derive the canonical slug set from STYLISTS_DATA for deactivation filtering
CANONICAL_SLUGS: set[str] = {entry["slug"] for entry in STYLISTS_DATA}


def print_table_header():
    """Print table header for stylist display."""
    print("\n" + "=" * 100)
    print(f"{'ID':<38} | {'Name':<15} | {'Slug':<12} | {'Category':<15} | {'Active':<8}")
    print("=" * 100)


def print_stylist_row(stylist: Stylist):
    """Print a single stylist row."""
    print(
        f"{str(stylist.id):<38} | "
        f"{stylist.name:<15} | "
        f"{(stylist.slug or ''):<12} | "
        f"{stylist.category.value:<15} | "
        f"{'✅' if stylist.is_active else '❌':<8}"
    )


async def show_current_stylists(session) -> None:
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

    print("=" * 100)
    print(f"\nTotal: {len(stylists)} stylists")


async def deactivate_non_canonical_stylists(session) -> None:
    """
    Deactivate stylists whose slug is NOT in the canonical list.

    This avoids deactivating the canonical stylists we are about to upsert,
    which would erase their google_calendar_id (set via the admin panel) on
    the subsequent re-activate step.
    """
    print("\n🔄 Deactivating non-canonical stylists...")

    # Fetch all active stylists not in the canonical slug set
    stmt = select(Stylist).where(Stylist.is_active.is_(True))
    result = await session.execute(stmt)
    all_active = result.scalars().all()

    deactivated = 0
    for stylist in all_active:
        if stylist.slug not in CANONICAL_SLUGS:
            stylist.is_active = False
            print(f"   ⏸  Deactivated non-canonical: {stylist.name} (slug={stylist.slug!r})")
            deactivated += 1

    await session.commit()
    print(f"✅ Deactivated {deactivated} non-canonical stylist(s)")


async def create_or_update_stylist(
    session,
    name: str,
    slug: str,
    category: ServiceCategory,
    is_active: bool,
) -> None:
    """
    Upsert a single stylist by slug.

    - If a row with that slug exists: update name, category, is_active.
      google_calendar_id is intentionally left untouched.
    - If no row exists: create a new row with google_calendar_id=None.
    """
    stmt = select(Stylist).where(Stylist.slug == slug)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        # Update identity fields only — NEVER assign google_calendar_id here
        existing.name = name
        existing.category = category
        existing.is_active = is_active
        print(f"   ✏️  Updated: {name} (slug={slug!r})")
    else:
        new_stylist = Stylist(
            name=name,
            slug=slug,
            category=category,
            is_active=is_active,
            google_calendar_id=None,  # assigned via admin panel OAuth flow
        )
        session.add(new_stylist)
        print(f"   ➕ Created: {name} (slug={slug!r})")

    await session.commit()


async def upsert_canonical_stylists(session) -> None:
    """Upsert all canonical stylists from STYLISTS_DATA."""
    print("\n📝 Upserting canonical stylists...")

    for entry in STYLISTS_DATA:
        await create_or_update_stylist(
            session,
            name=entry["name"],
            slug=entry["slug"],
            category=entry["category"],
            is_active=entry["is_active"],
        )

    print(f"✅ Processed {len(STYLISTS_DATA)} canonical stylists")


async def main() -> None:
    """Main execution function."""
    print("=" * 100)
    print("🔧 STYLIST DATABASE RECONCILIATION TOOL")
    print("=" * 100)
    print("\nThis script will:")
    print("  1. Show current stylists")
    print("  2. Deactivate stylists NOT in the canonical slug list")
    print(f"  3. Upsert {len(STYLISTS_DATA)} canonical stylists (name, category, is_active — NO calendar IDs)")
    print("  4. Show final state")
    print("\n⚠️  NOTE: Google Calendar IDs are preserved — assign them via the admin panel.")
    print("=" * 100)

    response = input("\n❓ Do you want to proceed? (yes/no): ").strip().lower()
    if response not in ["yes", "y"]:
        print("\n❌ Operation cancelled by user.")
        return

    try:
        async for session in get_async_session():
            await show_current_stylists(session)
            await deactivate_non_canonical_stylists(session)
            await upsert_canonical_stylists(session)

            print("\n" + "=" * 100)
            print("✅ RECONCILIATION COMPLETE!")
            await show_current_stylists(session)

            print("\n" + "=" * 100)
            print("📊 SUMMARY:")
            print("=" * 100)
            print("   • Non-canonical stylists deactivated (is_active=False)")
            print(f"   • {len(STYLISTS_DATA)} canonical stylists upserted by slug")
            print("   • google_calendar_id values preserved (admin panel assigns these)")
            print("\n✅ Database is ready!")
            print("=" * 100)

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
