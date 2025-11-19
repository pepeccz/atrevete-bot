# Architecture

## Executive Summary

Arquitectura de mejoras incrementales para Atrévete Bot v3.2, un asistente de reservas por WhatsApp para peluquería. Este documento define las decisiones arquitectónicas para completar el sistema de agendamiento y añadir el ciclo completo de confirmación/recordatorio/cancelación automática.

El enfoque es **brownfield**: extender la arquitectura existente (LangGraph + FastAPI + PostgreSQL + Redis) con un nuevo worker de recordatorios, 3 herramientas adicionales para el agente, y campos de tracking para el patrón de confirmación asíncrona.

**Cambios principales:**
- Worker separado `appointment_reminder` para confirmaciones 48h y recordatorios 24h
- Renombrar estados: CONFIRMED→PENDING (agendada), nuevo CONFIRMED (verificada)
- Herramientas: `cancel_appointment`, `reschedule_appointment`, `get_my_appointments`
- Sincronización Calendar en tiempo real con emojis visuales (🟡/🟢)

## Decision Summary

| Category | Decision | Version | Affects FRs | Rationale |
| -------- | -------- | ------- | ----------- | --------- |
| Background Jobs | Worker separado `appointment_reminder` | N/A | FR13-FR20 | Separación de responsabilidades, escalable independientemente |
| Integración WhatsApp | API de Chatwoot Templates | Chatwoot API v1 | FR13, FR17, FR20 | Centraliza comunicación, trazabilidad completa |
| Modelo de Datos | Renombrar CONFIRMED→PENDING, nuevo CONFIRMED | Alembic migration | FR9, FR10, FR15, FR16 | Terminología estándar de la industria |
| Estructura de Código | Archivo único `appointment_management_tools.py` | N/A | FR21-FR28 | Cohesión funcional, sigue patrón existente |
| Integración Externa | Sincronización Calendar en tiempo real | Google Calendar API v3 | FR10, FR15, FR19, FR27 | Visibilidad inmediata para estilistas |
| Modelo de Datos | Campos timestamp dedicados para tracking | Alembic migration | FR13, FR17, FR18 | Queries simples, auditoría clara |
| Modelo de Datos | Campo `chatwoot_conversation_id` en customers | Alembic migration | FR13, FR17, FR20 | Worker necesita conversation_id para enviar templates |

## Project Structure

```
atrevete-bot/
├── agent/
│   ├── tools/
│   │   ├── appointment_management_tools.py  # NUEVO: cancel, reschedule, get_my
│   │   ├── booking_tools.py                 # MODIFICAR: emojis Calendar
│   │   ├── availability_tools.py
│   │   ├── customer_tools.py
│   │   ├── info_tools.py
│   │   └── search_services.py
│   ├── prompts/
│   │   ├── core.md
│   │   ├── step1_general.md
│   │   ├── step2_availability.md
│   │   ├── step3_customer.md
│   │   ├── step4_confirmation.md
│   │   ├── step4_booking.md
│   │   └── step5_post_booking.md            # MODIFICAR: instrucciones confirmación
│   ├── workers/
│   │   ├── conversation_archiver.py
│   │   └── appointment_reminder.py          # NUEVO: worker 48h/24h
│   ├── graphs/
│   │   └── conversation_flow.py
│   ├── nodes/
│   │   └── conversational_agent.py
│   └── state/
│       ├── schemas.py
│       └── helpers.py
├── api/
│   ├── main.py
│   └── routes/
│       └── chatwoot.py
├── database/
│   ├── models.py                            # MODIFICAR: enum, timestamps
│   ├── connection.py
│   └── seed.py
├── shared/
│   ├── config.py
│   ├── logging.py
│   ├── redis_client.py
│   └── chatwoot_client.py                   # MODIFICAR: send_template()
├── admin/
│   └── atrevete_admin/
├── docker/
│   ├── Dockerfile.api
│   ├── Dockerfile.agent
│   ├── Dockerfile.admin
│   └── Dockerfile.reminder                  # NUEVO
├── tests/
│   ├── unit/
│   │   └── test_appointment_management.py   # NUEVO
│   └── integration/
│       └── test_reminder_worker.py          # NUEVO
├── docker-compose.yml                       # MODIFICAR: servicio reminder
├── requirements.txt
└── alembic/
    └── versions/                            # NUEVO: migration para timestamps/enum
```

