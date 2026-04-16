---
name: atrevete-shared
description: >
  Atrévete Bot shared utilities — config, Chatwoot client, Redis, and common helpers.
  Trigger: When working on shared/, config, clients, or utilities.
license: MIT
metadata:
  author: atrevete-bot
  version: "1.0"
  scope: [root, shared]
  auto_invoke:
    - "Working on shared/"
    - "Creating utilities"
    - "Working on config"
    - "Working on Redis"
    - "Working on Chatwoot client"
---

## Shared Structure

```
shared/
├── config.py              # Pydantic Settings (env vars)
├── chatwoot_client.py     # Chatwoot API client
├── redis_client.py        # Redis connection + utilities
├── circuit_breaker.py     # Circuit breaker for external APIs
├── resilient_api.py       # Resilient HTTP client
├── logging_config.py      # Structured logging setup
├── archive_retrieval.py   # Conversation archive retrieval
└── __init__.py            # Package exports
```

## Configuration Access

**CRITICAL:** Always use `shared/config.py`. NEVER use `os.getenv()` directly.

```python
from shared.config import get_settings

settings = get_settings()  # Cached via @lru_cache

# Database
 db_url = settings.DATABASE_URL

# Redis
redis_url = settings.REDIS_URL

# Chatwoot
api_url = settings.CHATWOOT_API_URL
api_token = settings.CHATWOOT_API_TOKEN

# LLM
llm_model = settings.LLM_MODEL  # openai/gpt-5.4-mini
openrouter_key = settings.OPENROUTER_API_KEY

# Resilience
resilience_enabled = settings.RESILIENCE_ENABLED  # True
fallback_model = settings.LLM_FALLBACK_MODEL

# Application
timezone = settings.TIMEZONE  # Europe/Madrid
```

## Chatwoot Client

```python
from shared.chatwoot_client import ChatwootClient

client = ChatwootClient()

# Send text message
await client.send_message(
    conversation_id=123,
    content="¡Hola! ¿En qué puedo ayudarte?",
)

# Send template message (WhatsApp)
await client.send_template(
    conversation_id=123,
    template_name="appointment_confirmation_48h",
    params=[
        {"type": "text", "value": "Maite"},
        {"type": "text", "value": "15 de marzo"},
    ],
)

# Send message to specific inbox
await client.send_message(
    conversation_id=123,
    content="Mensaje de prueba",
    inbox_id=5,
    message_type="outgoing",
    private=False,
)
```

## Redis Client

```python
from shared.redis_client import get_redis_client, RedisClient

redis = get_redis_client()

# Basic operations
await redis.set("key", "value", ex=3600)  # With expiry
value = await redis.get("key")

# Pub/Sub
await redis.publish("channel", "message")

# Streams (used by agent)
await redis.xadd("incoming_messages", {
    "conversation_id": "abc-123",
    "message_text": "Hola",
})

# JSON (RedisJSON module)
await redis.json().set("doc:key", "$", {"field": "value"})
doc = await redis.json().get("doc:key")

# Search (RedisSearch module)
# Requires Redis Stack
```

## Circuit Breaker

```python
from shared.circuit_breaker import circuit_breaker, CircuitBreakerError

@circuit_breaker(
    failure_threshold=5,
    recovery_timeout=30,
    name="openrouter_api"
)
async def call_openrouter(messages: list) -> str:
    """Call OpenRouter with circuit breaker protection."""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": messages},
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

# Usage
try:
    response = await call_openrouter(messages)
except CircuitBreakerError:
    # Circuit is open — fallback logic
    response = await fallback_llm(messages)
```

## Resilient API Client

```python
from shared.resilient_api import ResilientAPIClient, APIError

client = ResilientAPIClient(
    base_url="https://api.example.com",
    timeout=30,
    retries=3,
)

try:
    response = await client.get("/endpoint")
except APIError as e:
    logger.error(f"API call failed: {e}")
    raise
```

## Logging Configuration

```python
from shared.logging_config import get_logger, configure_logging

# Configure once at startup
configure_logging(level=settings.LOG_LEVEL)

# Get logger in modules
logger = get_logger(__name__)

# Usage
logger.info("Processing message", extra={
    "conversation_id": conversation_id,
    "customer_phone": phone,
})
logger.error("Failed to book appointment", exc_info=True)
```

## Timezone Utilities

```python
from datetime import datetime
from zoneinfo import ZoneInfo

def now_madrid() -> datetime:
    """Get current time in Europe/Madrid timezone."""
    return datetime.now(ZoneInfo("Europe/Madrid"))

def format_madrid(dt: datetime) -> str:
    """Format datetime to ISO 8601 string with Madrid timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("Europe/Madrid"))
    return dt.isoformat()
```

## Validation Utilities

```python
import re
from pydantic import validator

def validate_e164(phone: str) -> str:
    """Validate and format E.164 phone number."""
    cleaned = re.sub(r"[^\d+]", "", phone)
    if not cleaned.startswith("+"):
        raise ValueError("Phone must start with + (E.164 format)")
    if not re.match(r"^\+\d{10,15}$", cleaned):
        raise ValueError("Invalid phone number format")
    return cleaned

# Usage in Pydantic
class CustomerCreate(BaseModel):
    phone: str
    
    @validator("phone")
    def check_phone(cls, v):
        return validate_e164(v)
```

## Common Patterns

### Environment-Based Configuration

```python
# .env file (development)
DATABASE_URL=postgresql+asyncpg://atrevete:changeme@localhost:5432/atrevete_db
REDIS_URL=redis://localhost:6379/0
CHATWOOT_API_URL=https://app.chatwoot.com
LLM_MODEL=openai/gpt-5.4-mini
RESILIENCE_ENABLED=true
```

### Async Context Manager

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def managed_resource():
    resource = await create_resource()
    try:
        yield resource
    finally:
        await resource.close()

# Usage
async with managed_resource() as res:
    await res.do_something()
```

### Retry with Backoff

```python
import asyncio
from functools import wraps

def retry_with_backoff(max_retries=3, base_delay=1):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    delay = base_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
            return None
        return wrapper
    return decorator

@retry_with_backoff(max_retries=3)
async def flaky_operation():
    # Might fail sometimes
    pass
```

## Critical Rules

- **ALWAYS** import settings via `shared.config.get_settings()` — NEVER `os.getenv()`
- **ALWAYS** use `get_redis_client()` to get Redis connection (singleton)
- **ALWAYS** use circuit breaker for external API calls
- **ALWAYS** use structured logging with `get_logger(__name__)`
- **ALWAYS** use Europe/Madrid timezone for business logic
- **ALWAYS** validate phone numbers as E.164 format
- **NEVER** hardcode API URLs or credentials
- **NEVER** use sync Redis operations in async code
- **NEVER** log sensitive data (API keys, passwords)

---

**Version**: 1.0
**Last Updated**: March 2026
