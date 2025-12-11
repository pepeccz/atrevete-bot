# Epic Technical Specification: Sistema de Confirmación y Recordatorios

Date: 2025-11-21
Author: Pepe
Epic ID: 2
Status: Draft

---

## Overview

Epic 2 implementa el sistema automatizado de confirmación y recordatorios para citas agendadas en Atrévete Bot. Esta funcionalidad es crítica para reducir no-shows (clientes que no se presentan) mediante un flujo de notificaciones proactivas: confirmación 48 horas antes, recordatorio 24 horas antes (si confirmó), o cancelación automática (si no confirmó en 24h).

El sistema introduce un nuevo worker background (`appointment_reminder`) que ejecuta periódicamente para detectar citas en ventanas temporales específicas, enviar plantillas de WhatsApp Business mediante Chatwoot API, detectar respuestas de confirmación del cliente a través del agente conversacional, y actualizar el estado visual en Google Calendar (emojis 🟡/🟢) para visibilidad inmediata de estilistas. Esta epic cubre FR13-FR20 del PRD y es prerequisito para Epic 3 (cancelación/reagendamiento).

## Objectives and Scope

**In Scope:**
- ✅ Implementar worker `appointment_reminder` con ciclo de ejecución cada 15 minutos
- ✅ Envío automático de plantilla "confirmacion_cita" 48h antes de citas con estado PENDING
- ✅ Detección de respuestas afirmativas del cliente ("sí", "confirmo", "ok") por el agente conversacional
- ✅ Actualización de estado PENDING → CONFIRMED al recibir confirmación del cliente
- ✅ Actualización de emoji en Google Calendar (🟡 → 🟢) al confirmar
- ✅ Envío automático de recordatorio 24h antes para citas CONFIRMED
- ✅ Cancelación automática de citas PENDING sin respuesta después de 24h desde envío de confirmación
- ✅ Notificación al cliente cuando su cita es cancelada por falta de confirmación
- ✅ Eliminación de evento Google Calendar al cancelar por timeout
- ✅ Campos timestamp dedicados en modelo Appointment para tracking (confirmation_sent_at, reminder_sent_at, cancelled_at)
- ✅ Campo chatwoot_conversation_id en modelo Customer para envío de templates
- ✅ Manejo de errores robusto con retries y logging estructurado

**Out of Scope:**
- ❌ Cancelación manual por cliente (Epic 3)
- ❌ Reagendamiento de citas (Epic 3)
- ❌ Notificaciones a estilistas sobre cancelaciones (Post-MVP)
- ❌ Lista de espera para citas canceladas (Post-MVP)
- ❌ Métricas y analytics de confirmaciones (Post-MVP)
- ❌ Políticas de cancelación con restricciones de tiempo (Post-MVP)

## System Architecture Alignment

Esta epic se alinea con la arquitectura v3.2 existente mediante extensión incremental sin cambios disruptivos. El diseño sigue patrones establecidos en el sistema actual:

**Componentes Existentes Extendidos:**
- **Database Models (database/models.py)**: Se agregan campos timestamp a `Appointment` (confirmation_sent_at, reminder_sent_at, cancelled_at, notification_failed) y campo conversation_id a `Customer`. Se renombra enum AppointmentStatus: CONFIRMED→PENDING, nuevo CONFIRMED para verificadas.
- **Agent Tools (agent/tools/)**: El agente conversacional detectará respuestas de confirmación mediante keyword matching + contexto de cita pendiente, sin requerir nueva tool (se maneja en conversational_agent.py).
- **Chatwoot Client (shared/chatwoot_client.py)**: Se añade método `send_template()` para envío de plantillas de WhatsApp Business.
- **Google Calendar Integration**: Se reutilizan funciones existentes, agregando `update_event_emoji()` para cambiar título del evento (🟡→🟢).

**Nuevos Componentes:**
- **appointment_reminder Worker (agent/workers/appointment_reminder.py)**: Nuevo servicio background que ejecuta cada 15 minutos, siguiendo el patrón del worker `conversation_archiver` existente. Consulta PostgreSQL, envía templates via Chatwoot, actualiza Calendar.
- **Docker Service**: Nuevo contenedor `atrevete-reminder` con dockerfile dedicado, dependencias de postgres, configuración via variables de entorno.
- **Alembic Migration**: Nueva migración para campos timestamp, enum renaming, y conversation_id.

**Constraints Arquitectónicos Respetados:**
- Mantiene separación API (FastAPI) / Agent (LangGraph) / Workers (background)
- Usa PostgreSQL como única fuente de verdad
- Redis solo para checkpointing del agente (no para worker)
- Logging estructurado con Langfuse para tracing
- Google Calendar como sistema externo de visualización

## Detailed Design

### Services and Modules

| Módulo | Responsabilidad | Inputs | Outputs | Owner/Location |
|--------|----------------|--------|---------|----------------|
| **appointment_reminder** | Worker background para confirmaciones/recordatorios | PostgreSQL appointments table, Config (interval, windows) | Chatwoot template messages, Calendar updates, DB updates | `agent/workers/appointment_reminder.py` |
| **chatwoot_client.send_template()** | Envío de plantillas WhatsApp Business | conversation_id, template_name, params[] | HTTP 200/error, template sent flag | `shared/chatwoot_client.py` |
| **conversational_agent (extended)** | Detección de confirmaciones del cliente | User message, pending appointments context | Estado CONFIRMED actualizado, Calendar emoji update | `agent/nodes/conversational_agent.py` |
| **calendar_service (extended)** | Actualización de emojis en eventos | event_id, calendar_id, new_status | Updated event with emoji 🟢 or 🟡 | `agent/tools/booking_tools.py` (reutiliza funciones) |
| **Alembic Migration** | Schema updates para timestamps y enum | Existing DB schema | New columns: confirmation_sent_at, reminder_sent_at, cancelled_at, notification_failed, chatwoot_conversation_id | `alembic/versions/` |

