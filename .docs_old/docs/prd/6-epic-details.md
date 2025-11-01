# 6. Epic Details

## Epic 1: Foundation & Core Infrastructure

**Epic Goal:** Establish project foundation including Docker environment, database schema, API webhook receiver, and basic LangGraph orchestrator that can receive and respond to a simple WhatsApp message, demonstrating end-to-end connectivity from Chatwoot through the full system stack back to customer.

### Story 0.1: External Service Account Setup

**As a** developer,
**I want** all external service accounts created and API credentials obtained before starting development,
**so that** I can configure the application with real API keys and test integrations immediately.

**Acceptance Criteria:**

1. **Google Calendar API Setup:**
   - Google Cloud project created (e.g., "atrevete-bot-production")
   - Google Calendar API enabled in project
   - Service account created with name "atrevete-bot-calendar-service"
   - Service account granted domain-wide delegation for Calendar API scopes
   - Service account JSON key file downloaded and stored securely
   - Service account email documented in setup guide

2. **Stripe Account Setup:**
   - Stripe account created (business account recommended)
   - Test mode API keys obtained (publishable key + secret key)
   - Production API keys obtained and stored securely (separate from test keys)
   - Webhook endpoint placeholder configured (will be updated in Story 7.5 with production URL)
   - Stripe API version documented (default to latest stable)

3. **Chatwoot Setup:**
   - Chatwoot instance deployed (self-hosted recommended) OR Chatwoot Cloud account created
   - WhatsApp channel configured and connected
   - Chatwoot API access token generated with full permissions
   - Chatwoot account ID and inbox ID documented
   - Team WhatsApp group created for escalations and group conversation ID obtained

4. **Anthropic Claude API Setup:**
   - Anthropic account created at console.anthropic.com
   - API key generated with appropriate usage limits
   - Billing configured (pay-as-you-go or credits)
   - API key tier documented (free tier vs paid)

5. **Environment Configuration:**
   - `.env.example` updated with all API keys as placeholders
   - Each API key entry includes comment with acquisition URL
   - Example: `GOOGLE_SERVICE_ACCOUNT_JSON=/path/to/key.json  # Get from: https://console.cloud.google.com/iam-admin/serviceaccounts`
   - Secure storage location defined for production credentials (e.g., `.env.production`, Docker secrets)

6. **Documentation:**
   - Setup guide created: `docs/external-services-setup.md`
   - Guide includes step-by-step instructions with screenshots for each service
   - Links to official documentation for each service
   - Troubleshooting section for common setup issues
   - Estimated time per service documented (Google: 15min, Stripe: 10min, Chatwoot: 30min, Anthropic: 5min)

7. **Validation:**
   - All API keys tested with simple "hello world" requests (e.g., `curl` to Stripe API, test Calendar API list events)
   - Chatwoot webhook test message sent and received successfully
   - Claude API test completion generated successfully
   - All credentials stored in secure location (NOT committed to git)

8. **Service Account Permissions (Google Calendar):**
   - Domain-wide delegation configured with scopes: `https://www.googleapis.com/auth/calendar`, `https://www.googleapis.com/auth/calendar.events`
   - Service account granted access to all 5 stylist Google Calendars
   - Test calendar event creation validated across all stylist calendars

9. **Stripe Webhook Configuration:**
   - Webhook signing secret obtained and documented
   - Event types to listen for documented: `checkout.session.completed`, `charge.refunded`
   - Test webhook sent to temporary endpoint (webhook.site or ngrok) to validate signature

10. **Team Access:**
    - All API keys shared with development team via secure method (password manager, encrypted file, secrets management tool)
    - Access permissions documented (who has access to production vs test keys)

**Prerequisites:** None (this is the first story in Epic 1)

**Notes:**
- This story is a **prerequisite for Story 1.1** (dependency setup requires API keys in `.env`)
- Estimated completion time: 1-2 hours for all services
- Production API keys should be obtained but kept separate from development keys
- Service account JSON key should NEVER be committed to git (add to `.gitignore`)

### Story 1.1: Project Structure & Dependency Setup