## FR Category to Architecture Mapping

| FR Category | Componentes Afectados | Archivos Clave |
|-------------|----------------------|----------------|
| **Agendamiento (FR1-FR12)** | Tools, Models, Prompts | `booking_tools.py`, `models.py`, `step*.md` |
| **Confirmación/Recordatorios (FR13-FR20)** | Worker, Chatwoot, Models | `appointment_reminder.py`, `chatwoot_client.py` |
| **Cancelación/Reagendamiento (FR21-FR28)** | Tools, Models | `appointment_management_tools.py` |
| **Consultas/Info (FR29-FR32)** | Sin cambios | `info_tools.py`, `query_info` |
| **Escalamiento (FR33-FR37)** | Sin cambios | `escalate_to_human` tool |
| **UX (FR38-FR42)** | Prompts | `step*.md` (listas numeradas) |

## Integration Points

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Chatwoot API   │◄────┤  API (FastAPI)   │────►│  Redis Pub/Sub  │
│  - Webhooks     │     │  - Recibe msgs   │     │  - incoming_msg │
│  - Send msgs    │     │  - Health check  │     │  - outgoing_msg │
│  - Templates    │     └──────────────────┘     └────────┬────────┘
└────────┬────────┘                                       │
         │                                                ▼
         │            ┌──────────────────┐     ┌─────────────────┐
         │            │  Agent Worker    │◄────┤  LangGraph      │
         │            │  - Conversación  │     │  - 11 tools     │
         │            │  - Tool calling  │     │  - State mgmt   │
         │            └──────────────────┘     └─────────────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Reminder       │────►│  PostgreSQL      │◄────┤  Google Cal     │
│  Worker (NUEVO) │     │  - appointments  │     │  - Create event │
│  - 48h confirm  │     │  - customers     │     │  - Update emoji │
│  - 24h remind   │     │  - timestamps    │     │  - Delete event │
│  - Auto-cancel  │     └──────────────────┘     └─────────────────┘
└─────────────────┘
```

## Technology Stack Details

### Core Technologies

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.11+ | Runtime |
| LangGraph | 0.6.7+ | Agent orchestration |
| FastAPI | 0.116.1 | API framework |
| SQLAlchemy | 2.0+ | ORM (asyncpg driver) |
| Alembic | 1.13+ | Migrations |
| PostgreSQL | 15+ | Primary database |
| Redis Stack | Latest | Checkpointing + Pub/Sub |
| OpenRouter | API v1 | LLM gateway (GPT-4.1-mini) |

### New Dependencies

| Dependency | Purpose |
|------------|---------|
| tenacity | Retries para Chatwoot/Calendar API |
| (existing) | No se requieren nuevas dependencias |

### External Services

| Service | Purpose | Auth Method |
|---------|---------|-------------|
| Chatwoot | WhatsApp gateway + Templates | API Key |
| Google Calendar | Stylist availability | Service Account |
| OpenRouter | LLM API | API Key |
| Groq | Audio transcription | API Key |
| Langfuse | LLM monitoring | API Key |

## Novel Pattern: Async Confirmation Loop

### Purpose

Patrón para gestionar confirmaciones de citas con:
- Envío proactivo de mensaje (plantilla WhatsApp)
- Espera de respuesta con timeout (24h)
- Detección de respuesta en contexto conversacional
- Acción automática si no hay respuesta (cancelar + notificar)
- Actualización de estado visual externo (Calendar emoji)

### Component Interaction

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Worker    │    │   Agent     │    │  Calendar   │
│  (Trigger)  │    │ (Responder) │    │  (Visual)   │
└──────┬──────┘    └──────┬──────┘    └──────┬──────┘
       │                  │                  │
       │ 1. Send confirm  │                  │
       ├─────────────────►│                  │
       │                  │                  │
       │    2. User responds (async)         │
       │                  │◄─────────────────┤
       │                  │                  │
       │    3. Detect & update               │
       │                  ├─────────────────►│
       │                  │   Update emoji   │
       │                  │                  │
       │ 4. Check timeout │                  │
       ├──────────────────┤                  │
       │  (if no response)│                  │
       │                  │                  │
       │ 5. Cancel & notify                  │
       ├─────────────────►├─────────────────►│
       │                  │   Delete event   │
```