### Data Models and Contracts

**Appointment Model (Extended)**

```python
class Appointment(Base):
    __tablename__ = "appointments"

    # Existing fields...
    id: Mapped[UUID]
    customer_id: Mapped[UUID]  # FK to customers
    stylist_id: Mapped[UUID]   # FK to stylists
    start_time: Mapped[datetime]  # TIMESTAMP WITH TIME ZONE
    duration_minutes: Mapped[int]
    status: Mapped[AppointmentStatus]  # ENUM (see below)
    google_calendar_event_id: Mapped[str | None]
    notes: Mapped[str | None]
    first_name: Mapped[str]
    last_name: Mapped[str | None]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    # NEW FIELDS for Epic 2:
    confirmation_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when confirmation template was sent (48h before)"
    )
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when reminder template was sent (24h before)"
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when appointment was cancelled"
    )
    notification_failed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Flag if template sending failed after retries"
    )
```

**Customer Model (Extended)**

```python
class Customer(Base):
    __tablename__ = "customers"

    # Existing fields...
    id: Mapped[UUID]
    phone: Mapped[str]  # E.164 format, unique
    first_name: Mapped[str]
    last_name: Mapped[str | None]
    email: Mapped[str | None]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    # NEW FIELD for Epic 2:
    chatwoot_conversation_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        comment="Chatwoot conversation ID for sending templates"
    )
```

**AppointmentStatus Enum (Renamed)**

```python
class AppointmentStatus(str, Enum):
    PENDING = "pending"        # Renamed from CONFIRMED - Agendada, esperando confirmación
    CONFIRMED = "confirmed"    # NEW - Cliente confirmó asistencia
    COMPLETED = "completed"    # Sin cambios
    CANCELLED = "cancelled"    # Sin cambios
    NO_SHOW = "no_show"       # Sin cambios
```

**Migration Strategy:**
1. Alembic migration para añadir columnas nuevas (nullable=True)
2. Segunda migration para renombrar enum CONFIRMED→PENDING y crear nuevo CONFIRMED
3. Data migration: UPDATE appointments SET status='pending' WHERE status='confirmed'
4. Popular chatwoot_conversation_id en process_incoming_message durante primera interacción

**Indexes:**

```sql
-- Para queries del worker (ventana 48h)
CREATE INDEX idx_appointments_confirmation_pending
ON appointments (start_time, confirmation_sent_at)
WHERE status = 'pending';

-- Para timeout detection (24h sin respuesta)
CREATE INDEX idx_appointments_confirmation_timeout
ON appointments (confirmation_sent_at, status)
WHERE status = 'pending' AND confirmation_sent_at IS NOT NULL;

-- Para buscar citas del cliente
CREATE INDEX idx_appointments_customer_active
ON appointments (customer_id, start_time)
WHERE status IN ('pending', 'confirmed');
```

### APIs and Interfaces

**Chatwoot Template API (External)**

```python
# Method: POST
# Path: /api/v1/accounts/{account_id}/conversations/{conversation_id}/messages
# Headers: api_access_token: {CHATWOOT_API_KEY}

# Request Body:
{
    "content": "",  # Empty for templates
    "template_params": {
        "name": "confirmacion_cita",  # Template name approved by Meta
        "params": [
            "María",           # {{1}} - Customer first name
            "martes 21",       # {{2}} - Date formatted
            "10:00",           # {{3}} - Time formatted
            "Ana"              # {{4}} - Stylist name
        ]
    },
    "message_type": "template"
}

# Response: 200 OK
{
    "id": 123456,
    "content": "",
    "message_type": 0,
    "created_at": 1234567890
}

# Error: 400/422/500
{
    "error": "Template not found / Invalid params / Server error"
}
```

**Chatwoot Client Method (New)**

```python
# shared/chatwoot_client.py

async def send_template(
    self,
    conversation_id: str,
    template_name: str,
    template_params: list[str]
) -> dict[str, Any]:
    """
    Enviar plantilla de WhatsApp Business a través de Chatwoot.

    Args:
        conversation_id: ID de conversación en Chatwoot
        template_name: Nombre de plantilla aprobada por Meta
        template_params: Lista de parámetros {{1}}, {{2}}, etc.

    Returns:
        {"success": True/False, "message_id": str | None, "error": str | None}

    Raises:
        ChatwootAPIError: Si falla después de retries
    """
    endpoint = f"{self.api_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/messages"

    payload = {
        "content": "",
        "template_params": {
            "name": template_name,
            "params": template_params
        },
        "message_type": "template"
    }

    # Retry with exponential backoff (tenacity decorator)
    async with self.session.post(endpoint, json=payload, headers=self.headers) as resp:
        if resp.status == 200:
            data = await resp.json()
            return {"success": True, "message_id": str(data["id"]), "error": None}
        else:
            error_msg = await resp.text()
            return {"success": False, "message_id": None, "error": error_msg}
```

**Google Calendar Event Update (Extended)**