**As a** developer,
**I want** the project repository structure created with all Python dependencies properly configured,
**so that** I have a clean foundation to start building features without environment issues.

**Prerequisites:** Story 0.1 (External Service Account Setup)

**Acceptance Criteria:**

1. Repository structure created with folders: `/api`, `/agent/graphs`, `/agent/state`, `/agent/tools`, `/agent/nodes`, `/agent/prompts`, `/database`, `/docker`, `/tests`, `/docs`
2. Python 3.11+ virtual environment configured
3. `requirements.txt` includes all dependencies: `langgraph>=0.6.7`, `langchain>=0.3.0`, `langchain-anthropic>=0.3.0`, `anthropic>=0.40.0`, `fastapi[standard]==0.116.1`, `uvicorn[standard]>=0.30.0`, `psycopg[binary]>=3.2.0`, `sqlalchemy>=2.0.0`, `alembic>=1.13.0`, `redis>=5.0.0`, `pydantic>=2.9.0`, `python-dotenv>=1.0.0`, `pytest>=8.3.0`, `pytest-asyncio>=0.24.0`
4. `.gitignore` configured to exclude `.env`, `__pycache__`, `.pytest_cache`, `venv/`, service account JSON keys
5. `.env.example` template created with all required environment variables documented (populated from Story 0.1)
6. `README.md` includes setup instructions for local development, referencing `docs/external-services-setup.md` for API key setup
7. All dependencies install successfully without version conflicts

### Story 1.2: Docker Compose Multi-Container Setup

**As a** developer,
**I want** Docker Compose configured with 3 services (API, Agent, Data),
**so that** the entire system can run locally with a single `docker-compose up` command.

**Acceptance Criteria:**

1. `docker-compose.yml` defines 3 services: `api`, `agent`, `data`
2. `data` service runs PostgreSQL 15+ and Redis 7+
3. `api` service exposes port 8000 for webhook endpoints
4. `agent` service connects to Redis for pub/sub and PostgreSQL for data access
5. All services share a Docker network for inter-container communication
6. Environment variables loaded from `.env` file into containers
7. PostgreSQL data persists via Docker volume (survives container restart)
8. Redis configured with RDB persistence enabled (snapshots every 15 minutes)
9. Health checks configured for all 3 services
10. `docker-compose up` successfully starts all services without errors
11. Logs from all services visible via `docker-compose logs`

### Story 1.3a: Core Database Tables & Models

**As a** developer,
**I want** the core business entity tables created in PostgreSQL,
**so that** customer, stylist, service, and pack data can be stored and queried.

**Acceptance Criteria:**

1. SQLAlchemy models created for 4 core tables: `customers`, `stylists`, `services`, `packs`
2. `customers` table includes: `id` (PK), `phone` (unique, indexed), `first_name`, `last_name`, `created_at`, `last_service_date`, `preferred_stylist_id` (FK to stylists), `total_spent` (decimal), `metadata` (JSONB)
3. `stylists` table includes: `id` (PK), `name`, `category` (enum: Hairdressing/Aesthetics), `google_calendar_id` (unique), `is_active` (boolean, default true)
4. `services` table includes: `id` (PK), `name`, `category` (enum), `duration_minutes` (integer), `price_euros` (decimal), `requires_advance_payment` (boolean), `description` (text)
5. `packs` table includes: `id` (PK), `name`, `included_service_ids` (ARRAY of integers), `duration_minutes`, `price_euros`, `description`
6. Alembic initialized with migration script for these 4 tables
7. All foreign keys defined with ON DELETE CASCADE/SET NULL as appropriate
8. Indexes created on frequently queried columns: `customers.phone`, `stylists.google_calendar_id`, `services.category`
9. `alembic upgrade head` successfully creates these 4 tables
10. Seed data script populates 5 stylists: Pilar (Hairdressing), Marta (Hairdressing+Aesthetics), Rosa (Aesthetics), Harol (Hairdressing), Víctor (Hairdressing)
11. Unit test: Query each table after seeding → verify expected row counts

### Story 1.3b: Transactional & History Tables

**As a** developer,
**I want** transactional tables for appointments, policies, and conversation history,
**so that** bookings and conversation state can be persisted.

