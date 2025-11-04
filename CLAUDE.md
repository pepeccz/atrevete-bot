# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Atrévete Bot is an AI-powered WhatsApp booking assistant for a beauty salon. It handles customer bookings via WhatsApp through Chatwoot, managing appointments across 5 stylists using Google Calendar, processing payments via Stripe, and escalating to staff when needed. The agent uses LangGraph for stateful conversation orchestration and Claude Sonnet 4 for natural language understanding in Spanish.

**Key External Dependencies:**
- Google Calendar API (5 stylist calendars)
- Stripe API (payments)
- Chatwoot API (WhatsApp integration)
- Anthropic Claude API (Sonnet 4)
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

### Hybrid Two-Tier Architecture

The system uses a **hybrid architecture** with two distinct tiers:

**Tier 1: Conversational Agent (Claude-powered)**
- Single `conversational_agent` node handles all informational conversations
- Claude Sonnet 4 with tool access manages: FAQs, greetings, inquiries, customer identification, service information, indecision detection
- Natural language understanding and dialogue management via Claude's reasoning
- Transitions to Tier 2 when `booking_intent_confirmed=True`

**Tier 2: Transactional Nodes (Explicit flow)**
- Deterministic nodes for booking, availability checking, payment processing
- Examples: `check_availability`, `validate_booking_request`, `handle_category_choice`
- Ensures reliable transactional operations with explicit state transitions

This simplification reduced complexity from 25 nodes to 12 nodes by consolidating conversational logic into Claude.

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
- Tier 1 workhorse: Claude Sonnet 4 with bound tools
- Tools available: customer management, FAQs, services (92 individual), availability, consultations, escalation
- Uses LangChain's `ChatAnthropic` with tool binding
- Converts state messages to LangChain format (SystemMessage, HumanMessage, AIMessage, ToolMessage)

**State Schema (agent/state/schemas.py)**
- `ConversationState` TypedDict: 50 fields (simplified from 158)
- Message format: `{"role": "user"|"assistant", "content": str, "timestamp": str}`
- IMPORTANT: Use `add_message()` helper from `agent/state/helpers.py` for correct format
- FIFO windowing: Recent 10 messages kept, older messages summarized

**Database Models (database/models.py)**
- Core tables: `customers`, `stylists`, `services`, `business_hours`
- Transactional tables: `appointments`, `payments`, `conversation_history`
- All use UUID primary keys, TIMESTAMP WITH TIME ZONE, JSONB metadata
- Enums: `ServiceCategory`, `PaymentStatus`, `AppointmentStatus`, `MessageRole`

**Tools (agent/tools/)**
- Customer tools: `get_customer_by_phone`, `create_customer`
- Booking tools: `get_services`, `start_booking_flow`, `set_preferred_date`, `calculate_total`
- Availability tools: `check_availability_tool` (multi-calendar Google Calendar API)
- FAQ tools: `get_faqs` (knowledge base responses)
- Consultation tools: `offer_consultation_tool` (free consultation for indecisive customers)
- Escalation tools: `escalate_to_human` (notify team via Chatwoot group)

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
- **Mocks (tests/mocks/)**: Shared mock objects (Chatwoot, Stripe, Google Calendar APIs)
- **Coverage requirement**: 85% minimum (configured in pyproject.toml)
- **Excluded from coverage**: `admin/*` (deferred to Epic 7), migrations, tests

## Technology Stack

- **Agent:** LangGraph 0.6.7+, LangChain 0.3.0+, Claude Sonnet 4 (claude-sonnet-4-20250514)
- **API:** FastAPI 0.116.1, Uvicorn 0.30.0+, Pydantic 2.x (settings via pydantic-settings)
- **Database:** PostgreSQL 15+, SQLAlchemy 2.0+ (asyncpg driver), Alembic 1.13+
- **Cache:** Redis Stack (redis-stack-server with RedisSearch, RedisJSON)
- **Testing:** pytest 8.3.0+, pytest-asyncio 0.24.0+, asyncio_mode=auto
- **Code Quality:** black (line length 100), ruff (pycodestyle, pyflakes, isort), mypy (strict for shared/database/)

## Project Structure Notes

- `api/` - FastAPI webhook receiver with routes for Chatwoot/Stripe webhooks
- `agent/` - LangGraph orchestrator with graphs, nodes, tools, prompts, workers
- `database/` - SQLAlchemy models + Alembic migrations + seed data
- `shared/` - Shared utilities: config, logging, Redis client, Chatwoot client
- `admin/` - Django Admin interface (deferred to Epic 7, not implemented)
- `tests/` - Test suite organized by type (unit, integration, mocks)
- `docker/` - Dockerfiles for API and Agent services
- `.cursor/rules/bmad/` - BMAD development methodology rules (orchestrator, analyst, architect, dev, qa, pm, po, sm, ux-expert)

## Security Notes

- Chatwoot webhook authentication: Token in URL path + timing-safe comparison
- Stripe webhook authentication: Signature validation via `stripe.Webhook.construct_event`
- Environment variables: NEVER commit `.env` to git
- API keys: Use test keys for development, live keys only in production
- Database credentials: Minimum 16 characters for security