### State Flow

```
PENDING ──[book()]──► confirmation_sent_at=NULL
    │
    │ Worker: 48h antes
    ▼
PENDING ──[send_template()]──► confirmation_sent_at=NOW
    │
    ├─── User responds "sí" ───► CONFIRMED (emoji 🟢)
    │
    └─── 24h sin respuesta ───► CANCELLED (delete event)
```

### Implementation Guide

**1. Worker detecta cita en ventana 48h:**
```sql
WHERE status = 'PENDING'
  AND confirmation_sent_at IS NULL
  AND start_time BETWEEN NOW() + INTERVAL '47 hours'
                     AND NOW() + INTERVAL '49 hours'
```

**2. Worker envía plantilla y marca:**
```python
await chatwoot_client.send_template(
    conversation_id=customer.conversation_id,
    template_name="confirmacion_cita",
    params=[customer.first_name, date_str, time_str, stylist.name]
)
appointment.confirmation_sent_at = datetime.now(tz)
await session.commit()
```

**3. Agent detecta respuesta afirmativa:**
```python
# En conversational_agent.py o herramienta dedicada
pending = await get_pending_appointment_awaiting_confirmation(phone)
if pending and is_affirmative_response(message):
    await confirm_appointment(pending.id)
    # Actualiza Calendar con emoji 🟢
```

**4. Worker detecta timeout (24h sin respuesta):**
```sql
WHERE status = 'PENDING'
  AND confirmation_sent_at IS NOT NULL
  AND confirmation_sent_at < NOW() - INTERVAL '24 hours'
```

**5. Worker cancela con lock para evitar race condition:**
```python
async with session.begin():
    appointment = await session.execute(
        select(Appointment)
        .where(Appointment.id == apt_id)
        .with_for_update()  # Lock
    )
    if appointment.status == AppointmentStatus.PENDING:  # Double-check
        appointment.status = AppointmentStatus.CANCELLED
        appointment.cancelled_at = datetime.now(tz)
        await delete_calendar_event(appointment.google_calendar_event_id)
        await chatwoot_client.send_template("cancelacion_no_confirmada", ...)
```

### Edge Cases

| Caso | Solución |
|------|----------|
| Race condition (confirma mientras worker cancela) | `SELECT FOR UPDATE` + double-check status |
| Múltiples citas pendientes | Agente muestra lista, pregunta cuál confirma |
| Respuesta ambigua ("sí pero cambio hora") | Agente interpreta, ofrece reagendar |
| Plantilla no enviada (error API) | Retry 3x, flag `notification_failed`, no cancela |

### Affects FRs

FR13, FR14, FR15, FR16, FR17, FR18, FR19, FR20

## Implementation Patterns

These patterns ensure consistent implementation across all AI agents:

### Naming Conventions

| Elemento | Convención | Ejemplo |
|----------|------------|---------|
| Tablas DB | snake_case plural | `appointments`, `business_hours` |
| Columnas DB | snake_case | `confirmation_sent_at`, `google_calendar_event_id` |
| Modelos Python | PascalCase | `Appointment`, `ConversationHistory` |
| Funciones/métodos | snake_case | `get_pending_appointments()`, `send_template()` |
| Archivos Python | snake_case | `appointment_management_tools.py` |
| Constantes | UPPER_SNAKE | `APPOINTMENT_STATUS`, `DEFAULT_TIMEOUT` |
| Enums | UPPER_SNAKE values | `AppointmentStatus.PENDING` |
| Tool names | snake_case inglés | `cancel_appointment`, `get_my_appointments` |
| Tool docstrings | Español | Para que LLM responda en español |

### Tool Response Format