**Prerequisites:** Story 1.3a (Core Tables) completed

**Acceptance Criteria:**

1. SQLAlchemy models created for 3 tables: `appointments`, `policies`, `conversation_history`
2. `appointments` table includes: `id` (PK), `customer_id` (FK), `stylist_id` (FK), `service_ids` (ARRAY/JSONB), `start_time` (timestamp with timezone), `duration_minutes`, `total_price`, `advance_payment_amount`, `payment_status` (enum: pending/confirmed/refunded), `status` (enum: provisional/confirmed/completed/cancelled), `google_calendar_event_id` (nullable, indexed), `stripe_payment_id` (nullable, indexed for webhook lookup), `created_at`, `updated_at`
3. `policies` table includes: `id` (PK), `key` (unique varchar), `value` (JSONB) - stores business rules and FAQs
4. `conversation_history` table includes: `id` (PK), `customer_id` (FK), `conversation_id` (indexed), `timestamp`, `message_role` (enum: user/assistant), `message_content` (text), `metadata` (JSONB)
5. Alembic migration script creates these 3 tables with foreign keys to core tables
6. All timestamps use `Europe/Madrid` timezone (explicit in database schema via `AT TIME ZONE 'Europe/Madrid'`)
7. Indexes created: `appointments.stripe_payment_id`, `appointments.status`, `conversation_history.conversation_id`, `policies.key`
8. `alembic upgrade head` successfully creates all 7 tables total
9. Seed data script populates default policies and sample services/packs
10. Integration test: Create appointment → verify all fields populated → query by stripe_payment_id → verify retrieval

### Story 1.4: FastAPI Webhook Receiver

**As a** system,
**I want** FastAPI endpoints that receive and validate webhooks from Chatwoot and Stripe,
**so that** incoming customer messages and payment confirmations are securely captured and queued for processing.

**Acceptance Criteria:**

1. FastAPI application created in `/api` folder with main.py entry point
2. POST endpoint `/webhook/chatwoot` receives WhatsApp messages via Chatwoot webhook
3. Pydantic model validates Chatwoot webhook payload structure
4. Chatwoot webhook authentication implemented (signature validation, IP whitelist, or shared secret token)
5. POST endpoint `/webhook/stripe` receives payment confirmation events
6. Stripe webhook signature validation implemented using `stripe.Webhook.construct_event()`
7. Invalid signatures rejected with 401 Unauthorized
8. Valid Chatwoot messages enqueued to Redis channel `incoming_messages`
9. Valid Stripe payment events enqueued to Redis channel `payment_events`
10. Endpoints return 200 OK immediately after enqueuing (async processing)
11. Rate limiting middleware: max 10 requests/min per IP (returns 429 if exceeded)
12. Health check endpoint GET `/health` returns status with Redis/DB connectivity
13. Unit tests validate payload parsing and Redis enqueuing
14. Integration test simulates webhook → verifies Redis message published

### Story 1.5: Basic LangGraph State & Echo Bot

**As a** system,
**I want** a minimal LangGraph StateGraph that receives messages from Redis and echoes "Hello, I'm Maite" back to WhatsApp,
**so that** end-to-end connectivity is proven with crash recovery validation.

**Prerequisites:** Story 1.3a, 1.3b (Database), Story 1.4 (Webhooks)

**Acceptance Criteria:**

1. `ConversationState` TypedDict defined with fields: `conversation_id`, `customer_phone`, `customer_name`, `messages`, `current_intent`, `metadata`
2. LangGraph StateGraph created in `/agent/graphs/conversation_flow.py`
3. Graph has single node `greet_customer` that returns: "¡Hola! Soy Maite, la asistenta virtual de Atrévete Peluquería 🌸"
4. Redis-backed checkpointer configured using `MemorySaver`
5. Agent worker subscribes to Redis channel `incoming_messages`
6. Graph output published to `outgoing_messages` Redis channel
7. Separate worker sends messages via Chatwoot API
8. Chatwoot API client configured with credentials from environment
9. Checkpointing verified: Kill agent mid-conversation → restart → verify state recovered
10. Integration test: Send mock message → verify greeting sent to Chatwoot
11. Manual test: Send real WhatsApp message → receive greeting

