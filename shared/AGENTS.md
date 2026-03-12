# Shared Component Guidelines

This directory contains shared utilities, configuration, and clients used across the Atrévete Bot application.

> **Architecture**: Pure utilities with no business logic. Config via Pydantic Settings, singleton clients for Redis/Chatwoot, circuit breaker pattern for resilience.

---

## Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|
| Creating shared utilities | `atrevete-shared` |
| Working with configuration | `atrevete-shared` |
| Working with Redis | `atrevete-shared` |
| Working with Chatwoot client | `atrevete-shared` |
| Writing Python tests | `pytest` |

---

## Directory Structure

```
shared/
├── config.py                  # Pydantic Settings (ALL env vars)
├── chatwoot_client.py         # Chatwoot API client (singleton)
├── redis_client.py            # Redis client (singleton + Streams)
├── circuit_breaker.py         # Circuit breaker pattern
├── logging_config.py          # Structured JSON logging
├── encryption.py              # Fernet encryption utilities
├── business_hours_validator.py
├── stylist_cache.py
├── audio_transcription.py     # Groq Whisper integration
├── audio_conversion.py        # OGG → WAV conversion
├── resilient_api.py           # Resilient HTTP client
├── settings_service.py        # Settings cache/retrieval
├── startup_validator.py       # Startup config validation
├── archive_retrieval.py       # Archive data access
├── cache_signals.py           # Cache invalidation signals
└── __init__.py
```

---

## Architecture

### Config Access Pattern

**CRITICAL**: Access ALL environment variables through `shared/config.py`. NEVER use `os.getenv()` directly.

```python
# ❌ WRONG - don't do this
import os
db_url = os.getenv("DATABASE_URL")

# ✅ CORRECT - use this
from shared.config import get_settings
settings = get_settings()
db_url = settings.DATABASE_URL
```

### Pydantic Settings

```python
# shared/config.py
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://..."
    REDIS_URL: str = "redis://redis:6379/0"
    CHATWOOT_API_TOKEN: str = ""
    # ... 40+ more settings

    class Config:
        env_file = ".env"
        case_sensitive = True

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

**Benefits**:
- Type-safe configuration
- Validation on startup
- Caching (loaded once)
- Documentation via Field descriptions

---

## Config Access Patterns

### Basic Usage

```python
from shared.config import get_settings

settings = get_settings()

# Database
print(settings.DATABASE_URL)

# Redis
print(settings.REDIS_URL)

# Chatwoot
print(settings.CHATWOOT_API_URL)
```

### Property-Based Logic

```python
class Settings(BaseSettings):
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""

    @property
    def google_oauth_configured(self) -> bool:
        """True if OAuth2 credentials are set."""
        return bool(self.GOOGLE_OAUTH_CLIENT_ID and self.GOOGLE_OAUTH_CLIENT_SECRET)
```

---

## Chatwoot Client Usage

### Singleton Pattern

```python
# shared/chatwoot_client.py
class ChatwootClient:
    def __init__(self):
        settings = get_settings()
        self.api_url = settings.CHATWOOT_API_URL.rstrip("/")
        self.api_token = settings.CHATWOOT_API_TOKEN
        self.headers = {
            "api_access_token": self.api_token,
            "Content-Type": "application/json",
        }

# Usage
from shared.chatwoot_client import ChatwootClient

client = ChatwootClient()
await client.send_message(phone="+34612345678", message="Hola!")
```

### Rate Limiting

```python
async def _acquire_rate_limit(self) -> None:
    """Per-minute rate limiting via Redis."""
    limit = get_settings().CHATWOOT_RATE_LIMIT_PER_MINUTE
    if limit == 0:
        return

    redis = get_redis_client()
    now = datetime.now(ZoneInfo("Europe/Madrid"))
    key = f"chatwoot:rate_limit:{now.strftime('%Y%m%d_%H%M')}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 60)
    if count > limit:
        await asyncio.sleep(60 - now.second)
```

---

## Redis Patterns

### Singleton Client

```python
# shared/redis_client.py
from functools import lru_cache
import redis.asyncio as redis

@lru_cache
def get_redis_client() -> redis.Redis:
    settings = get_settings()
    return redis.from_url(
        settings.REDIS_URL,
        max_connections=20,
        decode_responses=True,
        retry_on_timeout=True,
        health_check_interval=30,
    )
```

### Redis Streams (Message Queue)

```python
# Add to stream (producer)
from shared.redis_client import add_to_stream, INCOMING_STREAM