```python
# agent/tools/booking_tools.py (new helper function)

async def update_calendar_event_emoji(
    event_id: str,
    calendar_id: str,
    new_status: AppointmentStatus,
    customer_name: str,
    service_names: list[str]
) -> bool:
    """
    Actualizar emoji en título de evento de Google Calendar.

    Args:
        event_id: ID del evento en Google Calendar
        calendar_id: Calendar ID del estilista
        new_status: Nuevo estado de cita (PENDING o CONFIRMED)
        customer_name: Nombre del cliente
        service_names: Lista de servicios

    Returns:
        True si actualización exitosa, False si falla
    """
    emoji = "🟢" if new_status == AppointmentStatus.CONFIRMED else "🟡"
    services_str = ", ".join(service_names)
    new_title = f"{emoji} {customer_name} - {services_str}"

    try:
        service = get_calendar_service()  # Existing function
        service.events().patch(
            calendarId=calendar_id,
            eventId=event_id,
            body={"summary": new_title}
        ).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to update calendar event {event_id}: {e}")
        return False
```

**Worker Internal Interfaces**

```python
# agent/workers/appointment_reminder.py

async def process_48h_confirmations() -> dict[str, int]:
    """
    Detectar y enviar confirmaciones para citas en ventana 48h.

    Returns:
        {"processed": int, "sent": int, "failed": int}
    """
    pass

async def process_24h_reminders() -> dict[str, int]:
    """
    Enviar recordatorios para citas confirmadas en ventana 24h.

    Returns:
        {"processed": int, "sent": int, "failed": int}
    """
    pass

async def process_confirmation_timeouts() -> dict[str, int]:
    """
    Cancelar citas sin confirmación después de 24h desde envío.

    Returns:
        {"cancelled": int, "notified": int, "failed": int}
    """
    pass
```

### Workflows and Sequencing

**Workflow 1: Confirmación 48h Antes**

```
┌──────────────┐
│ Worker Cycle │ (every 15 minutes)
└──────┬───────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│ Query DB: appointments WHERE                    │
│   status = 'pending'                            │
│   AND confirmation_sent_at IS NULL              │
│   AND start_time BETWEEN NOW()+47h AND NOW()+49h│
└──────┬──────────────────────────────────────────┘
       │
       ▼
┌──────────────┐
│ For each apt │
└──────┬───────┘
       │
       ▼
┌────────────────────────────────────┐
│ Get customer.chatwoot_conversation_id │
│ Format date/time in Spanish        │
│ Get stylist name                   │
└──────┬─────────────────────────────┘
       │
       ▼
┌────────────────────────────────────┐
│ chatwoot_client.send_template(    │
│   conversation_id,                 │
│   "confirmacion_cita",             │
│   [first_name, date, time, stylist]│
│ )                                  │
└──────┬─────────────────────────────┘
       │
       ├─── Success ───► UPDATE appointment
       │                  SET confirmation_sent_at = NOW()
       │
       └─── Fail ──────► Retry 3x with backoff
                         If still fails:
                         UPDATE notification_failed = TRUE
                         LOG ERROR (don't cancel apt)
```

**Workflow 2: Cliente Confirma (Async)**

```
┌─────────────┐
│ User Message│ "Sí, confirmo"
└──────┬──────┘
       │
       ▼
┌────────────────────────────────────┐
│ conversational_agent.py            │
│ - Detect affirmative response      │
│ - Check if pending appointment     │
│   with confirmation_sent_at < 24h  │
└──────┬─────────────────────────────┘
       │
       ▼
┌────────────────────────────────────┐
│ UPDATE appointment                 │
│ SET status = 'confirmed'           │
│ WHERE id = {apt_id}                │
│   AND status = 'pending'           │
└──────┬─────────────────────────────┘
       │
       ▼
┌────────────────────────────────────┐
│ update_calendar_event_emoji(       │
│   event_id,                        │
│   calendar_id,                     │
│   AppointmentStatus.CONFIRMED,     │
│   customer_name,                   │
│   service_names                    │
│ )                                  │
│ → Updates title: 🟡 → 🟢           │
└──────┬─────────────────────────────┘
       │
       ▼
┌────────────────────────────────────┐
│ Agent responds:                    │
│ "¡Perfecto! Tu cita está          │
│  confirmada para el..."            │
└────────────────────────────────────┘
```

**Workflow 3: Recordatorio 24h Antes**

```
┌──────────────┐
│ Worker Cycle │
└──────┬───────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│ Query DB: appointments WHERE                    │
│   status = 'confirmed'                          │
│   AND reminder_sent_at IS NULL                  │
│   AND start_time BETWEEN NOW()+23h AND NOW()+25h│
└──────┬──────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────┐
│ chatwoot_client.send_template(    │
│   conversation_id,                 │
│   "recordatorio_cita",             │
│   [first_name, date, time, stylist]│
│ )                                  │
└──────┬─────────────────────────────┘
       │
       └─── Success ───► UPDATE appointment
                         SET reminder_sent_at = NOW()
```

**Workflow 4: Timeout Cancelación (24h sin respuesta)**

```
┌──────────────┐
│ Worker Cycle │
└──────┬───────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│ Query DB: appointments WHERE                    │
│   status = 'pending'                            │
│   AND confirmation_sent_at IS NOT NULL          │
│   AND confirmation_sent_at < NOW() - 24h        │
└──────┬──────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────┐
│ BEGIN TRANSACTION                  │
│ SELECT FOR UPDATE (lock row)       │
└──────┬─────────────────────────────┘
       │
       ▼
┌────────────────────────────────────┐
│ Double-check status = 'pending'    │
│ (race condition protection)        │
└──────┬─────────────────────────────┘
       │
       ▼
┌────────────────────────────────────┐
│ UPDATE appointment                 │
│ SET status = 'cancelled',          │
│     cancelled_at = NOW()           │
└──────┬─────────────────────────────┘
       │
       ▼
┌────────────────────────────────────┐
│ delete_calendar_event(             │
│   event_id,                        │
│   calendar_id                      │
│ )                                  │
└──────┬─────────────────────────────┘
       │
       ▼
┌────────────────────────────────────┐
│ chatwoot_client.send_template(    │
│   conversation_id,                 │
│   "cancelacion_no_confirmada",     │
│   [first_name, date, time]         │
│ )                                  │
└──────┬─────────────────────────────┘
       │
       ▼
┌────────────────────────────────────┐
│ COMMIT TRANSACTION                 │
└────────────────────────────────────┘
```