### Story 1.6: CI/CD Pipeline Skeleton

**As a** developer,
**I want** a basic CI/CD pipeline that runs tests and enforces code quality standards,
**so that** regressions are caught early and minimum quality bar is maintained.

**Acceptance Criteria:**

1. GitHub Actions workflow configured in `.github/workflows/test.yml`
2. Pipeline triggers on push to `main` and pull requests
3. Pipeline steps: checkout, setup Python 3.11, install deps, run linter (ruff), type check (mypy), pytest
4. Linting must pass (ruff returns 0)
5. Type checking must pass (mypy returns 0)
6. All tests must pass
7. Code coverage must be ≥80% - pipeline fails if below threshold
8. Coverage report uploaded to CI artifacts
9. Pipeline completes in <5 minutes
10. Badge added to README.md showing status
11. Dependency caching configured for speed

---

## Epic 2: Customer Identification & Conversational Foundation

**Epic Goal:** Implement intelligent customer identification (new vs returning), warm greeting protocol with "Maite" persona, name confirmation flow, and conversational memory system—enabling natural back-and-forth dialogue that remembers context across multiple message exchanges.

### Story 2.1: CustomerTools Implementation

**As a** system,
**I want** CustomerTools that provide complete database operations for customer lifecycle management,
**so that** the agent can identify, create, update, and query customer records including name corrections.

**Prerequisites:** Story 1.3a (Customers table)

**Acceptance Criteria:**

1. CustomerTools class created in `/agent/tools/customer_tools.py`
2. Tool `get_customer_by_phone(phone: str)` queries database and returns customer or None
3. Tool `create_customer(phone: str, first_name: str, last_name: str = "")` creates new customer
4. Tool `update_customer_name(customer_id: int, first_name: str, last_name: str)` updates name
5. Tool `update_customer_preferences(customer_id: int, preferred_stylist_id: int)` updates preferences
6. Tool `get_customer_history(customer_id: int, limit: int = 5)` returns last N appointments
7. All tools use async SQLAlchemy sessions
8. Tools integrated with LangChain's `@tool` decorator
9. Phone number normalization applied (E.164 format)
10. Error handling: Database failures return graceful error messages
11. Unit tests with mocked database
12. Integration test: Create → query → update → verify persistence

### Story 2.2: New Customer Greeting & Name Confirmation

**As a** new customer,
**I want** the bot to greet me warmly, introduce itself as "Maite", and confirm my name with fallback handling,
**so that** I feel welcomed and the bot has accurate information even if I provide unclear responses.

**Prerequisites:** Story 2.1 (CustomerTools), Story 1.5 (Basic StateGraph)

**Acceptance Criteria:**

1. LangGraph node `identify_customer` queries CustomerTools by phone
2. If customer NOT found → triggers `greet_new_customer` node
3. Greeting message: "¡Hola! Soy **Maite, la asistenta virtual de Atrévete Peluquería** 🌸. Encantada de saludarte. ¿Me confirmas si tu nombre es {metadata_name}?"
4. If WhatsApp name unreliable → asks: "¿Me confirmas tu nombre para dirigirme a ti correctamente?"
5. State updated with `awaiting_name_confirmation: true`
6. `confirm_name` node processes response
7. If confirmed → create_customer with name
8. If different name provided → create_customer with corrected name
9. If ambiguous response (max 2 attempts) → escalate with note
10. After confirmation, state updated `customer_identified: true`
11. Integration test: New customer → greeting → name confirmation → database record
12. Emoji 🌸 validated in greeting

### Story 2.3: Returning Customer Recognition

**As a** returning customer,
**I want** the bot to recognize me and skip the introduction while intelligently routing to my request,
**so that** I can quickly get assistance without repetitive onboarding.

**Prerequisites:** Story 2.1 (CustomerTools), Story 2.2 (New customer flow)

**Acceptance Criteria:**

