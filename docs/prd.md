# Atrévete Bot - Brownfield Enhancement PRD v2.0
## Hybrid Architecture Edition

**Version:** 2.0
**Date:** 2025-10-31
**Author:** John (PM Agent)
**Status:** READY FOR IMPLEMENTATION ✅

---

## Table of Contents

1. [Intro: Project Analysis and Context](#1-intro-project-analysis-and-context)
2. [Requirements](#2-requirements)
3. [Technical Constraints and Integration Requirements](#3-technical-constraints-and-integration-requirements)
4. [Epic and Story Structure](#4-epic-and-story-structure)
5. [Next Steps](#5-next-steps)

---

## 1. Intro: Project Analysis and Context

### 1.1 Analysis Source

**✅ IDE-based fresh analysis + BMAD 3.0 documentation**

This PRD is based on direct analysis of the current codebase at `/home/pepe/atrevete-bot/` combined with the architectural pivot documentation (BMAD 3.0) that chronicles the shift toward hybrid architecture.

---

### 1.2 Current Project State

**Atrévete Bot** is an AI-powered WhatsApp booking assistant for a beauty salon/spa. Currently in **advanced development phase** with a hybrid 2-tier architecture:

**Implemented State (Epic 1 + Hybrid Architecture):**

- **Tier 1 - Conversational Agent**: Single `conversational_agent` node powered by Claude Sonnet 4 with access to 8 tools (customer, FAQ, services, availability, pack, consultation, booking initiation, escalation). Claude handles FAQs, greetings, customer identification, service inquiries, indecision detection, and pack suggestions in a natural, conversational manner.

- **Tier 2 - Transactional Flows**: 6 explicit LangGraph nodes for booking, service validation, availability checking, pack suggestion (post-booking intent), and payment management. Robust state (50 fields) tracks booking context and transactions.

- **Complete Infrastructure**: 4-service Docker architecture (PostgreSQL, Redis Stack, FastAPI API, LangGraph Agent), database models with Alembic migrations, AsyncRedisSaver checkpointing with Redis Stack (RedisSearch/RedisJSON), comprehensive JSON logging, Chatwoot webhook receiver with token auth, Stripe payment integration prepared.

- **Solid Testing**: 350 tests (~85% coverage), 42 test files organized by unit/integration/scenarios/mocks.

**Critical Transition (Oct 30 - BMAD 3.0):**
The project pivoted from an architecture of **25 explicit nodes** (158 state fields) toward **12 hybrid nodes** (50 fields), consolidating 13 conversational nodes into a single Claude-powered `conversational_agent`. This radical simplification (-52% nodes, -68% state fields) eliminated conversational rigidity while preserving transactional control.

**Primary Purpose:**
Automate 85%+ of booking conversations via WhatsApp without human intervention, manage appointments for 5 stylists using Google Calendar, process advance payments (20%) via Stripe, and escalate complex cases to the human team. First implementation of advance payment for the salon.

---

### 1.3 Available Documentation Analysis

**✅ Documentation Status: COMPREHENSIVE (Post-Consolidation)**

**Available Documentation:**

- ✅ **Tech Stack Documentation**: `CLAUDE.md` (165 lines) + `docs/architecture.md` (74KB, v1.1 updated post-Epic 1) - documents Python 3.12, LangGraph 0.6.7+, Claude Sonnet 4, FastAPI, PostgreSQL 15+, Redis Stack 7.4.0
- ✅ **Source Tree/Architecture**: `docs/architecture.md` covers high-level architecture (4-service Docker), deployment architecture (VPS), hybrid 2-tier pattern, complete component breakdown
- ✅ **Coding Standards**: `docs/architecture.md` Section + `CLAUDE.md` Important Patterns - config access via `shared/config.py`, state immutability, `add_message()` helper, async DB sessions, Chatwoot API patterns
- ✅ **API Documentation**: `docs/architecture.md` Section 9 (FastAPI endpoints), webhook payloads, Stripe integration, Chatwoot message format
- ✅ **External API Documentation**: Google Calendar API integration documented, Stripe payment flow, Chatwoot webhook auth, Anthropic Claude tool binding
- ⚠️ **UX/UI Guidelines**: Exists in `agent/prompts/maite_system_prompt.md` (31KB) - comprehensive personality, tone, emoji usage, conversational guidelines for Claude
- ✅ **Technical Debt Documentation**: 18 BMAD documents in `.docs_old/docs/bmad/` track all Epic 1 deviations + BMAD 3.0 documenting architectural pivot
- ✅ **PRD Original**: `docs/prd.md` (84KB, v1.0) - comprehensive but OUTDATED (assumes 25-node architecture, needs update)

**Important Note:**
The project recently consolidated fragmented (sharded) documentation into single files (`docs/prd.md`, `docs/architecture.md`), moving old docs to `.docs_old/`. This indicates recent documentary maturity and cleanup.

---

### 1.4 Enhancement Scope Definition

#### 1.4.1 Enhancement Type

**✅ Major Feature Completion + Architecture Alignment**

This is not an isolated enhancement, but the **completion of the original project adapted to the new hybrid architecture**. Specifically:

- **Technology Stack Upgrade**: ✅ ALREADY APPLIED (Python 3.11→3.12, hybrid architecture)
- **Major Feature Modification**: ✅ Conversational flows now Claude-driven vs node-driven
- **New Feature Addition**: Complete Epics 2-7 (customer identification, booking, payment, notifications) using new architecture

#### 1.4.2 Enhancement Description

Complete the development of **Atrévete Bot** (Epics 2-7) using the new **hybrid 2-tier architecture** implemented in the Oct 30 pivot (BMAD 3.0).

The system must finalize: customer identification (new/returning), complete booking flow with mixed category validation, real Google Calendar integration (5 stylists), Stripe payment processing (20% advance), modification/cancellation management with refund policies, and intelligent reminder/escalation system.

The key is to **adapt the original Epics 2-7** (designed for 25 explicit nodes) to the current reality of **12 nodes with Claude handling conversational logic**.

#### 1.4.3 Impact Assessment

**✅ Moderate Impact (architecture already established, completing features)**

- **NO major architectural changes** - the hybrid architecture is already implemented and validated
- **Affected existing code**: Transactional nodes need expansion (booking, payment) but base structure exists
- **New components**: Google Calendar integration (new), Stripe webhooks (partial), notification workers (new), but Docker infrastructure already supports workers (archiver exists)
- **Testing**: Solid test structure (350 tests), add E2E scenarios and mocks for Calendar/Stripe

---

### 1.5 Goals and Background Context

#### 1.5.1 Goals

**Enhancement Objectives (complete Atrévete Bot v1.0):**

- Finalize customer identification system (new vs returning) with persistent PostgreSQL database
- Implement complete booking flow with real availability checking in Google Calendar (5 stylists)
- Complete Stripe payment processing: link generation, webhook validation, booking confirmation
- Implement modification/cancellation management with automatic refund policies (>24h) vs rescheduling (<24h)
- Develop automatic reminder system (48h before) and urgent notifications (same-day bookings)
- Implement intelligent escalation to human team via Chatwoot (medical queries, payment failures, frustrations)
- Achieve 85%+ automation of conversations without human intervention
- Validate hybrid architecture in production with comprehensive testing (integration + E2E scenarios)

#### 1.5.2 Background Context

Atrévete Peluquería currently manages all reservations manually via WhatsApp (15-20 min per booking) for 5 stylists with separate Google Calendars. The salon loses 20-30% of inquiries outside business hours and faces operational friction during peak hours.

**Architectural Pivot (Oct 30, 2025):**
During Epic 1, the team detected that the original architecture (25 LangGraph nodes with explicit control of all conversational flows) generated **rigidity and unnatural responses**. The bot would get "trapped" in waiting states when customers changed topics, requiring "topic change detection" as an escape hatch (clear code smell).

The pivot toward **hybrid architecture** (BMAD 3.0) separated responsibilities:
- **Tier 1 (Claude)**: Handles all natural conversation, FAQs, queries, identification
- **Tier 2 (LangGraph)**: Handles critical transactions (booking, payment, modification) with robust state

This change reduced complexity by 52% (nodes) and 68% (state fields) while improving conversational naturalness. **This PRD documents how to complete Epics 2-7 under this new architectural reality.**

**First Implementation of Advance Payment:**
The salon never required advance payments before. The system must smoothly introduce the 20% advance requirement, handling objections and explaining benefits (reduce no-shows).

---

### 1.5.3 Change Log

| Change | Date | Version | Description | Author |
|--------|------|---------|-------------|--------|
| Initial Greenfield PRD | 2025-10-22 | v1.0 | Original PRD with 25-node architecture | Claude (PM Agent) |
| Architecture Pivot | 2025-10-30 | - | BMAD 3.0: Pivot to hybrid architecture (12 nodes) | Sarah (PO Agent) |
| Brownfield PRD Creation | 2025-10-31 | v2.0 | Updated PRD reflecting real hybrid architecture | John (PM Agent) |

---

## 2. Requirements

### 2.1 Functional Requirements

**IMPORTANT:** The functional requirements FR1-FR45 from the original PRD **remain valid** - the "what the system does" hasn't changed. What changed is the "how it implements it" (hybrid architecture vs explicit nodes).

**Tier 1 Requirements (Conversational Agent with Claude):**

**FR1:** The system shall identify customers (new/returning) by querying the database by phone number, using `get_customer_by_phone` tool called by Claude in the `conversational_agent` node

**FR2:** The system shall present itself as "Maite, la asistenta virtual de Atrévete Peluquería" with warm tone and appropriate emojis (🌸💕😊) in first interaction, using guidance from `maite_system_prompt.md`

**FR3:** The system shall confirm customer name for first-timers when WhatsApp metadata is unreliable, using `create_customer` tool in natural conversation

**FR4:** The system shall omit greeting/introduction protocol for returning customers, proceeding directly to their request based on `customer_history` loaded from database

**FR5:** The system shall maintain conversational memory using hybrid strategy: FIFO window of 10 recent messages + compressed summary (Claude-generated via `summarize_conversation` node) + customer service history from PostgreSQL

**FR6:** The system shall check real-time availability across 5 stylist Google Calendars, filtering by service category (Hairdressing/Aesthetics), using `check_availability_tool` called by Claude for informational queries OR transactional `check_availability` node during booking flow

**FR7:** The system shall calculate total price and duration for individual services or combinations, displaying both in responses, using `get_services` tool to obtain data from database

**FR8:** The system shall offer multiple time slot options (minimum 2 when available) across different professionals or time ranges per customer request

**FR9:** The system shall detect when customer requests services included in discounted packs and proactively suggest the pack with price comparison, using `suggest_pack_tool` in Tier 1 (conversational) OR `suggest_pack` node in Tier 2 (post-booking intent)

**FR10:** The system shall offer free consultation (10-15 min, €0) when customer expresses indecision about service selection or requests technical product comparisons, using `offer_consultation_tool` called by Claude when detecting indecision signals

**FR11:** The system shall enforce business rule that Hairdressing and Aesthetics services CANNOT be combined in a single appointment, validated in `validate_booking_request` node (Tier 2) with `mixed_category_detected` flag

**Tier 2 Requirements (Transactional Nodes - Booking & Payment):**

**FR12:** The system shall create provisional calendar blocks with 30-minute timeout (15 minutes for same-day) during payment processing to prevent double-booking

**FR13:** The system shall request customer surnames for new customers before generating payment links to complete registration (via `create_customer` tool)

**FR14:** The system shall generate Stripe payment links for 20% advance and send them via WhatsApp for all non-zero price services

**FR15:** The system shall send payment reminder at 25 minutes (5 min before timeout) before automatically releasing provisional calendar blocks

**FR16:** The system shall generate new payment link on first retry when customer reports payment failure, escalating to human team after second failure (using `escalate_to_human` tool)

**FR17:** The system shall validate payment completion via Stripe webhook before confirming final booking

**FR18:** The system shall create, modify, and cancel Google Calendar events for stylists while respecting individual working hours and blocked time

**FR19:** The system shall process cancellations with >24h notice by triggering automatic advance payment refund

**FR20:** The system shall process cancellations with <24h notice by offering rescheduling options without losing advance payment instead of refunds

**FR21:** The system shall detect holiday/closure events in Google Calendar and inform customers of closure with next available date suggestion

**FR22:** The system shall filter same-day availability to exclude time slots with <1 hour lead time to allow for payment processing and customer travel

**FR23:** The system shall send urgent notifications to professionals via email/SMS within 2 minutes for same-day bookings confirmed after payment

**FR24:** The system shall send automatic WhatsApp reminders 48 hours before each appointment including service, stylist, time, duration, advance amount, and cancellation policy notice (24h threshold)

**FR25:** The system shall retrieve and present customer's last service combination when requesting "lo de siempre" (the usual), including preferred professional, querying `customer_history` from database

**Intelligent Escalation Requirements:**

**FR26:** The system shall automatically escalate to human team via Chatwoot group notification for: medical queries (pregnancy, allergies, skin conditions), payment issues after 2 failed attempts, frustrated customer/requests human, assistant unsure after 3 clarification attempts. Implemented via `escalate_to_human` tool accessible from Claude at any conversational moment.

**External Integration Requirements:**

**FR27:** The system shall integrate with Google Calendar API using service account with access to 5 stylist calendars for CRUD event operations

**FR28:** The system shall integrate with Stripe API for payment link generation, webhook confirmation processing, and automatic refund execution

**FR29:** The system shall integrate with Chatwoot API to receive WhatsApp messages via webhooks, send responses, and publish escalation notifications to team group

**FR30:** The system shall integrate with Anthropic Claude API (Sonnet 4) for natural language processing, conversational reasoning, and tool calling decisions in `conversational_agent` node

**Persistence and State Requirements:**

**FR31:** The system shall persist customer data (name, surnames, phone, history) in PostgreSQL with UUID primary keys

**FR32:** The system shall persist confirmed appointments in PostgreSQL with foreign keys to customers, services, stylists

**FR33:** The system shall maintain short-term conversational state in Redis Stack (15 min TTL) using AsyncRedisSaver with RedisSearch indexes for LangGraph checkpointing

**FR34:** The system shall archive expired conversations from Redis to PostgreSQL every 5 minutes via `conversation_archiver` background worker

**FR35:** The system shall implement FIFO message windowing (last 10 exchanges) with automatic summarization of old messages via Claude for context window management

---

### 2.2 Non-Functional Requirements

**NFR1:** The system shall respond to standard queries in <5 seconds (95th percentile), allowing for external API latency (Claude: 1-3s, Calendar: 0.5-1s)

**NFR2:** The system shall maintain 99.5% uptime during business hours (Tuesday-Saturday 09:00-20:00 Europe/Madrid), excluding planned maintenance

**NFR3:** The system shall support concurrent conversations of up to 20 simultaneous customers without performance degradation (realistic limit for 5-stylist salon)

**NFR4:** The system shall implement comprehensive JSON structured logging to stdout with trace IDs (`conversation_id`) for production troubleshooting

**NFR5:** The system shall maintain testing coverage ≥85% (unit + integration + scenario tests) as deployment gate

**NFR6:** The system shall apply rate limiting to webhook endpoints (10 requests/sec per IP) to prevent abuse

**NFR7:** The system shall implement graceful degradation: if Claude API fails, respond with "Disculpa, estoy teniendo problemas técnicos. Un miembro del equipo te contactará pronto" and auto-escalate

**NFR8:** The system shall use timezone Europe/Madrid consistently for all date operations (Python `zoneinfo.ZoneInfo`)

**NFR9:** The system shall implement idempotency for critical operations (payment confirmation, booking creation) using deduplication keys

**NFR10:** The system shall limit Maite system prompt to 32K tokens (~31KB current file) for Claude context window compatibility

**NFR11:** The system shall execute database migrations using Alembic with rollback capability for zero-downtime deployments

**NFR12:** The system shall implement health check endpoints (`/health`) for monitoring and container orchestration

---

### 2.3 Compatibility Requirements

**CR1 - Existing Database Schema Compatibility:** New features must respect Epic 1 existing schema (`customers`, `stylists`, `services`, `packs`, `business_hours` tables). Modifications require backward-compatible Alembic migrations. Constraint: UUIDs as PKs, `TIMESTAMP WITH TIME ZONE`, established JSONB metadata fields.

**CR2 - Hybrid Architecture Compatibility:** New nodes/tools must adhere to Tier 1 (conversational, Claude-driven tools) vs Tier 2 (transactional, explicit LangGraph nodes) separation. Constraint: `booking_intent_confirmed` flag as sole Tier 1→2 transition. Do not introduce new conversational "awaiting_*" flags.

**CR3 - ConversationState Schema Compatibility:** New state fields must not exceed 60 total fields (current: 50). Prefer JSONB `metadata` dict for ad-hoc data vs new top-level fields. Constraint: Maintain state immutability (nodes return new dicts, never mutate input).

**CR4 - External API Consistency:** Integrations with Chatwoot, Stripe, Google Calendar must use existing patterns: `shared/config.py` for credentials, async/await for API calls, comprehensive error handling with escalation. Constraint: Chatwoot API URL trailing slash removal, E.164 phone format, Stripe webhook signature validation.

**CR5 - Testing Strategy Compatibility:** New features require tests following existing structure (`tests/unit/`, `tests/integration/`, `tests/mocks/`). Integration tests must mock external APIs (Chatwoot, Stripe, Calendar). Constraint: pytest-asyncio with `asyncio_mode=auto`, ≥85% coverage gate.

**CR6 - Message Format Compatibility:** Messages in `ConversationState.messages` must maintain dict format: `{"role": "user"|"assistant", "content": str, "timestamp": str}`. NEVER use "human"|"ai" roles (LangChain internal). Constraint: Use `add_message()` helper from `agent/state/helpers.py`.

**CR7 - Docker Compose Compatibility:** New services (workers, cron jobs) must integrate into existing `docker-compose.yml` respecting 4-service architecture (postgres, redis, api, agent). Constraint: Health checks with `start_period`, depends_on conditions, shared network.

**CR8 - Logging Compatibility:** New components must use `shared/logging.py` configuration outputting JSON structured logs with standard fields (`timestamp`, `level`, `message`, `conversation_id`, `component`). Constraint: Python `logging` stdlib, NO third-party logging libs.

---

## 3. Technical Constraints and Integration Requirements

### 3.1 Existing Technology Stack

Based on analysis of `CLAUDE.md`, `docs/architecture.md`, and current code:

**Languages:**
- Python 3.12.3 (upgraded from 3.11 in Epic 1 - BMAD 1.1a)
- SQL (PostgreSQL dialect via SQLAlchemy 2.0+)
- Markdown (documentation)

**Frameworks & Libraries:**
- **Agent**: LangGraph 0.6.7+, LangChain 0.3.0+, LangChain-Anthropic
- **API**: FastAPI 0.116.1, Uvicorn 0.30.0+, Pydantic 2.x, Pydantic-Settings
- **Database**: SQLAlchemy 2.0+ (asyncpg driver), Alembic 1.13+
- **Testing**: pytest 8.3.0+, pytest-asyncio 0.24.0+ (asyncio_mode=auto), pytest-cov

**Database:**
- PostgreSQL 15+ (docker: postgres:15-alpine)
- Redis Stack 7.4.0-v0 (pinned version - BMAD 1.2c) with RedisSearch + RedisJSON modules

**Infrastructure:**
- Docker Compose (4-service architecture: postgres, redis, api, agent)
- Nginx (reverse proxy for HTTPS in production)
- VPS deployment target (Hetzner/DigitalOcean recommended)

**External Dependencies:**
- **Anthropic Claude API**: claude-sonnet-4-20250514 (temperature: 0.7)
- **Google Calendar API**: v3 with service account authentication
- **Stripe API**: Payment links + webhook processing
- **Chatwoot API**: Webhook receiver + message sender (self-hosted or cloud)

**Version Constraints:**
- Python ≥3.12 (for enhanced type hints and performance)
- PostgreSQL ≥15 (for JSONB improvements)
- Redis Stack 7.4.0-v0 (pinned due to RedisSearch compatibility - BMAD 1.2c)
- LangGraph ≥0.6.7 (for AsyncRedisSaver support)

---

### 3.2 Integration Approach

#### Database Integration Strategy

**Established Pattern:**
- Async SQLAlchemy 2.0 with asyncpg driver
- Context manager pattern via `database/connection.py::get_async_session()`
- Alembic migrations for schema changes (backward-compatible required)
- UUID primary keys for all entities
- TIMESTAMP WITH TIME ZONE for all datetime fields (Europe/Madrid)
- JSONB metadata column for flexible data storage

**Example Pattern:**
```python
from database.connection import get_async_session

async for session in get_async_session():
    result = await session.execute(query)
    await session.commit()
    break  # Important: break after first iteration
```

**New Tables Needed:**
- `appointments` (provisional + confirmed bookings)
- `payments` (Stripe payment tracking)
- `conversation_history` (archived Redis conversations)
- `notifications` (reminder/escalation log)

#### API Integration Strategy

**FastAPI Webhook Receiver (`api/`):**
- Existing: `/webhook/chatwoot/{token}` with timing-safe token validation
- Needed: `/webhook/stripe` with signature validation
- Pattern: Publish to Redis `incoming_messages` channel for async processing
- Security: Token in URL path + timing-safe comparison (Chatwoot), Signature validation (Stripe)

**Agent Orchestration (`agent/`):**
- Existing: Subscribe to Redis `incoming_messages`, process via LangGraph, publish to `outgoing_messages`
- Pattern: AsyncRedisSaver checkpointing (15 min TTL, RDB snapshots every 15 min)
- Needed: Expand transactional nodes (Epic 4-6)

**Chatwoot Integration:**
- Existing: Message reception + token auth
- Needed: Message sending, group notifications (escalation)
- Critical Pattern: Strip trailing slash from `CHATWOOT_API_URL` before concatenation

**Google Calendar Integration:**
- Needed: NEW component
- Service account JSON key via `GOOGLE_SERVICE_ACCOUNT_JSON` env var
- Multi-calendar access (5 stylists) via `GOOGLE_CALENDAR_IDS` comma-separated
- Operations: availability check (read), event CRUD (write), holiday detection

**Stripe Integration:**
- Needed: NEW component (partial preparation exists)
- Payment link generation via API
- Webhook processing for payment confirmation
- Refund execution for cancellations >24h

---

### 3.3 Code Organization and Standards

#### File Structure Approach

**Established Pattern (Monorepo):**
```
atrevete-bot/
├── api/                    # FastAPI webhook receiver
│   ├── routes/            # Webhook endpoints
│   └── middleware/        # Auth, logging
├── agent/                  # LangGraph orchestrator
│   ├── graphs/            # conversation_flow.py (12 nodes)
│   ├── nodes/             # Node implementations
│   ├── tools/             # LangChain tools (8 existing)
│   ├── prompts/           # maite_system_prompt.md
│   ├── state/             # schemas.py (50 fields)
│   └── workers/           # conversation_archiver.py
├── database/               # SQLAlchemy models
│   ├── models.py          # Core tables
│   └── migrations/        # Alembic versions
├── shared/                 # Utilities
│   ├── config.py          # Pydantic Settings (CRITICAL)
│   ├── logging.py         # JSON structured logging
│   └── clients/           # Chatwoot, Redis
└── tests/                  # Test suite
    ├── unit/              # 42 test files
    ├── integration/
    └── mocks/
```

**New Components Placement:**
- Google Calendar client → `shared/clients/calendar_client.py`
- Stripe client → `shared/clients/stripe_client.py`
- New tools → `agent/tools/` (payment_tools.py, notification_tools.py)
- New nodes → `agent/nodes/` (payment_nodes.py, notification_nodes.py)
- New workers → `agent/workers/` (reminder_worker.py, notification_worker.py)

#### Naming Conventions

**Established:**
- Files: snake_case (`conversation_flow.py`)
- Classes: PascalCase (`ConversationState`)
- Functions/methods: snake_case (`add_message()`)
- Constants: UPPER_SNAKE_CASE (`MAITE_SYSTEM_PROMPT`)
- Tools: snake_case with `_tool` suffix (`check_availability_tool`)
- Nodes: snake_case describing action (`conversational_agent`, `validate_booking_request`)

#### Coding Standards

**Critical Patterns (from CLAUDE.md):**

1. **Configuration Access:**
   ```python
   # ✅ ALWAYS use shared/config.py
   from shared.config import get_settings
   settings = get_settings()  # Cached via @lru_cache

   # ❌ NEVER use directly
   import os
   os.getenv("API_KEY")  # DON'T DO THIS
   ```

2. **State Updates:**
   ```python
   # ✅ CORRECT: Return new dict
   from agent.state.helpers import add_message
   return add_message(state, "assistant", "Response")

   # ❌ WRONG: Mutate state
   state["messages"].append(...)  # NEVER DO THIS
   ```

3. **Message Format:**
   ```python
   # ✅ CORRECT: Use helper
   add_message(state, "user", "Hello")  # role: "user"|"assistant"

   # ❌ WRONG: Manual format or wrong role
   {"role": "human", ...}  # NEVER use "human"/"ai"
   ```

**Code Quality Tools:**
- black (line length: 100)
- ruff (pycodestyle, pyflakes, isort)
- mypy (strict for `shared/` and `database/`, relaxed for `agent/` and `admin/`)

---

### 3.4 Deployment and Operations

#### Deployment Strategy

**Target: VPS with Docker Compose**
- Recommended: Hetzner Cloud CPX21 (4GB RAM, 2 vCPU) in Germany/Netherlands
- Deployment: Git pull + `docker-compose up -d --build`
- Reverse proxy: Nginx for HTTPS (Let's Encrypt SSL)
- Zero-downtime: Blue-green deployment or rolling restart

**Database Migrations:**
- Run Alembic migrations BEFORE container restart
- Command: `docker-compose run api alembic upgrade head`
- Rollback strategy: `alembic downgrade -1`

#### Monitoring and Logging

**Logging Strategy (BMAD 1.0a):**
- JSON structured logs to stdout
- Fields: `timestamp`, `level`, `message`, `conversation_id`, `component`, `error_type`
- Collection: Docker logs → file or external aggregator (BetterStack, Grafana Loki)

**Metrics to Track:**
- Conversation success rate (booking confirmed / conversations started)
- Average response time (Claude API latency)
- Escalation rate (human intervention / total conversations)
- Payment success rate (paid / payment links sent)
- Error rate by component

---

### 3.5 Risk Assessment and Mitigation

#### Technical Risks

**Risk 1: Claude API Rate Limits / Failures**
- **Impact**: HIGH - Entire conversational Tier 1 depends on Claude
- **Probability**: MEDIUM (Claude has 99.9% uptime, but rate limits possible)
- **Mitigation**:
  - Implement exponential backoff + retry (3 attempts)
  - Graceful degradation: catch exceptions, send "technical issues" message, auto-escalate
  - Monitor Claude API latency/errors via structured logs

**Risk 2: Google Calendar API Quota Exhaustion**
- **Impact**: MEDIUM - Cannot check availability if quota exceeded
- **Probability**: LOW (10,000 requests/day default quota)
- **Mitigation**:
  - Cache availability results for 5 minutes per date/stylist combination
  - Batch calendar queries where possible
  - Monitor quota usage via Google Cloud Console

**Risk 3: Redis Data Loss (State Persistence)**
- **Impact**: HIGH - Conversation context lost, customers frustrated
- **Probability**: LOW (Redis RDB snapshots every 15 min - BMAD 1.2d)
- **Mitigation**:
  - RDB persistence configured (save 300 1)
  - Conversation archiver worker backs up to PostgreSQL every 5 min
  - Redis Stack version pinned (7.4.0-v0) for stability

**Risk 4: Stripe Webhook Delivery Failures**
- **Impact**: CRITICAL - Bookings paid but not confirmed
- **Probability**: MEDIUM (network issues, server downtime)
- **Mitigation**:
  - Idempotency: use Stripe event IDs as deduplication keys
  - Manual reconciliation tool (check Stripe → database mismatches)
  - Stripe webhook retry (automatic, 3 days)
  - Alert on payment-not-confirmed after 10 minutes

**Risk 5: Chatwoot WhatsApp Connection Issues**
- **Impact**: CRITICAL - Cannot receive/send messages
- **Probability**: MEDIUM (depends on Chatwoot setup quality)
- **Mitigation**:
  - Health check monitoring on Chatwoot inbox status
  - Email alerts for prolonged message delivery failures
  - Fallback: manual phone call for critical bookings

---

## 4. Epic and Story Structure

### 4.1 Epic Approach

**Epic Structure Decision: PRESERVE EPICS 2-7 ORIGINAL STRUCTURE WITH HYBRID ARCHITECTURE ADAPTATIONS**

**Rationale:**

For brownfield projects, the template recommends a single comprehensive epic unless there are multiple unrelated enhancements. However, in this case, I recommend **preserving the original 7-epic structure** for the following reasons:

1. **Traceability**: The PRD v1.0 already has Epics 1-7 defined - changing to single epic confuses the history
2. **Planning**: You can prioritize Epics 2-3 (conversational) → 4 (booking/payment) → 5-6 (management/notifications) → 7 (testing)
3. **Complexity**: Epic 4 (9 stories) and Epic 6 (6 stories) are substantially different - treating them separately facilitates estimation
4. **Hybrid Architecture Alignment**: Epics 2-3 are Tier 1 (conversational), Epics 4-5 are Tier 2 (transactional), Epic 6 is infrastructure, Epic 7 is validation

**Critical Changes from v1.0:**
- **Reduce story count**: Many v1.0 stories consolidate into Claude (e.g., 2.2 greet + 2.3 identify → single conversational behavior)
- **Re-phrase Acceptance Criteria**: Change from "node X must do Y" to "Claude must decide Y using tool X"
- **Eliminate obsolete stories**: Stories describing nodes that no longer exist

---

### 4.2 Epic 2: Customer Identification & Conversational Foundation

**Epic Goal**: Implement customer identification (new/returning) and establish Maite's natural conversational behavior in Tier 1 (conversational_agent).

**Integration Requirements**:
- Claude tool access (`get_customer_by_phone`, `create_customer`)
- Database customer table (already exists from Epic 1)
- System prompt guidance (`maite_system_prompt.md` - already has 31KB base)

**Status**: 🟡 Partially implemented (conversational_agent exists, tools exist, needs refinement and testing)

**Stories**: 6 stories
- 2.1: Customer Database Tools Implementation ✅
- 2.2: Natural Greeting & Name Confirmation (Claude-Driven) 🟡
- 2.3: Returning Customer Recognition (Claude-Driven) 🟡
- 2.4: Maite Personality & Tone Consistency ✅
- 2.5a: Redis Checkpointing & Message Memory (FIFO Windowing) ✅
- 2.5b: Conversation Summarization (Claude-Powered) 🟡
- 2.5c: PostgreSQL Conversation Archival (Background Worker) ✅
- 2.6: FAQ Knowledge Base Responses (Claude-Driven) 🟡

---

### 4.3 Epic 3: Service Discovery, Calendar & Availability

**Epic Goal**: Implement service discovery, Google Calendar availability checking, pack suggestions, and free consultation offers.

**Integration Requirements**:
- Google Calendar API integration (NEW - CRITICAL)
- Tools: `get_services`, `check_availability_tool`, `suggest_pack_tool`, `offer_consultation_tool`
- Transactional nodes: `check_availability`, `suggest_pack`, `handle_pack_response`, `validate_booking_request`

**Status**: 🟡 Partially implemented (tools and transactional nodes exist, missing real Google Calendar integration)

**Stories**: 6 stories
- 3.1: Service Catalog Database & Tool ✅
- 3.2: Google Calendar API Integration ❌ **CRITICAL BLOCKER**
- 3.3: Multi-Calendar Availability Checking 🟡
- 3.4: Intelligent Pack Suggestion Logic ✅
- 3.5: Free Consultation Offering (Indecision Detection) 🟡
- 3.6: Service Category Mixing Prevention ✅

---

### 4.4 Epic 4: Booking Flow & Payment Processing

**Epic Goal**: Implement complete transactional booking flow from intent confirmation to payment confirmed, including provisional calendar blocks, Stripe payment link generation, timeout handling, and final confirmation.

**Integration Requirements**:
- Google Calendar API (event creation/deletion for provisional blocks)
- Stripe API (payment link generation, webhook processing)
- Transactional nodes: `create_provisional_booking`, `generate_payment_link`, `process_payment_timeout`, `confirm_booking`
- State tracking: `provisional_appointment_id`, `payment_link_url`, `is_same_day`

**Status**: ❌ NOT IMPLEMENTED (placeholder nodes, no real booking/payment logic)

**Stories**: 9 stories
- 4.1: Booking Intent Transition (Tier 1 → Tier 2) ✅
- 4.2: Service Extraction & Date Collection 🟡
- 4.3: Provisional Calendar Block Creation ❌
- 4.4: Stripe Payment Link Generation ❌
- 4.5: Payment Timeout & Reminder ❌
- 4.6: Stripe Webhook Processing & Payment Confirmation ❌
- 4.7: Payment Failure Handling & Retry ❌
- 4.8: "Lo de Siempre" (Usual Service) Handling ❌
- 4.9: Same-Day Booking Urgent Notification ❌

---

### 4.5 Epic 5: Modification, Cancellation & Rescheduling

**Epic Goal**: Implement modification and cancellation management with refund policies based on timing (>24h vs ≤24h notice).

**Integration Requirements**:
- Google Calendar API (event update/deletion)
- Stripe API (refund processing)
- Transactional nodes: `handle_modification`, `handle_cancellation`, `process_reschedule`
- Policy enforcement: refund >24h, reschedule ≤24h

**Status**: ❌ NOT IMPLEMENTED (placeholder nodes)

**Stories**: 5 stories
- 5.1: Cancellation Request Detection (Claude-Driven) ❌
- 5.2: Cancellation Policy Enforcement (>24h vs ≤24h) ❌
- 5.3: Appointment Rescheduling ❌
- 5.4: Modification Request Handling ❌
- 5.5: Stripe Refund Processing ❌

---

### 4.6 Epic 6: Notifications, Reminders & Intelligent Escalation

**Epic Goal**: Implement automatic reminder system (48h before), urgent notifications (same-day), and intelligent escalation to human team.

**Integration Requirements**:
- Background workers for scheduled reminders
- Chatwoot API (group notifications for escalation)
- Email/SMS integration (urgent notifications)
- Claude tool: `escalate_to_human`

**Status**: 🟡 10% complete (escalate_to_human tool exists, rest not implemented)

**Stories**: 6 stories
- 6.1: 48-Hour Reminder Worker ❌
- 6.2: Same-Day Booking Urgent Notifications ❌
- 6.3: Intelligent Escalation to Human (Claude-Driven) ✅
- 6.4: Escalation Notification Formatting 🟡
- 6.5: Escalation Analytics & Monitoring ❌
- 6.6: Holiday/Closure Notification Proactive 🟡

---

### 4.7 Epic 7: Testing, Validation & Production Hardening

**Epic Goal**: Achieve coverage ≥85%, implement end-to-end scenario tests, production hardening (monitoring, error handling), and complete system validation.

**Integration Requirements**:
- Comprehensive test suite expansion
- Robust mock infrastructure
- Production monitoring setup
- Performance testing

**Status**: 🟡 40% complete (test structure exists, 350 current tests, missing robust E2E scenarios)

**Stories**: 7 stories
- 7.1: End-to-End Scenario Test Suite 🟡
- 7.2: External API Mock Infrastructure 🟡
- 7.3: Performance & Load Testing ❌
- 7.4: Production Monitoring Setup 🟡
- 7.5: Error Handling & Recovery Hardening 🟡
- 7.6: Security Audit & Hardening 🟡
- 7.7: Production Deployment Documentation & Runbook 🟡

---

## 4.8 Complete Epic Summary

| Epic | Stories | Status | Priority | Effort (days) |
|------|---------|--------|----------|---------------|
| **Epic 1** | 6 stories | ✅ 100% | - | COMPLETE |
| **Epic 2** | 6 stories | 🟢 80% | HIGH | 3 days |
| **Epic 3** | 6 stories | 🟡 50% | HIGH | 5 days |
| **Epic 4** | 9 stories | 🔴 10% | CRITICAL | 10 days |
| **Epic 5** | 5 stories | 🔴 0% | MEDIUM | 4 days |
| **Epic 6** | 6 stories | 🟡 20% | MEDIUM | 5 days |
| **Epic 7** | 7 stories | 🟡 40% | HIGH | 5 days |
| **TOTAL** | **45 stories** | **35% complete** | - | **32 days** |

**Critical Path:**
1. **Epic 3.2** (Google Calendar Integration) → Epic 4 (Booking/Payment) → Epic 5 (Modification) → Epic 6 (Notifications) → Epic 7 (Production)
2. **Epic 2** can be completed in parallel (refine prompts + testing)

**Biggest Risks:**
1. **Google Calendar Integration** (Epic 3.2) - doesn't exist currently, critical for all Epic 4+
2. **Stripe Integration** (Epic 4.4-4.6) - partial, needs webhooks + refunds
3. **Background Workers** (Epic 4.5, 6.1) - no infrastructure for scheduled tasks

**Effort Estimation Assumptions:**
- Google Calendar integration: 2-3 days (learning curve)
- Stripe full integration: 2 days (webhooks + refunds)
- Each transactional node: 0.5-1 day (with tests)
- Background workers: 1 day each

---

## 5. Next Steps

### 5.1 Immediate Actions

1. **Review and Approve PRD**: Validate that this PRD accurately reflects the hybrid architecture reality and project goals

2. **Prioritize Epics**: Confirm priority order (recommended: Epic 2 → 3 → 4 → 5 → 6 → 7)

3. **Begin Epic 3.2** (Google Calendar Integration) - This is the **critical blocker** for all subsequent work

### 5.2 Development Sequence

**Phase 1 (Week 1-2): Epic 2 + Epic 3**
- Refine Claude prompts for Epic 2 behaviors
- Implement Google Calendar API integration (Epic 3.2)
- Complete availability checking with real Calendar data
- Comprehensive testing of Tier 1 conversational flows

**Phase 2 (Week 3-4): Epic 4 (Booking & Payment)**
- Provisional booking creation
- Stripe payment link generation
- Webhook processing and confirmation
- Timeout handling and reminders

**Phase 3 (Week 5): Epic 5 (Modification/Cancellation)**
- Cancellation policy enforcement
- Rescheduling logic
- Stripe refund processing

**Phase 4 (Week 6): Epic 6 (Notifications) + Epic 7 (Testing)**
- Reminder workers
- Escalation refinement
- End-to-end scenario tests
- Production hardening

**Phase 5 (Week 7): Production Deployment**
- Performance testing
- Security audit
- Production deployment
- Monitoring setup

### 5.3 Success Criteria

- ✅ All 45 stories completed with passing tests
- ✅ Test coverage ≥85%
- ✅ All external integrations validated (Google Calendar, Stripe, Chatwoot)
- ✅ Production deployment successful with <5% error rate
- ✅ 85%+ automation rate achieved (measured: confirmed bookings / total conversations)

---

**END OF PRD v2.0 - HYBRID ARCHITECTURE EDITION**

🤖 Generated with Claude Code (claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
