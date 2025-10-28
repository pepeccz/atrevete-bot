# Epic 1: Foundation & Core Infrastructure

**Epic Goal:** Establish project foundation including Docker environment, database schema, API webhook receiver, and basic LangGraph orchestrator that can receive and respond to a simple WhatsApp message, demonstrating end-to-end connectivity from Chatwoot through the full system stack back to customer.

## Story 0.1: External Service Account Setup

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
   - Example: `GOOGLE_SERVICE_ACCOUNT_JSON=/path/to/key.json   Get from: https://console.cloud.google.com/iam-admin/serviceaccounts`
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

## Story 1.1: Project Structure & Dependency Setup

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

## Story 1.2: Docker Compose Multi-Container Setup

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

## Story 1.3a: Core Database Tables & Models

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

## Story 1.3b: Transactional & History Tables

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

## Story 1.4: FastAPI Webhook Receiver

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

## Story 1.5: Basic LangGraph State & Echo Bot

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

## Story 1.6: CI/CD Pipeline Skeleton

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
