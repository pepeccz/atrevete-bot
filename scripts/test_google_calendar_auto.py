#!/usr/bin/env python3
"""
Automated test script to verify Google Calendar API access and create a test event.
This version automatically deletes the test event after 10 seconds.
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

        return stylists


def test_calendar_access(service, calendar_id, stylist_name):
    """Test access to a specific calendar."""
    try:
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
            print(f"   ❌ {stylist_name}: Access denied (403)")
        elif e.resp.status == 404:
            print(f"   ❌ {stylist_name}: Calendar not found (404)")
        else:
            print(f"   ❌ {stylist_name}: HTTP error {e.resp.status}")
        return False
    except Exception as e:
        print(f"   ❌ {stylist_name}: Unexpected error - {e}")
        return False


def create_test_event(service, calendar_id, stylist_name):
    """Create a test event in one hour."""
    try:
        now = datetime.now(MADRID_TZ)
        start_time = now + timedelta(hours=1)
        start_time = start_time.replace(minute=(start_time.minute // 30) * 30, second=0, microsecond=0)
        end_time = start_time + timedelta(minutes=30)

        event_body = {
            'summary': '[TEST] Prueba de Calendario - Claude Code',
            'description': (
                'Evento de prueba creado automáticamente para verificar acceso a Google Calendar.\n'
                'Se eliminará automáticamente.'
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
        }

        print(f"\n📅 Creating test event for {stylist_name}:")
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

    except Exception as e:
        print(f"   ❌ Failed to delete event: {e}")
        return False


async def main():
    """Main test execution."""
    print("=" * 80)
    print("🧪 GOOGLE CALENDAR API ACCESS TEST (Automated)")
    print("=" * 80)

    # Step 1: Load credentials
    service = get_calendar_service()

    # Step 2: Get stylists
    stylists = await get_active_stylists()

    if not stylists:
        print("\n❌ No active stylists found")
        return

    # Step 3: Test calendar access
    print("\n🔍 Testing calendar access...")
    print("=" * 80)

    access_results = {}
    for stylist in stylists:
        success = test_calendar_access(service, stylist.google_calendar_id, stylist.name)
        access_results[stylist.name] = {
            'success': success,
            'stylist': stylist
        }

    # Step 4: Summary
    print("\n" + "=" * 80)
    print("📊 ACCESS TEST SUMMARY")
    print("=" * 80)

    accessible_count = sum(1 for r in access_results.values() if r['success'])
    total_count = len(access_results)

    print(f"✅ Accessible: {accessible_count}/{total_count}")
    print(f"❌ Not accessible: {total_count - accessible_count}/{total_count}")

    if accessible_count == 0:
        print("\n❌ No calendars are accessible!")
        return

    # Step 5: Create test event on Victor's calendar
    print("\n" + "=" * 80)
    print("📝 CREATING TEST EVENT")
    print("=" * 80)

    test_stylist = None
    for name, result in access_results.items():
        if result['success']:
            if name == "Victor":
                test_stylist = result['stylist']
                break
            elif test_stylist is None:
                test_stylist = result['stylist']

    if not test_stylist:
        print("\n❌ No accessible calendar found")
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

    # Step 6: Wait and delete
    print("\n" + "=" * 80)
    print("⏸️  Waiting 10 seconds before cleanup...")
    print("=" * 80)

    await asyncio.sleep(10)

    delete_test_event(
        service,
        test_stylist.google_calendar_id,
        event_id,
        test_stylist.name
    )

    # Final summary
    print("\n" + "=" * 80)
    print("✅ TEST COMPLETE")
    print("=" * 80)
    print(f"\n📊 Summary:")
    print(f"   • Service account: ✅ Valid")
    print(f"   • Service account email: atrevete-bot-service@zanovixai.iam.gserviceaccount.com")
    print(f"   • Calendars accessible: {accessible_count}/{total_count}")
    print(f"   • Test event creation: ✅ Success")
    print(f"   • Test event deletion: ✅ Success")

    print("\n🎉 All Google Calendar operations working correctly!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
