# Epic 4: Booking Flow & Payment Processing

**Epic Goal:** Complete the booking lifecycle from provisional calendar blocking through Stripe payment processing to confirmed appointment creation, including timeout management, payment retry logic, group bookings, third-party bookings, and confirmation notifications.

## Story 4.1: BookingTools - Price & Duration Calculations

**As a** system,
**I want** BookingTools that calculate accurate pricing, durations, and advance payments,
**so that** customers receive correct amounts and calendar blocks are sized appropriately.

**Prerequisites:** Story 1.3b (Appointments table), Story 3.1 (Services database)

**Acceptance Criteria:**

1. BookingTools class created
2. `calculate_booking_details(service_ids, pack_id)` returns dict with total_price, duration, advance_payment, service_names
3. If pack_id → use pack totals
4. If service_ids → sum individual services
5. Advance payment = total_price * (payment_percentage/100) from policies table
6. Services with price=0€ return advance_payment_amount=0
7. Rounds to 2 decimal places
8. Service names concatenated with " + "
9. Returns Decimal type for precision
10. Unit tests for single service, pack, 3 services, 0€ consultation

## Story 4.2: Provisional Calendar Blocking with Timeouts

**As a** system,
**I want** to create provisional calendar blocks with appropriate timeouts,
**so that** slots are held during payment while preventing ghost reservations.

**Prerequisites:** Story 3.2 (Calendar integration), Story 4.1 (Calculations)

**Acceptance Criteria:**

1. `create_provisional_block(stylist_id, start_time, duration, customer_id, service_names, is_same_day)`
2. Timeout logic: same_day=True → 15min, otherwise 30min (from policies table)
3. Creates Google Calendar event with status="provisional"
4. Event summary: "[PROVISIONAL] {customer_name} - {service_names}"
5. Yellow color for provisional
6. Creates appointment record: status='provisional', payment_status='pending'
7. Returns appointment_id, event_id, timeout_minutes, expires_at
8. Same-day detection: Compare dates in Europe/Madrid timezone
9. Integration test: Tomorrow booking → verify 30min timeout
10. Integration test: Same-day → verify 15min timeout

## Story 4.3: PaymentTools - Stripe Payment Link Generation

**As a** system,
**I want** to generate Stripe Payment Links with booking metadata,
**so that** customers can pay securely and payments are traceable.

**Prerequisites:** Story 4.1 (Calculations), Story 4.2 (Provisional blocks)

**Acceptance Criteria:**

1. PaymentTools class created
2. Stripe API client configured with secret key from environment
3. `create_payment_link(appointment_id, amount_euros, customer_name, service_names)`
4. Configured with amount in cents, currency='eur', description
5. Metadata attached: appointment_id, customer_id, booking_type
6. Single-use payment link
7. Success URL configurable via env
8. Returns payment_url, payment_link_id
9. If amount_euros==0 → returns {payment_url: None, skipped: true}
10. Error handling returns {success: false, error}
11. Unit test with mocked Stripe
12. Integration test with Stripe test mode

## Story 4.4: Payment Timeout Reminder & Auto-Release Worker

**As a** system,
**I want** automated reminders at 25 minutes and automatic release at timeout,
**so that** customers are prompted and abandoned slots are freed.

**Prerequisites:** Story 4.2 (Provisional blocks), Story 4.3 (Payment links)

**Acceptance Criteria:**

1. Worker `/agent/workers/payment_timeout_worker.py`
2. Runs every 1 minute
3. Queries appointments: status='provisional', payment_status='pending'
4. If age >=(timeout-5min) AND reminder_sent=false → send reminder
5. Reminder message with 5 min warning
6. Updates reminder_sent=true
7. If age >=timeout → release: delete calendar event, update status='expired', send expiration message
8. Worker logs all actions
9. Error handling: Failed calendar delete → log but mark expired
10. Metrics tracking: reminders sent, blocks released per hour
11. Integration test: 25min wait → verify reminder → 30min → verify released
12. Unit test: Various ages → verify correct actions

## Story 4.5: Stripe Webhook Payment Confirmation

**As a** system,
**I want** to validate Stripe webhooks and convert provisional blocks to confirmed,
**so that** successful payments result in guaranteed bookings.

