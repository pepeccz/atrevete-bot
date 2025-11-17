# Components Map - Quick Code Navigation

**Purpose:** Find any function, class, or component without grep/search.

**Last Updated:** 2025-11-13

---

## 🗺️ Quick Index

- [API Layer](#api-layer-fastapi) - Webhook receivers
- [Agent Layer](#agent-layer-langgraph) - Core orchestration
  - [Graph](#graph-definition)
  - [Nodes](#nodes-3-total)
  - [Tools](#tools-8-total)
  - [Prompts](#prompts-9-files)
- [Database Layer](#database-layer) - Models and migrations
- [Shared Utilities](#shared-utilities) - Config, logging, clients
- [Admin Interface](#admin-interface-django) - Django Admin
- [Tests](#tests) - Unit and integration tests

---

## API Layer (FastAPI)

**Location:** `/home/pepe/atrevete-bot/api/`

| Component | File | Key Functions | Lines |
|-----------|------|---------------|-------|
| **Main App** | `api/main.py` | `app = FastAPI()` | 10-50 |
| **Chatwoot Webhook** | `api/routes/chatwoot.py` | `handle_webhook()` | 20-80 |
| | | `validate_token()` | 90-110 |
| | | `filter_message()` | 120-150 |
| | | `publish_to_redis()` | 200-230 |
| **Conversations** | `api/routes/conversations.py` | `get_conversation()` | 15-40 |
| | | `list_conversations()` | 50-80 |
| **Health Check** | `api/routes/health.py` | `health_check()` | 15-45 |
| **Webhook Models** | `api/models/webhooks.py` | `ChatwootWebhook` (Pydantic) | 10-80 |

---

## Agent Layer (LangGraph)

**Location:** `/home/pepe/atrevete-bot/agent/`

### Graph Definition

| Component | File | Key Elements | Lines |
|-----------|------|--------------|-------|
| **Main Graph** | `agent/graphs/conversation_flow.py` | `create_graph()` | 150-200 |
| | | `StateGraph` definition | 30-80 |
| | | Edge routing logic | 100-140 |
| **Entry Point** | `agent/main.py` | `main()` - Redis subscriber | 300-350 |
| | | `process_message()` | 200-250 |
| | | `setup_logging()` | 50-80 |

### Nodes (3 total)

| Node Name | File | Function | Lines | Purpose |
|-----------|------|----------|-------|---------|
| `process_incoming_message` | `agent/nodes/conversational_agent.py` | `process_incoming_message()` | 30-60 | Add user message to history |
| `conversational_agent` | `agent/nodes/conversational_agent.py` | `conversational_agent()` | 200-550 | Main GPT-4.1-mini node |
| `summarize` | `agent/nodes/summarization.py` | `summarize()` | 30-120 | FIFO windowing |

**Key functions in `conversational_agent`:**
- `load_contextual_prompt()` - Line 318 - Load modular prompts
- `detect_booking_state()` - Line 400 - 6-state detection
- `format_messages()` - Line 250 - Convert to LangChain format

### Tools (8 total)

**Location:** `/home/pepe/atrevete-bot/agent/tools/`

| # | Tool Name | File | Function | Lines | Purpose |
|---|-----------|------|----------|-------|---------|
| 1 | `query_info` | `info_tools.py` | `query_info()` | 50-200 | Unified info (services, FAQs, hours, policies) |
| 2 | `search_services` | `search_services.py` | `search_services()` | 70-180 | Fuzzy search 92 services |
| 3 | `manage_customer` | `customer_tools.py` | `manage_customer()` | 50-150 | Customer CRUD |
| 4 | `get_customer_history` | `customer_tools.py` | `get_customer_history()` | 180-230 | Appointment history |
| 5 | `check_availability` | `availability_tools.py` | `check_availability_tool()` | 60-220 | Single-date availability |
| 6 | `find_next_available` | `availability_tools.py` | `find_next_available()` | 250-420 | Multi-date search |
| 7 | `book` | `booking_tools.py` | `book()` | 50-280 | Atomic booking |
| 8 | `escalate_to_human` | `escalation_tools.py` | `escalate_to_human()` | 20-90 | Human handoff |

**Tool Registration:**
- All tools registered in: `agent/tools/__init__.py:10-50`

### Prompts (9 files)

**Location:** `/home/pepe/atrevete-bot/agent/prompts/`

| File | Lines | Booking State | Purpose |
|------|-------|---------------|---------|
| `core.md` | ~200 | All | Base rules, identity, error handling |
| `general.md` | ~100 | GENERAL | FAQs, greetings, no booking intent |
| `step1_service.md` | ~150 | SERVICE_SELECTION | Service selection guidance |
| `step2_availability.md` | ~120 | AVAILABILITY_CHECK | Availability checking |
| `step3_customer.md` | ~100 | CUSTOMER_DATA | Customer data collection |
| `step4_booking.md` | ~130 | BOOKING_EXECUTION | Execute book() tool |
| `step5_post_booking.md` | ~80 | POST_BOOKING | Post-booking confirmations |
| `maite_system_prompt.md` | 730 | - | **Legacy (not used)** |
| `summarization_prompt.md` | ~50 | - | Conversation summarization |

**Prompt Loading:**
- Function: `load_contextual_prompt()` in `agent/prompts/__init__.py:246-327`
- State Detection: `_detect_booking_state()` in `agent/prompts/__init__.py:197-243`
- Stylist Caching: `_load_stylist_context_cached()` in `agent/prompts/__init__.py:350-410`

---

## State Management

**Location:** `/home/pepe/atrevete-bot/agent/state/`

| Component | File | Key Elements | Lines |
|-----------|------|--------------|-------|
| **State Schema** | `schemas.py` | `ConversationState` TypedDict | 21-122 |
| | | 19 fields total | |
| **Helpers** | `helpers.py` | `add_message()` | 20-50 |
| | | `should_summarize()` | 60-80 |
| | | `window_messages()` | 90-130 |
| **Checkpointer** | `checkpointer.py` | `get_redis_checkpointer()` | 20-60 |
| | | `initialize_redis_indexes()` | 70-100 |

**ConversationState Fields (19):**
```python
# Core (5)
conversation_id, customer_phone, messages, metadata, user_message

# Message Management (2)
conversation_summary, total_message_count

# Escalation (3)
escalation_triggered, escalation_reason, error_count

# v3.2 Tool Tracking (4)
customer_data_collected, service_selected, slot_selected, appointment_created

# Node Tracking (1)
last_node

# Timestamps (2)
created_at, updated_at

# Deprecated (2)
customer_id, customer_name
```

---

## Database Layer

**Location:** `/home/pepe/atrevete-bot/database/`

### Models (7 tables)

| Model | File | Key Fields | Lines |
|-------|------|-----------|-------|
| `Stylist` | `models.py` | id, name, category, google_calendar_id | 50-90 |
| `Customer` | `models.py` | id, phone, first_name, last_name, total_spent | 100-150 |
| `Service` | `models.py` | id, name, category, duration_minutes | 160-200 |
| `Appointment` | `models.py` | id, customer_id, stylist_id, service_ids, start_time | 210-280 |
| `BusinessHours` | `models.py` | id, day_of_week, start_hour, end_hour | 290-330 |
| `Policy` | `models.py` | id, key, value (JSONB) | 340-370 |
| `ConversationHistory` | `models.py` | id, customer_id, conversation_id, message_content | 380-420 |

**Enums:**
- `ServiceCategory`: Peluquería, Estética (Line 30-35)
- `AppointmentStatus`: provisional, confirmed, completed, cancelled, expired (Line 40-45)
- `MessageRole`: user, assistant, system (Line 50-55)

### Transactions

| Component | File | Key Functions | Lines |
|-----------|------|---------------|-------|
| **Booking Transaction** | `agent/transactions/booking_transaction.py` | `BookingTransaction.execute()` | 80-250 |
| | | `create_calendar_event()` | 150-200 |
| | | `save_appointment()` | 210-250 |
| **Validators** | `agent/validators/transaction_validators.py` | `validate_slot_available()` | 20-60 |
| | | `validate_business_hours()` | 70-110 |

### Connection & Migrations

| Component | File | Key Elements | Lines |
|-----------|------|--------------|-------|
| **Connection** | `connection.py` | `get_async_session()` | 20-50 |
| | | `engine` (AsyncEngine) | 10-20 |
| **Migrations** | `alembic/versions/` | 9 migration files | - |
| **Seeds** | `seeds/` | 6 seed scripts | - |

---

## Shared Utilities

**Location:** `/home/pepe/atrevete-bot/shared/`

| Component | File | Key Functions | Lines |
|-----------|------|---------------|-------|
| **Config** | `config.py` | `get_settings()` | 30-80 |
| | | `Settings` (Pydantic) | 10-120 |
| **Logging** | `logging.py` | `setup_logging()` | 20-60 |
| | | `JSONFormatter` | 70-110 |
| **Redis Client** | `redis_client.py` | `get_redis_client()` | 15-40 |
| | | `publish()` | 50-70 |
| | | `subscribe()` | 80-110 |
| **Chatwoot Client** | `chatwoot_client.py` | `send_message()` | 30-80 |
| | | `get_conversation()` | 90-120 |
| | | `update_conversation()` | 130-160 |

**Config Fields (Settings):**
```python
# Database
DATABASE_URL, POSTGRES_*

# Redis
REDIS_URL

# APIs
OPENROUTER_API_KEY, CHATWOOT_*, GOOGLE_*

# Observability
LANGFUSE_*, GROQ_API_KEY

# Model
LLM_MODEL (default: "openai/gpt-4o-mini")
```

---

## Admin Interface (Django)

**Location:** `/home/pepe/atrevete-bot/admin/`

| Component | File | Key Classes | Lines |
|-----------|------|------------|-------|
| **Admin Models** | `core/admin.py` | 7 `ModelAdmin` classes | 1-452 |
| | | `CustomerAdmin` | 50-120 |
| | | `StylistAdmin` | 130-180 |
| | | `ServiceAdmin` | 190-240 |
| | | `AppointmentAdmin` | 250-320 |
| **Unmanaged Models** | `core/models.py` | 7 models (`managed=False`) | 1-355 |
| **Settings** | `settings.py` | Django configuration | 1-200 |
| **URLs** | `urls.py` | URL routing | 1-20 |

**Access:**
- URL: http://localhost:8001/admin
- Credentials: admin/admin123

---

## Tests

**Location:** `/home/pepe/atrevete-bot/tests/`

### Unit Tests (19 files)

| Test File | Component Tested | Lines |
|-----------|------------------|-------|
| `test_booking_tools.py` | book() tool | 1-300 |
| `test_customer_tools.py` | Customer CRUD | 1-250 |
| `test_calendar_tools.py` | Google Calendar integration | 1-280 |
| `test_conversational_agent.py` | Main agent node | 1-400 |
| `test_prompt_loading.py` | Modular prompt system | 1-200 |
| `test_prompt_optimization_v32.py` | v3.2 optimizations | 1-180 |
| `test_database_models.py` | SQLAlchemy models | 1-250 |
| `test_redis_client.py` | Redis pub/sub | 1-150 |
| ... | (11 more files) | - |

### Integration Tests (15 files)

| Test File | Flow Tested | Lines |
|-----------|-------------|-------|
| `test_agent_flow.py` | End-to-end conversation | 1-350 |
| `test_new_customer_flow.py` | New customer booking | 1-280 |
| `test_returning_customer_flow.py` | Returning customer | 1-250 |
| `test_scenario_08_indecision_consultation.py` | Consultation offer | 1-200 |
| `test_conversation_archival.py` | Redis → PostgreSQL | 1-180 |
| ... | (10 more files) | - |

### Mocks

| Mock File | Purpose | Lines |
|-----------|---------|-------|
| `mocks/calendar_mock.py` | Google Calendar responses | 1-150 |
| `mocks/chatwoot_mock.py` | Chatwoot API responses | 1-120 |

---

## Background Workers

**Location:** `/home/pepe/atrevete-bot/agent/workers/`

| Worker | File | Key Functions | Lines | Status |
|--------|------|---------------|-------|--------|
| **Conversation Archiver** | `conversation_archiver.py` | `archive_conversations()` | 80-150 | ✅ Running |
| | | `fetch_expired_checkpoints()` | 160-200 | |
| | | `save_to_postgres()` | 210-250 | |
| **Reminder** | `reminder_worker.py` | `send_reminders()` | - | ⏳ Scaffolded |
| **Payment Timeout** | - | - | - | ❌ Removed |

---

## Utilities & Helpers

**Location:** `/home/pepe/atrevete-bot/agent/utils/`

| Component | File | Key Functions | Lines |
|-----------|------|---------------|-------|
| **Date Parser** | `date_parser.py` | `parse_date()` | 20-80 |
| | | `parse_time()` | 90-130 |
| | | `to_europe_madrid()` | 140-160 |
| **Service Resolver** | `service_resolver.py` | `resolve_service_names()` | 18-180 |
| | | `fuzzy_match()` | 100-140 |

---

## Quick Search Patterns

### Find a specific function
```bash
# Example: Find where book() tool is defined
grep -r "def book(" agent/tools/

# Example: Find ConversationState definition
grep -r "class ConversationState" agent/state/
```

### Find tool implementations
```bash
# All tools are in agent/tools/*.py
ls agent/tools/*.py
```

### Find where a tool is called
```bash
# Example: Where is escalate_to_human called?
grep -r "escalate_to_human" agent/
```

### Find database queries
```bash
# Example: Find all queries to appointments table
grep -r "Appointment" database/ agent/ --include="*.py"
```

---

## Common Navigation Paths

### "I need to modify the booking logic"
1. Start: `agent/tools/booking_tools.py:book()` (Line 50-280)
2. Transaction: `agent/transactions/booking_transaction.py` (Line 80-250)
3. Validators: `agent/validators/transaction_validators.py`

### "I need to change prompt behavior"
1. Start: `agent/prompts/` directory
2. Loading logic: `agent/prompts/__init__.py:load_contextual_prompt()` (Line 246)
3. State detection: `agent/prompts/__init__.py:_detect_booking_state()` (Line 197)

### "I need to add a new field to state"
1. Schema: `agent/state/schemas.py:ConversationState` (Line 21-122)
2. Update all nodes that read/write that field
3. Update tests

### "I need to understand the conversation flow"
1. Graph: `agent/graphs/conversation_flow.py`
2. Main node: `agent/nodes/conversational_agent.py:conversational_agent()`
3. Test: `tests/integration/test_agent_flow.py`

---

Last updated: 2025-11-13
