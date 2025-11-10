# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Atrévete Bot is an AI-powered WhatsApp booking assistant for a beauty salon. It handles customer bookings via WhatsApp through Chatwoot, managing appointments across 5 stylists using Google Calendar, and escalating to staff when needed. The agent uses LangGraph for stateful conversation orchestration and GPT-4.1-mini via OpenRouter for natural language understanding in Spanish.

**Key External Dependencies:**
- Google Calendar API (5 stylist calendars)
- Chatwoot API (WhatsApp integration)
- OpenRouter API (LLM gateway - using openai/gpt-4.1-mini for cost optimization)
- PostgreSQL 15+ (data persistence)
- Redis Stack (checkpointing + RedisSearch/RedisJSON for LangGraph)

## Development Commands

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

# IMPORTANT: Google Calendar credentials
# The agent service requires service-account-key.json to be present in the project root
# This file is mounted as a read-only volume in docker-compose.yml
# Verify it's accessible inside the container:
docker exec atrevete-agent ls -la /app/service-account-key.json
```

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

### Django Admin Panel
```bash
# Access Django Admin web interface
# URL: http://localhost:8001/admin
# Username: admin
# Password: admin123

# View Django Admin logs
docker-compose logs -f admin

# Restart Django Admin service
docker-compose restart admin

# Access Django shell for manual operations
docker exec atrevete-admin python manage.py shell

# Create additional superuser
docker exec atrevete-admin python manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser('username', 'email@example.com', 'password')"

# Collect static files (if needed for production)
docker exec atrevete-admin python manage.py collectstatic --noinput

