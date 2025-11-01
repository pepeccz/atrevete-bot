# Epic 6: Notifications & Intelligent Escalation

**Epic Goal:** Implement automated 48-hour advance reminders, same-day booking urgent notifications, intelligent escalation system for medical consultations, payment failures, and complex queries, with rich context passed to the human team.

## Story 6.1: 48-Hour Automated Reminder Worker

**As a** customer with an upcoming appointment,
**I want** to receive an automated reminder 48 hours in advance,
**so that** I don't forget and can cancel with sufficient notice if needed.

**Prerequisites:** Story 4.5 (Confirmed appointments), Story 1.4 (Chatwoot API)

**Acceptance Criteria:**

1. Worker `/agent/workers/reminder_worker.py`
2. Runs every 1 hour (or 30 min)
3. Queries appointments: status='confirmed' AND start_time between (now+47.5h) and (now+48.5h) AND reminder_sent=false
4. For each: retrieve customer details
5. Message format with service, date, time, stylist, duration, advance amount, 24h policy
6. Send via Chatwoot API
7. If no conversation_id → create conversation first
8. Update reminder_sent=true, reminder_sent_at
9. Worker logs activity
10. Error handling: Retry once, then mark reminder_failed
11. Metrics tracking
12. Integration test: Appointment at now+48h → run worker → verify sent
13. Unit test: Various times → verify only 48h window processed

## Story 6.2: Same-Day Booking Urgent Notifications

**As a** stylist,
**I want** immediate notification when same-day appointment confirmed,
**so that** I can prepare and don't miss urgent bookings.

**Prerequisites:** Story 4.5 (Payment confirmation), Story 4.2 (Same-day detection)

**Acceptance Criteria:**

1. In `process_payment_confirmation`, check is_same_day
2. If same-day → trigger urgent notification within 2 minutes
3. `send_urgent_stylist_notification` function created
4. Notification channels (priority): SMS, email, WhatsApp team group
5. Message format with 🚨 emoji, customer, service, time, hours_until
6. Sent via Twilio/SendGrid/Chatwoot
7. Delivery tracked in database
8. If delivery fails → fallback to team group
9. Response time <2 minutes validation
10. Integration test (Scenario 18): Same-day booking → verify notification <2min
11. Unit test: Failed SMS → verify email fallback

## Story 6.3: Medical Consultation Escalation

**As a** customer with health-related questions,
**I want** immediate escalation to a human professional,
**so that** I receive accurate medical advice.

**Prerequisites:** Story 2.4 (Maite prompt with escalation)

**Acceptance Criteria:**

1. `detect_medical_query` analyzes messages for medical intent
2. Medical patterns: pregnancy, allergies, skin conditions, medications, contraindications
3. Confidence >0.8 → immediate escalation
4. Response with empathy and firm boundary
5. Follow-up: transfer message
6. Calls `escalate_to_human(reason='medical_consultation', context)`
7. State updated: escalated=true
8. Conversation marked for human takeover
9. Integration test (Scenario 4): "embarazada" → escalation → bot stops
10. Unit test: 10 medical + 10 service queries → verify detection

## Story 6.4: Escalation Tool & Team Notification System

**As a** team member,
**I want** to receive escalated cases via WhatsApp group with full context,
**so that** I can seamlessly take over conversations.

**Prerequisites:** Story 6.3 (Medical), Story 4.6 (Payment failure), Story 5.4 (Delay)

**Acceptance Criteria:**

1. `escalate_to_human(reason, context)` function
2. Receives reason enum
3. Retrieves conversation context
4. Formats escalation message for team group
5. Sends to team WhatsApp group via Chatwoot
6. Updates conversation_history with escalation record
7. Sets Redis flag `conversation:{id}:human_mode=true` (24h TTL)
8. Bot ignores messages while flag set
9. Logs escalation
10. Returns success confirmation
11. Integration test: Trigger escalation → verify team message → verify bot paused
12. Unit test: All 5 escalation reasons → verify formatting

## Story 6.5: Unresolved Ambiguity Escalation

**As a** customer whose needs the bot cannot understand,
**I want** transfer to human after reasonable attempts,
**so that** I'm not stuck in a loop.

**Prerequisites:** Story 6.4 (Escalation system)

**Acceptance Criteria:**

1. `track_conversation_progress` monitors with clarification_attempts counter
2. Ambiguity indicators: unclear_intent classification
3. After each failed clarification, increment counter
4. If attempts >=3 → escalate
5. Message to customer
6. Call escalate_to_human with context
7. Reset counter if conversation becomes clear
8. Edge case: Social chatting → ask for booking assistance before escalating
9. Integration test: 3 ambiguous exchanges → escalation
10. Unit test: Counter resets on clear intent

## Story 6.6: Holiday/Closure Detection & Customer Notification

**As a** customer requesting a closed date,
**I want** immediate notification with alternatives,
**so that** I don't waste time on impossible slots.

**Prerequisites:** Story 3.2 (Calendar holiday detection)

**Acceptance Criteria:**

1. In `check_availability`, if CalendarTools returns holiday_detected
2. Response informs of closure with reason
3. Proactively suggests next 2 available dates
4. Alternative: Offer day2 and day3
5. Customer selects → proceed with that date
6. Holiday detection works for: national holidays, local holidays, salon closures
7. Closure events follow naming: "Festivo", "Cerrado", "Vacaciones"
8. Integration test (Scenario 17): Holiday request → closure notice → alternatives
9. Unit test: Extract closure reason from event summary
10. Edge case: Insist on closed date → polite reaffirmation

---