**Éxito:**
```python
return {
    "status": "success",
    "message": "Cita cancelada correctamente",
    "data": {
        "appointment_id": str(appointment.id),
        "cancelled_at": appointment.cancelled_at.isoformat()
    }
}
```

**Error:**
```python
return {
    "status": "error",
    "message": "No se encontró la cita",
    "error_code": "APPOINTMENT_NOT_FOUND"
}
```

### Appointment Display Format

```python
{
    "id": str(appointment.id),
    "fecha": "martes 21 de noviembre",
    "hora": "10:00",
    "servicio": "Corte largo",
    "estilista": "Ana",
    "estado": "Pendiente de confirmación"  # Human-readable español
}
```

### Tool Structure Pattern

```python
# agent/tools/appointment_management_tools.py

from langchain_core.tools import tool
from database.connection import get_async_session
from database.models import Appointment, AppointmentStatus

@tool
async def get_my_appointments(customer_phone: str) -> list[dict]:
    """Obtener las citas activas del cliente.

    Args:
        customer_phone: Teléfono del cliente en formato E.164

    Returns:
        Lista de citas con id, fecha, hora, servicio, estilista, estado
    """
    async for session in get_async_session():
        # Query implementation
        break
    return appointments_list

@tool
async def cancel_appointment(appointment_id: str, reason: str = "") -> dict:
    """Cancelar una cita del cliente.

    Args:
        appointment_id: UUID de la cita a cancelar
        reason: Motivo de cancelación (opcional)

    Returns:
        Resultado con status y mensaje
    """
    # Implementation with Calendar delete
    pass

@tool
async def reschedule_appointment(
    appointment_id: str,
    new_date: str,
    new_time: str
) -> dict:
    """Reagendar una cita existente.

    Args:
        appointment_id: UUID de la cita a reagendar
        new_date: Nueva fecha en formato YYYY-MM-DD
        new_time: Nueva hora en formato HH:MM

    Returns:
        Nueva cita creada o error si no hay disponibilidad
    """
    # Cancel old + create new
    pass
```

### Chatwoot Template Integration

```python
# shared/chatwoot_client.py
async def send_template(
    self,
    conversation_id: str,
    template_name: str,
    template_params: list[str]
) -> bool:
    """Enviar plantilla de WhatsApp.

    Args:
        conversation_id: ID de conversación en Chatwoot
        template_name: Nombre de plantilla aprobada por Meta
        template_params: Parámetros {{1}}, {{2}}, etc.
    """
    endpoint = f"{self.api_url}/conversations/{conversation_id}/messages"
    payload = {
        "content": "",
        "template_params": {
            "name": template_name,
            "params": template_params
        },
        "message_type": "template"
    }
    async with self.session.post(endpoint, json=payload) as resp:
        return resp.status == 200
```

### Calendar Emoji Update

```python
async def update_event_emoji(
    event_id: str,
    calendar_id: str,
    new_status: AppointmentStatus,
    customer_name: str,
    service_name: str
) -> bool:
    emoji = "🟢" if new_status == AppointmentStatus.CONFIRMED else "🟡"
    new_title = f"{emoji} {customer_name} - {service_name}"

    service = get_calendar_service()
    service.events().patch(
        calendarId=calendar_id,
        eventId=event_id,
        body={"summary": new_title}
    ).execute()
    return True
```

### Status Transitions

```
PENDING → CONFIRMED  (cliente confirma)
PENDING → CANCELLED  (timeout 24h o cancelación manual)
CONFIRMED → COMPLETED (cita realizada)
CONFIRMED → CANCELLED (cancelación manual)
CONFIRMED → NO_SHOW  (cliente no se presenta)
```

### Environment Variables

```bash
# Nuevas variables para reminder worker
REMINDER_WORKER_INTERVAL_MINUTES=15
CONFIRMATION_WINDOW_HOURS=48
CONFIRMATION_TIMEOUT_HOURS=24
```

### Docker Service Definition

