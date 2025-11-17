# Atrévete Bot - Quick Context (5-minute onboarding)

**Last Updated:** 2025-11-13
**Version:** v3.2 (Prompt Optimization deployed)
**Branch:** master
**Status:** ✅ Production-ready

---

## 🎯 What is this project?

WhatsApp booking assistant for a beauty salon. AI-powered (GPT-4.1-mini via OpenRouter), handles 85%+ bookings automatically across 5 stylists.

---

## 🏗️ Architecture (30 seconds)

**Pattern:** Simplified tool-based architecture (v3.2)
**Flow:** 3 nodes (process_incoming_message → conversational_agent → summarize)
**Stack:** Python 3.11, FastAPI, LangGraph 0.6, PostgreSQL 15, Redis Stack 7.4
**Deployment:** Docker Compose (4 services: postgres, redis, api, agent, admin)
**LLM:** GPT-4.1-mini via OpenRouter (7-10x cheaper than Claude, automatic caching)

---

## 📂 Code Structure (Where is everything?)

```
atrevete-bot/
├── api/                  # FastAPI webhook receiver (Chatwoot)
├── agent/                # LangGraph orchestration
│   ├── graphs/          # conversation_flow.py (3-node graph)
│   ├── nodes/           # conversational_agent.py (main node)
│   ├── tools/           # 8 tools (query_info, search_services, manage_customer, etc.)
│   ├── prompts/         # Modular prompts (core.md + 6 state-specific)
│   ├── state/           # schemas.py (ConversationState: 19 fields)
│   └── workers/         # conversation_archiver.py
├── database/             # SQLAlchemy models (7 tables) + Alembic migrations
├── shared/               # Config, logging, Redis, Chatwoot clients
├── admin/                # Django Admin (http://localhost:8001/admin)
└── tests/                # 85% coverage (unit + integration)
```

---

## 🔑 Key Concepts

### 1. ConversationState (20 fields)
- **Core** (5): conversation_id, customer_phone, messages, metadata, user_message
- **Message Management** (2): conversation_summary, total_message_count
- **Escalation** (3): escalation_triggered, escalation_reason, error_count
- **v3.2 Tool Tracking** (5): customer_data_collected, service_selected, slot_selected, booking_confirmed, appointment_created
- **Node Tracking** (1): last_node
- **Timestamps** (2): created_at, updated_at
- **Deprecated** (2): customer_id, customer_name (tools handle internally)

### 2. Booking Flow (with confirmation step - Nov 13, 2025)
User message → Conversational agent (GPT-4.1-mini + 8 tools) → **Booking summary + user confirmation** → `book(first_name, last_name, notes)` execution → Auto-confirmed booking → Google Calendar event

**Customer Auto-Creation** (Nov 13, 2025): Customers auto-created in first interaction (no tool calls during booking)
**Appointment-Specific Data** (Nov 13, 2025): PASO 3 collects first_name, last_name, notes from user; stored directly in `appointments` table
**No payment processing** (Stripe integration removed Nov 10, 2025)
**User confirmation required** (Added Nov 13, 2025)

### 3. Tools (8 total)
1. `query_info` - Unified info (services, FAQs, hours, policies)
2. `search_services` - Fuzzy search across 92 services
3. `manage_customer` - CRUD operations
4. `get_customer_history` - Appointment history
5. `check_availability` - Single-date check
6. `find_next_available` - Multi-date search
7. `book` - Atomic booking (auto-confirms, no payment)
8. `escalate_to_human` - Human handoff

### 4. v3.2 Optimizations (Updated Nov 13, 2025)
- **Modular prompts:** 7 booking states (GENERAL → SERVICE_SELECTION → AVAILABILITY_CHECK → CUSTOMER_DATA → BOOKING_CONFIRMATION → BOOKING_EXECUTION → POST_BOOKING)
- **Token reduction:** 27KB → 8-10KB (-63%)
- **Cost reduction:** $1,350/mo → $280/mo (-79%)
- **Confirmation step:** Agent shows booking summary and waits for explicit user confirmation before executing `book()`
- **Caching:** OpenRouter auto-caches prompts >1024 tokens + in-memory stylist context (10min TTL)

---

## 🚀 Current State (What's implemented?)

