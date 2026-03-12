# Atrévete Bot

AI-powered WhatsApp booking assistant for a beauty salon, built with LangGraph v6.0, GPT-4o-mini (via OpenRouter), and FastAPI.

## Overview

Atrévete Bot handles customer bookings via WhatsApp through Chatwoot, managing appointments across 5 stylists using a DB-first calendar architecture with Google Calendar as a push-only mirror. The agent uses LangGraph v6.0 for stateful conversation orchestration with a mode-based architecture (GREETING, BOOKING, GENERAL, ESCALATION) and GPT-4o-mini via OpenRouter for natural language understanding in Spanish.

**Key Features:**
- **Mode-Based Architecture** - 4 independent conversation modes with intent routing and automatic transitions
- **DB-First Calendar** - PostgreSQL as source of truth, <100ms availability checks (vs 2-5s via Google Calendar API)
- **Blocking Events & Holidays** - Stylist-specific unavailability and salon-wide closures
- **Next.js Admin Panel** - Modern React admin interface with full CRUD, real-time calendar, and charts
- **OpenRouter Integration** - Cost-effective LLM access with automatic prompt caching
- **Redis Streams** - Message delivery with acknowledgment and idempotency checks

## Quick Start

### 1. Clone & Configure

```bash
git clone <repository-url>
cd atrevete-bot
cp .env.example .env
# Edit .env with your API keys
```

### 2. Setup Environment

```bash
# Python
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Admin Panel
cd admin-panel && npm install && cd ..
```

### 3. Run Services

```bash
docker-compose up -d
docker-compose ps
```

### 4. Access Services

- **Admin Panel**: http://localhost:3001 (Next.js)
- **Django Admin**: http://localhost:8001 (legacy admin)
- **API Docs**: http://localhost:8000/docs

## Documentation Structure

This repository uses a **progressive-disclosure documentation system** for AI-assisted development:

### For AI Assistants

| File | Purpose |
|------|---------|
| **[AGENTS.md](AGENTS.md)** | Root AI governance: repository navigation, documentation precedence, skills catalog |
| **[CLAUDE.md](CLAUDE.md)** | Comprehensive development guide: commands, architecture decisions, operational details |
| **[agent/AGENTS.md](agent/AGENTS.md)** | LangGraph v6.0 mode-based agent architecture |
| **[api/AGENTS.md](api/AGENTS.md)** | FastAPI routes and webhook handling |
| **[database/AGENTS.md](database/AGENTS.md)** | SQLAlchemy models and Alembic migrations |
| **[admin-panel/AGENTS.md](admin-panel/AGENTS.md)** | Next.js 15 admin panel patterns |
| **[shared/AGENTS.md](shared/AGENTS.md)** | Shared utilities and configuration |
| **[skills/](skills/)** | Project-specific AI skills with auto-invoke triggers |

**How it works:** When working on any component, the AI assistant reads the component's `AGENTS.md` file first, which references the appropriate skills from the `skills/` directory.

### For Humans

- **[CLAUDE.md](CLAUDE.md)** - Primary development guide with commands, workflows, and architecture
- **[docs/](docs/)** - Product requirements, architecture decisions, and stories
- **[.env.example](.env.example)** - Environment variable template

## Project Structure

```
atrevete-bot/
├── AGENTS.md                  # Root AI governance and navigation
├── CLAUDE.md                  # Comprehensive development guide
├── README.md                  # This file - quick start and overview
│
├── agent/                     # LangGraph v6.0 orchestrator
│   ├── AGENTS.md              # Agent component documentation
│   ├── graphs/
│   │   └── conversation_flow.py   # v6.0 mode-based StateGraph
│   ├── modes/                 # Mode implementations
│   │   ├── base.py            # BaseModeNode
│   │   ├── greeting_mode.py   # GREETING mode
│   │   ├── booking_mode.py    # BOOKING mode
│   │   ├── general_mode.py    # GENERAL mode
│   │   └── escalation_mode.py # ESCALATION mode
│   ├── routing/
│   │   └── intent_router.py   # Keyword + LLM hybrid classifier
│   ├── prompts/               # System prompts
│   │   ├── shared/            # Core prompts (identity, rules, glossary)
│   │   └── modes/             # Mode-specific overlays
│   └── tools/                 # LangChain tools
│
├── api/                       # FastAPI webhook receiver
│   ├── AGENTS.md              # API component documentation
│   ├── routes/
│   │   ├── chatwoot.py        # Chatwoot webhook handler
│   │   └── admin.py           # Admin API endpoints
│   └── services/              # Business logic services
│
├── database/                  # SQLAlchemy models & Alembic
│   ├── AGENTS.md              # Database component documentation
│   ├── models.py              # Core models
│   └── migrations/            # Alembic migrations
│
├── admin-panel/               # Next.js 15 admin interface
│   ├── AGENTS.md              # Admin panel component documentation
│   └── src/
│       ├── app/               # Next.js App Router
│       ├── components/        # React components
│       └── lib/               # API client, types
│
├── shared/                    # Shared utilities
│   ├── AGENTS.md              # Shared component documentation
│   ├── config.py              # Pydantic Settings
│   ├── chatwoot_client.py     # Chatwoot API client
│   └── redis_client.py        # Redis client
│
├── skills/                    # AI skills for development
│   ├── README.md              # Skills overview
│   ├── atrevete/              # Project-wide patterns
│   ├── atrevete-agent/        # LangGraph agent patterns
│   ├── atrevete-api/          # FastAPI patterns
│   ├── atrevete-database/     # Database patterns
│   ├── atrevete-admin/        # Next.js patterns
│   ├── atrevete-shared/       # Shared utilities patterns
│   ├── atrevete-prompts/      # Prompt editing gateway
│   └── skill-sync/            # Skills governance
│
├── tests/                     # Test suite
├── docker/                    # Docker configurations
└── docs/                      # Documentation
```