1. `identify_customer` node checks if customer exists
2. If FOUND → state updated with customer details and `is_returning: true`
3. `extract_intent` node uses Claude to analyze message for intent
4. Intent passed to router (booking, modification, cancellation, inquiry, faq)
5. If clear intent → personalized response directly addressing request
6. If greeting-only → "¡Hola, {first_name}! Soy Maite 🌸. ¿En qué puedo ayudarte hoy?"
7. No name confirmation for returning customers
8. Customer history retrieved for "lo de siempre" logic
9. Integration test: Returning customer → no name confirmation → intent routing
10. Edge case: Incomplete profile → still recognized, proceed

### Story 2.4: Maite System Prompt & Personality

**As a** system,
**I want** the "Maite" persona defined in a comprehensive system prompt with escalation instructions,
**so that** all responses maintain consistent tone and the agent knows how to handle edge cases.

**Acceptance Criteria:**

1. System prompt file created in `/agent/prompts/maite_system_prompt.md`
2. Prompt includes role: "Eres Maite, la asistenta virtual de Atrévete Peluquería..."
3. Tone guidelines: warm, friendly, Spanish (tú form), emoji usage (🌸💕😊🎉💇)
4. Business context: 5 stylists, service categories, advance payment policy
5. Tool usage instructions: "SIEMPRE consulta herramientas, NUNCA inventes"
6. Escalation instructions with tool calls: medical → `escalate_to_human(reason='medical_consultation')`, payment failures → after 2 attempts, ambiguity → after 3 exchanges
7. Example interactions demonstrating tone
8. Prompt loaded as initial system message in StateGraph
9. Integration test: Generate 5 responses → manual tone/emoji/Spanish validation
10. Unit test: Verify prompt file loads correctly

### Story 2.5a: Redis Checkpointing & Recent Message Memory

**As a** system,
**I want** LangGraph conversation state persisted to Redis with recent message windowing,
**so that** conversations can recover from crashes and maintain short-term context.

**Prerequisites:** Story 1.5 (Basic LangGraph setup)

**Acceptance Criteria:**

1. State schema includes `recent_messages` (last 10 message exchanges)
2. LangGraph `MemorySaver` uses Redis backend
3. Checkpoints saved after each node with key pattern `langgraph:checkpoint:{conversation_id}:{timestamp}`
4. `add_message` helper maintains max 10 messages (FIFO)
5. Redis RDB snapshots every 15 minutes
6. State TTL: 24 hours
7. On resume, StateGraph loads latest checkpoint
8. Crash recovery test: 3 messages → kill agent → restart → send message → verify 3 previous messages retained
9. Unit test: add_message maintains exactly 10 messages
10. Integration test: Verify checkpoint in Redis, retrieve, validate structure

### Story 2.5b: Conversation Summarization with Claude

**As a** system,
**I want** long conversations automatically summarized to compress token usage,
**so that** the agent can maintain context without exceeding Claude's token limits.

**Prerequisites:** Story 2.5a (Message windowing)

**Acceptance Criteria:**

1. State includes `conversation_summary` field
2. `summarize_conversation` node triggers after every 5 message exchanges
3. Node calls Claude to compress messages beyond recent 10
4. Summary prompt: "Resume la siguiente conversación en 2-3 oraciones..."
5. Summary stored, older messages removed
6. All LLM calls receive: system_prompt + summary + recent_messages
7. Token overflow protection: If >70% context → aggressive summarization or escalation flag
8. Unit test: 25 messages → verify summaries at message 15 and 25
9. Integration test: 30 messages → verify final context <10k tokens

### Story 2.5c: PostgreSQL Archiving Worker & TTL Management

**As a** system,
**I want** expired conversation state archived from Redis to PostgreSQL for historical analysis,
**so that** customer interaction history is preserved beyond 24-hour Redis TTL.

**Prerequisites:** Story 2.5a (Redis checkpointing), Story 1.3b (conversation_history table)

**Acceptance Criteria:**

1. Background worker `/agent/workers/conversation_archiver.py`
2. Runs hourly on cron schedule
3. Queries Redis for checkpoints older than 23 hours
4. For each: retrieve state → insert messages to conversation_history → delete checkpoint
5. Records include customer_id, conversation_id, timestamp, role, content, metadata
6. Worker logs archiving activity
7. Error handling: Retry once on PostgreSQL failure, then skip
8. Health check endpoint/file for monitoring
9. Integration test: Create 23.5h old checkpoint → run worker → verify in conversation_history → verify deleted from Redis
10. Unit test: Mock expired checkpoints → verify processing