✅ **Fully Functional:**
- 3-node LangGraph architecture
- 8 consolidated tools
- GPT-4.1-mini via OpenRouter
- Modular prompt loading (7 states, including BOOKING_CONFIRMATION)
- Pre-booking confirmation flow (Nov 13)
- PostgreSQL 7 tables (NO payment fields)
- Redis checkpointing (15min TTL)
- Django Admin panel (Nov 6)
- Conversation archival worker
- 85% test coverage

❌ **Removed:**
- Payment system (Stripe) - Eliminated Nov 10, 2025
- Provisional booking states - All bookings auto-confirm
- `price_euros` field in services table

⏳ **Not Implemented:**
- Reminder worker (scaffolded, not deployed)
- Payment timeout worker (n/a after payment removal)

---

## 📖 Where to find more?

- **Architecture details:** `docs/architecture.md` (being deprecated, see DEPRECATION NOTICE)
- **Current implementation:** See CLAUDE.md (root) for up-to-date development guide
- **Scenarios:** `docs/specs/scenarios.md` (18 conversation flows)
- **Database models:** `database/models.py:15-400` (7 tables)
- **Component locations:** See CLAUDE.md "Key Components" section

---

## 🔧 Quick Commands

```bash
# Start services
docker-compose up -d

# View logs
docker-compose logs -f agent

# Run tests (85% coverage required)
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest

# Migrations
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic upgrade head

# Django Admin
# http://localhost:8001/admin (admin/admin123)

# PostgreSQL access
docker exec -it atrevete-postgres psql -U atrevete -d atrevete_db
```

---

## 🎭 Conversation Flow (Simplified)

1. **Customer** → Chatwoot → FastAPI webhook (`api/routes/chatwoot.py`)
2. FastAPI → Redis pub/sub (`incoming_messages` channel)
3. **Agent** subscribes → LangGraph processes:
   - `process_incoming_message` → Adds message to history
   - `conversational_agent` → GPT-4.1-mini + 8 tools
   - `summarize` → FIFO windowing (recent 10 messages)
4. Response → Redis pub/sub → Chatwoot → **Customer**

---

## 📊 Key Metrics (v3.2)

| Metric | Value |
|--------|-------|
| Prompt size (avg) | 8-10KB (was 27KB) |
| Tokens/request | 2,500-3,000 (was 7,000) |
| Cost/1K conversations | $280/mo (was $1,350/mo) |
| Response time (p95) | <5s |
| Test coverage | 85% |
| Automation rate | 85%+ bookings |

---

## ⚠️ Important Rules

- **ALWAYS** use `shared/config.py` for env vars (never `os.getenv()`)
- **ALWAYS** use `add_message()` helper for state updates (immutable state)
- **Phone format:** E.164 (+34612345678)
- **Timezone:** Europe/Madrid
- **Message role:** "user" or "assistant" (NEVER "human" or "ai")
- **NO payment processing:** All bookings auto-confirm

---

## 🔗 External Dependencies

- **Google Calendar API** (5 stylist calendars) - Requires `service-account-key.json`
- **Chatwoot API** (WhatsApp integration)
- **OpenRouter API** (GPT-4.1-mini via unified gateway)
- **PostgreSQL 15+**
- **Redis Stack 7.4** (RedisSearch + RedisJSON required)

---

## 🐛 Common Issues

### Google Calendar credentials missing
**Error:** `FileNotFoundError: service-account-key.json`
**Fix:**
1. Verify file: `ls -la /home/pepe/atrevete-bot/service-account-key.json`
2. Recreate container: `docker-compose up -d agent`
3. Verify mount: `docker exec atrevete-agent ls -la /app/service-account-key.json`

### Tests failing
**Cause:** Wrong DATABASE_URL (must use `asyncpg` driver)
**Fix:** Use `postgresql+asyncpg://...` not `postgresql+psycopg://...`

---

## 📝 Recent Changes (Last 6 commits)

```
[pending] - Add pre-booking confirmation flow (Nov 13)
          - 7 states: Added BOOKING_CONFIRMATION between CUSTOMER_DATA and BOOKING_EXECUTION
          - Agent shows booking summary and waits for user confirmation before calling book()
          - New field: booking_confirmed (ConversationState: 19→20 fields)
          - New prompt: step3_5_confirmation.md
b517001 - Prompt Code Change (Nov 12)
f380048 - Complete Phase 11 - Final verification (Nov 10)
faab512 - Complete Phase 10 - Update CLAUDE.md (Nov 10)
8c8efe1 - Complete Phase 9 - Eliminate payment tests (Nov 10)
```

---

**Need more details?** See `CLAUDE.md` in project root for complete development guide.
