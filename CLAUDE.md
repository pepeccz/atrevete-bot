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

> ✅ **ADR-011 IMPLEMENTATION COMPLETE (2025-11-24):** Sistema migrado de **dual persistence a single source of truth**. FSM state ahora consolidado en LangGraph checkpoints (eliminada raza condition, +100ms latencia).

### FSM-LangGraph Single Source of Truth (ADR-011) - IMPLEMENTED

**Problema anterior (ADR-010):** Dual persistence causaba race conditions y requería workaround de 100ms sleep:
- FSM persistía en Redis key `fsm:{conversation_id}` (síncrono)
- LangGraph checkpoint persistía en `langchain:checkpoint:thread:*` (asincrónico)
- Divergencia posible si mensajes llegaban rápido

**Solución ADR-011 (Implementada):** FSM consolidado en checkpoint:
```
Message llega
    ↓
FSM carga desde ConversationState.fsm_state (ÚNICA FUENTE)
    ↓
FSM procesa + transiciona
    ↓
FSM serializa a state["fsm_state"] = fsm.to_dict()
    ↓
LangGraph persiste TODO en checkpoint (una escritura, no dos)
    ↓
Próximo mensaje: FSM y checkpoint SIEMPRE en sync
```

**Beneficios:**
- ✅ Eliminada race condition (0% divergencia garantizado)
- ✅ -100ms latencia (sin sleep workaround)
- ✅ -20-30% Redis memory (sin fsm:* keys)
- ✅ Arquitectura más simple (una fuente de verdad)

**Implementación:**
- Fases 1-4 completadas (serialización, dual-read, cutover)
- Phase 5 pendiente (optimización + documentación)
- Ver `docs/fsm-langgraph-harmony-analysis-2025-11-24.md` para análisis completo

### FSM Hybrid Architecture (v4.0) - FOUNDATION FOR ADR-011

**Base (v4.0):** FSM híbrida donde LLM solo maneja NLU y generación de lenguaje, mientras FSM controla flujo de conversación.
- Implementado en Epic 5 (commit 3366117)
- FSM now consolidated in checkpoint (ADR-011, 2025-11-24)

```
┌──────────────┐
│ LLM (NLU)    │ ← Interpreta INTENCIÓN + Genera LENGUAJE
└──────┬───────┘
       ↓
┌──────────────┐
│ FSM Control  │ ← Controla FLUJO + Valida PROGRESO + Decide TOOLS
└──────┬───────┘
       ↓
┌──────────────┐
│ Tool Calls   │ ← Ejecuta ACCIONES validadas
└──────────────┘
```

**Nuevos componentes (Epic 5):**
- `agent/fsm/booking_fsm.py` - FSM Controller con estados y transiciones
- `agent/fsm/intent_extractor.py` - Extracción de intención estructurada

**Estados del Booking FSM:**
- IDLE → SERVICE_SELECTION → STYLIST_SELECTION → SLOT_SELECTION → CUSTOMER_DATA → CONFIRMATION → BOOKED

**Beneficios:**
- ✅ Transiciones deterministas y testeables
- ✅ Estado siempre claro y debuggeable
- ✅ LLM enfocado en lenguaje natural
- ✅ Validación explícita antes de tool calls

### Legacy: Tool-Based Architecture (v3.2)

The system currently uses a **simplified tool-based architecture** with 3 nodes (being replaced by FSM):

**Main Conversational Flow (3 Nodes)**
1. **`process_incoming_message`**: Adds user message to conversation history
2. **`conversational_agent`**: GPT-4.1-mini via OpenRouter with 8 tools handles ALL conversations
   - Tools available: customer management, FAQs, services (92 individual), availability, booking, escalation
   - Natural language understanding and dialogue management via LLM reasoning
   - OpenRouter provides automatic prompt caching (>1024 tokens) for cost optimization
   - Handles both informational queries AND booking transactions
3. **`summarize`**: FIFO windowing - keeps recent 10 messages, summarizes older ones

**Model Selection Rationale:**
- Using `openai/gpt-4.1-mini` for 7-10x cost savings vs Claude Haiku 4.5
- Input: $0.15/1M tokens vs $1.00/1M tokens
- Automatic caching via OpenRouter (no configuration needed)
- Sufficient capability for booking assistant use case

This architecture eliminated the hybrid tier system, consolidating all logic into a single conversational agent with tool access.

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

2. **Granular State Detection (7 Booking States)** - Updated Nov 13, 2025
   - Function: `_detect_booking_state()` in `agent/prompts/__init__.py`
   - States detected:
     - `GENERAL`: FAQs, greetings, no booking intent
     - `SERVICE_SELECTION`: User wants to book, needs service selection
     - `AVAILABILITY_CHECK`: Service selected, checking availability
     - `CUSTOMER_DATA`: Slot selected, collecting customer info
     - `BOOKING_CONFIRMATION`: Customer data collected, waiting for user confirmation (NEW)
     - `BOOKING_EXECUTION`: User confirmed, ready to execute `book()` tool
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
   - State schema: `agent/state/schemas.py` (19 fields, v3.2 enhanced)

