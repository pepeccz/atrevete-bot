# Development Guide - Atrévete Bot

## Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Git

## Environment Setup

### 1. Clone and Create Virtual Environment

```bash
# Create virtual environment (Python 3.11+ required)
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with real API keys
# Required variables:
# - OPENROUTER_API_KEY
# - CHATWOOT_API_URL
# - CHATWOOT_API_ACCESS_TOKEN
# - CHATWOOT_WEBHOOK_TOKEN
# - CHATWOOT_ACCOUNT_ID
# - GOOGLE_SERVICE_ACCOUNT_KEY (or service-account-key.json file)
# - POSTGRES_PASSWORD (min 16 chars)
# - LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY (optional)
```

### 3. Google Calendar Credentials

Place `service-account-key.json` in project root. This file is mounted as read-only volume in Docker.

---

## Running Services

### Start All Services

```bash
# Start all services (PostgreSQL, Redis, API, Agent, Archiver, Admin)
docker-compose up -d

# Check service health
docker-compose ps

# View logs
docker-compose logs -f api      # FastAPI webhook receiver
docker-compose logs -f agent    # LangGraph orchestrator
docker-compose logs -f archiver # Conversation archival worker
docker-compose logs -f admin    # Django Admin panel

# Restart specific service
docker-compose restart api
```

### Service URLs

| Service | URL | Credentials |
|---------|-----|-------------|
| API | http://localhost:8000 | - |
| Django Admin | http://localhost:8001/admin | admin / admin123 |
| pgAdmin | http://localhost:5050 | admin@example.com / admin |

### Verify Google Calendar Access

```bash
# Check if service account key is accessible inside agent container
docker exec atrevete-agent ls -la /app/service-account-key.json
```

---

## Database Operations

### Migrations with Alembic

```bash
# Create new migration
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/alembic revision --autogenerate -m "description"

# Apply migrations
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/alembic upgrade head

# Check current version
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/alembic current

# Rollback one migration
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/alembic downgrade -1
```

### Direct Database Access

```bash
# Access PostgreSQL directly
PGPASSWORD="changeme_min16chars_secure_password" psql -h localhost -U atrevete -d atrevete_db

# Access via Docker
docker exec -it atrevete-postgres psql -U atrevete -d atrevete_db
```

---

## Testing

### Run Tests

```bash
# Run all tests with coverage (minimum 85% required)
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/pytest

# Run unit tests only
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/pytest tests/unit/

# Run integration tests
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/pytest tests/integration/

# Run specific test file
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/pytest tests/unit/test_customer_tools.py

# Run specific test with verbose output
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/pytest tests/unit/test_customer_tools.py::test_create_customer -v
```

### Test Organization

- `tests/unit/` - Individual function/tool tests with mocks
- `tests/integration/` - Component interaction tests
- `tests/integration/scenarios/` - Complete conversation flows
- `tests/mocks/` - Shared mock objects

### Coverage Requirements

- Minimum: 85%
- Excluded: `admin/*`, migrations, tests

---

## Code Quality

### Formatting

```bash
# Format code (line length: 100, Python 3.11)
black .
```

### Linting

```bash
# Lint code
ruff check .
```

### Type Checking

```bash
# Type check (strict for shared/ and database/, relaxed for agent/ and admin/)
mypy .
```

---

## Key Development Patterns

### Configuration Access

**CRITICAL**: Always use `shared/config.py` for environment variables.

```python
# CORRECT
from shared.config import get_settings
settings = get_settings()  # Cached via @lru_cache
api_key = settings.OPENROUTER_API_KEY

# WRONG - Never do this
import os
api_key = os.getenv("OPENROUTER_API_KEY")  # DON'T DO THIS
```

### State Updates

State is immutable. Nodes must return new dicts:

```python
from agent.state.helpers import add_message

async def my_node(state: ConversationState) -> dict[str, Any]:
    # CORRECT: Use helper to return new state dict
    return add_message(state, "assistant", "Response text")

    # WRONG: Never mutate state directly
    # state["messages"].append(...)  # DON'T DO THIS
```

### Message Format

Always use `add_message()` helper:

```python
# Message format (role is "user" or "assistant", NEVER "human" or "ai")
{
    "role": "user" | "assistant",
    "content": str,
    "timestamp": str  # ISO 8601 in Europe/Madrid timezone
}
```

