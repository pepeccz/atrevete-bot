# Source Tree Analysis - Atrévete Bot

## Project Structure

```
atrevete-bot/
│
├── api/                           # FastAPI Webhook Receiver
│   ├── __init__.py
│   ├── main.py                   # 🚀 ENTRY POINT: FastAPI application
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── chatwoot.py           # POST /webhook/chatwoot/{token}
│   │   └── conversations.py       # GET /conversations/ endpoints
│   ├── models/
│   │   ├── __init__.py
│   │   └── chatwoot_webhook.py   # Pydantic models for webhook payloads
│   └── middleware/
│       ├── __init__.py
│       └── rate_limiting.py       # RateLimitMiddleware
│
├── agent/                         # LangGraph Orchestrator
│   ├── __init__.py
│   ├── main.py                   # 🚀 ENTRY POINT: Agent worker
│   ├── graphs/
│   │   ├── __init__.py
│   │   └── conversation_flow.py  # 🔑 StateGraph definition (v3.2)
│   ├── nodes/
│   │   ├── __init__.py
│   │   ├── conversational_agent.py  # Main agent node (GPT-4.1-mini)
│   │   └── summarization.py         # Message summarization node
│   ├── tools/                     # Agent Tools (8 total)
│   │   ├── __init__.py
│   │   ├── info_tools.py         # query_info
│   │   ├── search_services.py    # search_services
│   │   ├── customer_tools.py     # manage_customer, get_customer_history
│   │   ├── calendar_tools.py     # check_availability, find_next_available
│   │   ├── booking_tools.py      # book
│   │   ├── escalation_tools.py   # escalate_to_human
│   │   ├── availability_tools.py # Availability helpers
│   │   └── notification_tools.py # ChatwootClient wrapper
│   ├── prompts/                   # System Prompts
│   │   ├── __init__.py           # Prompt loading + state detection
│   │   ├── core.md               # Base Maite persona
│   │   ├── step1_general.md      # GENERAL + SERVICE_SELECTION
│   │   ├── step2_availability.md # AVAILABILITY_CHECK
│   │   ├── step3_customer.md     # CUSTOMER_DATA
│   │   ├── step4_confirmation.md # BOOKING_CONFIRMATION
│   │   ├── step4_booking.md      # BOOKING_EXECUTION
│   │   ├── step5_post_booking.md # POST_BOOKING
│   │   └── summarization.md      # Summarization prompt
│   ├── state/
│   │   ├── __init__.py
│   │   ├── schemas.py            # ConversationState TypedDict
│   │   ├── helpers.py            # add_message(), should_summarize()
│   │   └── checkpointer.py       # AsyncRedisSaver configuration
│   ├── transactions/
│   │   ├── __init__.py
│   │   └── booking_transaction.py # BookingTransaction handler
│   ├── validators/
│   │   ├── __init__.py
│   │   └── transaction_validators.py
│   ├── workers/
│   │   ├── __init__.py
│   │   └── conversation_archiver.py # Archives expired checkpoints
│   └── utils/
│       ├── __init__.py
│       ├── date_parser.py        # Natural language date parsing
│       ├── service_resolver.py   # Service name resolution
│       └── monitoring.py         # Langfuse integration
│
├── database/                      # SQLAlchemy + Alembic
│   ├── __init__.py
│   ├── models.py                 # 🔑 ORM models (7 tables)
│   ├── connection.py             # Database connection manager
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/             # Migration scripts (10 migrations)
│   └── seeds/
│       └── ...                   # Seed data files
│
├── shared/                        # Shared Utilities
│   ├── __init__.py
│   ├── config.py                 # 🔑 Settings (pydantic-settings)
│   ├── redis_client.py           # Redis connection + pub/sub
│   ├── chatwoot_client.py        # Chatwoot API client
│   ├── logging_config.py         # JSON logging configuration
│   ├── archive_retrieval.py      # Conversation history queries
│   ├── audio_conversion.py       # OGG → WAV conversion
│   └── audio_transcription.py    # Groq Whisper service
│
├── admin/                         # Django Admin Panel
│   ├── __init__.py
│   ├── atrevete_admin/
│   │   ├── settings.py           # Django settings
│   │   ├── urls.py               # URL configuration
│   │   └── wsgi.py               # 🚀 ENTRY POINT: WSGI application
│   ├── core/
│   │   ├── admin.py              # Admin model registrations
│   │   └── models.py             # Unmanaged models (managed=False)
│   ├── static/                   # Static files (CSS, JS)
│   └── templates/                # Admin templates
│
├── tests/                         # Test Suite
│   ├── __init__.py
│   ├── conftest.py               # Pytest fixtures
│   ├── unit/                     # Unit tests
│   ├── integration/              # Integration tests
│   │   └── scenarios/            # End-to-end conversation tests
│   └── mocks/                    # Shared mock objects
│
├── docker/                        # Dockerfiles
│   ├── Dockerfile.api            # FastAPI image
│   ├── Dockerfile.admin          # Django image
│   ├── Dockerfile.agent          # LangGraph worker image
│   └── nginx/                    # Nginx configuration
│
├── docs/                          # Generated Documentation
│   └── sprint-artifacts/         # Sprint tracking
│
├── scripts/                       # Utility Scripts
│   └── ...
│
├── .github/
│   └── workflows/
│       └── test.yml              # CI/CD test pipeline
│
├── docker-compose.yml            # 🔑 Service orchestration
├── requirements.txt              # Python dependencies
├── pyproject.toml                # Tool configuration
├── alembic.ini                   # Alembic configuration
├── CLAUDE.md                     # AI assistant context
├── README.md                     # Project overview
└── .env                          # Environment variables (not in git)
```

