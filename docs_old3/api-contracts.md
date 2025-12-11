# API Contracts - Atrévete Bot

## Overview

FastAPI REST API serving as webhook receiver for Chatwoot and providing conversation history endpoints.

**Base URL**: `http://localhost:8000`

## Endpoints

### Health Check

#### `GET /health`

Health check endpoint for Docker health checks and monitoring.

**Checks:**
- Redis connectivity (PING command)
- PostgreSQL connectivity (SELECT 1 query)

**Response 200 OK:**
```json
{
  "status": "healthy",
  "redis": "connected",
  "postgres": "connected"
}
```

**Response 503 Service Unavailable:**
```json
{
  "status": "degraded",
  "redis": "disconnected",
  "postgres": "connected"
}
```

---

### Root

#### `GET /`

Root endpoint.

**Response 200 OK:**
```json
{
  "message": "Atrévete Bot API by zanovix.com - Use /health for health checks"
}
```

---

### Webhooks

#### `POST /webhook/chatwoot/{token}`

Receive and process Chatwoot webhook events.

**Authentication**: Token in URL path must match `CHATWOOT_WEBHOOK_TOKEN` (timing-safe comparison).

**Parameters:**
| Parameter | Type | Location | Description |
|-----------|------|----------|-------------|
| `token` | string | path | Secret webhook token |

**Request Body**: Chatwoot webhook payload (JSON)

**Processing Flow:**
1. Validate token
2. Parse webhook payload
3. Filter: Only `message_created` events
4. Filter: Only `message_type == 0` (incoming messages)
5. Filter: Check `atencion_automatica` custom attribute
6. Handle audio attachments (transcribe via Groq Whisper)
7. Publish to Redis `incoming_messages` channel

**Response 200 OK:**
```json
{
  "status": "received"
}
```

**Response 200 OK (ignored):**
```json
{
  "status": "ignored"
}
```

**Response 401 Unauthorized:**
```json
{
  "detail": "Invalid token"
}
```

**Response 400 Bad Request:**
```json
{
  "error": "Validation error",
  "details": [...]
}
```

---

### Conversations

#### `GET /conversations/{conversation_id}/history`

Retrieve archived conversation messages from PostgreSQL.

**Parameters:**
| Parameter | Type | Location | Default | Description |
|-----------|------|----------|---------|-------------|
| `conversation_id` | string | path | - | Unique conversation identifier |
| `limit` | int | query | 100 | Max messages (1-500) |
| `offset` | int | query | 0 | Pagination offset |

**Response 200 OK:**
```json
{
  "conversation_id": "wa-msg-123",
  "customer_phone": "+34612345678",
  "messages": [
    {
      "role": "user",
      "content": "Hola",
      "timestamp": "2025-10-29T10:00:00+01:00"
    },
    {
      "role": "assistant",
      "content": "¡Hola! Bienvenido...",
      "timestamp": "2025-10-29T10:00:05+01:00"
    }
  ],
  "total_messages": 25,
  "has_more": false
}
```

**Response 404 Not Found:**
```json
{
  "detail": "Conversation wa-msg-123 not found in archive"
}
```

---

#### `GET /conversations/`

List archived conversations with optional filtering.

**Parameters:**
| Parameter | Type | Location | Default | Description |
|-----------|------|----------|---------|-------------|
| `customer_phone` | string | query | null | E.164 format filter |
| `start_date` | datetime | query | null | ISO 8601 start date |
| `end_date` | datetime | query | null | ISO 8601 end date |
| `limit` | int | query | 50 | Max conversations (1-100) |
| `offset` | int | query | 0 | Pagination offset |

**Response 200 OK:**
```json
{
  "conversations": [
    {
      "conversation_id": "wa-msg-123",
      "customer_phone": "+34612345678",
      "created_at": "2025-10-29T10:00:00+01:00",
      "message_count": 25,
      "has_summary": true
    }
  ],
  "total_count": 150,
  "has_more": true
}
```

---

## Middleware

### Rate Limiting

Applied via `RateLimitMiddleware` to all endpoints.

### CORS

Configured for all origins (webhooks from external services):
- `allow_origins`: `["*"]`
- `allow_credentials`: `True`
- `allow_methods`: `["*"]`
- `allow_headers`: `["*"]`

---

## Internal Message Formats

### Redis Channel: `incoming_messages`

Published by API, consumed by Agent.

```json
{
  "conversation_id": "wa-msg-123",
  "customer_phone": "+34612345678",
  "message_text": "Quiero reservar un corte",
  "customer_name": "Pepe García",
  "is_audio_transcription": false,
  "audio_url": null
}
```

### Redis Channel: `outgoing_messages`

Published by Agent, consumed by API for Chatwoot delivery.

```json
{
  "conversation_id": "wa-msg-123",
  "customer_phone": "+34612345678",
  "message": "¡Hola! ¿Qué servicio te gustaría reservar?"
}
```

---

## Error Handling

All endpoints return standard FastAPI error responses:

```json
{
  "detail": "Error message"
}
```

Validation errors include additional details:

```json
{
  "error": "Validation error",
  "details": [
    {
      "loc": ["body", "field_name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```
