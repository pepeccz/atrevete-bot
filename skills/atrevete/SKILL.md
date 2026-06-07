---
name: atrevete
description: >
  Main entry point for Atrévete Bot development - quick reference for all components.
  Trigger: General Atrévete Bot development questions, project overview, component navigation.
metadata:
  author: atrevete-bot
  version: "1.0"
  scope: [root]
  auto_invoke:
    - "Working on atrevete-bot"
    - "General Atrévete Bot development questions"
    - "Project overview and architecture"
---

## Project Overview

**Atrévete Bot** is an AI-powered WhatsApp booking assistant for a beauty salon. It handles customer bookings via WhatsApp through Chatwoot, managing appointments across 5 stylists using a DB-first calendar architecture with Google Calendar as a push-only mirror.

## Components

| Component | Stack | Location |
|-----------|-------|----------|
| Agent | Python 3.11+, LangGraph, GPT-4o-mini via OpenRouter | `agent/` |
| API | FastAPI, Pydantic, SQLAlchemy | `api/` |
| Admin Panel | Django (legacy) / Next.js 15 (planned) | `admin/` / `admin-panel/` |
| Database | PostgreSQL, SQLAlchemy, Alembic | `database/` |
| Shared | Config, logging, Redis client, Chatwoot client | `shared/` |

## Architecture Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         MESSAGE PROCESSING                              │
└─────────────────────────────────────────────────────────────────────────┘

WhatsApp → Chatwoot → Webhook (API) → Redis Streams → Agent
                                            ↓
                               create_agent + 7 middleware
                               (SSOT: agent/agent_factory.py:47-55)
                                            ↓
                              ┌─────────────────────────────────────┐
                              │  Middleware Stack (per turn)        │
                              │  1. DisclosureMiddleware            │
                              │  2. CustomerResolveMiddleware       │
                              │  3. AppointmentContextMiddleware    │
                              │  4. DynamicPromptMiddleware         │
                              │  5. AvailabilityContextMiddleware   │
                              │  6. PromptAssemblyMiddleware        │
                              │  7. SummarizeMiddleware             │
                              └─────────────────────────────────────┘
                                            ↓
                                  LLM tool-calling loop (6 tools)
                                            ↓
                                    PostgreSQL (State)
                                            ↓
                               Response → Chatwoot → WhatsApp


┌─────────────────────────────────────────────────────────────────────────┐
│                    DB-FIRST CALENDAR                                    │
└─────────────────────────────────────────────────────────────────────────┘

Availability Check (read):
  PostgreSQL query → <100ms response

Booking (write):
  1. DB commit (atomic transaction)
  2. Fire-and-forget Google Calendar push (async)
```

## Key Data Flow

1. **Message Reception**: Chatwoot webhook → `api/routes/chatwoot.py`
2. **Queue**: Redis Streams for reliable async processing
3. **Processing**: Agent reads from stream, processes via `create_agent` + 7 middleware
4. **Response**: Agent sends via Chatwoot API → WhatsApp

## Agent Architecture

Single LangChain `create_agent` tool-calling loop. The LLM picks tools directly; middleware hydrates context per turn. No mode dispatch, no keyword router.

**6 tools:**

| Tool | Purpose |
|------|---------|
| `check_availability` | Probe slots for service + stylist + day |
| `get_next_available_options` | Return next N free slots |
| `book` | Atomic create appointment + push to GCal |
| `update_booking` | Mutate active booking draft |
| `manage_appointments` | List / cancel / reschedule existing appointments |
| `escalate` | Hand off to human agent |

## Quick Commands

```bash
# Start all services
docker-compose up -d

# View specific service logs
docker-compose logs -f agent
docker-compose logs -f api

# Run migrations
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic upgrade head

# Access PostgreSQL
docker exec -it atrevete-postgres psql -U atrevete -d atrevete_db

# Access Redis CLI
docker exec -it atrevete-redis redis-cli

# Run tests
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest

# Format code
black .
ruff check .
mypy .
```

## Environment Variables

### Core Configuration

| Category | Key Variables |
|----------|---------------|
| **Database** | `DATABASE_URL`, `POSTGRES_*` |
| **Redis** | `REDIS_URL` |
| **Chatwoot** | `CHATWOOT_API_URL/TOKEN/ACCOUNT_ID/INBOX_ID/WEBHOOK_TOKEN` |
| **LLM** | `OPENROUTER_API_KEY`, `LLM_MODEL` (default: `openai/gpt-5.4-mini`) |
| **Resilience** | `RESILIENCE_ENABLED`, `LLM_FALLBACK_MODEL`, `LLM_EMERGENCY_MODEL` |
| **Google Calendar** | `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_CALENDAR_IDS` |

See `.env.example` for complete list.

## Related Skills

| Skill | When to Use |
|-------|-------------|
| `atrevete-agent` | Working on conversation flow, nodes, modes, tools |
| `atrevete-api` | Creating routes, services, webhooks |
| `atrevete-database` | Database models, migrations |

## Critical Rules

- **ALWAYS** use `shared/config.py` for environment variables - NEVER use `os.getenv()` directly
- **ALWAYS** use `add_message()` helper for state updates - NEVER mutate state directly
- **NEVER** use `{**state}` spread in node return values - causes message duplication
- **ALWAYS** use `Annotated[T, reducer_fn]` for custom reducers in state schema
- **ALWAYS** use async/await for all I/O operations
- **ALWAYS** maintain Spanish for user-facing content, English for code/docs
- **NEVER** start services (docker, npm, etc.) unless explicitly requested

## Cross-Cutting Concerns

### State Management

LangGraph state is immutable. Nodes return partial dicts:

```python
# CORRECT: Partial return - only what changes
async def summarize_node(state: ConversationState) -> dict:
    return {"conversation_summary": new_summary, "user_message": None}

# WRONG: Full state spread - causes reducers to re-apply
async def summarize_node(state: ConversationState) -> dict:
    return {**state, "conversation_summary": new_summary}
```

### Configuration Access

```python
from shared.config import get_settings

settings = get_settings()  # Cached via @lru_cache
api_key = settings.OPENROUTER_API_KEY
```

### Database Connections

```python
from database.connection import get_async_session

async for session in get_async_session():
    result = await session.execute(query)
    await session.commit()
    break  # Important: break after first iteration
```

### Redis Checkpointer

```python
from agent.state.checkpointer import get_redis_checkpointer, initialize_redis_indexes

checkpointer = get_redis_checkpointer()
await initialize_redis_indexes(checkpointer)
```

## Testing Patterns

- **Unit tests**: `tests/unit/` - Test individual functions/tools with mocks
- **Integration tests**: `tests/integration/` - Test component interactions
- **Scenario tests**: `tests/integration/scenarios/` - End-to-end conversation flows
- **Coverage requirement**: 85% minimum
- **Excluded from coverage**: `admin/*`, migrations, tests

### Running Tests

```bash
# All tests with coverage
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest

# Specific test file
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/unit/test_customer_tools.py

# With verbose output
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/unit/test_customer_tools.py::test_create_customer -v
```

## Common Utilities

### Adding Messages to State

```python
from agent.state.helpers import add_message

return add_message(state, "assistant", "Response text")
```

### Chatwoot API Integration

```python
settings = get_settings()
api_url = settings.CHATWOOT_API_URL.rstrip('/')
endpoint = f"{api_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
```

### Mode Transitions

```python
from agent.state.schemas import transition_mode

# Always use transition_mode helper - it resets mode_context properly
return {
    **transition_mode("BOOKING"),
    "service_id": service_id
}
```

## Resources

- [CLAUDE.md](../../CLAUDE.md) - Comprehensive development guide (most up-to-date)
- [README.md](../../README.md) - Project overview and quick start
- Component AGENTS.md: [agent/](../../agent/AGENTS.md), [api/](../../api/AGENTS.md), [database/](../../database/AGENTS.md)
