# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Atrévete Bot is an AI-powered WhatsApp booking assistant for a beauty salon. Manages appointments across 5 stylists using LangGraph v6.0 mode-based architecture with GPT-4.1-mini via OpenRouter. DB-first calendar (PostgreSQL as source of truth, Google Calendar as push-only mirror).

## Development Commands

### Testing

```bash
# All tests (60% coverage minimum enforced)
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest

# Unit tests only
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/unit/

# Integration tests
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/integration/

# Specific test file or test function
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/unit/test_booking_mode.py -v
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/unit/test_booking_mode.py::test_function_name -v
```

Test markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.e2e`, `@pytest.mark.slow`

### Code Quality

```bash
black .          # Format (line length: 100, Python 3.11)
ruff check .     # Lint (E, W, F, I, B, C4, UP rules)
mypy .           # Type check (strict for shared/ and database/, relaxed for agent/)
```

### Database

```bash
# Create migration (note: uses psycopg driver, NOT asyncpg)
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic revision --autogenerate -m "description"

# Apply migrations
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic upgrade head

# Check current version
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic current

# Direct DB access
docker exec -it atrevete-postgres psql -U atrevete -d atrevete_db
```

### Docker

```bash
docker-compose up -d              # Start all services
docker-compose ps                 # Check health
docker-compose logs -f agent      # Agent logs
docker-compose logs -f api        # API logs
docker-compose restart api        # Restart specific service
```

### Admin Panel (Next.js)

```bash
cd admin-panel && npm install
npm run dev      # Dev server
npm run build    # Production build
npm run lint     # Lint
```

## Architecture

### Message Flow

```
WhatsApp → Chatwoot webhook → FastAPI (api/) → Redis Streams → Agent (LangGraph) → Redis → Chatwoot API → WhatsApp
```

### Agent Graph (v6.0)

```
preprocess → router → [GREETING | BOOKING | GENERAL | ESCALATION] → summarize → END
```

- **GREETING**: First contact + name collection. Fires ONCE per new customer, then transitions.
- **BOOKING**: Multi-step appointment flow with 4 tools (availability, booking, search, customer).
- **GENERAL**: FAQs and info queries with 2 read-only tools (query_info, search_services).
- **ESCALATION**: Human handoff. Triggered by intent or `error_count >= 3`.

### Routing Priority (router_node)

1. `escalation_triggered=True` → ESCALATION
2. `error_count >= 3` → ESCALATION
3. `is_first_interaction=True` or `customer_name is None` → GREETING
4. `intent == escalate` → ESCALATION
5. Currently in BOOKING and not cancel/reject → stay BOOKING
6. `intent == book` → BOOKING
7. `intent == greet` and not in BOOKING → GREETING
8. Default → GENERAL

### Key Components

| Component | Entry Point | Purpose |
|-----------|-------------|---------|
| Agent | `agent/main.py` | Redis Streams consumer, LangGraph orchestrator |
| API | `api/main.py` | FastAPI webhooks + admin endpoints |
| Database | `database/models.py` | 9 SQLAlchemy models (UUID PKs, JSONB metadata) |
| Admin Panel | `admin-panel/src/app/` | Next.js App Router |
| Shared | `shared/config.py` | Pydantic Settings, Redis client, Chatwoot client |

### DB-First Calendar

PostgreSQL is source of truth for availability (<100ms). Google Calendar is a push-only mirror (async, fire-and-forget after DB commit).

## Critical Rules

1. **Config access**: ALWAYS use `shared/config.py` via `get_settings()`. NEVER use `os.getenv()`.
2. **State updates**: ALWAYS use `add_message()` from `agent/state/helpers.py`. NEVER mutate state directly.
3. **No state spread**: NEVER use `{**state}` in node return values — causes message duplication via `operator.add` reducer.
4. **Partial returns**: Node returns must be partial dicts — only include fields you intend to change.
5. **Annotated reducers**: ALWAYS use `Annotated[T, reducer_fn]` for custom reducers. Bare types silently fall back to REPLACE semantics.
6. **Mode transitions**: ALWAYS use `transition_mode()` helper — resets `mode_context` via `__reset__` sentinel.
7. **Async I/O**: ALWAYS use `async/await` for all I/O operations.
8. **Spanish user-facing**: All bot responses in Spanish. Code and docs in English.
9. **UUID PKs**: All database models use UUID primary keys.
10. **Timezone-aware**: ALWAYS use `DateTime(timezone=True)`. Canonical timezone: `Europe/Madrid`.
11. **Transient fields**: `user_message` must survive the full pipeline — set by caller, read by mode nodes, cleared only in `summarize_node`.

## State Schema (v6.0)

Key fields in `ConversationState` (`agent/state/schemas.py`):

- `messages: Annotated[list, operator.add]` — Conversation history
- `current_mode: str` — Active mode (GREETING/BOOKING/GENERAL/ESCALATION)
- `mode_context: Annotated[dict, merge_dicts]` — Mode-specific transient data
- `mode_history: Annotated[list[str], operator.add]` — Mode transition log
- `is_first_interaction: bool` — True only on first message
- `customer_name: str | None` — Name collected in GREETING mode
- `user_message: str | None` — Current user message (transient)

Message format: `{"role": "user"|"assistant", "content": str, "timestamp": str}` (roles are NEVER "human" or "ai").

## Tools (8 LangChain tools)

1. `query_info` — Unified info retrieval (services, FAQs, hours, policies)
2. `search_services` — Fuzzy search across 92 services
3. `manage_customer` — Customer CRUD (get, create, update)
4. `get_customer_history` — Appointment history
5. `check_availability` — Check availability for specific date
6. `find_next_available` — Multi-date search for next slots
7. `book` — Atomic booking (auto-confirms, no payment flow)
8. `escalate_to_human` — Human handoff

Tools declare state changes via `_internal_flags` in return values.

## Prompt System (v6.1)

```
agent/prompts/
├── loader.py          # get_system_prompt(), load_markdown() with 10-min TTL cache
├── shared/            # identity.md, critical_rules.md, glossary.md, recovery.md
└── modes/             # greeting.md, booking.md, general.md, escalation.md
```

System prompt = shared components (~2,200 tokens, cached). Mode overlay = mode-specific instructions (~800 tokens, per request).

## Resilience Layer

Multi-provider LLM fallback (controlled by `RESILIENCE_ENABLED` env var):
- Primary: `openai/gpt-4.1-mini`
- Fallback: `deepseek/deepseek-chat`
- Emergency: `meta-llama/llama-3.1-8b-instruct`

Error classification: TRANSIENT (retry with backoff), RATE_LIMIT (retry after delay), PERMANENT/VALIDATION/PARTIAL_FAILURE (fail immediately). Per-conversation retry budget: max 5.

## Documentation Hierarchy

```
CLAUDE.md (this file — operational details) > AGENTS.md (governance) > Component AGENTS.md > skills/*
```

Component-specific guidance lives in `agent/AGENTS.md`, `api/AGENTS.md`, `database/AGENTS.md`. Detailed patterns in `skills/` (auto-invoked based on context — see AGENTS.md for mapping).

## Tech Stack

| Layer | Stack |
|-------|-------|
| Agent | Python 3.11+, LangGraph 0.6.7+, LangChain 0.3.0+, GPT-4.1-mini via OpenRouter |
| API | FastAPI 0.116.1, Pydantic 2.x, Uvicorn 0.30.0+ |
| Database | PostgreSQL 15+, SQLAlchemy 2.0+ (asyncpg), Alembic 1.13+ |
| Cache/Queue | Redis Stack (Streams, RedisSearch, RedisJSON) |
| Admin Panel | Next.js 15, React 18, Tailwind CSS 3.4, shadcn/ui, FullCalendar 6.1 |
| Testing | pytest 8.3+, pytest-asyncio 0.24+ (asyncio_mode=auto) |
| Quality | black (100 cols), ruff, mypy |
