# 6. Components

This section defines major logical components/services across the fullstack, establishing clear boundaries and interfaces between system parts.

## 6.1 FastAPI Webhook Receiver

**Responsibility:** Receives and validates incoming HTTP webhooks from external systems (Chatwoot, Stripe), performs signature validation, rate limiting, and enqueues events to Redis for async processing.

**Key Interfaces:**
- `POST /webhook/chatwoot` - Receives WhatsApp message events
- `POST /webhook/stripe` - Receives payment confirmation/refund events
- `GET /health` - System health check endpoint

**Dependencies:**
- Redis (pub/sub channels: `incoming_messages`, `payment_events`)
- Environment secrets (CHATWOOT_SECRET, STRIPE_WEBHOOK_SECRET)

**Technology Stack:**
- FastAPI 0.116.1 with async route handlers
- Pydantic models for request validation
- Redis client (redis-py 5.0+) for message publishing
- Custom middleware for signature validation and rate limiting

---

## 6.2 LangGraph Conversation Orchestrator

**Responsibility:** Core AI agent that orchestrates 18 conversational scenarios using a StateGraph, manages conversation state with automatic checkpointing, coordinates tool execution, and implements conditional routing based on Claude's reasoning.

**Key Interfaces:**
- `process_incoming_message(conversation_id, customer_phone, message_text)` - Main entry point
- `resume_from_checkpoint(conversation_id)` - Crash recovery
- `escalate_to_human(reason, context)` - Human handoff trigger

**Dependencies:**
- Redis (checkpointing, state persistence, pub/sub subscription)
- PostgreSQL (customer data, appointments, policies via Tools)
- Anthropic Claude API (LLM reasoning)
- All 5 tool categories (Calendar, Payment, Customer, Booking, Notification)

**Technology Stack:**
- LangGraph 0.6.7+ StateGraph engine
- LangChain 0.3.0+ for tool abstraction
- langchain-anthropic 0.3.0+ for Claude Sonnet 4 integration
- Redis MemorySaver for checkpointing
- Custom ConversationState TypedDict

---

## 6.3 CalendarTools

**Responsibility:** Abstracts Google Calendar API operations including availability checks across multiple stylists, event creation/modification/deletion, holiday detection, and timezone handling.

**Key Interfaces:**
- `get_availability(service_category, date, time_range, stylist_id=None)` → List[AvailableSlot]
- `create_event(stylist_id, start_time, duration, title, status="provisional")` → event_id
- `update_event(event_id, new_start_time=None, status=None)` → success
- `delete_event(event_id)` → success
- `check_holiday(date)` → bool (detects "Festivo", "Cerrado" events)

**Dependencies:**
- Google Calendar API (service account with domain-wide delegation)
- Stylist table (google_calendar_id mapping)
- Europe/Madrid timezone configuration

**Technology Stack:**
- google-api-python-client 2.150+
- OAuth2 service account authentication
- Retry logic with exponential backoff (3 attempts)

---

## 6.4 PaymentTools

**Responsibility:** Manages Stripe payment link generation, webhook event processing, refund operations, and payment state validation.

**Key Interfaces:**
- `create_payment_link(appointment_id, amount_euros, customer_name, description)` → payment_url
- `process_payment_webhook(event_type, appointment_id, stripe_payment_id)` → success
- `refund_payment(stripe_payment_id, amount_euros)` → refund_id
- `validate_payment_status(stripe_payment_id)` → PaymentStatus

**Dependencies:**
- Stripe API (Payment Links, Refunds API)
- Appointment table (metadata injection for webhook matching)
- Redis (idempotency tracking for webhook deduplication)

**Technology Stack:**
- stripe 10.0+ Python SDK
- Webhook signature validation (stripe.Webhook.construct_event)
- Test mode support via STRIPE_SECRET_KEY env var

---

## 6.5 CustomerTools

**Responsibility:** CRUD operations for customer records including identification, profile creation, preference updates, and booking history retrieval.