stream_msg_id = await add_to_stream(
    INCOMING_STREAM,
    {"conversation_id": "123", "message": "Hola"}
)

# Read from stream (consumer)
from shared.redis_client import read_from_stream, CONSUMER_GROUP

messages = await read_from_stream(
    stream=INCOMING_STREAM,
    group=CONSUMER_GROUP,
    consumer="agent-1",
    count=1,
    block_ms=5000,
)

# Acknowledge
from shared.redis_client import acknowledge_message

await acknowledge_message(INCOMING_STREAM, CONSUMER_GROUP, message_id)
```

### Pub/Sub (Legacy)

```python
from shared.redis_client import publish_to_channel

await publish_to_channel("incoming_messages", {"data": "value"})
```

---

## Circuit Breaker Pattern

### Pre-Configured Breakers

```python
# shared/circuit_breaker.py
from shared.circuit_breaker import openrouter_breaker, calendar_breaker, chatwoot_breaker

# Usage
async def call_llm():
    return await openrouter_breaker.call_async(_actual_llm_call)
```

### Creating Custom Breakers

```python
from shared.circuit_breaker import get_circuit_breaker

my_breaker = get_circuit_breaker(
    name="my_service",
    fail_max=5,
    reset_timeout=30,
)

result = await my_breaker.call_async(my_async_function)
```

### Decorator Pattern

```python
from shared.circuit_breaker import with_circuit_breaker, openrouter_breaker

@with_circuit_breaker(openrouter_breaker)
async def call_external_api():
    return await fetch_data()
```

### States

- **CLOSED**: Normal operation, requests pass through
- **OPEN**: Service is down, requests fail fast
- **HALF_OPEN**: Testing if service recovered

---

## Common Utilities

### Business Hours Validation

```python
from shared.business_hours_validator import is_business_hours, get_next_opening

if not await is_business_hours(datetime.now(ZoneInfo("Europe/Madrid"))):
    next_open = await get_next_opening()
    return f"We're closed. Next opening: {next_open}"
```

### Stylist Cache

```python
from shared.stylist_cache import get_stylist_cache, refresh_stylist_cache

# Get cached stylists
stylists = await get_stylist_cache()

# Force refresh
await refresh_stylist_cache()
```

### Audio Transcription

```python
from shared.audio_transcription import get_transcription_service

service = get_transcription_service()
text, confidence = await service.transcribe_audio(wav_file_path)
```

### Encryption

```python
from shared.encryption import encrypt_value, decrypt_value

encrypted = encrypt_value("sensitive data")
decrypted = decrypt_value(encrypted)
```

---

## Critical Rules

1. **ALWAYS use `get_settings()`** — NEVER use `os.getenv()` directly
2. **ALWAYS cache Redis client** — Use `@lru_cache` or module-level singleton
3. **ALWAYS use circuit breakers** for external API calls
4. **ALWAYS use async Redis** — `redis.asyncio`, not sync client
5. **NEVER store credentials in code** — Use env vars via Settings
6. **NEVER create multiple Redis connections** — Always use `get_redis_client()`
7. **NEVER ignore circuit breaker state** — Handle `CircuitBreakerError`

---

## Startup Validation

```python
# shared/startup_validator.py
async def validate_startup_config(require_google_calendar: bool = True):
    """Validate critical config at startup."""
    settings = get_settings()

    # Check required env vars
    if not settings.DATABASE_URL:
        raise StartupValidationError("DATABASE_URL is required")

    # Check Google Calendar credentials
    if require_google_calendar and not settings.GOOGLE_CALENDAR_IDS:
        raise StartupValidationError("GOOGLE_CALENDAR_IDS is required")

    # Test Redis connection
    try:
        redis = get_redis_client()
        await redis.ping()
    except Exception as e:
        raise StartupValidationError(f"Redis connection failed: {e}")
```

---

## Resources

- [Root AGENTS.md](../AGENTS.md) — Repository governance
- [atrevete-shared skill](../skills/atrevete-shared/SKILL.md) — Detailed patterns
- `shared/config.py` — All configuration settings
- `shared/redis_client.py` — Redis client and Streams
- `shared/chatwoot_client.py` — Chatwoot API client
- `shared/circuit_breaker.py` — Resilience patterns

**Last Updated**: March 2026

### Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|
| Creating utilities | `atrevete-shared` |
| Working on Chatwoot client | `atrevete-shared` |
| Working on Redis | `atrevete-shared` |
| Working on config | `atrevete-shared` |
| Working on shared/ | `atrevete-shared` |