```yaml
# docker-compose.yml
reminder:
  build:
    context: .
    dockerfile: docker/Dockerfile.reminder
  container_name: atrevete-reminder
  environment:
    - DATABASE_URL=${DATABASE_URL}
    - CHATWOOT_API_URL=${CHATWOOT_API_URL}
    - CHATWOOT_API_KEY=${CHATWOOT_API_KEY}
    - GOOGLE_APPLICATION_CREDENTIALS=/app/service-account-key.json
  volumes:
    - ./service-account-key.json:/app/service-account-key.json:ro
  depends_on:
    postgres:
      condition: service_healthy
  restart: unless-stopped
  healthcheck:
    test: ["CMD", "pgrep", "python"]
    interval: 30s
    timeout: 10s
    retries: 3
```

## Consistency Rules

### Naming Conventions

Ver sección "Implementation Patterns > Naming Conventions" para tabla completa.

### Code Organization

**Principio:** Separación por responsabilidad funcional.

- `agent/tools/`: Una herramienta por archivo o agrupadas por función
- `agent/workers/`: Un worker por archivo
- `agent/prompts/`: Un archivo por estado de booking
- `shared/`: Utilidades compartidas entre API y Agent
- `tests/`: Espejo de estructura de código

### Error Handling

**Patrón general (establecido):**
- Logging estructurado con `shared/logging.py`
- Retries con `tenacity` para APIs externas (3 intentos, backoff exponencial)
- Fallback messages cuando LLM falla

**Worker de recordatorios:**
- Reintentar envío de plantilla 3 veces con backoff exponencial
- Si falla después de 3 intentos: Loggear error, marcar con flag `notification_failed`
- **NUNCA** cancelar cita automáticamente por fallo de envío (solo por timeout 24h sin respuesta)

### Logging Strategy

**Formato:** JSON estructurado con Langfuse para tracing LLM

**Campos obligatorios para worker:**
```python
logger.info("confirmation_sent", extra={
    "appointment_id": str(appointment.id),
    "customer_phone": appointment.customer.phone,
    "template": "confirmacion_cita",
    "scheduled_time": appointment.start_time.isoformat()
})
```

**Niveles:**
- INFO: Operaciones exitosas (envío plantilla, confirmación recibida)
- WARNING: Reintentos, citas sin respuesta
- ERROR: Fallos de API, errores de DB

### Date/Time Handling

**Timezone:** `Europe/Madrid` (todos los cálculos y displays)

**Formato DB:** `TIMESTAMP WITH TIME ZONE`

**Formato display:** `"martes 21 de noviembre a las 10:00"`

**Cálculos de ventanas:**
- 48h antes: `start_time - timedelta(hours=48)`
- 24h antes: `start_time - timedelta(hours=24)`
- Timeout confirmación: `confirmation_sent_at + timedelta(hours=24)`

### Idempotency Pattern

**Crítico para worker:** Los campos timestamp actúan como locks para idempotencia.

```python
# Query solo citas que NO han recibido confirmación
appointments = await session.execute(
    select(Appointment)
    .where(Appointment.status == AppointmentStatus.PENDING)
    .where(Appointment.confirmation_sent_at.is_(None))  # Lock
    .where(Appointment.start_time <= now + timedelta(hours=48))
    .where(Appointment.start_time > now)
)
```

### Agent Confirmation Detection

**Patrón:** Keyword matching + contexto de cita pendiente

El agente detecta confirmaciones cuando:
1. Mensaje contiene keywords: "sí", "confirmo", "ok", "perfecto", "claro"
2. Cliente tiene cita con `status=PENDING`
3. Cita tiene `confirmation_sent_at` en últimas 24h

**Prompt instruction:** Verificar contexto antes de interpretar afirmaciones como confirmación de cita.

## Data Architecture

### Model Changes

**Appointment (modificaciones):**
```python
class Appointment(Base):
    # Campos existentes...

    # Nuevos campos de tracking
    confirmation_sent_at: Mapped[datetime | None]  # Timestamp envío plantilla 48h
    reminder_sent_at: Mapped[datetime | None]      # Timestamp envío recordatorio 24h
    cancelled_at: Mapped[datetime | None]          # Timestamp cancelación
    notification_failed: Mapped[bool] = False      # Flag si falló envío
```

