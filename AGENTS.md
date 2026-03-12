# AGENTS.md — Atrévete Bot

## Repository Overview

**Atrévete Bot** is an AI-powered WhatsApp booking assistant for a beauty salon. It handles customer bookings via WhatsApp through Chatwoot, managing appointments across 5 stylists using a DB-first calendar architecture with Google Calendar as a push-only mirror.

### Tech Stack

| Component | Technology |
|-----------|------------|
| **Agent** | Python 3.11+, LangGraph 0.6.7+, LangChain 0.3.0+ |
| **LLM** | GPT-4.1-mini via OpenRouter (openai/gpt-4.1-mini) |
| **API** | FastAPI 0.116.1, Pydantic 2.x, Uvicorn 0.30.0+ |
| **Database** | PostgreSQL 15+, SQLAlchemy 2.0+ (asyncpg), Alembic 1.13+ |
| **Cache** | Redis Stack (RedisSearch, RedisJSON) |
| **Admin Panel** | Next.js 15.0.3 (App Router), React 18.3.1, Tailwind CSS |
| **External APIs** | Google Calendar API, Chatwoot API |
| **Testing** | pytest 8.3.0+, pytest-asyncio 0.24.0+ |
| **Code Quality** | black (line length 100), ruff, mypy |

### Key External Dependencies

- Google Calendar API (5 stylist calendars)
- Chatwoot API (WhatsApp integration)
- OpenRouter API (LLM gateway)
- PostgreSQL 15+ (data persistence)
- Redis Stack (checkpointing + RedisSearch/RedisJSON for LangGraph)

---

## Documentation Precedence

When guidance conflicts, follow this hierarchy (highest priority first):

```
1. CLAUDE.md (operational details) >
2. AGENTS.md (repository governance) >
3. Component AGENTS.md (component-specific) >
4. skills/* (pattern libraries)
```

### Boundary Rules

| Question | Where to Look |
|----------|---------------|
| How do I run tests? | **CLAUDE.md** (commands) |
| What's the database schema? | **CLAUDE.md** (models) |
| How do I add a new agent mode? | **agent/AGENTS.md** → **atrevete-agent** skill |
| How do I create a migration? | **database/AGENTS.md** → **atrevete-database** skill |
| What's the project architecture? | **AGENTS.md** (this file) |
| How do I write a FastAPI route? | **api/AGENTS.md** → **atrevete-api** skill |
| How do I style React components? | **atrevete-admin** skill → **tailwind-4** skill |

### Decision Tree

```
Need operational command (docker, test, migrate)?
  → CLAUDE.md

Need repository structure or navigation?
  → AGENTS.md (this file)

Working on a specific component?
  → Component AGENTS.md (agent/, api/, database/)

Need detailed patterns or examples?
  → skills/* (auto-invoked based on context)
```

---

## Project Navigation