## Architecture

### Mode-Based Conversation Flow (v6.0)

The system uses a mode-based architecture where independent modes handle different conversation contexts:

```
Message Arrives (Redis Streams)
    ↓
Preprocess → Intent Router (keyword + LLM hybrid)
    ↓
├─ GREETING Mode → First contact + name collection
├─ BOOKING Mode  → Multi-step appointment booking
├─ GENERAL Mode  → FAQs and information queries
└─ ESCALATION Mode → Human handoff
    ↓
Summarize → END
```

**Key Principles:**
- **Mode-Specific Tools** - Each mode loads only relevant tools
- **Automatic Transitions** - Via `transition_mode()` helper
- **State Management** - LangGraph checkpoints with custom reducers
- **Tool-Driven State** - Tools declare state changes via `_internal_flags`

See [agent/AGENTS.md](agent/AGENTS.md) for detailed architecture.

### DB-First Calendar Architecture

PostgreSQL is the source of truth for availability. Google Calendar is a push-only mirror:

```
Availability Check (read):  PostgreSQL query → <100ms
Booking (write):           DB commit → async Google Calendar push
```

See [CLAUDE.md](CLAUDE.md) for full architecture details.

## Technology Stack

### Backend
- **Agent:** LangGraph 0.6.7+, LangChain 0.3.0+, GPT-4o-mini via OpenRouter
- **API:** FastAPI 0.116.1, Pydantic 2.x, Uvicorn 0.30.0+
- **Database:** PostgreSQL 15+, SQLAlchemy 2.0+ (asyncpg), Alembic 1.13+
- **Cache:** Redis Stack (RedisSearch, RedisJSON, Streams)
- **External APIs:** Google Calendar API, Chatwoot API

### Frontend (Admin Panel)
- **Framework:** Next.js 15.0.3 (App Router), React 18.3.1
- **Styling:** Tailwind CSS 3.4.15
- **UI:** shadcn/ui + Radix UI primitives
- **Tables:** TanStack React Table 8.20.0
- **Calendar:** FullCalendar 6.1.15

### Development Tools
- **Testing:** pytest 8.3.0+, pytest-asyncio 0.24.0+ (85% coverage)
- **Formatting:** black (line length 100)
- **Linting:** ruff
- **Type Checking:** mypy

## Common Commands

### Database
```bash
# Create migration
DATABASE_URL="postgresql+psycopg://..." alembic revision --autogenerate -m "description"

# Apply migrations
DATABASE_URL="postgresql+psycopg://..." alembic upgrade head

# Access PostgreSQL
docker exec -it atrevete-postgres psql -U atrevete -d atrevete_db
```

### Testing
```bash
# Run all tests
DATABASE_URL="postgresql+asyncpg://..." pytest

# Run with coverage
DATABASE_URL="postgresql+asyncpg://..." pytest --cov

# Run specific test
DATABASE_URL="postgresql+asyncpg://..." pytest tests/unit/test_file.py -v
```

### Code Quality
```bash
black .        # Format
ruff check .   # Lint
mypy .         # Type check
```

### Docker
```bash
docker-compose up -d          # Start all services
docker-compose logs -f agent  # View agent logs
docker-compose restart api    # Restart API
```

### Admin Panel
```bash
cd admin-panel
npm run dev      # Development server
npm run build    # Production build
npm run lint     # Lint frontend
```

## Skills Maintenance

After modifying any skill, regenerate the auto-invoke tables:

```bash
./skills/skill-sync/assets/sync.sh
```

## Key Features

### Implemented ✅
- **Multi-stylist booking** - 5 stylists with individual Google Calendars
- **DB-first availability** - PostgreSQL as source of truth (<100ms queries)
- **Google Calendar sync** - Push-only mirror (async, non-blocking)
- **Blocking events** - Stylist-specific unavailability
- **Holiday management** - Salon-wide closures
- **Mode-based agent** - 4 modes with intent routing (v6.0)
- **Redis Streams** - Message delivery with acknowledgment
- **Next.js admin panel** - Full CRUD with real-time calendar
- **JWT authentication** - Secure admin access
- **Dashboard analytics** - KPIs + charts

### Planned 🚧
- **Blocking events UI** - Admin panel interface (backend complete)
- **Holidays UI** - Admin panel interface (backend complete)
- **Email notifications** - Appointment confirmations

### Removed ❌
- **Payment system** - All appointments auto-confirm
- **FSM-based booking** - Replaced by mode-based v6.0

## Documentation

### AI Development
- **[AGENTS.md](AGENTS.md)** - Repository governance and navigation
- **[agent/AGENTS.md](agent/AGENTS.md)** - Agent architecture
- **[api/AGENTS.md](api/AGENTS.md)** - API patterns
- **[database/AGENTS.md](database/AGENTS.md)** - Database patterns
- **[admin-panel/AGENTS.md](admin-panel/AGENTS.md)** - Admin panel patterns
- **[shared/AGENTS.md](shared/AGENTS.md)** - Shared utilities
- **[skills/](skills/)** - Project skills

### Human Development
- **[CLAUDE.md](CLAUDE.md)** - Comprehensive development guide (commands, workflows, architecture)
- **[docs/](docs/)** - Product requirements and architecture decisions
- **[.env.example](.env.example)** - Environment variables

## Contributing

See [CLAUDE.md](CLAUDE.md) for development guidelines, coding standards, and architecture patterns.

## License

[Add license information]

## Support

For issues, questions, or contributions, please [add contact information or link to issue tracker].