**Customer (modificaciones):**
```python
class Customer(Base):
    # Campos existentes...

    # Nuevo campo para templates
    chatwoot_conversation_id: Mapped[str | None]  # ID conversación en Chatwoot
```

**AppointmentStatus (renombrar):**
```python
class AppointmentStatus(str, Enum):
    PENDING = "pending"        # Antes: CONFIRMED - agendada, esperando confirmación
    CONFIRMED = "confirmed"    # Nuevo - cliente confirmó asistencia
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"
```

### Migration Strategy

1. Crear migración para añadir nuevos campos (nullable)
2. Crear migración para renombrar enum values
3. Actualizar código que usa CONFIRMED → PENDING
4. Poblar `chatwoot_conversation_id` en process_incoming_message

### Indexes

```sql
-- Para queries del worker
CREATE INDEX idx_appointments_confirmation_pending
ON appointments (start_time, confirmation_sent_at)
WHERE status = 'pending';

-- Para buscar citas del cliente
CREATE INDEX idx_appointments_customer_active
ON appointments (customer_id, start_time)
WHERE status IN ('pending', 'confirmed');
```

## API Contracts

### Existing Endpoints (sin cambios)

- `GET /health` - Health check
- `POST /webhook/chatwoot/{token}` - Webhook receiver
- `GET /conversations/{id}/history` - Conversation history

### New Tool Contracts

**get_my_appointments:**
```python
Input: customer_phone: str  # E.164 format
Output: list[{
    "id": str,
    "fecha": str,  # "martes 21 de noviembre"
    "hora": str,   # "10:00"
    "servicio": str,
    "estilista": str,
    "estado": str  # "Pendiente de confirmación" | "Confirmada"
}]
```

**cancel_appointment:**
```python
Input: appointment_id: str, reason: str = ""
Output: {
    "status": "success" | "error",
    "message": str,
    "data": {"appointment_id": str, "cancelled_at": str} | None
}
```

**reschedule_appointment:**
```python
Input: appointment_id: str, new_date: str, new_time: str
Output: {
    "status": "success" | "error",
    "message": str,
    "data": {"new_appointment_id": str, "start_time": str} | None
}
```

### Chatwoot Template API

```python
POST /api/v1/accounts/{account_id}/conversations/{conv_id}/messages
{
    "content": "",
    "template_params": {
        "name": "confirmacion_cita",
        "params": ["María", "martes 21", "10:00", "Ana"]
    },
    "message_type": "template"
}
```

## Security Architecture

### Authentication (sin cambios)

- **Chatwoot Webhook:** Token en URL + comparación timing-safe
- **Google Calendar:** Service account key (read-only mount)
- **Database:** Password auth (min 16 chars)
- **Django Admin:** Username/password

### New Security Considerations

**Worker de recordatorios:**
- Acceso solo a DB y Chatwoot API (no expone endpoints)
- Credenciales via variables de entorno
- Service account key montado read-only

**Cancelación de citas:**
- Validar que la cita pertenece al cliente que la cancela
- No permitir cancelar citas de otros clientes

```python
# En cancel_appointment tool
if appointment.customer.phone != customer_phone:
    return {"status": "error", "message": "No tienes permiso para cancelar esta cita"}
```

### Data Protection

- Phone numbers: E.164 format, único identificador de cliente
- Conversation IDs: Solo para envío de plantillas, no sensible
- Timestamps: Auditoría de operaciones

## Performance Considerations

### NFR Compliance

| NFR | Requirement | Strategy |
|-----|-------------|----------|
| NFR1 | Respuesta <5s | Caching existente, prompts optimizados |
| NFR2 | Worker <2min | Índices condicionales, batch processing |
| NFR3 | Calendar <3s | Timeout en API calls |

### Worker Optimization

**Queries eficientes:**
```python
# Usar índice condicional
SELECT * FROM appointments
WHERE status = 'pending'
  AND confirmation_sent_at IS NULL
  AND start_time BETWEEN NOW() + '47h' AND NOW() + '49h'
LIMIT 100;  # Batch processing
```

**Batch processing:**
- Procesar máximo 100 citas por ciclo
- Si hay más, continúa en siguiente ejecución
- Evita timeouts y memory issues

