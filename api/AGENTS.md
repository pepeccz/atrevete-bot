# API Component Guidelines

This directory contains the Atrévete Bot FastAPI backend.

> **Architecture**: FastAPI + Uvicorn with async route handlers, Chatwoot webhook processing, and JWT-secured admin endpoints.

---

## Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|
| Creating/modifying API routes | `atrevete-api` |
| Creating FastAPI services | `atrevete-api` |
| Working with Pydantic models | `atrevete-api` |
| Working with Chatwoot webhooks | `atrevete-api` |
| Writing Python tests | `pytest` |

---

## Directory Structure

```
api/
├── main.py                      # FastAPI app factory, router registration
├── routes/
│   ├── chatwoot.py             # Chatwoot webhook handler (Redis Streams)
│   ├── admin.py                # Admin panel API (appointments, customers, stylists)
│   ├── conversations.py        # Conversation history endpoints
│   ├── settings.py             # System settings management
│   ├── google_oauth.py         # Google OAuth2 flow
│   └── system.py               # Health checks, logs
├── services/
│   └── conversation_delete_service.py
├── models/
│   └── chatwoot_webhook.py     # Pydantic webhook schemas
└── middleware/
    └── rate_limiting.py        # Rate limiting middleware
```

---

## Architecture

### FastAPI + Uvicorn Stack

- **Framework**: FastAPI 0.116.1 with Pydantic 2.x validation
- **Server**: Uvicorn 0.30.0+ with async workers
- **Database**: Async SQLAlchemy 2.0+ with asyncpg driver
- **Cache/Queue**: Redis (RedisSearch, RedisJSON, Streams)

### Router Registration

```python
# api/main.py
app = FastAPI(title="Atrévete Bot API", version="1.0.0")

# Include routers
app.include_router(chatwoot.router, prefix="/webhook", tags=["webhooks"])
app.include_router(conversations.router, tags=["conversations"])
app.include_router(admin.router, tags=["admin"])
app.include_router(google_oauth.router, tags=["google-oauth"])
app.include_router(settings.router, tags=["settings"])
app.include_router(system.router, tags=["system"])
```

---

## Route Patterns

### Async Route Handler

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter()

class MyRequest(BaseModel):
    name: str
    phone: str

class MyResponse(BaseModel):
    id: str
    message: str

@router.post("/endpoint", response_model=MyResponse)
async def my_endpoint(
    request: MyRequest,
    session: AsyncSession = Depends(get_async_session),
) -> MyResponse:
    """Endpoint description."""
    # Business logic here
    return MyResponse(id="123", message="Success")
```

### Pydantic with Validators

```python
from pydantic import BaseModel, Field, validator

class CustomerCreate(BaseModel):
    phone: str = Field(..., min_length=10, max_length=20)
    first_name: str = Field(..., min_length=1, max_length=100)

    @validator('phone')
    def validate_phone_e164(cls, v):
        if not v.startswith('+'):
            raise ValueError('Phone must be in E.164 format (start with +)')
        return v
```

---

## Chatwoot Webhook Handling

### Authentication

Token-based authentication via URL path parameter:

```python
@router.post("/chatwoot/{token}")
async def receive_chatwoot_webhook(
    request: Request,
    token: str,
) -> JSONResponse:
    # Timing-safe comparison
    if not hmac.compare_digest(token, settings.CHATWOOT_WEBHOOK_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid token")
    # ... process webhook
```

### Idempotency

Redis-based duplicate detection (5-minute TTL):

```python
IDEMPOTENCY_TTL = 300  # 5 minutes
IDEMPOTENCY_PREFIX = "idempotency:chatwoot:"

async def check_and_set_idempotency(message_id: int) -> bool:
    """Returns True if duplicate, False if new."""
    client = get_redis_client()
    key = f"{IDEMPOTENCY_PREFIX}{message_id}"
    was_set = await client.setnx(key, "1")
    if was_set:
        await client.expire(key, IDEMPOTENCY_TTL)
        return False  # New message
    return True  # Duplicate
```

### Audio Processing

WhatsApp audio messages are transcribed using Groq Whisper:

```python
# 1. Download audio from Chatwoot
async with aiohttp.ClientSession() as session:
    async with session.get(audio_url) as response:
        audio_data = await response.read()

# 2. Convert OGG → WAV
wav_path = await convert_ogg_to_wav(ogg_path)

# 3. Transcribe with Groq
message_text, confidence = await transcription_service.transcribe_audio(wav_path)
```

---

## Async Patterns

### Database Sessions

```python
from database.connection import get_async_session
from sqlalchemy import select

@router.get("/customers")
async def list_customers(
    session: AsyncSession = Depends(get_async_session),
):
    result = await session.execute(select(Customer))
    customers = result.scalars().all()
    return customers
```

### Redis Operations

```python
from shared.redis_client import get_redis_client

async def cache_value(key: str, value: str, ttl: int = 3600):
    redis = get_redis_client()
    await redis.setex(key, ttl, value)
```

---

## Security Patterns

### CORS Configuration

```python
# Add CORS middleware (executes FIRST)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
```

### Rate Limiting

Custom middleware with Redis backing (for multi-instance):

```python
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Rate limit by IP + endpoint
    key = f"rate_limit:{request.client.host}:{request.url.path}"
    # ... Redis-based sliding window
```

### Validation Error Handling

```python
@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    return JSONResponse(
        status_code=400,
        content={"error": "Validation error", "details": exc.errors()},
    )
```

---

## Critical Rules

1. **ALWAYS use `async def`** for route handlers
2. **ALWAYS use Pydantic models** for request/response validation
3. **ALWAYS use `Depends(get_async_session)`** for database access
4. **ALWAYS validate file types** before processing
5. **ALWAYS use timing-safe comparison** for tokens (`hmac.compare_digest`)
6. **NEVER put business logic in routes** — use services
7. **NEVER trust user input** — validate everything
8. **NEVER use raw SQL** — use SQLAlchemy ORM
9. **NEVER expose internal error details** to users

---

## Health Check

```python
@app.get("/health")
async def health_check() -> JSONResponse:
    """Check Redis and PostgreSQL connectivity."""
    health_status = {"status": "healthy", "redis": "unknown", "postgres": "unknown"}
    status_code = 200

    # Check Redis
    try:
        redis_client = get_redis_client()
        await redis_client.ping()
        health_status["redis"] = "connected"
    except Exception:
        health_status["redis"] = "disconnected"
        health_status["status"] = "degraded"
        status_code = 503

    # Check PostgreSQL
    try:
        async with get_async_session() as session:
            await session.execute(text("SELECT 1"))
            health_status["postgres"] = "connected"
    except Exception:
        health_status["postgres"] = "disconnected"
        health_status["status"] = "degraded"
        status_code = 503

    return JSONResponse(status_code=status_code, content=health_status)
```

---

## Resources

- [Root AGENTS.md](../AGENTS.md) — Repository governance
- [atrevete-api skill](../skills/atrevete-api/SKILL.md) — Detailed patterns
- `api/routes/chatwoot.py` — Webhook implementation
- `api/main.py` — App factory and middleware

**Last Updated**: March 2026

### Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|
| Creating webhooks | `atrevete-api` |
| Creating/modifying services | `atrevete-api` |
| Working on API routes | `atrevete-api` |
| Working on Chatwoot | `atrevete-api` |
| Working on FastAPI | `atrevete-api` |