**Sequence Diagram: Full Confirmation Loop**

```
Customer    Agent     Worker    Chatwoot    Calendar    DB
   │          │          │          │           │        │
   │  Book    │          │          │           │        │
   ├─────────►│          │          │           │        │
   │          ├──────────┼──────────┼───────────┼───────►│
   │          │          │          │           │   INSERT status=pending
   │          │          │          │           │◄───────┤
   │          ├──────────┼──────────┼──────────►│        │
   │          │          │          │    Create event 🟡  │
   │◄─────────┤          │          │           │        │
   │ "Cita    │          │          │           │        │
   │  creada" │          │          │           │        │
   │          │          │          │           │        │
   │         ... 48h antes ...      │           │        │
   │          │          │          │           │        │
   │          │  ┌───────┤          │           │        │
   │          │  │ Query ├──────────┼───────────┼───────►│
   │          │  │ pending          │           │   SELECT
   │          │  │ apts  │          │           │◄───────┤
   │          │  └───────┤          │           │        │
   │          │          ├─────────►│           │        │
   │          │          │ send_template         │        │
   │◄─────────┼──────────┼──────────┤           │        │
   │ "Confirma│          │          │           │        │
   │  tu cita"│          ├──────────┼───────────┼───────►│
   │          │          │          │           │   UPDATE
   │          │          │          │           │   confirmation_sent_at
   │          │          │          │           │        │
   │ "Sí"     │          │          │           │        │
   ├─────────►│          │          │           │        │
   │          ├──────────┼──────────┼───────────┼───────►│
   │          │ Detect   │          │           │   UPDATE
   │          │ confirm  │          │           │   status=confirmed
   │          ├──────────┼──────────┼──────────►│        │
   │          │          │          │    Update emoji 🟢  │
   │◄─────────┤          │          │           │        │
   │ "¡Confirmada!"      │          │           │        │
   │          │          │          │           │        │
   │         ... 24h antes ...      │           │        │
   │          │          │          │           │        │
   │          │  ┌───────┤          │           │        │
   │          │  │ Query ├──────────┼───────────┼───────►│
   │          │  │ confirmed        │           │   SELECT
   │          │  │ apts  │          │           │◄───────┤
   │          │  └───────┤          │           │        │
   │          │          ├─────────►│           │        │
   │          │          │ send_template         │        │
   │◄─────────┼──────────┼──────────┤           │        │
   │ "Recordatorio       │           │           │        │
   │  mañana"│          │          │           │        │
```

**Edge Cases Handled:**

1. **Race Condition (cliente confirma mientras worker cancela)**:
   - Worker usa `SELECT FOR UPDATE` para lockear row
   - Double-check status antes de cancelar
   - Si status cambió a CONFIRMED, skip cancelación

2. **Múltiples citas pendientes**:
   - Agent muestra lista de citas pendientes
   - Cliente especifica cuál confirma (por fecha/estilista)

3. **Respuesta ambigua** ("sí pero cambio hora"):
   - Agent interpreta como NO confirmación
   - Ofrece reagendar (Epic 3 feature)

4. **Plantilla no enviada** (error API):
   - Retry 3x con exponential backoff
   - Si falla: marcar `notification_failed = TRUE`
   - **NO** cancelar cita automáticamente por fallo técnico

5. **Cliente responde fuera de ventana** (después de 24h):
   - Cita ya cancelada por worker
   - Agent informa que debe agendar nueva cita

## Non-Functional Requirements

### Performance

**NFR2 (from PRD)**: El worker de confirmaciones debe procesar todas las citas pendientes en menos de 2 minutos por ejecución.

**Implementation:**
- Query con índices condicionales: `idx_appointments_confirmation_pending`, `idx_appointments_confirmation_timeout`
- Batch processing: Máximo 100 citas por ciclo (LIMIT 100 en queries)
- Worker interval: 15 minutos (configurable via `REMINDER_WORKER_INTERVAL_MINUTES`)
- Timeout en API calls: 10 segundos para Chatwoot, 5 segundos para Calendar

**Measurable Targets:**
- Worker cycle completion: <120 segundos con 100+ citas pendientes
- Template send latency: <2 segundos per message (Chatwoot API)
- Calendar emoji update: <3 segundos per event (Google Calendar API)
- Database query time: <500ms para queries de ventana temporal con índices

**Monitoring:**
- Log tiempo de ejecución de cada worker cycle
- Alert si cycle time >120 segundos
- Métricas de latencia para Chatwoot/Calendar APIs (Langfuse)

### Security

**Authentication:**
- Worker accede a DB con credenciales existentes (DATABASE_URL env var)
- Chatwoot API key via `CHATWOOT_API_KEY` env var (nunca hardcoded)
- Google Calendar service account key montado read-only (`/app/service-account-key.json:ro`)

**Data Protection:**
- Phone numbers en formato E.164 como identificador único (no sensible según GDPR para uso interno)
- Conversation IDs de Chatwoot no contienen información sensible (solo IDs numéricos)
- Timestamps de confirmación/recordatorio son metadatos de auditoría (no PII)

**Authorization:**
- Worker no expone endpoints HTTP (no requiere autenticación de red)
- Solo procesa citas del sistema (no hay input externo directo)
- Templates enviados solo a customers con chatwoot_conversation_id válido

