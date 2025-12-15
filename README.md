# Pro -01— Atrévete Bot

![CI Status](https://github.com/pepe/atrevete-bot/actions/workflows/test.yml/badge.svg)

AI-powered WhatsApp booking assistant for a beauty salon, built with LangGraph, GPT-4o-mini (via OpenRouter), and FastAPI.

## Overview

This bot handles customer bookings via WhatsApp through Chatwoot, managing appointments across 5 stylists using a DB-first calendar architecture with Google Calendar as a push-only mirror. The agent uses LangGraph for stateful conversation orchestration, a prescriptive FSM for deterministic booking flows, and GPT-4o-mini via OpenRouter for natural language understanding in Spanish.

**Key Features:**
- **FSM-Based Booking Flow** - 7-state prescriptive FSM eliminates LLM hallucinations in booking transactions
- **DB-First Calendar** - PostgreSQL as source of truth, <100ms availability checks (vs 2-5s via Google Calendar API)
- **Blocking Events & Holidays** - Stylist-specific unavailability and salon-wide closures
- **Next.js Admin Panel** - Modern React admin interface with full CRUD, real-time calendar, and charts
- **OpenRouter Integration** - 7-10x cost savings vs Claude API with automatic prompt caching
- **Redis Streams** - Message delivery with acknowledgment and idempotency checks

## Prerequisites

- **Python 3.11+** - Required for type hints and async/await support
- **Node.js 20+** - Required for Next.js admin panel
- **Docker & Docker Compose** - For running PostgreSQL, Redis Stack, and containerized services
- **External Service Accounts** - API keys and credentials for:
  - Google Calendar API (service account)
  - Chatwoot API (self-hosted or cloud)
  - OpenRouter API (LLM gateway)

## Quick Start

### 1. Clone Repository

```bash
git clone <repository-url>
cd atrevete-bot
```

### 2. Configure Environment Variables

Copy the example environment file and configure your API keys:

```bash
cp .env.example .env
```

Edit `.env` with your actual credentials. For detailed instructions on obtaining API keys, see [docs/external-services-setup.md](docs/external-services-setup.md).

**Required Variables:**
- `GOOGLE_SERVICE_ACCOUNT_JSON` - Path to Google service account JSON key
- `GOOGLE_CALENDAR_IDS` - Comma-separated calendar IDs for 5 stylists
- `CHATWOOT_API_URL`, `CHATWOOT_API_TOKEN`, `CHATWOOT_ACCOUNT_ID`, `CHATWOOT_INBOX_ID`
- `OPENROUTER_API_KEY` - OpenRouter API key (unified LLM gateway)
- `LLM_MODEL` - Model name (default: `openai/gpt-4o-mini`)
- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string

### 3. Setup Python Environment

```bash
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Setup Admin Panel Dependencies

```bash
cd admin-panel
npm install
cd ..
```

### 5. Run Services with Docker Compose

```bash
# Start all services (PostgreSQL, Redis, API, Agent, Admin Panel, Archiver)
docker-compose up -d

# Check service health
docker-compose ps

# View logs
docker-compose logs -f api           # FastAPI webhook receiver
docker-compose logs -f agent         # LangGraph orchestrator
docker-compose logs -f admin-panel   # Next.js admin interface
docker-compose logs -f archiver      # Conversation archival worker
```

### 6. Access Admin Panel

Navigate to [http://localhost:8001](http://localhost:8001) and login with default credentials:
- **Username:** admin
- **Password:** admin123

## Project Structure

```
atrevete-bot/
├── api/                    # FastAPI webhook receiver
│   └── routes/
│       ├── chatwoot.py     # Webhook handler
│       └── admin.py        # Admin API endpoints (87 KB, 2,547 lines)
├── agent/                  # LangGraph orchestrator
│   ├── fsm/                # BookingFSM (7-state prescriptive FSM)
│   ├── graphs/             # conversation_flow.py (3-node graph)
│   ├── nodes/              # conversational_agent.py (intent router + handlers)
│   ├── services/           # availability_service.py, gcal_push_service.py
│   ├── routing/            # IntentRouter (v5.0)
│   ├── tools/              # 8 consolidated LangChain tools
│   ├── prompts/            # System prompts (modular, 8 files)
│   └── workers/            # conversation_archiver.py
├── admin-panel/            # Next.js 15 admin interface
│   ├── src/
│   │   ├── app/            # App Router pages
│   │   │   ├── (authenticated)/
│   │   │   │   ├── dashboard/      # KPIs + charts
│   │   │   │   ├── appointments/   # Full CRUD
│   │   │   │   ├── stylists/       # Stylist management
│   │   │   │   ├── customers/      # Customer management
│   │   │   │   ├── services/       # Service catalog
│   │   │   │   ├── business-hours/ # Salon hours config
│   │   │   │   ├── calendar/       # Interactive calendar
│   │   │   │   ├── conversations/  # Chat history viewer
│   │   │   │   ├── settings/       # Configuration hub
│   │   │   │   └── system/         # System status
│   │   │   └── login/              # JWT authentication
│   │   ├── components/     # UI components (Radix + Tailwind)
│   │   └── lib/            # API client, types
│   └── package.json        # Next.js 15.0.3, React 18.3.1
├── database/               # SQLAlchemy models & Alembic migrations
│   ├── models.py           # 9 models (BlockingEvent, Holiday included)
│   └── migrations/         # Alembic migration versions
├── shared/                 # Shared utilities & config
│   ├── config.py           # Settings (OpenRouter, Chatwoot, etc.)
│   ├── logging_config.py   # Logging configuration
│   └── redis_client.py     # Redis client singleton
├── docker/                 # Docker configurations
│   ├── Dockerfile.api      # FastAPI image
│   ├── Dockerfile.agent    # Agent image
│   └── Dockerfile.admin-panel  # Next.js image (multi-stage)
├── tests/                  # Test suite (85% coverage)
│   ├── unit/               # Unit tests
│   ├── integration/        # Integration tests
│   │   └── scenarios/      # End-to-end conversation flows
│   └── mocks/              # API mocks (Chatwoot, Google Calendar)
├── scripts/                # Utility scripts
└── docs/                   # Documentation
    ├── prd/                # Product Requirements (sharded)
    ├── architecture/       # Architecture docs (sharded)
    ├── stories/            # Development stories
    └── qa/                 # QA documentation
```

## Architecture

### FSM-Based Conversation Flow (v5.0)

The system uses a prescriptive FSM architecture where the LLM only handles natural language understanding, while the FSM controls all booking logic:

```
Message Arrives
    ↓
LLM (NLU) - Extract intent + disambiguate state-aware
    ↓
IntentRouter - Route to booking vs non-booking flow
    ↓
├─ BookingHandler - FSM prescribes exact tools (0% hallucinations)
│  ├─ IDLE → SERVICE_SELECTION
│  ├─ SERVICE_SELECTION → STYLIST_SELECTION
│  ├─ STYLIST_SELECTION → SLOT_SELECTION
│  ├─ SLOT_SELECTION → CUSTOMER_DATA
│  ├─ CUSTOMER_DATA → CONFIRMATION
│  └─ CONFIRMATION → BOOKED
└─ NonBookingHandler - LLM with safe tools (FAQs, escalation)
```

**Benefits:**
- **Deterministic Transitions** - FSM validates all state changes
- **Zero Hallucinations** - Tools prescriptively called by FSM, not LLM
- **Clear State** - Always know where user is in booking flow
- **Testable** - FSM logic unit-tested in isolation

### DB-First Calendar Architecture (v4.1)

PostgreSQL is the source of truth for availability. Google Calendar is a push-only mirror updated asynchronously after bookings:

```
┌──────────────────────────────────────────────────────┐
│ Availability Check (read):                          │
│   PostgreSQL query → <100ms response                │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│ Booking (write):                                     │
│   1. DB commit (atomic transaction)                 │
│   2. Fire-and-forget Google Calendar push (async)   │
└──────────────────────────────────────────────────────┘
```

**Performance Improvements:**
- Availability checks: 2-5s → <100ms (20-50x faster)
- Booking creation: 3s blocking → <50ms + async push
- Admin calendar load: 5 API calls → 1 DB query <50ms

### State Management (ADR-011 Single Source of Truth)

FSM state is consolidated in LangGraph checkpoints stored in Redis Stack:

```
FSM loads from ConversationState.fsm_state (ÚNICA FUENTE)
    ↓
FSM processes + transitions
    ↓
state["fsm_state"] = fsm.to_dict() (ÚNICA ESCRITURA)
    ↓
LangGraph persists checkpoint (atomic write)
```

**Benefits:**
- 0% race conditions (eliminated dual persistence)
- -100ms latency (removed sleep workaround)
- -100% Redis memory for fsm:* keys
- Single source of truth guarantees consistency

## Technology Stack

### Backend
- **Agent:** LangGraph 0.6.7+, LangChain 0.3.0+, GPT-4o-mini via OpenRouter
- **LLM Provider:** OpenRouter API (unified gateway with automatic prompt caching)
- **LLM Model:** openai/gpt-4o-mini (7-10x cost savings vs Claude API)
- **API:** FastAPI 0.116.1, Uvicorn 0.30.0+, Pydantic 2.x
- **Database:** PostgreSQL 15+, SQLAlchemy 2.0+ (asyncpg driver), Alembic 1.13+
- **Cache:** Redis Stack (redis-stack-server with RedisSearch, RedisJSON, RDB snapshots every 15min)
- **External APIs:** Google Calendar API, Chatwoot API
- **Observability:** Langfuse (optional, for trace monitoring)

### Frontend (Admin Panel)
- **Framework:** Next.js 15.0.3 (App Router)
- **UI Library:** React 18.3.1
- **Component Library:** Radix UI primitives (Dropdown, Dialog, Select, etc.)
- **Styling:** Tailwind CSS 3.4.15 + tailwindcss-animate
- **Data Tables:** TanStack React Table 8.20.0
- **Calendar:** FullCalendar 6.1.15
- **Charts:** Recharts 2.13.0
- **Forms:** React Hook Form 7.53.2 + Zod validation
- **Auth:** JWT (jose library 5.9.6)

### Testing
- **Framework:** pytest 8.3.0+, pytest-asyncio 0.24.0+
- **Mode:** asyncio_mode=auto
- **Coverage:** 85% minimum (configured in pyproject.toml)
- **Excluded:** admin-panel/ (deferred), migrations, tests

### Code Quality
- **Formatter:** black (line length 100)
- **Linter:** ruff (pycodestyle, pyflakes, isort)
- **Type Checker:** mypy (strict for shared/database/, relaxed for agent/)

## Development Workflow

### Database Operations

```bash
# Create new migration
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic revision --autogenerate -m "description"

# Apply migrations
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic upgrade head

# Check current migration version
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic current

# Rollback one migration
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic downgrade -1

# Access PostgreSQL directly
PGPASSWORD="changeme_min16chars_secure_password" psql -h localhost -U atrevete -d atrevete_db

# Access via Docker
docker exec -it atrevete-postgres psql -U atrevete -d atrevete_db
```

### Running Tests

```bash
# Run all tests with coverage (minimum 85% required)
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest

# Run unit tests only
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/unit/

# Run integration tests
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/integration/

# Run specific test file
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/unit/test_customer_tools.py

# Run with verbose output
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/unit/test_customer_tools.py::test_create_customer -v
```

### Code Quality

```bash
# Format code (line length: 100, Python 3.11)
black .

# Lint code
ruff check .

# Type check (strict for shared/ and database/, relaxed for agent/)
mypy .
```

### Admin Panel Development

```bash
# Navigate to admin panel
cd admin-panel

# Install dependencies
npm install

# Run development server (with hot reload)
npm run dev

# Build for production
npm run build

# Start production server
npm start

# Lint frontend code
npm run lint
```

### Docker Services Management

```bash
# Start all services
docker-compose up -d

# Check service health
docker-compose ps

# View logs
docker-compose logs -f api           # FastAPI webhook receiver
docker-compose logs -f agent         # LangGraph orchestrator
docker-compose logs -f admin-panel   # Next.js admin interface
docker-compose logs -f archiver      # Conversation archival worker

# Restart specific service
docker-compose restart api

# Rebuild and restart
docker-compose up -d --build api

# Stop all services
docker-compose down

# Stop and remove volumes (WARNING: data loss)
docker-compose down -v
```

## Key Features

### Implemented ✅
- **Multi-stylist booking** - 5 stylists with individual Google Calendars
- **DB-first availability** - PostgreSQL as source of truth (<100ms queries)
- **Google Calendar sync** - Push-only mirror (async, non-blocking)
- **Blocking events** - Stylist-specific unavailability (vacations, meetings, breaks)
- **Holiday management** - Salon-wide closures (national/regional holidays)
- **FSM-based booking** - 7-state prescriptive FSM (zero hallucinations)
- **Redis Streams** - Message delivery with acknowledgment and idempotency
- **Conversation archival** - Long-term PostgreSQL persistence of chat history
- **Admin panel (Next.js)** - Full CRUD for all resources with real-time calendar
- **JWT authentication** - Secure admin access with token-based auth
- **Dashboard analytics** - KPIs + 5 chart types (appointments, services, hours, customers, stylists)
- **OpenRouter integration** - 7-10x cost savings with automatic prompt caching
- **Langfuse observability** - Optional trace monitoring for debugging

### Planned 🚧
- **Blocking events UI** - Admin panel interface (backend complete, UI pending)
- **Holidays UI** - Admin panel interface (backend complete, UI pending)
- **Email notifications** - Appointment confirmations and reminders
- **SMS notifications** - WhatsApp-only currently

### Removed ❌
- **Payment system** - All appointments auto-confirm (no provisional state, no Stripe integration)

## API Endpoints

### Webhook Endpoints
- `POST /webhook/chatwoot/{token}` - Chatwoot webhook receiver

### Admin API Endpoints

**Authentication:**
- `POST /api/admin/auth/login` - JWT login
- `GET /api/admin/auth/me` - Get current user

**Dashboard:**
- `GET /api/admin/dashboard/kpis` - Key performance indicators
- `GET /api/admin/dashboard/charts/appointments-trend` - Appointments over time
- `GET /api/admin/dashboard/charts/top-services` - Most booked services
- `GET /api/admin/dashboard/charts/hours-worked` - Hours worked by month
- `GET /api/admin/dashboard/charts/customer-growth` - Customer acquisition
- `GET /api/admin/dashboard/charts/stylist-performance` - Stylist metrics

**CRUD Operations (all support GET/POST/PUT/DELETE):**
- `/api/admin/stylists` - Stylist management
- `/api/admin/customers` - Customer management
- `/api/admin/services` - Service catalog
- `/api/admin/appointments` - Appointment management
- `/api/admin/business-hours` - Salon hours configuration

**Calendar & Availability:**
- `GET /api/admin/calendar/appointments` - Calendar view (month)
- `GET /api/admin/calendar/events` - Events (appointments + blocking events)
- `GET /api/admin/calendar/availability` - Check stylist availability
- `POST /api/admin/availability/search` - Multi-date availability search

**Blocking Events & Holidays:**
- `GET /api/admin/blocking-events` - List blocking events
- `POST /api/admin/blocking-events` - Create blocking event
- `PUT /api/admin/blocking-events/{id}` - Update blocking event
- `DELETE /api/admin/blocking-events/{id}` - Delete blocking event
- `GET /api/admin/holidays` - List holidays
- `POST /api/admin/holidays` - Create holiday
- `DELETE /api/admin/holidays/{id}` - Delete holiday

**Conversations:**
- `GET /api/admin/conversations` - List conversations (paginated)
- `GET /api/admin/conversations/{id}` - Conversation detail

**System:**
- `GET /health` - Health check (Redis, PostgreSQL status)

## Database Models

### Core Models
- **Customer** - Phone, name, notes, metadata
- **Stylist** - Name, category, Google Calendar ID, active status
- **Service** - Name, category, duration, description, active status
- **Appointment** - Customer, stylist, services, start time, duration, status, notes
- **BusinessHours** - Day of week, open/closed, start/end hours
- **Policy** - System policies (FAQ responses)

### Calendar Models (v4.1)
- **BlockingEvent** - Stylist-specific unavailability (types: VACATION, MEETING, BREAK, UNAVAILABLE)
- **Holiday** - Salon-wide closures (national/regional holidays)

### Conversation Models
- **ConversationHistory** - Archived chat logs (message count, summary, metadata)

**Note:** No payment-related models. All appointments auto-confirm without payment processing.

## Configuration

### Environment Variables

See [.env.example](.env.example) for complete list. Key variables:

**LLM & APIs:**
```bash
OPENROUTER_API_KEY=sk-or-v1-...           # OpenRouter API key
LLM_MODEL=openai/gpt-4o-mini              # Model name (default)
LANGFUSE_PUBLIC_KEY=pk-lf-...             # Optional: Langfuse observability
LANGFUSE_SECRET_KEY=sk-lf-...             # Optional: Langfuse observability
```

**Google Calendar:**
```bash
GOOGLE_SERVICE_ACCOUNT_JSON=service-account-key.json
GOOGLE_CALENDAR_IDS=cal1@group.calendar.google.com,cal2@...
```

**Chatwoot:**
```bash
CHATWOOT_API_URL=https://app.chatwoot.com
CHATWOOT_API_TOKEN=...
CHATWOOT_ACCOUNT_ID=1
CHATWOOT_INBOX_ID=1
CHATWOOT_WEBHOOK_TOKEN=...
```

**Database:**
```bash
DATABASE_URL=postgresql+asyncpg://atrevete:changeme@localhost:5432/atrevete_db
REDIS_URL=redis://localhost:6379/0
```

**Admin Panel:**
```bash
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=...  # bcrypt hash
JWT_SECRET_KEY=...       # For admin JWT tokens
```

## External Services Setup

For detailed instructions on setting up external service accounts and obtaining API keys, see:

- [docs/external-services-setup.md](docs/external-services-setup.md) - Complete setup guide
- [.env.example](.env.example) - Environment variable template with comments

## Documentation

- **[CLAUDE.md](CLAUDE.md)** - Comprehensive development guide (most up-to-date)
- **[ADR-011-STATUS.md](ADR-011-STATUS.md)** - FSM consolidation implementation status
- [docs/prd/](docs/prd/) - Product Requirements Document (sharded)
- [docs/architecture/](docs/architecture/) - Architecture documentation (sharded)
- [docs/stories/](docs/stories/) - Development stories organized by epic
- [docs/qa/](docs/qa/) - QA documentation

## Troubleshooting

### Google Calendar API Errors

**Error:** `FileNotFoundError: [Errno 2] No such file or directory: 'service-account-key.json'`

**Solution:**
1. Verify file exists: `ls -la service-account-key.json`
2. Check docker-compose.yml volume mount in `agent` service
3. Recreate container: `docker-compose up -d agent`
4. Verify inside container: `docker exec atrevete-agent ls -la /app/service-account-key.json`

### Business Hours Page Error

**Error:** "Application error: a client-side exception has occurred"

**Cause:** TypeScript type mismatch - hour/minute fields can be null when `is_closed=true`

**Solution:** This has been fixed in commit [latest]. Ensure you're on the latest version.

### Admin Panel Won't Start

**Error:** `EADDRINUSE: address already in use :::3000`

**Solution:**
```bash
# Find process using port 3000
lsof -i :3000  # macOS/Linux
netstat -ano | findstr :3000  # Windows

# Kill the process or restart admin-panel service
docker-compose restart admin-panel
```

## Contributing

See [CLAUDE.md](CLAUDE.md) for development guidelines, coding standards, and architecture patterns.

## License

[Add license information]

## Support

For issues, questions, or contributions, please [add contact information or link to issue tracker].