**Prerequisites:** Story 1.4 (Webhook receiver), Story 4.3 (Payment), Story 4.2 (Provisional)

**Acceptance Criteria:**

1. `process_payment_confirmation` node subscribes to `payment_events`
2. Receives Stripe event with metadata
3. Queries appointments by appointment_id
4. Validates status='provisional', payment_status='pending'
5. Updates: status='confirmed', payment_status='confirmed', stripe_payment_id, confirmed_at
6. Updates Google Calendar: remove [PROVISIONAL], change to green
7. Sends confirmation message with full details
8. Updates customer total_spent
9. Notifies stylist of new confirmed booking
10. Idempotency: Duplicate webhooks don't error
11. Integration test: Provisional block → mock webhook → verify confirmed
12. Unit test: Duplicate webhook → verify idempotent

## Story 4.6: Payment Retry Logic & Escalation

**As a** customer experiencing payment issues,
**I want** a new payment link on first failure and escalation on second,
**so that** temporary issues don't block my booking.

**Prerequisites:** Story 4.3 (Payment links), Story 4.5 (Confirmation)

**Acceptance Criteria:**

1. `handle_payment_failure` triggered when customer reports payment error
2. Checks appointment `payment_retry_count` (default 0)
3. If retry_count==0 → generate new link, increment to 1, extend timeout +15min
4. Response with new link
5. If retry_count>=1 → escalate to human
6. Escalation message to customer and team
7. Provisional block remains active for human resolution
8. State updated: requires_human=true, escalation_reason='payment_failure_after_retry'
9. Integration test (Scenario 5): Failure → new link → second failure → escalation
10. Unit test: Verify retry_count tracking

## Story 4.7: Group Bookings & Simultaneous Availability

**As a** customer booking for multiple people,
**I want** the bot to find simultaneous availability,
**so that** my party can receive services at the same time.

**Prerequisites:** Story 3.3 (Availability), Story 4.1 (Calculations)

**Acceptance Criteria:**

1. `detect_group_booking` identifies multi-person requests
2. Extracts: number of people, service per person
3. `find_simultaneous_availability` searches for same start time across stylists
4. Response presents simultaneous slot
5. If none → offers staggered times
6. If accepted → creates multiple provisional blocks
7. Payment: Sum all services, single payment link for combined 20%
8. Appointments linked via shared group_booking_id
9. Integration test (Scenario 7): Group request → simultaneous slot → 2 blocks → pay → both confirmed
10. Edge case: One free + one paid → advance = 20% of paid only

## Story 4.8: Third-Party Booking Support

**As a** customer booking for someone else,
**I want** the bot to capture the recipient's name and create their profile,
**so that** I can book appointments for family/friends.

**Prerequisites:** Story 2.1 (CustomerTools), Story 4.5 (Confirmation)

**Acceptance Criteria:**

1. `detect_third_party_booking` identifies "para mi madre", "para mi hija" patterns
2. Asks for third-party name
3. Customer provides name
4. Searches database for existing customer
5. If not found → creates new customer: name=provided, phone=NULL, referred_by=booker
6. Appointment created with customer_id=third-party, booked_by_customer_id=booker
7. Payment sent to booker
8. Confirmation addresses both parties
9. Future: Ask for third-party phone for reminders
10. Database tracking via booked_by_customer_id
11. Integration test (Scenario 12): Book for mother → verify new customer → pay → verify linkage
12. Unit test: Verify referred_by relationship

## Story 4.9: Booking Confirmation & Notifications

**As a** customer who just completed payment,
**I want** clear confirmation with all booking details,
**so that** I have written record of my appointment.

**Prerequisites:** Story 4.5 (Payment confirmation)

**Acceptance Criteria:**

1. After payment confirmation, `send_booking_confirmation` formats message
2. Message format with date, time, stylist, services, duration, advance amount
3. Includes cancellation policy reminder (24h threshold)
4. Same-day bookings get urgency note
5. Stylist notification sent separately via email/SMS
6. Group bookings list all people/services in single message
7. State updated: booking_completed=true, confirmation_sent=true
8. Integration test: Full flow → verify all details in confirmation
9. Unit test: Day name in Spanish rendered correctly
10. Edge case: Free consultation → confirmation skips "anticipo" mention

---