```
atrevete-bot/
├── AGENTS.md              # This file — repository governance
├── CLAUDE.md              # Operational guide — READ THIS FIRST
├── README.md              # Project overview and quick start
│
├── api/                   # FastAPI webhook receiver
│   ├── AGENTS.md          # API-specific guidance
│   ├── main.py            # FastAPI app factory
│   ├── models/            # Pydantic models
│   ├── routes/            # API endpoints
│   │   ├── chatwoot.py    # Chatwoot webhook handler
│   │   └── admin.py       # Admin API endpoints
│   ├── services/          # Business logic
│   └── middleware/        # CORS, logging, rate limiting
│
├── agent/                 # LangGraph orchestrator
│   ├── AGENTS.md          # Agent-specific guidance
│   ├── main.py            # Redis Streams consumer
│   ├── graphs/            # StateGraph definitions
│   │   └── conversation_flow.py   # v6.0 mode-based graph
│   ├── modes/             # Mode nodes (v6.0)
│   │   ├── greeting_mode.py       # GREETING mode
│   │   ├── booking_mode.py        # BOOKING mode
│   │   ├── general_mode.py        # GENERAL mode
│   │   └── escalation_mode.py     # ESCALATION mode
│   ├── routing/           # Intent router
│   │   └── intent_router.py       # Keyword + LLM hybrid classifier
│   ├── tools/             # 8 LangChain tools
│   ├── prompts/           # System prompts
│   │   ├── shared/        # Core prompts (identity, rules, glossary)
│   │   └── modes/         # Mode-specific overlays
│   ├── state/             # State schemas and checkpointer
│   ├── services/          # Business logic (availability, GCal push)
│   └── workers/           # Background workers (archiver)
│
├── database/              # SQLAlchemy models & Alembic migrations
│   ├── AGENTS.md          # Database-specific guidance
│   ├── models.py          # 9 core models + calendar models
│   ├── connection.py      # Async engine and session factory
│   ├── alembic/           # Migration files
│   └── seeds/             # Data seeding
│
├── admin-panel/           # Next.js 15 admin interface
│   ├── src/
│   │   ├── app/           # Next.js App Router
│   │   ├── components/    # React components
│   │   ├── contexts/      # Auth context
│   │   ├── hooks/         # Custom hooks
│   │   └── lib/           # API client, types
│   └── package.json
│
├── shared/                # Shared utilities
│   ├── config.py          # Pydantic Settings (env vars)
│   ├── chatwoot_client.py # Chatwoot API client
│   ├── redis_client.py    # Redis connection
│   ├── logging_config.py  # Structured logging
│   └── circuit_breaker.py # Circuit breaker pattern
│
├── tests/                 # Test suite
│   ├── unit/              # Unit tests
│   ├── integration/       # Integration tests
│   └── mocks/             # API mocks
│
├── skills/                # AI agent skills
│   ├── atrevete/          # Main project skill
│   ├── atrevete-agent/    # Agent patterns
│   ├── atrevete-api/      # FastAPI patterns
│   ├── atrevete-database/ # SQLAlchemy patterns
│   ├── atrevete-admin/    # Next.js patterns
│   ├── atrevete-shared/   # Shared utilities
│   └── skill-sync/        # Skill sync tool
│
├── docker/                # Docker configurations
├── docs/                  # Documentation
│   ├── prd/               # Product Requirements
│   ├── architecture/      # Architecture docs
│   └── migrations/        # Migration guides
│
├── docker-compose.yml     # Service orchestration
├── requirements.txt       # Python dependencies
└── .env.example           # Environment variables template
```

---

## Component Map

Each component has its own AGENTS.md with specific guidance:

| Component | Location | AGENTS.md | Purpose |
|-----------|----------|-----------|---------|
| **Agent** | `agent/` | [agent/AGENTS.md](agent/AGENTS.md) | LangGraph orchestrator, modes, routing, tools |
| **API** | `api/` | [api/AGENTS.md](api/AGENTS.md) | FastAPI routes, webhooks, services |
| **Database** | `database/` | [database/AGENTS.md](database/AGENTS.md) | SQLAlchemy models, migrations |
| **Shared** | `shared/` | N/A (use `atrevete-shared` skill) | Config, clients, utilities |
| **Admin Panel** | `admin-panel/` | N/A (use `atrevete-admin` skill) | Next.js 15 React components |

---

### Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|
| After creating/modifying a skill | `skill-sync` |
| Creating React components | `atrevete-admin` |
| Creating UI components | `atrevete-admin` |
| Creating agent tools | `atrevete-agent` |
| Creating migrations | `atrevete-database` |
| Creating new prompt module | `atrevete-prompts` |
| Creating utilities | `atrevete-shared` |
| Creating webhooks | `atrevete-api` |
| Creating/modifying mode nodes | `atrevete-agent` |
| Creating/modifying models | `atrevete-database` |
| Creating/modifying services | `atrevete-api` |
| Editing agent system prompts | `atrevete-prompts` |
| Editing identity.md or critical_rules.md | `atrevete-prompts` |
| General Atrévete Bot development questions | `atrevete` |
| Modifying core prompt rules | `atrevete-prompts` |
| Modifying files in agent/prompts/ | `atrevete-prompts` |
| Modifying mode prompt instructions | `atrevete-prompts` |
| Project overview and architecture | `atrevete` |
| Regenerate AGENTS.md Auto-invoke tables | `skill-sync` |
| Reviewing prompt quality | `atrevete-prompts` |
| Troubleshoot missing skill in auto-invoke | `skill-sync` |
| Working on API routes | `atrevete-api` |
| Working on Chatwoot | `atrevete-api` |
| Working on Chatwoot client | `atrevete-shared` |
| Working on FastAPI | `atrevete-api` |
| Working on LangGraph | `atrevete-agent` |
| Working on Next.js | `atrevete-admin` |
| Working on Redis | `atrevete-shared` |
| Working on admin-panel/ | `atrevete-admin` |
| Working on agent/ | `atrevete-agent` |
| Working on atrevete-bot | `atrevete` |
| Working on config | `atrevete-shared` |
| Working on database models | `atrevete-database` |
| Working on prompt .md files | `atrevete-prompts` |
| Working on prompts | `atrevete-agent` |
| Working on routing | `atrevete-agent` |
| Working on shared/ | `atrevete-shared` |
| Working on state management | `atrevete-agent` |
| Working on system prompts | `atrevete-prompts` |
| Working with SQLAlchemy | `atrevete-database` |

---

## Quick Reference

### Environment Setup

```bash
# Create virtual environment (Python 3.11+ required)
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with real API keys - see docs/external-services-setup.md
```

### Running Services

```bash
# Start all services (PostgreSQL, Redis, API, Agent, Archiver)
docker-compose up -d

# Check service health
docker-compose ps

# View logs
docker-compose logs -f api      # FastAPI webhook receiver
docker-compose logs -f agent    # LangGraph orchestrator
docker-compose logs -f archiver # Conversation archival worker

# Restart specific service
docker-compose restart api
```

### Database Operations

```bash
# Create new migration
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic revision --autogenerate -m "description"

# Apply migrations
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic upgrade head

# Check current migration version
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic current

# Access PostgreSQL directly
PGPASSWORD="changeme_min16chars_secure_password" psql -h localhost -U atrevete -d atrevete_db

# Access via Docker
docker exec -it atrevete-postgres psql -U atrevete -d atrevete_db
```

### Testing

```bash
# Run all tests with coverage (minimum 85% required)
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest

# Run unit tests only
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/unit/

# Run integration tests
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/integration/

# Run specific test file
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/unit/test_customer_tools.py

# Run specific test with verbose output
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/unit/test_customer_tools.py::test_create_customer -v
```

### Code Quality

```bash
# Format code (line length: 100, Python 3.11)
black .

# Lint code
ruff check .

# Type check (strict for shared/ and database/, relaxed for agent/ and admin/)
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

# Lint frontend code
npm run lint
```

---

## Critical Rules

These rules apply across ALL components:

1. **ALWAYS use `shared/config.py`** — NEVER use `os.getenv()` directly
2. **ALWAYS use `add_message()` helper** — NEVER mutate state directly
3. **NEVER use `{**state}` spread** in node return values — causes message duplication
4. **ALWAYS use `Annotated[T, reducer_fn]`** for custom reducers in state schema
5. **ALWAYS use async/await** for all I/O operations
6. **ALWAYS maintain Spanish** for user-facing content, English for code/docs
7. **NEVER start services** (docker, npm, etc.) unless explicitly requested
8. **ALWAYS use Pydantic Settings** for environment variables
9. **ALWAYS use UUID** for primary keys (not auto-increment)
10. **ALWAYS use `DateTime(timezone=True)`** for timestamps

---

## Resources

- **[CLAUDE.md](CLAUDE.md)** — Comprehensive development guide (most up-to-date)
- **[README.md](README.md)** — Project overview and quick start
- **[skills/](skills/)** — AI agent skills for detailed patterns

---

**Last Updated**: March 2026  
**Version**: 1.0 (Mode-based architecture v6.0)