### Caching (existente)

- Stylist context: In-memory, 10 min TTL
- Prompt cache: OpenRouter automatic
- Checkpoint cache: Redis con TTL

## Deployment Architecture

### Docker Services (actualizado)

| Service | Container | Port | Purpose |
|---------|-----------|------|---------|
| postgres | atrevete-postgres | 5432 | Database |
| redis | atrevete-redis | 6379 | Cache + Pub/Sub |
| api | atrevete-api | 8000 | Webhook receiver |
| admin | atrevete-admin | 8001 | Django Admin |
| agent | atrevete-agent | - | LangGraph worker |
| archiver | atrevete-archiver | - | Conversation archival |
| **reminder** | **atrevete-reminder** | - | **Confirmation/reminder worker (NUEVO)** |

### Service Dependencies

```
postgres ─┬─► api
          ├─► agent
          ├─► admin
          ├─► archiver
          └─► reminder (NUEVO)

redis ────┬─► api
          └─► agent
```

### Health Checks

Todos los servicios tienen health checks configurados. El nuevo worker usa `pgrep python`.

### Volumes

- `postgres_data`: Database persistence
- `redis_data`: Redis persistence
- `pgadmin_data`: pgAdmin config

## Development Environment

### Prerequisites

- Python 3.11+
- Docker + Docker Compose
- PostgreSQL client (psql)
- Service account key for Google Calendar

### Setup Commands

```bash
# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start services
docker-compose up -d

# Apply migrations
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/alembic upgrade head

# Run tests
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/pytest

# View logs
docker-compose logs -f reminder  # New worker
```

### Environment Variables (nuevas)

```bash
# Añadir a .env
REMINDER_WORKER_INTERVAL_MINUTES=15
CONFIRMATION_WINDOW_HOURS=48
CONFIRMATION_TIMEOUT_HOURS=24
```

## Architecture Decision Records (ADRs)

### ADR-001: Worker Separado para Recordatorios

**Contexto:** Necesitamos ejecutar tareas programadas para confirmaciones y recordatorios.

**Decisión:** Crear worker separado `appointment_reminder` en lugar de extender archiver.

**Razones:**
- Separación de responsabilidades
- Escalable independientemente
- Monitoreo específico
- Patrón probado con archiver existente

### ADR-002: Renombrar Estados de Cita

**Contexto:** El estado CONFIRMED existente significa "agendada", pero necesitamos distinguir "verificada por cliente".

**Decisión:** Renombrar CONFIRMED→PENDING, crear nuevo CONFIRMED para verificadas.

**Razones:**
- Terminología estándar de la industria
- PENDING = esperando acción del cliente
- CONFIRMED = cliente confirmó asistencia
- Más intuitivo para usuarios y desarrolladores

### ADR-003: Campos Timestamp vs JSONB

**Contexto:** El worker necesita tracking de notificaciones enviadas.

**Decisión:** Usar campos timestamp dedicados (confirmation_sent_at, reminder_sent_at, cancelled_at).

**Razones:**
- Queries simples con índices
- Idempotencia natural (IS NULL)
- Auditoría clara
- Mejor performance que JSONB queries

### ADR-004: Sincronización Calendar en Tiempo Real

**Contexto:** Los estilistas necesitan ver el estado de citas en Google Calendar.

**Decisión:** Actualizar emoji en Calendar inmediatamente cuando cambia estado.

**Razones:**
- Visibilidad inmediata para estilistas
- Pocas operaciones (solo confirmaciones/cancelaciones)
- Consistencia visual importante

### ADR-005: Detección de Confirmación por Contexto

**Contexto:** El agente debe reconocer cuando cliente responde a solicitud de confirmación.

**Decisión:** Keyword matching + verificación de cita PENDING con confirmation_sent_at.

**Razones:**
- Aprovecha capacidad natural del LLM
- Robusto con contexto
- Evita falsos positivos
- No requiere estado adicional en conversación

---

_Generated by BMAD Decision Architecture Workflow v1.0_
_Date: 2025-11-19_
_For: Pepe_
