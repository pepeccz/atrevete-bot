# Epic 5: Modification & Cancellation Management

**Epic Goal:** Handle post-booking changes including appointment modifications, cancellations with refund logic (>24h), rescheduling offers (<24h), customer delay notifications, and "lo de siempre" recognition.

## Story 5.1: Appointment Modification Flow

**As a** customer with an existing appointment,
**I want** to change my appointment time or stylist,
**so that** I can adjust my booking to fit my schedule.

**Prerequisites:** Story 4.5 (Confirmed appointments), Story 3.3 (Availability)

**Acceptance Criteria:**

1. `detect_modification_intent` identifies change requests
2. Queries upcoming appointments (status='confirmed', start_time>now)
3. If multiple → asks which one
4. If single → confirms which
5. Customer specifies changes
6. Checks new availability
7. Asks confirmation
8. On confirmation: delete old event, create new event, update record
9. Confirmation message with retained payment
10. Advance payment NOT charged again
11. Integration test (Scenario 2): Change morning to afternoon → verify updated
12. Edge case: Request fully booked day → offer alternatives

## Story 5.2: Cancellation with >24h Notice (Refund)

**As a** customer canceling with sufficient notice,
**I want** automatic refund of my advance payment,
**so that** I'm not penalized for canceling responsibly.

**Prerequisites:** Story 4.5 (Confirmed appointments with stripe_payment_id)

**Acceptance Criteria:**

1. `detect_cancellation_intent` identifies cancellation requests
2. Retrieves upcoming appointments
3. Calculates hours_until appointment
4. Retrieves threshold from policies (24h)
5. If hours_until >24 → proceed with refund
6. Asks confirmation with refund notice
7. On confirmation: delete calendar event, update status='cancelled', payment_status='refunded'
8. Call Stripe refund API
9. Confirmation message with refund timeline
10. Stylist notification
11. Error handling: Refund failure → mark refund_pending, escalate
12. Integration test: Cancel >24h → verify Stripe refund called
13. Unit test: Verify hours_until calculation across timezones

## Story 5.3: Cancellation with <24h Notice (Rescheduling Offer)

**As a** customer canceling with short notice,
**I want** the option to reschedule without losing my payment,
**so that** I have flexibility even with short notice.

**Prerequisites:** Story 5.2 (Cancellation detection), Story 5.1 (Modification)

**Acceptance Criteria:**

1. Using `detect_cancellation_intent` from 5.2
2. If hours_until ≤24 → no refund, offer rescheduling
3. Response explains no refund policy
4. Immediately offers rescheduling with payment retention
5. If accepts → transition to modification flow
6. If declines → asks final confirmation
7. On cancellation: delete event, update status='cancelled_no_refund', payment_status='forfeited'
8. Do NOT call Stripe refund
9. Message confirms cancellation without refund
10. Track retention metric (reschedule vs cancel)
11. Integration test (Scenario 14): <24h cancel → verify no refund → reschedule → new slot
12. Unit test: Verify policy message includes threshold and amount

## Story 5.4: Customer Delay Notifications (<1h to Appointment)

**As a** customer running late,
**I want** to notify the salon of my delay,
**so that** they can adjust or decide if my appointment is still viable.

**Prerequisites:** Story 4.5 (Confirmed appointments)

**Acceptance Criteria:**

1. `detect_delay_notification` identifies late notifications
2. Retrieves today's appointment in next 4 hours
3. Extracts estimated arrival time or delay duration
4. Calculates minutes_until_appointment and estimated_delay
5. If minutes_until >60 → handle without escalation, notify stylist
6. If ≤60 OR delay >30min → escalate
7. Message about potential service adjustment
8. On confirmation → escalate with full context
9. Appointment marked with delay metadata
10. Integration test (Scenario 11): 17:00 appt, 17:10 "llego en 20 min" → verify escalation
11. Edge case: "5 min" with 2h until appt → no escalation

## Story 5.5: "Lo de Siempre" (Usual Service) Recognition

**As a** frequent customer,
**I want** the bot to remember "my usual" service,
**so that** I can quickly rebook without re-explaining.

**Prerequisites:** Story 2.1 (get_customer_history), Story 3.3 (Availability)

**Acceptance Criteria:**

1. `detect_usual_service_request` identifies "lo de siempre" patterns
2. Calls get_customer_history(limit=1)
3. If no history → "Es tu primera vez..."
4. If found → confirms understanding with details
5. If customer confirms → proceed with same services
6. Preferred stylist: Default to same stylist, offer alternatives if unavailable
7. Message when preferred unavailable with options
8. If customer wants different → transition to normal flow
9. Customer preference reinforcement after booking
10. Integration test (Scenario 16): "lo de siempre" → last service retrieved → booked
11. Unit test: 5 previous appointments → verify most recent stylist used

---
