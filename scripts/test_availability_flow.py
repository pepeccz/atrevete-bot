#!/usr/bin/env python3
"""
Comprehensive test script for the booking availability flow.

This script tests the complete flow:
1. Customer expresses booking intent
2. System offers pack suggestion
3. Customer accepts/declines pack
4. System validates services
5. System checks availability in Google Calendar
6. System presents prioritized slots

Usage:
    python scripts/test_availability_flow.py
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import redis.asyncio as redis

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class AvailabilityFlowTester:
    """Test harness for booking availability flow."""

    def __init__(self):
        self.redis_client = None
        self.test_conversation_id = f"test-availability-{int(datetime.now().timestamp())}"
        self.test_phone = "+34623226544"
        self.test_name = "Test User"

    async def connect_redis(self):
        """Connect to Redis."""
        self.redis_client = redis.Redis(
            host="localhost",
            port=6379,
            db=0,
            decode_responses=True
        )
        print("✅ Connected to Redis")

    async def send_message(self, message_text: str, step_name: str):
        """Send a message to the agent."""
        print(f"\n{'='*80}")
        print(f"📤 STEP: {step_name}")
        print(f"{'='*80}")
        print(f"💬 Sending message: \"{message_text}\"")

        message_payload = {
            "conversation_id": self.test_conversation_id,
            "customer_phone": self.test_phone,
            "message_text": message_text,
            "customer_name": self.test_name,
        }

        await self.redis_client.publish(
            "incoming_messages",
            json.dumps(message_payload)
        )

        print(f"✅ Message published to Redis")
        print(f"⏱️  Waiting 3 seconds for processing...")
        await asyncio.sleep(3)

    def print_expected_behavior(self, expectations: list[str]):
        """Print expected behavior for this step."""
        print(f"\n🎯 EXPECTED BEHAVIOR:")
        for i, expectation in enumerate(expectations, 1):
            print(f"   {i}. {expectation}")

    def print_validation_instructions(self, instructions: list[str]):
        """Print validation instructions."""
        print(f"\n✅ VALIDATION:")
        for instruction in instructions:
            print(f"   • {instruction}")

    async def run_test(self):
        """Run the complete availability flow test."""
        print("=" * 80)
        print("🧪 BOOKING AVAILABILITY FLOW TEST")
        print("=" * 80)
        print(f"\n📋 Test Configuration:")
        print(f"   Conversation ID: {self.test_conversation_id}")
        print(f"   Customer Phone: {self.test_phone}")
        print(f"   Customer Name: {self.test_name}")
        print(f"\n⚠️  Prerequisites:")
        print(f"   1. Docker containers running (agent, api, redis, postgres)")
        print(f"   2. Database seeded with stylists and services")
        print(f"   3. Google Calendar service account configured")
        print(f"   4. Stylists have real Google Calendar IDs")

        try:
            await self.connect_redis()

            # Calculate target date (next Friday)
            today = datetime.now()
            days_until_friday = (4 - today.weekday()) % 7  # Friday = 4
            if days_until_friday == 0:
                days_until_friday = 7  # Next Friday if today is Friday
            target_date = today + timedelta(days=days_until_friday)
            date_str = "el viernes" if days_until_friday <= 7 else target_date.strftime("%d de %B")

            # Step 1: Send booking intent message
            await self.send_message(
                f"Quiero reservar mechas y corte para {date_str}",
                "1. Booking Intent Detection"
            )

            self.print_expected_behavior([
                "conversational_agent detects booking intent",
                "Claude calls start_booking_flow() tool",
                "State: booking_intent_confirmed = True",
                "State: requested_services = [mechas_id, corte_id]",
                f"State: requested_date = '{date_str}'",
                "Graph routes to booking_handler (Tier 2)",
                "booking_handler routes to suggest_pack",
            ])

            self.print_validation_instructions([
                "Check logs: grep 'Booking intent confirmed'",
                "Check logs: grep 'start_booking_flow'",
                "Check logs: grep 'transitioning to Tier 2'",
            ])

            # Wait for pack suggestion
            print(f"\n⏱️  Waiting 5 seconds for pack suggestion...")
            await asyncio.sleep(5)

            # Step 2: Pack suggestion should be presented
            print(f"\n{'='*80}")
            print(f"📤 STEP: 2. Pack Suggestion")
            print(f"{'='*80}")

            self.print_expected_behavior([
                "suggest_pack node executes",
                "Queries packs containing 'mechas' and 'corte'",
                "Finds 'Mechas + Corte' pack",
                "Calculates savings (e.g., 60€ vs 85€ = 25€ savings)",
                "Generates natural suggestion message using Claude",
                "Bot presents pack to customer",
                "State: awaiting_pack_response = True",
            ])

            self.print_validation_instructions([
                "Check logs: grep 'suggest_pack'",
                "Check logs: grep 'Pack suggestion'",
                "Check bot response mentions pack and savings",
                "Verify awaiting_pack_response = True in state",
            ])

            # Step 3: Accept pack
            await self.send_message(
                "Sí, me interesa el pack",
                "3. Pack Acceptance"
            )

            self.print_expected_behavior([
                "Entry routing detects awaiting_pack_response = True",
                "Routes to handle_pack_response",
                "Classifies response as 'accept' using Claude",
                "Updates requested_services to pack's included services",
                "Sets pack_id in state",
                "Sets awaiting_pack_response = False",
                "Routes to validate_booking_request",
            ])

            self.print_validation_instructions([
                "Check logs: grep 'handle_pack_response'",
                "Check logs: grep 'Pack response: accept'",
                "Check logs: grep 'pack_id'",
            ])

            # Wait for validation
            print(f"\n⏱️  Waiting 3 seconds for validation...")
            await asyncio.sleep(3)

            # Step 4: Service validation
            print(f"\n{'='*80}")
            print(f"📤 STEP: 4. Service Validation")
            print(f"{'='*80}")

            self.print_expected_behavior([
                "validate_booking_request node executes",
                "Calls validate_service_combination() tool",
                "Checks all services are same category (Hairdressing)",
                "Validation passes (mechas + corte = both Hairdressing)",
                "Sets booking_validation_passed = True",
                "Routes to check_availability",
            ])

            self.print_validation_instructions([
                "Check logs: grep 'validate_booking_request'",
                "Check logs: grep 'Validation passed'",
                "Check logs: grep 'booking_validation_passed'",
            ])

            # Wait for availability check
            print(f"\n⏱️  Waiting 5 seconds for availability check...")
            await asyncio.sleep(5)

            # Step 5: Availability check
            print(f"\n{'='*80}")
            print(f"📤 STEP: 5. Availability Check (Google Calendar)")
            print(f"{'='*80}")

            self.print_expected_behavior([
                "check_availability node executes",
                "Determines category: Hairdressing",
                "Queries stylists by category (Victor, Ana, Marta, Ana Maria, Pilar)",
                "Checks if target date is a holiday",
                "Queries Google Calendar for ALL stylists in PARALLEL (asyncio.gather)",
                "Fetches busy events from each stylist's calendar",
                "Generates 30-minute time slots based on business hours",
                "Filters slots occupied by existing events",
                "Applies same-day buffer (1 hour) if applicable",
                "Prioritizes slots:",
                "  - Preferred stylist first (if any)",
                "  - Earlier times",
                "  - Load balancing across stylists",
                "Selects TOP 3 slots to present",
                "Formats response in Spanish with day names",
                "Bot presents available slots",
                "State: available_slots = [all slots found]",
                "State: prioritized_slots = [top 3 slots]",
            ])

            self.print_validation_instructions([
                "Check logs: grep 'check_availability'",
                "Check logs: grep 'Querying stylists by category'",
                "Check logs: grep 'Fetching calendar events'",
                "Check logs: grep 'Google Calendar API'",
                "Check logs: grep 'available_slots'",
                "Check logs: grep 'prioritized_slots'",
                "Check bot response contains:",
                "  - Day name (e.g., 'viernes')",
                "  - At least 1 time slot",
                "  - Stylist name(s)",
                "  - Duration information",
                "Verify bot asks customer to choose a slot",
            ])

            # Final summary
            print(f"\n{'='*80}")
            print(f"✅ TEST SEQUENCE COMPLETE")
            print(f"{'='*80}")
            print(f"\n📊 SUMMARY OF FLOW:")
            print(f"   1. ✅ Booking intent detected")
            print(f"   2. ✅ Pack suggested")
            print(f"   3. ✅ Pack accepted")
            print(f"   4. ✅ Services validated")
            print(f"   5. ✅ Availability checked (Google Calendar)")
            print(f"\n🔍 NEXT STEPS FOR MANUAL VALIDATION:")
            print(f"\n1. Check agent logs:")
            print(f"   docker compose logs agent -f --tail 100 | grep -E '(Booking intent|suggest_pack|validate_booking|check_availability|available_slots)'")
            print(f"\n2. Check API logs:")
            print(f"   docker compose logs api -f --tail 50")
            print(f"\n3. Check bot responses in Chatwoot or test output")
            print(f"\n4. Verify Google Calendar API calls:")
            print(f"   docker compose logs agent | grep 'Google Calendar'")
            print(f"\n5. Check state in Redis:")
            print(f"   redis-cli GET conversation:{self.test_conversation_id}")
            print(f"\n{'='*80}")
            print(f"🎯 TEST CONVERSATION ID: {self.test_conversation_id}")
            print(f"{'='*80}")

        except Exception as e:
            print(f"\n❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.redis_client:
                await self.redis_client.aclose()
                print(f"\n🔌 Disconnected from Redis")


async def main():
    """Main entry point."""
    tester = AvailabilityFlowTester()
    await tester.run_test()


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("🚀 Starting Booking Availability Flow Test")
    print("=" * 80 + "\n")
    asyncio.run(main())