**Secure Coding:**
- SQL injection prevention: SQLAlchemy ORM con parametrized queries
- No eval() o exec() en código del worker
- Logging estructurado sin incluir tokens/keys (usa placeholders)

**Template Security (WhatsApp Business):**
- Plantillas aprobadas por Meta (política de WhatsApp Business)
- Parámetros sanitizados antes de envío (strip whitespace, max length)
- No permite inyección de markdown o URLs no verificadas

### Reliability/Availability

**NFR4 (from PRD)**: El sistema debe manejar errores de APIs externas (Chatwoot, Google Calendar) sin perder datos.

**Implementation:**
- **Retry Logic**: 3 intentos con exponential backoff (1s, 2s, 4s) usando `tenacity` decorator
- **Error Isolation**: Fallos en Chatwoot no afectan DB updates (appointment tracking persiste)
- **Fallback Behavior**: Si template falla después de 3 retries, marca `notification_failed=TRUE` pero NO cancela cita
- **Transactional Safety**: Cancelación usa `BEGIN TRANSACTION` + `SELECT FOR UPDATE` para evitar race conditions

**NFR5 (from PRD)**: Las citas deben persistir en PostgreSQL antes de crear eventos en Calendar.

**Implementation:**
- Order of operations en `book()` tool:
  1. INSERT appointment en DB
  2. COMMIT transaction
  3. Create Calendar event (si falla, appointment ya existe en DB)
- Worker solo procesa appointments con `google_calendar_event_id` válido

**NFR6 (from PRD)**: El worker debe ser idempotente (re-ejecutar no duplica mensajes).

**Implementation:**
- Campos timestamp actúan como locks naturales:
  - `confirmation_sent_at IS NULL` → solo procesa citas sin confirmación enviada
  - `reminder_sent_at IS NULL` → solo procesa citas sin recordatorio enviado
- Double-check de status antes de cancelar (race condition protection)
- Si worker crash durante ejecución, siguiente ciclo retoma sin duplicados

**Availability:**
- Docker healthcheck: `pgrep python` cada 30s
- Restart policy: `unless-stopped` (auto-restart en failures)
- No SPOF: Worker stateless, puede reiniciar sin pérdida de contexto

### Observability

**Logging Strategy (JSON structured):**

```python
# INFO level - Operaciones exitosas
logger.info("confirmation_sent", extra={
    "appointment_id": str(apt_id),
    "customer_phone": customer.phone,
    "template": "confirmacion_cita",
    "scheduled_time": apt.start_time.isoformat(),
    "worker_cycle": cycle_id
})

# WARNING level - Reintentos, citas sin respuesta
logger.warning("confirmation_timeout_detected", extra={
    "appointment_id": str(apt_id),
    "confirmation_sent_at": apt.confirmation_sent_at.isoformat(),
    "hours_elapsed": 24
})

# ERROR level - Fallos de API, errores de DB
logger.error("template_send_failed", extra={
    "appointment_id": str(apt_id),
    "template": "confirmacion_cita",
    "error": str(e),
    "retry_count": 3,
    "notification_failed": True
})
```

**Metrics (via Langfuse):**
- Template send success rate (by template name)
- Calendar update latency (p50, p95, p99)
- Worker cycle duration (p50, p95, p99)
- Confirmation response rate (% citas confirmadas vs canceladas)

**Tracing:**
- LangGraph agent traces para detección de confirmaciones (Langfuse)
- Worker operations no usan Langfuse (no LLM calls)