---

## Critical Directories

### `/api` - FastAPI Webhook Receiver

**Purpose**: Receives Chatwoot webhooks, publishes to Redis, serves conversation history API.

**Key Files**:
- `main.py` - FastAPI app with CORS, rate limiting, health check
- `routes/chatwoot.py` - Webhook handler with audio transcription
- `routes/conversations.py` - History retrieval endpoints

### `/agent` - LangGraph Orchestrator

**Purpose**: Core AI agent with conversation flow, tools, and state management.

**Key Files**:
- `main.py` - Worker entry point, Redis subscribers
- `graphs/conversation_flow.py` - StateGraph (3 nodes)
- `nodes/conversational_agent.py` - GPT-4.1-mini with tools
- `tools/*.py` - 8 agent tools
- `prompts/__init__.py` - 7-state prompt loading
- `state/schemas.py` - ConversationState (20 fields)

### `/database` - SQLAlchemy + Alembic

**Purpose**: ORM models, migrations, database connection.

**Key Files**:
- `models.py` - 7 tables (Customer, Stylist, Service, Appointment, Policy, ConversationHistory, BusinessHours)
- `connection.py` - Async session management
- `alembic/versions/*.py` - 10 migrations

### `/shared` - Shared Utilities

**Purpose**: Configuration, clients, and cross-cutting concerns.

**Key Files**:
- `config.py` - Pydantic settings with validation
- `redis_client.py` - Connection pool + pub/sub
- `chatwoot_client.py` - API wrapper
- `audio_transcription.py` - Groq Whisper service

### `/admin` - Django Admin Panel

**Purpose**: Web interface for data management.

**Key Files**:
- `core/admin.py` - Model registrations with import/export
- `core/models.py` - Unmanaged models (don't use Django migrations)

---

## Entry Points Summary

| Service | Entry Point | Command |
|---------|-------------|---------|
| API | `api/main.py` | `uvicorn api.main:app` |
| Agent | `agent/main.py` | `python -m agent.main` |
| Archiver | `agent/workers/conversation_archiver.py` | `python -m agent.workers.conversation_archiver` |
| Admin | `admin/atrevete_admin/wsgi.py` | `gunicorn atrevete_admin.wsgi:application` |

---

## Integration Points

### API → Agent (Redis Pub/Sub)

```
api/routes/chatwoot.py
  └─► publish_to_channel("incoming_messages", {...})
        │
        ▼
agent/main.py:subscribe_to_incoming_messages()
  └─► graph.ainvoke(state, config)
        │
        ▼
  └─► publish_to_channel("outgoing_messages", {...})
        │
        ▼
agent/main.py:subscribe_to_outgoing_messages()
  └─► chatwoot.send_message(...)
```

### Agent → Database (SQLAlchemy)

```
agent/tools/customer_tools.py
  └─► get_async_session()
        └─► Customer, Appointment queries

agent/tools/booking_tools.py
  └─► BookingTransaction
        └─► Appointment creation
```

### Agent → Google Calendar

```
agent/tools/calendar_tools.py
  └─► GoogleCalendarService
        └─► List/Create/Delete events
```

---

## File Counts

| Directory | Python Files | Lines (approx) |
|-----------|-------------|----------------|
| api/ | 8 | 800 |
| agent/ | 30 | 4,000 |
| database/ | 4 | 600 |
| shared/ | 8 | 1,200 |
| admin/ | 6 | 800 |
| tests/ | 20+ | 2,000+ |

**Total**: ~70 Python files, ~9,400 lines of code