# IMPORTANT: Django migrations
# Django Admin uses unmanaged models (managed=False) for core app tables
# DO NOT run Django migrations for the 'core' app - those are managed by Alembic
# Only Django's built-in apps (auth, admin, sessions, contenttypes) use Django migrations
```

**Django Admin Features:**
- **Customers**: Full CRUD with export/import (CSV, Excel, JSON), appointment history, total spent statistics
- **Stylists**: Manage stylist profiles, categories, Google Calendar integration
- **Services**: Service catalog management with duration, categories
- **Appointments**: View/edit appointments with service details, Google Calendar sync
- **Policies**: Manage FAQ responses and business policies (JSON format)
- **Conversation History**: View customer conversation logs with the AI agent
- **Business Hours**: Configure salon opening hours by day of week

**Important Notes:**
- Django Admin models have `managed=False` to prevent interference with Alembic migrations
- Database schema changes must be done via Alembic migrations in the main project
- Django Admin only manages its own auth tables (auth_user, auth_group, etc.)
- Custom purple gradient theme with Spanish language interface
- Import/Export functionality available for customers, services, and appointments

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

## Architecture Overview

### Hybrid Two-Tier Architecture (v3.2)

The system uses a **hybrid architecture** with two distinct tiers:

**Tier 1: Conversational Agent (GPT-4.1-mini via OpenRouter)**
- Single `conversational_agent` node handles all informational conversations
- GPT-4.1-mini with tool access manages: FAQs, greetings, inquiries, customer identification, service information, indecision detection
- Natural language understanding and dialogue management via LLM reasoning
- OpenRouter provides automatic prompt caching (>1024 tokens) for cost optimization
- Transitions to Tier 2 when `booking_intent_confirmed=True`

**Tier 2: Transactional Nodes (Explicit flow)**
- Deterministic nodes for booking, availability checking
- Examples: `check_availability`, `validate_booking_request`, `handle_category_choice`
- Ensures reliable transactional operations with explicit state transitions

**Model Selection Rationale:**
- Using `openai/gpt-4.1-mini` for 7-10x cost savings vs Claude Haiku 4.5
- Input: $0.15/1M tokens vs $1.00/1M tokens
- Automatic caching via OpenRouter (no configuration needed)
- Sufficient capability for booking assistant use case

This simplification reduced complexity from 25 nodes to 12 nodes by consolidating conversational logic into the LLM.

### v3.2 Optimizations: Dynamic Prompt Injection

**Goal:** Reduce token usage by 60-70% through intelligent prompt caching and truncation strategies.

**Key Optimizations Implemented:**

1. **Layered Prompt Architecture (Cacheable vs Dynamic)**
   - **SystemMessage (Cacheable)**: Core prompt + Stylist context (~2,500 tokens)
     - Stable content that benefits from OpenRouter's automatic caching
     - Changes infrequently (only when prompts updated or stylists change)
   - **HumanMessage (Dynamic)**: Temporal + Customer context (~300 tokens)
     - Content that changes per request (current date/time, customer info)
     - NOT cached, minimizing cache invalidation

2. **Granular State Detection (6 Booking States)**
   - Function: `_detect_booking_state()` in `agent/prompts/__init__.py`
   - States detected:
     - `GENERAL`: FAQs, greetings, no booking intent
     - `SERVICE_SELECTION`: User wants to book, needs service selection
     - `AVAILABILITY_CHECK`: Service selected, checking availability
     - `CUSTOMER_DATA`: Slot selected, collecting customer info
     - `BOOKING_EXECUTION`: Ready to execute `book()` tool
     - `POST_BOOKING`: Booking completed, handling confirmations
   - Each state loads focused prompt (2-4KB) instead of monolithic 27KB

3. **In-Memory Caching (Stylist Context)**
   - TTL: 10 minutes
   - Thread-safe with `asyncio.Lock`
   - Reduces DB queries by 90%
   - Saves ~150ms per request (after first cache)
   - Trade-off: Stylist data up to 10 min stale (acceptable, rarely changes)

4. **Tool Output Truncation**
   - `query_info`: Max 10 results (default), configurable 1-50
   - `search_services`: Max 5 results, simplified output (removed `id`)
   - `find_next_available`: Max 5 slots per stylist, simplified output
   - Output fields reduced: Only essential data returned to LLM

5. **Monitoring and Alerts**
   - Logging of prompt sizes (cacheable + dynamic + total)
   - Automatic alerts if prompt >4000 tokens (~16KB)
   - Booking state logged with every request
   - Helps detect regressions in prompt size

**Performance Impact:**

| Metric | Before (v3.0) | After (v3.2) | Improvement |
|--------|---------------|--------------|-------------|
| Prompt size (avg) | 27KB | 8-10KB | -63% |
| Tokens/request | ~7,000 | ~2,500-3,000 | -60% |
| Tokens cacheable | 0 | ~2,500 | OpenRouter cache active |
| Tool output tokens | ~3,500 | ~800-1,200 | -65% |
| DB queries (stylists) | 100% | 10% | -90% |
| Cache hit rate | 0% | 70-80% (est.) | +70-80% |
| Cost/1K conversations | $1,350/mo | $280/mo | -79% ($1,070/mo saved) |

**Files Modified:**
- `agent/prompts/__init__.py`: Granular state detection + stylist caching
- `agent/nodes/conversational_agent.py`: Layered prompts + logging
- `agent/state/schemas.py`: New state flags (v3.2 enhanced)
- `agent/tools/info_tools.py`: Truncation for `query_info`
- `agent/tools/search_services.py`: Simplified output
- `agent/tools/availability_tools.py`: Truncation for `find_next_available`
- `agent/prompts/step5_post_booking.md`: New prompt for POST_BOOKING state

### Request Flow

1. **Webhook Reception (api/)**
   - Chatwoot webhook arrives at `/webhook/chatwoot/{token}` (api/routes/chatwoot.py)
   - Token validated using `CHATWOOT_WEBHOOK_TOKEN` (timing-safe comparison)
   - Message filtered (only `message_type=0` incoming messages processed)
   - Published to Redis `incoming_messages` channel

2. **Agent Orchestration (agent/)**
   - `agent/main.py` subscribes to `incoming_messages` channel
   - LangGraph StateGraph processes message through conversation flow
   - State persisted to Redis via AsyncRedisSaver (RedisSearch indexes)
   - Response published to `outgoing_messages` channel
   - FastAPI consumes response and sends to Chatwoot API

3. **State Management**
   - Redis: Short-term checkpointing (15 min TTL, RDB snapshots every 15 min)
   - PostgreSQL: Long-term archival via `conversation_archiver` worker
   - State schema: `agent/state/schemas.py` (50 fields, hybrid architecture)

### Key Components

**LangGraph Flow (agent/graphs/conversation_flow.py)**
- Main StateGraph: 12 nodes orchestrating conversation
- Router function: `should_route_to_booking` determines Tier 1 → Tier 2 transition
- Checkpointing: AsyncRedisSaver with Redis Stack (requires RedisSearch/RedisJSON)
- System prompt: `agent/prompts/maite_system_prompt.md` (31KB Spanish personality)

**Conversational Agent Node (agent/nodes/conversational_agent.py)**
- Tier 1 workhorse: GPT-4.1-mini via OpenRouter with bound tools
- Tools available: customer management, FAQs, services (92 individual), availability, consultations, escalation
- Uses LangChain's `ChatOpenAI` with tool binding (configured for OpenRouter API)
- Converts state messages to LangChain format (SystemMessage, HumanMessage, AIMessage, ToolMessage)
- Automatic prompt caching enabled (OpenRouter feature for prompts >1024 tokens)

**State Schema (agent/state/schemas.py) - v3.2 Enhanced**
- `ConversationState` TypedDict: 19 fields (v3.2 adds 3 booking state flags)
- Message format: `{"role": "user"|"assistant", "content": str, "timestamp": str}`
- IMPORTANT: Use `add_message()` helper from `agent/state/helpers.py` for correct format
- FIFO windowing: Recent 10 messages kept, older messages summarized
- **New v3.2 fields for granular state detection:**
  - `service_selected: str | None` - Selected service name
  - `slot_selected: dict | None` - Selected slot `{stylist_id, start_time, duration}`
- These flags enable 6-state detection for focused prompt loading

**Database Models (database/models.py)**
- Core tables: `customers`, `stylists`, `services`, `business_hours`
- Transactional tables: `appointments`, `conversation_history`
- All use UUID primary keys, TIMESTAMP WITH TIME ZONE, JSONB metadata
- Enums: `ServiceCategory`, `AppointmentStatus`, `MessageRole`

**Tools (agent/tools/) - v3.1 Consolidated (7 tools)**
- Information: `query_info` (services, FAQs, hours, policies - replaces 4 tools)
- Customer management: `manage_customer` (get, create, update - replaces 3 tools)
- Customer history: `get_customer_history` (appointment history)
- Availability: `check_availability` (single date) and `find_next_available` (multi-date search)
- Booking: `book` (atomic transaction via BookingTransaction handler)
- Escalation: `escalate_to_human` (human handoff)
- Note: Consultation service is offered via `query_info("services", {"name": "consulta gratuita"})`, not a separate tool

**Background Workers (agent/workers/)**
- `conversation_archiver.py`: Archives expired Redis checkpoints to PostgreSQL
- Runs every 5 minutes, processes conversations with TTL expired
- Ensures conversation history persistence beyond Redis TTL

## Important Patterns

### Configuration Access
**CRITICAL:** Always use `shared/config.py` for environment variables. NEVER use `os.getenv()` directly.
```python
from shared.config import get_settings
settings = get_settings()  # Cached via @lru_cache
api_key = settings.ANTHROPIC_API_KEY
```

### State Updates
State is immutable. Nodes must return new dicts, not mutate input state:
```python
from agent.state.helpers import add_message