**Alerts:**
- Worker cycle time >120 segundos (NFR2 violation)
- Template send failures >10% en ventana de 1 hora
- Confirmation timeout cancellations >50% (indicador de problema UX)
- Database connection errors (worker can't query appointments)

**Dashboard Requirements:**
- Worker health: último ciclo exitoso, duración promedio
- Confirmation funnel: enviadas → confirmadas → recordatorios → canceladas
- Error rates: Chatwoot API, Calendar API, DB queries

## Dependencies and Integrations

**Python Dependencies (Existing):**
| Package | Version | Purpose |
|---------|---------|---------|
| sqlalchemy | >=2.0.0 | ORM para DB queries (appointments, customers) |
| asyncpg | >=0.29.0 | PostgreSQL async driver |
| alembic | >=1.13.0 | Database migrations |
| httpx | >=0.27.0 | HTTP client para Chatwoot API |
| google-api-python-client | >=2.150 | Google Calendar API client |
| redis | >=5.0.0 | Redis client (checkpointing, no usado en worker) |
| pydantic | >=2.9.0 | Data validation |
| python-dotenv | >=1.0.0 | Environment variables |

**Python Dependencies (NEW - to add):**
| Package | Version | Purpose |
|---------|---------|---------|
| tenacity | >=8.0.0 | Retry logic con exponential backoff para APIs externas |

**External Services:**
| Service | API Version | Purpose | Auth Method | SLA/Timeout |
|---------|------------|---------|-------------|-------------|
| Chatwoot API | v1 | Envío de templates WhatsApp | API Key (CHATWOOT_API_KEY) | 10s timeout, 3 retries |
| Google Calendar API | v3 | Actualización de emojis en eventos | Service Account JSON | 5s timeout, 3 retries |
| PostgreSQL | 15+ | Primary data store | Password auth | Connection pool (default) |
| WhatsApp Business API | (via Chatwoot) | Delivery de templates a clientes | Managed by Chatwoot | N/A (async) |

**Integration Points:**

**1. Chatwoot Template Sending**
```python
# Endpoint: POST /api/v1/accounts/{account_id}/conversations/{conv_id}/messages
# Auth: Bearer {CHATWOOT_API_KEY}
# Constraint: Plantillas deben estar aprobadas por Meta (requiere gestión en Meta Business Suite)
# Error Handling: Retry 3x, mark notification_failed si persiste fallo
```

**2. Google Calendar Event Updates**
```python
# API: Calendar.events().patch(calendarId, eventId, body)
# Auth: Service Account with domain-wide delegation
# Constraint: Service account debe tener permisos en calendarios de estilistas
# Error Handling: Retry 3x, log error pero no bloquea worker
```

**3. PostgreSQL Queries**
```python
# Connection: Async pool via asyncpg (SQLAlchemy engine)
# Constraint: Índices condicionales requeridos para performance (ver Data Models)
# Transaction Isolation: READ COMMITTED con SELECT FOR UPDATE para locks
```

**Configuration Dependencies:**

**Environment Variables (NEW):**
```bash
# Worker timing configuration
REMINDER_WORKER_INTERVAL_MINUTES=15      # Worker cycle frequency
CONFIRMATION_WINDOW_HOURS=48             # Enviar confirmación 48h antes
CONFIRMATION_TIMEOUT_HOURS=24            # Cancelar si no responde en 24h

# Existing vars reused
DATABASE_URL=postgresql+asyncpg://...
CHATWOOT_API_URL=https://...
CHATWOOT_API_KEY=...
CHATWOOT_ACCOUNT_ID=...
GOOGLE_APPLICATION_CREDENTIALS=/app/service-account-key.json
```

**Docker Image Dependencies:**
```yaml
# Base image: python:3.11-slim
# System packages: libpq-dev, gcc, postgresql-client, procps
# Volumes: service-account-key.json (read-only)
```

**Meta WhatsApp Business Templates (External Approval Required):**
- ✅ `confirmacion_cita` - Already exists
- ❌ `recordatorio_cita` - Needs creation and Meta approval (1-2 days)
- ❌ `cancelacion_no_confirmada` - Needs creation and Meta approval (1-2 days)

**Dependency on Epic 1:**
- `book()` tool debe estar funcional y crear appointments con `status=PENDING`
- Google Calendar integration debe estar operativa (evento con emoji 🟡)
- Customer creation debe poblar `chatwoot_conversation_id` en primera interacción

## Acceptance Criteria (Authoritative)

Epic 2 será considerada completa cuando se cumplan todos los siguientes criterios:

**AC1: Worker Operational**
- El worker `appointment_reminder` ejecuta cada 15 minutos sin crashes
- Health check responde correctamente (`pgrep python`)
- Logs estructurados muestran cada ciclo de ejecución

**AC2: Confirmación 48h Enviada (FR13)**
- Citas con `status=pending` y `start_time` en ventana 47-49h reciben template "confirmacion_cita"
- Campo `confirmation_sent_at` se actualiza con timestamp correcto
- Template incluye: nombre cliente, fecha formatted, hora, nombre estilista

**AC3: Detección de Confirmación (FR14, FR15, FR16)**
- Agent detecta respuestas afirmativas ("sí", "confirmo", "ok", "perfecto", "claro")
- Solo confirma si existe cita `pending` con `confirmation_sent_at` en últimas 24h
- Al confirmar: `status` cambia a `confirmed`
- Emoji en Calendar se actualiza de 🟡 a 🟢

**AC4: Recordatorio 24h Enviado (FR17)**
- Citas con `status=confirmed` y `start_time` en ventana 23-25h reciben template "recordatorio_cita"
- Campo `reminder_sent_at` se actualiza con timestamp correcto
- Solo se envía a citas previamente confirmadas (no a pending)

**AC5: Cancelación Automática por Timeout (FR18, FR19, FR20)**
- Citas con `confirmation_sent_at` >24h sin cambio de status se cancelan automáticamente
- `status` cambia a `cancelled`, `cancelled_at` se setea
- Evento de Google Calendar se elimina completamente
- Cliente recibe template "cancelacion_no_confirmada" con fecha/hora de la cita cancelada

**AC6: Error Handling Robusto (NFR4, NFR6)**
- Template send failures retintentan 3x con exponential backoff
- Si falla después de 3 retries: marca `notification_failed=TRUE` pero NO cancela cita
- Worker es idempotente: re-ejecución no duplica mensajes
- Race conditions manejadas con `SELECT FOR UPDATE`

**AC7: Performance Compliance (NFR2)**
- Worker procesa 100 citas en <120 segundos
- Template send latency <2 segundos per message
- Calendar update latency <3 segundos per event

**AC8: Data Integrity (NFR5)**
- Alembic migration ejecuta sin errores
- Campos nuevos creados: `confirmation_sent_at`, `reminder_sent_at`, `cancelled_at`, `notification_failed`, `chatwoot_conversation_id`
- Enum `AppointmentStatus` renombrado correctamente (CONFIRMED→PENDING, nuevo CONFIRMED)
- Índices condicionales creados y funcionales

**AC9: Integration Testing**
- End-to-end test: Book cita → Worker envía confirmación → Agent detecta confirmación → Emoji actualizado → Recordatorio enviado
- End-to-end test: Book cita → Worker envía confirmación → No respuesta → Timeout cancela → Notificación enviada → Calendar deleted
- Manual testing via WhatsApp con 5 escenarios (happy path, timeout, multiple appointments, edge cases)

## Traceability Mapping

| AC | PRD FR | Spec Section | Component/Module | Test Idea |
|----|--------|--------------|------------------|-----------|
| AC1 | N/A (Infrastructure) | Services and Modules | `appointment_reminder` worker | Unit test: worker loop execution, healthcheck |
| AC2 | FR13 | Workflows: Confirmación 48h | `process_48h_confirmations()`, `chatwoot_client.send_template()` | Integration test: mock DB query, verify template sent |
| AC3 | FR14, FR15, FR16 | Workflows: Cliente Confirma | `conversational_agent.py`, `update_calendar_event_emoji()` | E2E test: simulate user message "sí", verify status change + Calendar update |
| AC4 | FR17 | Workflows: Recordatorio 24h | `process_24h_reminders()`, `chatwoot_client.send_template()` | Integration test: mock confirmed appointments, verify reminder sent |
| AC5 | FR18, FR19, FR20 | Workflows: Timeout Cancelación | `process_confirmation_timeouts()`, `delete_calendar_event()` | E2E test: simulate timeout (24h elapsed), verify cancellation + notification |
| AC6 | NFR4, NFR6 | APIs: Chatwoot Client, Reliability | `send_template()` with tenacity retries | Unit test: mock API failures, verify retry logic + notification_failed flag |
| AC7 | NFR2 | Performance | Worker query optimization, indexes | Load test: 100 appointments, measure cycle time <120s |
| AC8 | NFR5 | Data Models | Alembic migration, Appointment/Customer models | Migration test: run upgrade/downgrade, verify schema |
| AC9 | Integration | All sections | Full system (Worker + Agent + Chatwoot + Calendar) | Manual testing: Real WhatsApp conversations with 5 scenarios |

**Coverage Matrix:**

| PRD Requirement | AC Coverage | Implementation Files |
|-----------------|-------------|---------------------|
| FR13: Send confirmation 48h | AC2 | `appointment_reminder.py`, `chatwoot_client.py` |
| FR14: Detect affirmative response | AC3 | `conversational_agent.py` |
| FR15: Update Calendar emoji 🟢 | AC3 | `booking_tools.py::update_calendar_event_emoji()` |
| FR16: Update status to CONFIRMED | AC3 | `conversational_agent.py` (DB update) |
| FR17: Send reminder 24h | AC4 | `appointment_reminder.py::process_24h_reminders()` |
| FR18: Auto-cancel after 24h timeout | AC5 | `appointment_reminder.py::process_confirmation_timeouts()` |
| FR19: Delete Calendar event on cancel | AC5 | `booking_tools.py::delete_calendar_event()` |
| FR20: Notify client of cancellation | AC5 | `chatwoot_client.py::send_template("cancelacion_no_confirmada")` |
| NFR2: Worker <2 min | AC7 | Worker loop + DB indexes |
| NFR4: Handle API errors | AC6 | `chatwoot_client.py` retry logic |
| NFR5: DB persistence first | AC8 | `book()` tool order of operations |
| NFR6: Idempotent worker | AC6 | Timestamp-based locking logic |

## Risks, Assumptions, Open Questions

**Risks:**

| ID | Risk | Probability | Impact | Mitigation |
|----|------|-------------|--------|------------|
| R1 | Meta rechaza nuevas plantillas WhatsApp | Media | Alto | Preparar contenido de plantillas siguiendo guías de Meta, submit con 1 semana de anticipación |
| R2 | Cliente responde confirmación fuera de ventana 24h | Alta | Medio | Agent informa que cita ya cancelada, ofrece reagendar (Epic 3) |
| R3 | Race condition entre confirmación y timeout | Baja | Alto | `SELECT FOR UPDATE` + double-check status antes de cancelar |
| R4 | Worker crash durante cancelación masiva | Media | Medio | Idempotencia natural via timestamps, restart recupera sin duplicados |
| R5 | Chatwoot API rate limiting | Baja | Alto | Batch processing (max 100/cycle), exponential backoff, monitorear error rates |
| R6 | Google Calendar API quota exceeded | Baja | Medio | Implementar circuit breaker, cache calendar IDs, monitorear quota usage |
| R7 | Cliente tiene múltiples citas pendientes | Media | Bajo | Agent lista todas y pide especificar, timeout cancela todas si no responde |
| R8 | Timezone issues (DST changes) | Media | Alto | Usar `Europe/Madrid` timezone explícitamente, test DST transitions |

**Assumptions:**

| ID | Assumption | Validation Strategy |
|----|-----------|---------------------|
| A1 | Epic 1 completada con `book()` funcional y creando `status=PENDING` | Verificar en Epic 1 DoD, manual testing |
| A2 | Plantilla "confirmacion_cita" ya existe y está aprobada | Verificar en Meta Business Suite antes de empezar Epic 2 |
| A3 | Customers tienen `chatwoot_conversation_id` poblado en primera interacción | Verificar en `process_incoming_message`, agregar migración si falta |
| A4 | Estilistas tienen permisos configurados para que service account actualice Calendar | Testing manual, verificar domain-wide delegation |
| A5 | Clientes responden dentro de 24h en la mayoría de casos | Monitorear tasas de confirmación en producción, ajustar timeout si needed |
| A6 | Worker interval de 15 minutos es suficiente (no requiere real-time) | Validado por negocio, ventanas de 48h/24h no requieren precisión de minutos |
| A7 | PostgreSQL puede manejar queries cada 15 minutos sin performance issues | Load testing con 1000+ appointments, verificar índices funcionan |

**Open Questions:**

| ID | Question | Owner | Status | Resolution |
|----|----------|-------|--------|------------|
| Q1 | ¿Qué hacer si cliente responde "no puedo" (rechaza confirmación)? | Product | Open | Considerar en Epic 3 (cancelación), por ahora trata como no-confirmación |
| Q2 | ¿Enviar recordatorio también a citas PENDING (no confirmadas)? | Product | Open | **Decision needed**: PRD dice solo a CONFIRMED, confirmar con negocio |
| Q3 | ¿Cancelar solo citas >24h en el futuro o todas? | Product | Open | Assumption: Todas las pending sin confirmar, incluso mismo día |
| Q4 | ¿Notificar a estilistas cuando cita es cancelada por timeout? | Product | Deferred | Post-MVP feature, Epic 2 solo notifica a cliente |
| Q5 | ¿Cómo manejar clientes que nunca responden (patron repeat)? | Product/Tech | Open | Considerar flag "always_no_show" en Customer model (Post-MVP) |
| Q6 | ¿Límite de reintentos para notification_failed? | Tech | Open | **Decision needed**: ¿Worker reintenta en siguiente ciclo o flag permanente? |

## Test Strategy Summary

**Testing Levels:**

**1. Unit Tests (pytest)**
- **Target Coverage:** >85% for new code
- **Scope:**
  - `appointment_reminder.py`: Worker functions (`process_48h_confirmations`, `process_24h_reminders`, `process_confirmation_timeouts`)
  - `chatwoot_client.py`: `send_template()` with mocked httpx responses
  - `booking_tools.py`: `update_calendar_event_emoji()` with mocked Google Calendar API
  - Helper functions: date formatting, affirmative response detection
- **Mocking Strategy:**
  - Database: pytest fixtures with in-memory SQLite or transaction rollback
  - Chatwoot API: Mock httpx responses (200 OK, 400 error, timeout)
  - Google Calendar API: Mock googleapiclient.discovery service
  - Redis: No mocking needed (worker doesn't use Redis)
- **Test Files:**
  - `tests/unit/test_appointment_reminder.py`
  - `tests/unit/test_chatwoot_client.py`
  - `tests/unit/test_booking_tools.py`

**2. Integration Tests (pytest-asyncio)**
- **Scope:**
  - Worker ↔ PostgreSQL: Real DB queries con test database
  - Agent ↔ Calendar: Real Calendar API calls con test calendar
  - Agent ↔ Chatwoot: Mocked (no enviar templates reales en tests)
- **Test Scenarios:**
  - Full confirmation flow: Book → 48h window → template sent → confirmation_sent_at updated
  - Full timeout flow: Book → 48h window → no response → 24h elapsed → cancelled
  - Race condition handling: Simulate concurrent confirmation + timeout
  - Retry logic: Simulate API failures, verify exponential backoff
- **Test Files:**
  - `tests/integration/test_reminder_worker.py`
  - `tests/integration/test_confirmation_flow.py`

**3. End-to-End Tests (Manual + Automated)**
- **Automated E2E (pytest):**
  - Mock time advancement (freeze_time) para simular ventanas temporales
  - Full system test: DB + Worker + Agent (mocked Chatwoot/Calendar)
  - Verify state transitions: PENDING → CONFIRMED → reminder sent
  - Verify timeout: PENDING → (24h) → CANCELLED
- **Manual E2E (WhatsApp):**
  - **Scenario 1 (Happy Path):** Book cita → Recibir confirmación → Responder "sí" → Recibir recordatorio
  - **Scenario 2 (Timeout):** Book cita → Recibir confirmación → No responder → Recibir cancelación después 24h
  - **Scenario 3 (Multiple Appointments):** Book 2 citas → Confirmar solo una → Verificar estados correctos
  - **Scenario 4 (Edge Case):** Responder confirmación después de 24h → Agent informa que ya cancelada
  - **Scenario 5 (API Failure Recovery):** Simular fallo Chatwoot → Verificar retry → Verificar notification_failed flag
- **Test Environment:**
  - Development DB (isolated from production)
  - Test WhatsApp number
  - Test Google Calendar (no calendarios de estilistas reales)

**4. Migration Tests**
- **Scope:**
  - Alembic upgrade: Verify new columns created, enum renamed
  - Alembic downgrade: Verify rollback funciona sin data loss
  - Data migration: Verify status CONFIRMED→PENDING actualizado correctamente
- **Test Files:**
  - `tests/integration/test_alembic_migrations.py`

**5. Performance Tests (pytest-benchmark)**
- **Scope:**
  - Worker cycle time con 100 appointments: <120s (NFR2)
  - DB query performance con índices: <500ms
  - Template send latency: <2s per message
- **Load Testing:**
  - Simulate 1000 appointments en ventana 48h
  - Measure worker cycle completion time
  - Verify no memory leaks en worker loop

**6. Security Tests**
- **Scope:**
  - SQL injection: Verify parametrized queries (automated via SQLAlchemy)
  - Credential exposure: Verify env vars not logged
  - Authorization: Verify worker solo accede appointments válidos
- **Manual Review:**
  - Code review de logging statements (no tokens/keys)
  - Review de template parameter sanitization

**Test Execution Strategy:**

```bash
# Unit tests (fast, run frequently)
pytest tests/unit/ -v

# Integration tests (slower, run before PR)
DATABASE_URL="postgresql+asyncpg://test:test@localhost:5432/test_db" \
  pytest tests/integration/ -v

# Coverage report
pytest --cov=agent --cov=shared --cov-report=html

# Performance tests
pytest tests/performance/ -v --benchmark-only
```

**Coverage Targets:**
- Unit tests: >90% coverage of new worker code
- Integration tests: All AC scenarios covered
- E2E tests: 5 manual scenarios documented and executed
- Total coverage: >85% (proyecto requirement)

**Test Documentation:**
- Test plan document: `docs/testing/epic-2-test-plan.md`
- Test results log: `docs/testing/epic-2-test-results.md`
- Manual test checklist: `docs/testing/epic-2-manual-tests.md`