### Key Components

**LangGraph Flow (agent/graphs/conversation_flow.py)**
- Main StateGraph: 3 nodes (process_incoming_message → conversational_agent → summarize)
- Linear flow with conditional edges for conversation summarization
- Checkpointing: AsyncRedisSaver with Redis Stack (requires RedisSearch/RedisJSON)
- System prompts: Modular architecture with 8 files (core.md + 6 state-specific prompts + summarization)

**Conversational Agent Node (agent/nodes/conversational_agent.py)**
- Main workhorse: GPT-4.1-mini via OpenRouter with 8 bound tools
- Tools available: query_info, search_services, manage_customer, get_customer_history, check_availability, find_next_available, book, escalate_to_human
- **Customer Creation Flow:** Customers auto-created in `process_incoming_message` (first interaction), NOT during booking
- **Booking Flow:** PASO 3 collects first_name, last_name, notes from user; PASO 4 calls `book()` with these fields
- Uses LangChain's `ChatOpenAI` with tool binding (configured for OpenRouter API)
- Converts state messages to LangChain format (SystemMessage, HumanMessage, AIMessage, ToolMessage)
- Automatic prompt caching enabled (OpenRouter feature for prompts >1024 tokens)
- Modular prompt loading: Detects booking state (6 states) and loads only relevant prompt files (core.md + state-specific)

**State Schema (agent/state/schemas.py) - v3.2 Enhanced**
- `ConversationState` TypedDict: 19 fields total
- Message format: `{"role": "user"|"assistant", "content": str, "timestamp": str}`
- IMPORTANT: Use `add_message()` helper from `agent/state/helpers.py` for correct format
- FIFO windowing: Recent 10 messages kept, older messages summarized
- **v3.2 fields for granular state detection (enables 6-state booking flow):**
  - `customer_data_collected: bool` - Customer identified/created
  - `service_selected: str | None` - Selected service name
  - `slot_selected: dict | None` - Selected slot `{stylist_id, start_time, duration}`
  - `appointment_created: bool` - Booking completed
- These flags enable 6-state detection (GENERAL → SERVICE_SELECTION → AVAILABILITY_CHECK → CUSTOMER_DATA → BOOKING_EXECUTION → POST_BOOKING) for focused prompt loading

**Database Models (database/models.py)**
- Core tables: `customers`, `stylists`, `services`, `business_hours`, `policies`
- Transactional tables: `appointments`, `conversation_history`
- All use UUID primary keys, TIMESTAMP WITH TIME ZONE, JSONB metadata
- Enums: `ServiceCategory`, `AppointmentStatus`, `MessageRole`
- **IMPORTANT:** System de pagos eliminado completamente (Nov 10, 2025):
  - `services` table NO tiene campo `price_euros` (servicios sin precio)
  - `appointments` table NO tiene campos de pago (`stripe_payment_id`, `payment_status`, etc.)
  - Todas las citas se auto-confirman al crear (status=`CONFIRMED`, sin flujo provisional)
  - Sin integración con Stripe
- **IMPORTANT:** Customer management separado del flujo de reserva (Nov 13, 2025):
  - Customers auto-created in `process_incoming_message` (first interaction)
  - `appointments` table has appointment-specific fields: `first_name` (required), `last_name` (optional), `notes` (optional)
  - These fields allow booking-specific customer data without calling `manage_customer`
  - `customer_id` in appointments remains FK (NOT NULL) linking to `customers` table
  - Booking flow (PASO 3) collects name/notes directly from user, no database operations until book()

**Tools (agent/tools/) - v3.2 Consolidated (8 tools)**
1. **`query_info`**: Unified information retrieval (services, FAQs, hours, policies)
2. **`search_services`**: Fuzzy search across 92 services (handles ambiguous service names)
3. **`manage_customer`**: Unified customer CRUD (get, create, update)
4. **`get_customer_history`**: Retrieve appointment history
5. **`check_availability`**: Check availability for specific date
6. **`find_next_available`**: Multi-date automatic search for next available slots
7. **`book`**: Atomic booking transaction (auto-confirms, no payment flow)
8. **`escalate_to_human`**: Human handoff for complex cases

Note: Consultation service is offered via `query_info("services", {"name": "consulta gratuita"})`, not a separate tool

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
api_key = settings.OPENROUTER_API_KEY  # OpenRouter unified gateway
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
- `admin/` - Django Admin interface (✅ Implemented Nov 6, 2025 - accessible at http://localhost:8001/admin)
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
