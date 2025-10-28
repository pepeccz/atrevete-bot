# Epic 3: Service Discovery & Calendar Availability

**Epic Goal:** Enable customers to inquire about services, view pricing, receive intelligent pack suggestions, and check real-time availability across 5 stylist Google Calendars with filtering by service category (Hairdressing/Aesthetics).

## Story 3.1: Service & Pack Database with Pricing Logic

**As a** system,
**I want** services and packs stored in database with fuzzy search capability,
**so that** the agent can match customer requests to actual offerings even with typos.

**Prerequisites:** Story 1.3a (Services, Packs tables - seeded in 1.3b)

**Acceptance Criteria:**

1. Seed script populates all services from scenarios.md (13+ services)
2. Each service includes: name, category, duration, price, description, requires_advance_payment
3. Seed script populates packs including "Mechas + Corte" (80€, 60min)
4. Function `get_service_by_name(name, fuzzy=True)` uses PostgreSQL ILIKE or pg_trgm (similarity >0.6)
5. Function `get_packs_containing_service(service_id)` returns applicable packs
6. Function `get_packs_for_multiple_services(service_ids)` returns exact matches
7. Function `calculate_total(service_ids)` sums prices and durations
8. Unit test: Search "mechas" → matches "MECHAS"
9. Unit test: Search "mecha" (typo) → fuzzy match returns "MECHAS"
10. Unit test: Verify all scenarios.md services present
11. Unit test: Query packs containing CORTAR → verify "Mechas + Corte"

## Story 3.2: Google Calendar API Integration

**As a** system,
**I want** to integrate with Google Calendar API with holiday detection and robust error handling,
**so that** I can read/write calendar events while respecting salon closures and API rate limits.

**Prerequisites:** Story 1.3a (Stylists table with google_calendar_id)

**Acceptance Criteria:**

1. Google Calendar credentials stored securely in environment
2. CalendarTools class created
3. Tool `get_calendar_availability` returns available slots filtered by category
4. Tool filters stylists by category before checking
5. Tool respects busy events and blocked time
6. Tool detects holidays: queries ALL calendars for events with "Festivo", "Cerrado", "Vacaciones" → returns empty if found
7. Returns slots in 30-min increments within business hours (10-20:00 M-F, 10-14:00 Sat)
8. All datetime operations use Europe/Madrid timezone explicitly
9. Tool `create_calendar_event` creates with metadata
10. Events have status field (provisional/confirmed)
11. Rate limit handling: Max 3 retries (1s, 2s, 4s backoff) → return error after failures
12. Tool `delete_calendar_event` removes events
13. Unit test with mocked API
14. Integration test with sandbox: create → detect busy → delete
15. Integration test: Holiday event → verify empty availability

## Story 3.3: Multi-Calendar Availability Checking

**As a** customer,
**I want** the bot to check availability across multiple stylists and offer me several time options,
**so that** I can choose the slot that best fits my schedule.

**Prerequisites:** Story 3.2 (Calendar integration), Story 3.1 (Service database)

**Acceptance Criteria:**

1. `check_availability` node receives service(s), date, time range from state
2. If no stylist preference → checks ALL matching category stylists
3. If specific stylist requested → checks only that stylist
4. Aggregates slots, selects top 2-3 (prioritize: preferred stylist, earlier times, load balancing)
5. Response: "Este {day} tenemos libre a las {time1} con {stylist1} y a las {time2} con {stylist2}. ¿Cuál prefieres?"
6. If NO availability → offers next 2 dates
7. Same-day bookings: Filter slots <1h from now
8. Performance: Multi-calendar check <8s (95th percentile)
9. Integration test: Request Friday → verify multiple options across stylists
10. Integration test: Fully booked day → verify alternatives
11. Edge case: Request specific stylist → verify only that calendar checked

## Story 3.4: Intelligent Pack Suggestion Logic

**As a** customer requesting an individual service,
**I want** the bot to suggest the best money-saving package deal when multiple options exist,
**so that** I get maximum value without being overwhelmed.

**Prerequisites:** Story 3.1 (Service & Pack database)

**Acceptance Criteria:**

1. `suggest_pack` node queries packs containing requested service
2. If multiple packs → suggest highest savings percentage, tie-break by shorter duration
3. If pack found → transparent comparison
4. Response format with individual vs pack pricing and savings amount
5. If accepted → state updated with pack_id
6. If declined → proceed with individual service
7. If NO pack → skip node (conditional edge)
8. Integration test (Scenario 1): Request "mechas" → verify pack suggested → accept → verify pack_id in state
9. Unit test: Multiple packs → verify highest savings suggested

## Story 3.5: Free Consultation Offering for Indecisive Customers

**As a** customer unsure about which service to choose,
**I want** the bot to offer a free consultation appointment with clear indecision detection,
**so that** I can get expert advice before committing.

**Prerequisites:** Story 3.1 (Consulta Gratuita service)

**Acceptance Criteria:**

1. `detect_indecision` node analyzes message with Claude
2. Indecision patterns provided to Claude: "¿cuál recomiendas?", "no sé si...", "¿qué diferencia?"
3. Classifies with confidence (>0.7 triggers offer)
4. If indecision → `offer_consultation` triggers
5. Retrieves Consulta Gratuita (15min, 0€, requires_advance_payment=false)
6. Response offers consultation
7. If accepted → proceed to availability (no payment)
8. If declined → re-offer service options
9. Consultation skips payment flow (checked via requires_advance_payment)
10. Integration test (Scenario 8): Indecision → consultation offered → booked without payment
11. Unit test: 5 indecision + 5 clear request patterns → verify detection

## Story 3.6: Service Category Mixing Prevention

**As a** system,
**I want** to prevent booking mixed Hairdressing/Aesthetics services with helpful alternatives,
**so that** operational constraints are respected while maintaining good UX.

**Prerequisites:** Story 3.1 (Service database with categories)

**Acceptance Criteria:**

1. `validate_service_combination(service_ids)` function checks categories
2. If mixed categories → returns `{valid: false, reason: 'mixed_categories'}`
3. If same category → returns `{valid: true}`
4. `validate_booking_request` node calls validation before availability
5. If invalid → helpful message with alternatives (book separately or choose one)
6. Offers to process each category as separate booking
7. State tracks multiple pending bookings if customer splits
8. Integration test: "corte + bioterapia facial" → verify error → alternatives offered
9. Unit test: Verify detection for all service combinations
10. Edge case: "corte + color" (both Hairdressing) → verify passes

---