### Story 2.6: FAQ Knowledge Base Responses

**As a** customer,
**I want** to ask common questions and receive instant answers in Maite's tone,
**so that** I get information quickly without escalation.

**Prerequisites:** Story 1.3b (Policies table), Story 2.4 (Maite prompt)

**Acceptance Criteria:**

1. FAQ data stored in `policies` table with JSON structure
2. Seed script populates minimum 5 FAQs: hours, parking, address, cancellation policy, payment
3. `detect_faq_intent` node uses Claude for classification
4. If FAQ detected → `answer_faq` retrieves from database
5. Answers formatted with Maite's tone + emojis
6. After FAQ → proactive: "¿Hay algo más en lo que pueda ayudarte? 😊"
7. Sample FAQs implemented per AC
8. If location FAQ → optionally offer Google Maps link
9. Integration test: "¿Abrís los sábados?" → verify answer → verify follow-up
10. Unit test: 10 variations per FAQ → verify detection

**Enhanced Capabilities (Implemented):**

11. **Multi-FAQ Detection:** `detect_faq_intent` returns list `detected_faq_ids` (e.g., ["address", "parking"])
12. **Query Complexity Classification:** Node classifies queries as "simple", "compound", or "none"
13. **Hybrid Routing Strategy:**
    - Simple single-FAQ queries → `answer_faq` (static, fast path)
    - Compound multi-FAQ queries → `fetch_faq_context` → `generate_personalized_faq_response` (AI path)
14. **AI Personalization Module (`faq_generation.py`):**
    - Detects customer tone (formal vs informal) from message markers
    - Personalizes greeting with customer name when available
    - Synthesizes multiple FAQs into single cohesive response
    - Enforces 150-word maximum for conciseness
    - Adapts emoji usage to customer communication style
15. **State Extensions:**
    - `detected_faq_ids`: list[str] (multi-FAQ support)
    - `query_complexity`: Literal["simple", "compound", "contextual", "none"]
    - `faq_context`: list[dict] (FAQ data for AI generation)
16. **Graceful Fallback:** AI generation errors fall back to static `answer_faq`
17. Integration test: Compound query ("¿Dónde estáis y hay parking?") → both FAQs answered in single response
18. Unit test: Tone detection → formal query returns formal response, informal returns informal
19. Performance: Simple FAQ response <2s, compound AI response <5s (95th percentile)

**Note:** The hybrid approach optimizes for both speed (simple queries) and intelligence (compound queries), maintaining backward compatibility with the basic static system while enhancing user experience.

---

## Epic 3: Service Discovery & Calendar Availability

**Epic Goal:** Enable customers to inquire about services, view pricing, receive intelligent pack suggestions, and check real-time availability across 5 stylist Google Calendars with filtering by service category (Hairdressing/Aesthetics).

### Story 3.1: Service & Pack Database with Pricing Logic

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

### Story 3.2: Google Calendar API Integration

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

### Story 3.3: Multi-Calendar Availability Checking

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

### Story 3.4: Intelligent Pack Suggestion Logic

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

### Story 3.5: Free Consultation Offering for Indecisive Customers

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

### Story 3.6: Service Category Mixing Prevention

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

## Epic 4: Booking Flow & Payment Processing

**Epic Goal:** Complete the booking lifecycle from provisional calendar blocking through Stripe payment processing to confirmed appointment creation, including timeout management, payment retry logic, group bookings, third-party bookings, and confirmation notifications.

### Story 4.1: BookingTools - Price & Duration Calculations

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

### Story 4.2: Provisional Calendar Blocking with Timeouts

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

### Story 4.3: PaymentTools - Stripe Payment Link Generation

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

### Story 4.4: Payment Timeout Reminder & Auto-Release Worker

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

### Story 4.5: Stripe Webhook Payment Confirmation

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

### Story 4.6: Payment Retry Logic & Escalation

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