async def my_node(state: ConversationState) -> dict[str, Any]:
    # CORRECT: Use helper to return new state dict
    return add_message(state, "assistant", "Response text")

    # WRONG: Never mutate state directly
    # state["messages"].append(...)  # DON'T DO THIS
```

### Message Format
Always use `add_message()` helper to ensure correct message format:
```python
# Message format (role is "user" or "assistant", NEVER "human" or "ai")
{
    "role": "user" | "assistant",
    "content": str,
    "timestamp": str  # ISO 8601 in Europe/Madrid timezone
}
```

### Redis Checkpointer Initialization
AsyncRedisSaver requires Redis Stack (for RedisSearch/RedisJSON modules):
```python
from agent.state.checkpointer import get_redis_checkpointer, initialize_redis_indexes

checkpointer = get_redis_checkpointer()
await initialize_redis_indexes(checkpointer)  # Creates checkpoint_writes index
```

### Database Connections
Use async context manager for database sessions:
```python
from database.connection import get_async_session

async for session in get_async_session():
    result = await session.execute(query)
    await session.commit()
    break  # Important: break after first iteration
```

### Chatwoot API Integration
Chatwoot API URL must have trailing slash removed before use:
```python
settings = get_settings()
api_url = settings.CHATWOOT_API_URL.rstrip('/')
endpoint = f"{api_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
```

## Testing Strategy

- **Unit tests (tests/unit/)**: Test individual functions/tools in isolation with mocks
- **Integration tests (tests/integration/)**: Test component interactions (API → Redis → Agent)
- **Scenario tests (tests/integration/scenarios/)**: Test complete conversation flows end-to-end
- **Mocks (tests/mocks/)**: Shared mock objects (Chatwoot, Google Calendar APIs)
- **Coverage requirement**: 85% minimum (configured in pyproject.toml)
- **Excluded from coverage**: `admin/*` (deferred to Epic 7), migrations, tests

## Technology Stack

- **Agent:** LangGraph 0.6.7+, LangChain 0.3.0+, GPT-4.1-mini via OpenRouter (openai/gpt-4.1-mini)
- **LLM Provider:** OpenRouter API (unified gateway with automatic prompt caching)
- **API:** FastAPI 0.116.1, Uvicorn 0.30.0+, Pydantic 2.x (settings via pydantic-settings)
- **Database:** PostgreSQL 15+, SQLAlchemy 2.0+ (asyncpg driver), Alembic 1.13+
- **Cache:** Redis Stack (redis-stack-server with RedisSearch, RedisJSON)
- **Testing:** pytest 8.3.0+, pytest-asyncio 0.24.0+, asyncio_mode=auto
- **Code Quality:** black (line length 100), ruff (pycodestyle, pyflakes, isort), mypy (strict for shared/database/)

## Project Structure Notes

- `api/` - FastAPI webhook receiver with routes for Chatwoot webhooks
- `agent/` - LangGraph orchestrator with graphs, nodes, tools, prompts, workers
- `database/` - SQLAlchemy models + Alembic migrations + seed data
- `shared/` - Shared utilities: config, logging, Redis client, Chatwoot client
- `admin/` - Django Admin interface (deferred to Epic 7, not implemented)
- `tests/` - Test suite organized by type (unit, integration, mocks)
- `docker/` - Dockerfiles for API and Agent services
- `.cursor/rules/bmad/` - BMAD development methodology rules (orchestrator, analyst, architect, dev, qa, pm, po, sm, ux-expert)

## Security Notes

- Chatwoot webhook authentication: Token in URL path + timing-safe comparison
- Environment variables: NEVER commit `.env` to git
- API keys: Use test keys for development, live keys only in production
- Database credentials: Minimum 16 characters for security
- Google service account key: Mounted as read-only volume, never commit to git

## Troubleshooting

### Google Calendar API Errors

**Error:** `FileNotFoundError: [Errno 2] No such file or directory: 'service-account-key.json'`

**Cause:** The Google service account credentials file is not accessible inside the Docker container.

**Solution:**
1. Verify the file exists on the host: `ls -la /home/pepe/atrevete-bot/service-account-key.json`
2. Verify `docker-compose.yml` has the volume mount in the `agent` service:
   ```yaml
   agent:
     volumes:
       - ./service-account-key.json:/app/service-account-key.json:ro
   ```
3. Recreate the container (restart is not enough): `docker-compose up -d agent`
4. Verify the file is accessible: `docker exec atrevete-agent ls -la /app/service-account-key.json`

**Impact if not fixed:**
- Customers cannot check availability
- Booking flow is blocked (requires availability check)
- Agent can only handle informational queries (FAQs, service info)
- All booking attempts will escalate to human staff
