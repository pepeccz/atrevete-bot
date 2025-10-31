#!/usr/bin/env python3
"""
Test script to verify Google Calendar API access and create a test event.

This script:
1. Verifies service account credentials
2. Lists all active stylists with their calendar IDs
3. Tests access to each calendar by fetching events
4. Creates a test event in one hour on Victor's calendar
5. Cleans up the test event after verification
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from database.connection import get_async_session
from database.models import Stylist
from sqlalchemy import select

# Google Calendar API setup
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = '/home/pepe/atrevete-bot/service-account-key.json'

# Madrid timezone
MADRID_TZ = ZoneInfo("Europe/Madrid")


def get_calendar_service():
    """Get authenticated Google Calendar service."""
    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=SCOPES
        )
        service = build('calendar', 'v3', credentials=credentials)
        print("✅ Service account credentials loaded successfully")
        print(f"   Service account email: {credentials.service_account_email}")
        return service
    except FileNotFoundError:
        print(f"❌ Service account file not found: {SERVICE_ACCOUNT_FILE}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error loading credentials: {e}")
        sys.exit(1)


async def get_active_stylists():
    """Get all active stylists from database."""
    print("\n📋 Fetching active stylists from database...")

    async for session in get_async_session():
        stmt = select(Stylist).where(Stylist.is_active == True).order_by(Stylist.name)
        result = await session.execute(stmt)
        stylists = list(result.scalars().all())

        print(f"   Found {len(stylists)} active stylists:")
        for stylist in stylists:
            print(f"   - {stylist.name} ({stylist.category.value})")
            print(f"     Calendar ID: {stylist.google_calendar_id[:60]}...")

        return stylists


def test_calendar_access(service, calendar_id, stylist_name):
    """Test access to a specific calendar."""
    try:
        # Try to fetch events from the calendar
        now = datetime.now(MADRID_TZ)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=7)).isoformat()

        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=5,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])

        print(f"   ✅ {stylist_name}: Access verified ({len(events)} events in next 7 days)")
        return True

    except HttpError as e:
        if e.resp.status == 403:
            print(f"   ❌ {stylist_name}: Access denied (403) - Calendar not shared with service account")
        elif e.resp.status == 404:
            print(f"   ❌ {stylist_name}: Calendar not found (404) - Check calendar ID")
        else:
            print(f"   ❌ {stylist_name}: HTTP error {e.resp.status} - {e}")
        return False
    except Exception as e:
        print(f"   ❌ {stylist_name}: Unexpected error - {e}")
        return False


def create_test_event(service, calendar_id, stylist_name):
    """Create a test event in one hour."""
    try:
        # Calculate start time (1 hour from now)
        now = datetime.now(MADRID_TZ)
        start_time = now + timedelta(hours=1)
        end_time = start_time + timedelta(minutes=30)

        # Round to nearest 30 minutes for cleaner display
        start_time = start_time.replace(minute=(start_time.minute // 30) * 30, second=0, microsecond=0)
        end_time = start_time + timedelta(minutes=30)

        event_body = {
            'summary': '[TEST] Prueba de Calendario - Claude Code',
            'description': (
                'Este es un evento de prueba creado automáticamente para verificar '
                'que el sistema tiene acceso correcto a Google Calendar.\n\n'
                'Se eliminará automáticamente al final del test.'
            ),
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'Europe/Madrid',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'Europe/Madrid',
            },
            'colorId': '11',  # Red color for test events
            'reminders': {
                'useDefault': False,
                'overrides': [],
            },
        }

        print(f"\n📅 Creating test event for {stylist_name}:")
        print(f"   Calendar: {calendar_id[:60]}...")
        print(f"   Start: {start_time.strftime('%Y-%m-%d %H:%M %Z')}")
        print(f"   End: {end_time.strftime('%Y-%m-%d %H:%M %Z')}")

        event = service.events().insert(
            calendarId=calendar_id,
            body=event_body
        ).execute()

        event_id = event.get('id')
        event_link = event.get('htmlLink')

        print(f"   ✅ Event created successfully!")
        print(f"   Event ID: {event_id}")
        print(f"   Link: {event_link}")

        return event_id

    except HttpError as e:
        print(f"   ❌ Failed to create event: HTTP {e.resp.status}")
        print(f"      Error: {e}")
        return None
    except Exception as e:
        print(f"   ❌ Failed to create event: {e}")
        return None


def delete_test_event(service, calendar_id, event_id, stylist_name):
    """Delete the test event."""
    try:
        print(f"\n🗑️  Deleting test event from {stylist_name}'s calendar...")

        service.events().delete(
            calendarId=calendar_id,
            eventId=event_id
        ).execute()

        print(f"   ✅ Test event deleted successfully")
        return True

    except HttpError as e:
        print(f"   ❌ Failed to delete event: HTTP {e.resp.status}")
        return False
    except Exception as e:
        print(f"   ❌ Failed to delete event: {e}")
        return False


async def main():
    """Main test execution."""
    print("=" * 80)
    print("🧪 GOOGLE CALENDAR API ACCESS TEST")
    print("=" * 80)

    # Step 1: Load credentials and create service
    service = get_calendar_service()

    # Step 2: Get active stylists
    stylists = await get_active_stylists()

    if not stylists:
        print("\n❌ No active stylists found in database")
        return

    # Step 3: Test access to each calendar
    print("\n🔍 Testing calendar access for each stylist...")
    print("=" * 80)

    access_results = {}
    for stylist in stylists:
        success = test_calendar_access(service, stylist.google_calendar_id, stylist.name)
        access_results[stylist.name] = {
            'success': success,
            'stylist': stylist
        }

    # Step 4: Summary of access tests
    print("\n" + "=" * 80)
    print("📊 ACCESS TEST SUMMARY")
    print("=" * 80)

    accessible_count = sum(1 for r in access_results.values() if r['success'])
    total_count = len(access_results)

    print(f"✅ Accessible: {accessible_count}/{total_count}")
    print(f"❌ Not accessible: {total_count - accessible_count}/{total_count}")

    if accessible_count == 0:
        print("\n❌ No calendars are accessible!")
        print("\n💡 TROUBLESHOOTING:")
        print("   1. Verify each calendar is shared with the service account:")
        print(f"      Service account email: (check service-account-key.json)")
        print("   2. Share each calendar with 'See all event details' permission")
        print("   3. Verify calendar IDs are correct in the database")
        return

    # Step 5: Create test event on Victor's calendar (or first accessible)
    print("\n" + "=" * 80)
    print("📝 CREATING TEST EVENT")
    print("=" * 80)

    # Find Victor or use first accessible stylist
    test_stylist = None
    for name, result in access_results.items():
        if result['success']:
            if name == "Victor":
                test_stylist = result['stylist']
                break
            elif test_stylist is None:
                test_stylist = result['stylist']

    if not test_stylist:
        print("\n❌ No accessible calendar found for testing")
        return

    print(f"Selected stylist: {test_stylist.name}")

    event_id = create_test_event(
        service,
        test_stylist.google_calendar_id,
        test_stylist.name
    )

    if not event_id:
        print("\n❌ Failed to create test event")
        return

    # Step 6: Wait for confirmation
    print("\n" + "=" * 80)
    print("⏸️  TEST EVENT VERIFICATION")
    print("=" * 80)
    print(f"\n✅ Test event created successfully on {test_stylist.name}'s calendar!")
    print(f"\n📌 Please verify:")
    print(f"   1. Open Google Calendar")
    print(f"   2. Check {test_stylist.name}'s calendar")
    print(f"   3. Look for event: '[TEST] Prueba de Calendario - Claude Code'")
    print(f"   4. Verify it appears in approximately 1 hour from now")

    response = input("\n❓ Delete the test event now? (yes/no): ").strip().lower()

    if response in ['yes', 'y']:
        delete_test_event(
            service,
            test_stylist.google_calendar_id,
            event_id,
            test_stylist.name
        )
    else:
        print(f"\n⚠️  Test event left in calendar (Event ID: {event_id})")
        print(f"   You can manually delete it from Google Calendar")

    # Final summary
    print("\n" + "=" * 80)
    print("✅ TEST COMPLETE")
    print("=" * 80)
    print(f"\n📊 Summary:")
    print(f"   • Service account credentials: ✅ Valid")
    print(f"   • Calendars accessible: {accessible_count}/{total_count}")
    print(f"   • Test event creation: {'✅ Success' if event_id else '❌ Failed'}")

    if accessible_count < total_count:
        print(f"\n⚠️  Warning: {total_count - accessible_count} calendar(s) not accessible")
        print(f"   Review calendar sharing settings for:")
        for name, result in access_results.items():
            if not result['success']:
                print(f"   - {name}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