### Database Sessions

Use async context manager:

```python
from database.connection import get_async_session

async with get_async_session() as session:
    result = await session.execute(query)
    await session.commit()
```

### Chatwoot API

Remove trailing slash from URL:

```python
settings = get_settings()
api_url = settings.CHATWOOT_API_URL.rstrip('/')
endpoint = f"{api_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
```

---

## Django Admin

### Access

- URL: http://localhost:8001/admin
- Username: admin
- Password: admin123

### Features

- **Customers**: Full CRUD, export/import (CSV, Excel, JSON)
- **Stylists**: Manage profiles, Google Calendar integration
- **Services**: Service catalog (92 items)
- **Appointments**: View/edit with Google Calendar sync
- **Policies**: FAQ responses and business policies
- **Conversation History**: View customer logs
- **Business Hours**: Configure opening hours

### Important Notes

- Django Admin models have `managed=False` to prevent interference with Alembic migrations
- Database schema changes must be done via Alembic migrations
- Django only manages its own auth tables

### Shell Access

```bash
# Access Django shell
docker exec atrevete-admin python manage.py shell

# Create additional superuser
docker exec atrevete-admin python manage.py shell -c \
  "from django.contrib.auth import get_user_model; User = get_user_model(); \
   User.objects.create_superuser('username', 'email@example.com', 'password')"
```

---

## Troubleshooting

### Google Calendar API Errors

**Error**: `FileNotFoundError: service-account-key.json`

**Solution**:
1. Verify file exists: `ls -la /home/pepe/atrevete-bot/service-account-key.json`
2. Verify docker-compose.yml has volume mount
3. Recreate container: `docker-compose up -d agent`
4. Verify access: `docker exec atrevete-agent ls -la /app/service-account-key.json`

### Checkpoint Corruption

**Symptoms**: Graph invocation fails, fallback message sent

**Solution**:
1. Check Redis connectivity
2. Clear corrupted checkpoint: `redis-cli DEL checkpoint:{thread_id}`
3. Restart agent service

### Audio Transcription Failures

**Error**: Groq rate limit / API error

**Handling**: System sends fallback message asking user to type instead

### Database Connection Issues

**Check**:
```bash
# Test PostgreSQL
PGPASSWORD="..." psql -h localhost -U atrevete -d atrevete_db -c "SELECT 1"

# Test Redis
docker exec atrevete-redis redis-cli ping
```

---

## Project Structure

```
atrevete-bot/
├── api/                    # FastAPI webhook receiver
│   ├── main.py            # Application entry point
│   ├── routes/            # API endpoints
│   ├── models/            # Pydantic models
│   └── middleware/        # Rate limiting
├── agent/                  # LangGraph orchestrator
│   ├── main.py            # Worker entry point
│   ├── graphs/            # StateGraph definitions
│   ├── nodes/             # Graph nodes
│   ├── tools/             # Agent tools (8 total)
│   ├── prompts/           # System prompts
│   ├── state/             # State schema + helpers
│   ├── workers/           # Background workers
│   └── transactions/      # Booking transaction
├── database/               # SQLAlchemy models + Alembic
│   ├── models.py          # ORM models
│   ├── connection.py      # Database connection
│   ├── alembic/           # Migrations
│   └── seeds/             # Seed data
├── shared/                 # Shared utilities
│   ├── config.py          # Settings (pydantic-settings)
│   ├── redis_client.py    # Redis connection
│   ├── chatwoot_client.py # Chatwoot API client
│   └── logging_config.py  # Logging setup
├── admin/                  # Django Admin interface
├── tests/                  # Test suite
├── docker/                 # Dockerfiles
├── docs/                   # Generated documentation
└── docker-compose.yml      # Service orchestration
```

---

## Best Practices

### Security

- Never commit `.env` or `service-account-key.json`
- Use test keys for development
- Database passwords: minimum 16 characters
- Webhook tokens: timing-safe comparison

### Code Style

- Line length: 100 characters
- Type hints: Required for shared/ and database/
- Docstrings: Google style

### Git Workflow

- Main branch: master
- Feature branches for development
- Run tests before committing
- Keep commits atomic