**Key Interfaces:**
- `get_customer_by_phone(phone)` → Customer | None
- `create_customer(phone, first_name, last_name="", metadata={})` → Customer
- `update_customer_name(customer_id, first_name, last_name)` → success
- `update_preferences(customer_id, preferred_stylist_id)` → success
- `get_customer_history(customer_id, limit=5)` → List[Appointment]

**Dependencies:**
- PostgreSQL Customer table
- SQLAlchemy async session

**Technology Stack:**
- SQLAlchemy 2.0+ async ORM
- Phone number normalization (phonenumbers library)
- LangChain @tool decorator for LLM integration

---

## 6.6 BookingTools

**Responsibility:** Business logic for appointment management including provisional booking creation, price/duration calculations, timeout tracking, and state transitions (provisional → confirmed).

**Key Interfaces:**
- `calculate_booking_details(service_ids, pack_id=None)` → {total_price, duration, advance_payment}
- `create_provisional_booking(customer_id, stylist_id, start_time, service_ids, is_same_day)` → Appointment
- `confirm_booking(appointment_id, stripe_payment_id)` → success
- `cancel_booking(appointment_id, reason)` → {refund_triggered, amount}
- `check_timeout_status(appointment_id)` → {expired, minutes_remaining}

**Dependencies:**
- PostgreSQL (Appointment, Service, Pack tables)
- CalendarTools (for provisional event creation)
- PolicyTools (for timeout thresholds, payment percentage)

**Technology Stack:**
- SQLAlchemy transactions with SERIALIZABLE isolation
- Decimal arithmetic for price calculations
- Atomic state transitions (provisional/confirmed/cancelled)

---

## 6.7 NotificationTools

**Responsibility:** Multi-channel notification dispatch including WhatsApp messages via Chatwoot, email/SMS to stylists, and team escalation alerts.

**Key Interfaces:**
- `send_whatsapp_message(customer_phone, message_text)` → success
- `send_stylist_notification(stylist_id, message, channel="email")` → success
- `send_team_escalation(reason, conversation_context, customer_id)` → success
- `send_reminder(appointment_id)` → success (48h advance reminder)

**Dependencies:**
- Chatwoot API (for WhatsApp message sending)
- SMTP/SendGrid (for email notifications)
- Twilio (optional, for SMS notifications)
- Team WhatsApp group conversation ID (for escalations)

**Technology Stack:**
- httpx async HTTP client
- Chatwoot REST API
- Jinja2 templates for message formatting
- Retry logic with circuit breaker pattern

---

## 6.8 Background Workers

**Responsibility:** Scheduled tasks running independently of the main LangGraph flow including 48h reminders, payment timeout enforcement, provisional block cleanup, and conversation archival.

**Key Interfaces:**
- `ReminderWorker.run()` - Runs every 30 minutes, queries appointments 48h out
- `PaymentTimeoutWorker.run()` - Runs every 1 minute, checks provisional bookings
- `ConversationArchiverWorker.run()` - Runs hourly, moves Redis checkpoints to PostgreSQL

**Dependencies:**
- PostgreSQL (Appointment, ConversationHistory tables)
- Redis (checkpoint queries, TTL management)
- NotificationTools (for sending reminders and timeout warnings)

**Technology Stack:**
- Python asyncio with `asyncio.create_task()` for concurrent workers
- APScheduler 3.10+ for cron-like scheduling
- Graceful shutdown handling (SIGTERM)

---

## 6.9 Django Admin Interface

**Responsibility:** Web-based administration panel for salon staff to manage business data including services, packs, stylists, policies, and view read-only appointment calendars.

**Key Interfaces:**
- CRUD forms for Service, Pack, Stylist, Policy models
- Read-only list views for Appointment (filterable by date, stylist, status)
- Holiday blocking form (creates "Cerrado" events in all calendars)

**Dependencies:**
- PostgreSQL (all 7 tables)
- Django authentication (User model for staff login)

**Technology Stack:**
- Django 5.0+ Admin framework
- Django ORM (wraps SQLAlchemy models)
- Default admin theme (responsive, WCAG AA compliant)
- No custom JavaScript (uses Django's built-in admin.js)

---