### Story 4.7: Group Bookings & Simultaneous Availability

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

### Story 4.8: Third-Party Booking Support

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

### Story 4.9: Booking Confirmation & Notifications

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

## Epic 5: Modification & Cancellation Management

**Epic Goal:** Handle post-booking changes including appointment modifications, cancellations with refund logic (>24h), rescheduling offers (<24h), customer delay notifications, and "lo de siempre" recognition.

### Story 5.1: Appointment Modification Flow

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

### Story 5.2: Cancellation with >24h Notice (Refund)

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

### Story 5.3: Cancellation with <24h Notice (Rescheduling Offer)

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

### Story 5.4: Customer Delay Notifications (<1h to Appointment)

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

### Story 5.5: "Lo de Siempre" (Usual Service) Recognition

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

## Epic 6: Notifications & Intelligent Escalation

**Epic Goal:** Implement automated 48-hour advance reminders, same-day booking urgent notifications, intelligent escalation system for medical consultations, payment failures, and complex queries, with rich context passed to the human team.

### Story 6.1: 48-Hour Automated Reminder Worker

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

### Story 6.2: Same-Day Booking Urgent Notifications

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

### Story 6.3: Medical Consultation Escalation

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

### Story 6.4: Escalation Tool & Team Notification System

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

### Story 6.5: Unresolved Ambiguity Escalation

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

### Story 6.6: Holiday/Closure Detection & Customer Notification

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

## Epic 7: Testing, Validation & Production Hardening

**Epic Goal:** Comprehensive validation of all 18 conversational scenarios through automated integration tests, manual stylist testing, concurrency/race condition testing, security hardening, performance validation, and production deployment preparation.

### Story 7.1: Integration Tests for 18 Conversational Scenarios

**As a** QA engineer,
**I want** automated integration tests for all 18 scenarios,
**so that** every conversational path is validated before production.

**Prerequisites:** All Epics 1-6 completed

**Acceptance Criteria:**

1. Integration test suite `/tests/integration/scenarios/` with 18 files
2. Each test uses pytest-asyncio
3. Tests use staging environment with mocked external APIs
4. Test harness simulates complete conversation flows
5-22. Each scenario test validates specific flow (Scenario 1-18)
23. All tests must pass for deployment
24. Full suite completes in <10 minutes
25. CI/CD integration

### Story 7.2: Concurrency & Race Condition Testing

**As a** system architect,
**I want** to validate concurrent booking attempts don't cause double-booking,
**so that** the system safely handles simultaneous requests.

**Prerequisites:** Story 4.2 (Provisional blocks), Story 4.5 (Payment confirmation)

**Acceptance Criteria:**

1. Concurrency test suite created
2. Test: Two customers book same slot simultaneously (<100ms apart)
3. Expected: Only ONE succeeds
4. Validates atomic transactions (PostgreSQL locking)
5. Test: Customer 1 has provisional, Customer 2 tries same slot
6. Expected: Customer 2 blocked or gets "unavailable"
7. Test: Two payment webhooks for same appointment_id
8. Expected: Idempotency - only first processes
9. Test: 50 concurrent requests across different slots
10. Expected: All succeed, <10s response time (95th percentile)
11. Test: Provisional block expires when payment arrives
12. Expected: Graceful handling
13. Test logs timing data
14. Integration test: Run 10 times → verify 0 double-bookings
15. No database timeout errors

### Story 7.3: Security Validation & Penetration Testing

**As a** security engineer,
**I want** to validate all security controls,
**so that** customer data and payments are protected.

**Prerequisites:** Story 1.4 (Webhook validation), Epic 4 (Payment flows)

**Acceptance Criteria:**

1. Security test suite created
2. Test: Invalid Stripe signature → 401
3. Test: Invalid Chatwoot auth → rejection
4. Test: Rate limiting → 429 after 10 requests
5. Test: SQL injection protection
6. Test: No API keys in git
7. Test: HTTPS requirement
8. Test: GDPR data deletion
9. Test: PCI compliance (no card data stored)
10. Test: Redis security (password required)
11. Test: Session hijacking resistance
12. Manual penetration test or OWASP ZAP scan
13. 0 critical/high severity issues
14. Security documentation created
15. Secrets rotation procedure tested

