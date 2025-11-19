# Atrévete Bot - Project Overview

## Executive Summary

Atrévete Bot is an AI-powered WhatsApp booking assistant for a beauty salon. It handles customer bookings via WhatsApp through Chatwoot, managing appointments across 5 stylists using Google Calendar, and escalating to staff when needed.

## Project Classification

| Attribute | Value |
|-----------|-------|
| **Repository Type** | Monolith |
| **Project Type** | Backend API with AI Agent |
| **Primary Language** | Python 3.11+ |
| **Architecture Pattern** | Service/API-centric with LangGraph orchestration |

## Technology Stack

### Core Technologies

| Category | Technology | Version | Purpose |
|----------|------------|---------|---------|
| **Agent Framework** | LangGraph | 0.6.7+ | Stateful conversation orchestration |
| **LLM Provider** | OpenRouter | - | API gateway (GPT-4.1-mini) |
| **Web Framework** | FastAPI | 0.116.1 | Webhook receiver |
| **ORM** | SQLAlchemy | 2.0+ | Async database access |
| **Database** | PostgreSQL | 15+ | Primary data store |
| **Cache/Messaging** | Redis Stack | Latest | Checkpointing + Pub/Sub |
| **Admin Panel** | Django | 5.0+ | Web administration |

### External Integrations

| Service | Purpose |
|---------|---------|
| **Chatwoot** | WhatsApp message gateway |
| **Google Calendar API** | Stylist availability management |
| **Groq Whisper** | Audio transcription |
| **Langfuse** | LLM monitoring and tracing |

## Architecture Overview

### Simplified Tool-Based Architecture (v3.2)

The system uses a 3-node LangGraph StateGraph:

1. **`process_incoming_message`**: Adds user message to history, ensures customer exists
2. **`conversational_agent`**: GPT-4.1-mini with 8 tools handles ALL conversations
3. **`summarize`**: FIFO windowing (keeps 10 recent messages, summarizes older)

### Request Flow

```
Chatwoot Webhook → FastAPI API → Redis (incoming_messages)
                                        ↓
                               LangGraph Agent
                                        ↓
                               Redis (outgoing_messages)
                                        ↓
                               FastAPI → Chatwoot API → WhatsApp
```

### Available Tools (8 total)

1. **`query_info`** - FAQs, services, hours, policies
2. **`search_services`** - Fuzzy search across 92 services
3. **`manage_customer`** - Customer CRUD operations
4. **`get_customer_history`** - Appointment history retrieval
5. **`check_availability`** - Check specific date availability
6. **`find_next_available`** - Auto-search next available slots
7. **`book`** - Atomic booking transaction
8. **`escalate_to_human`** - Human handoff

## Database Schema

### Core Tables

| Table | Description | Key Fields |
|-------|-------------|------------|
| `customers` | Salon customers | phone (E.164), first_name, last_name, preferred_stylist_id |
| `stylists` | Salon professionals | name, category, google_calendar_id |
| `services` | Service catalog (92 items) | name, category, duration_minutes |
| `appointments` | Booking transactions | customer_id, stylist_id, service_ids, start_time, status |
| `policies` | Business rules/FAQs | key, value (JSONB) |
| `business_hours` | Operating hours | day_of_week, start_hour, end_hour |
| `conversation_history` | Archived conversations | conversation_id, message_role, message_content |

### Enums

- **ServiceCategory**: HAIRDRESSING, AESTHETICS, BOTH
- **AppointmentStatus**: PROVISIONAL, CONFIRMED, COMPLETED, CANCELLED, EXPIRED
- **MessageRole**: USER, ASSISTANT, SYSTEM

## Services Architecture

### Docker Services (6 containers)

| Service | Port | Description |
|---------|------|-------------|
| `postgres` | 5432 | PostgreSQL 15 database |
| `redis` | 6379 | Redis Stack with RedisSearch/RedisJSON |
| `api` | 8000 | FastAPI webhook receiver |
| `admin` | 8001 | Django Admin panel |
| `agent` | - | LangGraph orchestrator |
| `archiver` | - | Conversation archival worker |

## Key Features

### v3.2 Optimizations

- **Dynamic Prompt Injection**: 60-70% token reduction
- **Layered Prompt Architecture**: Cacheable (core + stylists) vs Dynamic (temporal + customer)
- **7-State Booking Flow**: GENERAL → SERVICE_SELECTION → AVAILABILITY_CHECK → CUSTOMER_DATA → BOOKING_CONFIRMATION → BOOKING_EXECUTION → POST_BOOKING
- **In-Memory Stylist Caching**: 10-minute TTL, 90% DB query reduction

### Audio Transcription

- OGG → WAV conversion via ffmpeg
- Groq Whisper transcription
- Confidence scoring with fallback messages

### Conversation Management

- FIFO windowing (10 recent messages)
- Automatic summarization for older messages
- Redis checkpointing (15 min TTL)
- PostgreSQL archival via worker

## Entry Points

| Entry Point | Location | Purpose |
|-------------|----------|---------|
| API Main | `api/main.py` | FastAPI application |
| Agent Main | `agent/main.py` | LangGraph worker |
| Django Admin | `admin/atrevete_admin/wsgi.py` | Admin panel |
| Archiver | `agent/workers/conversation_archiver.py` | Background worker |

## Getting Started

See [Development Guide](./development-guide.md) for setup instructions.

## Related Documentation

- [Architecture Document](./architecture.md)
- [API Contracts](./api-contracts.md)
- [Data Models](./data-models.md)
- [Development Guide](./development-guide.md)
- [Source Tree Analysis](./source-tree-analysis.md)
