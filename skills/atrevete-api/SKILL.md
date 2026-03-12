---
name: atrevete-api
description: >
  Atrévete Bot FastAPI patterns for webhook handling and Chatwoot integration.
  Trigger: When working on API routes, FastAPI, Chatwoot webhooks, or services.
license: MIT
metadata:
  author: atrevete-bot
  version: "1.0"
  scope: [root, api]
  auto_invoke:
    - "Working on API routes"
    - "Working on FastAPI"
    - "Creating/modifying services"
    - "Working on Chatwoot"
    - "Creating webhooks"
---

## API Structure

```
api/
├── main.py                 # FastAPI app factory
├── models/
│   └── chatwoot.py         # Chatwoot webhook Pydantic models
├── routes/
│   ├── health.py           # Health check endpoint
│   ├── chatwoot.py         # Chatwoot webhook handler
│   └── admin.py            # Admin API endpoints
├── middleware/
│   ├── cors.py             # CORS configuration
│   ├── logging.py          # Request logging
│   └── rate_limit.py       # Rate limiting
└── services/
    ├── chatwoot_service.py # Chatwoot API client wrapper
    └── admin_service.py    # Admin business logic
```

## FastAPI App Factory

```python
from fastapi import FastAPI
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await initialize_redis_indexes()
    yield
    # Shutdown
    await close_redis_connection()

app = FastAPI(
    title="Atrévete Bot API",
    version="1.0.0",
    lifespan=lifespan,
)

# Register routers
app.include_router(health.router, tags=["Health"])
app.include_router(chatwoot.router, prefix="/webhook", tags=["Webhooks"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
```

## Chatwoot Webhook Handler

```python
import hmac
from fastapi import APIRouter, Request, HTTPException, Depends
from api.models.chatwoot import ChatwootWebhook
from shared.config import get_settings

router = APIRouter()

@router.post("/chatwoot/{token}")
async def chatwoot_webhook(
    token: str,
    request: Request,
):
    settings = get_settings()
    
    # 1. Timing-safe token validation
    if not hmac.compare_digest(token, settings.CHATWOOT_WEBHOOK_TOKEN):
        raise HTTPException(403, "Invalid token")
    
    # 2. Parse payload
    payload = await request.json()
    webhook = ChatwootWebhook.model_validate(payload)
    
    # 3. Filter events (only incoming messages)
    if webhook.event != "message_created" or webhook.message_type != 0:
        return {"status": "ignored"}
    
    # 4. Idempotency check (Redis SETNX)
    redis = get_redis_client()
    key = f"webhook:{webhook.conversation_id}:{webhook.id}"
    if not await redis.setnx(key, "1"):
        return {"status": "duplicate"}
    await redis.expire(key, 300)  # 5 min TTL
    
    # 5. Queue to Redis Streams
    await redis.xadd("incoming_messages", {
        "conversation_id": str(webhook.conversation_id),
        "customer_phone": webhook.sender.phone_number,
        "message_text": webhook.content or "",
        "timestamp": datetime.now(UTC).isoformat(),
    })
    
    return {"status": "queued"}
```

## Pydantic Models

```python
from pydantic import BaseModel, Field, validator
from typing import Literal

class ChatwootSender(BaseModel):
    id: int
    name: str
    phone_number: str | None = None
    
    @validator('phone_number')
    def validate_e164(cls, v):
        if v and not v.startswith('+'):
            raise ValueError('Phone must be E.164 format')
        return v

class ChatwootWebhook(BaseModel):
    event: Literal["message_created", "conversation_created"]
    message_type: Literal[0, 1, 2, 3]  # 0=incoming, 1=outgoing
    id: int
    content: str | None
    conversation_id: int
    sender: ChatwootSender
    created_at: str

class HealthResponse(BaseModel):
    status: str
    version: str
    services: dict[str, str]
```

## Service Layer Pattern

```python
from database.connection import get_async_session

class ChatwootService:
    def __init__(self):
        self.settings = get_settings()
        self.client = ChatwootClient()
    
    async def send_message(
        self,
        conversation_id: int,
        content: str,
        message_type: str = "outgoing",
    ) -> dict:
        """Send message to Chatwoot conversation."""
        url = f"{self.settings.CHATWOOT_API_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers={"Authorization": f"Bearer {self.settings.CHATWOOT_API_TOKEN}"},
                json={"content": content, "message_type": message_type},
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
```

## Async Patterns

```python
# Use async context manager for DB sessions
from database.connection import get_async_session

@router.get("/admin/appointments")
async def list_appointments():
    async for session in get_async_session():
        result = await session.execute(select(Appointment))
        appointments = result.scalars().all()
        break  # Important: break after first iteration
    return {"appointments": appointments}
```

## Error Handling

```python
from fastapi import HTTPException
from shared.resilient_api import APIError

@router.post("/admin/book")
async def admin_book_appointment(data: BookingRequest):
    try:
        appointment = await booking_service.create(data)
        return {"success": True, "appointment_id": appointment.id}
    except ValidationError as e:
        raise HTTPException(400, detail=str(e))
    except APIError as e:
        raise HTTPException(502, detail=f"External API error: {e}")
    except Exception as e:
        logger.exception("Unexpected error")
        raise HTTPException(500, detail="Internal server error")
```

## CORS Configuration

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
```

## Critical Rules

- **ALWAYS** use `async def` for routes
- **ALWAYS** use Pydantic for request/response models
- **ALWAYS** use timing-safe comparison (`hmac.compare_digest`) for tokens
- **ALWAYS** use idempotency keys for webhooks (Redis SETNX)
- **ALWAYS** validate Chatwoot webhook token
- **NEVER** put business logic in routes (use services)
- **NEVER** use raw SQL (use SQLAlchemy ORM)
- **NEVER** expose internal errors to clients

## Chatwoot API Client

```python
from shared.chatwoot_client import ChatwootClient

client = ChatwootClient()

# Send text message
await client.send_message(
    conversation_id=123,
    content="¡Hola! ¿En qué puedo ayudarte?",
)

# Send template message
await client.send_template(
    conversation_id=123,
    template_name="appointment_confirmation",
    params=[{"type": "text", "value": "Maite"}],
)
```

---

**Version**: 1.0
**Last Updated**: March 2026