### Story 7.4: Performance Testing & Optimization

**As a** performance engineer,
**I want** to validate system meets all NFR performance targets,
**so that** customer experience remains fast under load.

**Prerequisites:** All functional epics complete

**Acceptance Criteria:**

1. Performance test suite using locust or pytest-benchmark
2. Test: Standard query response time
3. Target: 95th percentile <5s
4. Test: Complex operation (multi-calendar check)
5. Target: 95th percentile <10s
6. Test: 100 concurrent conversations
7. Target: No degradation
8. Test: Database query optimization
9. Index optimization validated
10. Test: Redis checkpoint performance
11. Target: <100ms checkpoint save
12. Test: Claude API latency
13. Typical: 1-3s (external dependency)
14. Load test: 30 conversations/hour for 8 hours
15. Target: 99.5% uptime, no crashes/leaks
16. Monitoring: Memory, CPU, connection pool
17. Optimization: Profile and fix bottlenecks if needed

### Story 7.5: Production Environment Setup & Deployment

**As a** DevOps engineer,
**I want** production infrastructure configured with HTTPS, monitoring, and backups,
**so that** the system is secure, observable, and recoverable.

**Prerequisites:** All testing complete (Stories 7.1-7.4 passing)

**Acceptance Criteria:**

1. VPS/Cloud server provisioned (4GB RAM, 2 vCPU, 50GB SSD)
2. Docker and Docker Compose installed
3. HTTPS: Nginx + Let's Encrypt with auto-renewal
4. Domain configured pointing to server
5. Production `.env` with all secrets
6. Firewall: Only 80, 443, 22 open
7. PostgreSQL automated daily backups (S3/Spaces)
8. Backup retention: 30 days
9. Redis RDB snapshots every 15 minutes
10. Docker Compose production config (restart: always)
11. Deployment script: zero-downtime
12. Monitoring: LangSmith + structured logs
13. Logging: JSON format, /var/log/, 14-day rotation
14. Health check monitored by UptimeRobot
15. Smoke test after deployment
16. Rollback procedure documented
17. Deployment completed with 0 downtime

### Story 7.6: Manual Stylist Validation & Soft Launch

**As a** product manager,
**I want** stylists to test the system with real scenarios before full launch,
**so that** we catch usability issues and validate MVP success criteria.

**Prerequisites:** Story 7.5 (Production deployment), All scenario tests passing

**Acceptance Criteria:**

1. Beta testing plan: 2-week validation with 5 stylists
2. Training session: 30-min walkthrough
3. Test scenarios provided
4. Real WhatsApp integration
5. Stylist feedback collection: daily check-ins, end-of-week survey
6. Success metrics tracking: ≥70% automation, ≥80% escalation precision, ≥99.5% uptime, ≥20 real bookings, ≥7/10 satisfaction
7. Bug tracking and prioritization
8. Data analysis: conversation logs review
9. Iteration: prompt adjustments, FAQ additions
10. Go/No-Go decision after 2 weeks
11. If criteria not met → extend beta
12. Final validation: ≥20 successful end-to-end bookings
13. Stylist sign-off: All 5 approve

### Story 7.7: Monitoring Dashboard & Operational Runbook

**As a** system operator,
**I want** a monitoring dashboard and runbook for common issues,
**so that** I can quickly diagnose and resolve problems.

**Prerequisites:** Story 7.5 (Production deployment)

**Acceptance Criteria:**

1. Monitoring dashboard (Grafana/Datadog/custom)
2. Key metrics: conversations/hour, automation rate, escalation rate, response time, payment success, uptime, error rate
3. Database metrics: connection pool, slow queries, table sizes
4. Redis metrics: memory, keyspace, checkpoint count
5. External API health tracking
6. Alerting rules: uptime, error rate, escalation rate, worker failures, disk usage
7. Operational runbook: restart, logs, manual escalation, refund, restore, outage handling, stuck checkpoints, emergency contacts
8. Incident response procedure
9. On-call rotation defined
10. Dashboard read-only for stakeholders
11. Weekly metrics review scheduled

---
