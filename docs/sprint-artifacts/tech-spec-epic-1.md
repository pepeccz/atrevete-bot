# Epic Technical Specification: Corrección del Flujo de Agendamiento

Date: 2025-11-19
Author: Pepe
Epic ID: 1
Status: Draft

---

## Overview

Este Epic aborda los errores críticos que impiden completar reservas en el sistema Atrévete Bot v3.2. El flujo de agendamiento actual tiene fallos en la herramienta `book()` y carece de una experiencia de usuario consistente con listas numeradas.

El objetivo es entregar un flujo de reserva completo y sin errores que permita a los clientes: seleccionar servicios (uno o múltiples), elegir estilista, ver disponibilidad, proporcionar datos personales, y completar la reserva con un evento creado en Google Calendar. Este Epic establece la base para los Epics posteriores (confirmación 48h, cancelación/reagendamiento) al implementar correctamente los estados de cita y campos de tracking.

## Objectives and Scope

### In Scope

- **Migración de base de datos**: Renombrar estado CONFIRMED→PENDING, agregar campos de tracking (`confirmation_sent_at`, `reminder_sent_at`, `cancelled_at`, `notification_failed`, `chatwoot_conversation_id`)
- **Corrección de herramienta book()**: Arreglar error actual, crear evento Calendar con emoji 🟡, guardar `google_calendar_event_id` y `chatwoot_conversation_id`
- **Listas numeradas**: Implementar en presentación de servicios, estilistas y horarios disponibles
- **Selección múltiple de servicios**: Permitir agregar varios servicios a una cita con confirmación entre cada selección
- **Recopilación de datos del cliente**: Solicitar nombre/apellidos a nuevos clientes, confirmar datos de recurrentes
- **Actualización de prompts**: Modificar prompts para flujo completo con tono amigable en español

### Out of Scope

- Worker de recordatorios (Epic 2)
- Envío de plantillas WhatsApp proactivas (Epic 2)
- Herramientas cancel_appointment, reschedule_appointment, get_my_appointments (Epic 3)
- Mejoras de escalamiento inteligente (Epic 4)

## System Architecture Alignment

Este Epic se alinea con la arquitectura existente de LangGraph + FastAPI + PostgreSQL + Redis:

**Componentes afectados:**
- `database/models.py`: Modificar enum `AppointmentStatus`, agregar campos a `Appointment` y `Customer`
- `agent/tools/booking_tools.py`: Corregir `book()`, integrar creación de evento Calendar con emoji
- `agent/prompts/*.md`: Actualizar 6 archivos de prompts para listas numeradas y flujo completo
- `alembic/versions/`: Nueva migración para cambios de esquema

**Decisiones arquitectónicas aplicables:**
- ADR-002: Renombrar CONFIRMED→PENDING para terminología estándar
- ADR-003: Campos timestamp dedicados para tracking (vs JSONB)
- Pattern: Tool Response Format con status/message/data

**Constraints:**
- NFR5: Transacción DB primero, Calendar después (rollback si falla)
- NFR3: Timeout Calendar de 3 segundos
- NFR1: Respuesta total <5 segundos

## Detailed Design

### Services and Modules

| Módulo | Responsabilidad | Inputs | Outputs | Owner |
|--------|-----------------|--------|---------|-------|
| `database/models.py` | Definir esquema de datos con nuevos estados y campos | N/A | Modelos SQLAlchemy | Dev |
| `alembic migration` | Migrar esquema de BD de forma reversible | Modelos actualizados | Tablas modificadas | Dev |
| `agent/tools/booking_tools.py` | Crear citas con integración Calendar | Datos de reserva | Cita creada + evento Calendar | Dev |
| `agent/prompts/*.md` | Definir comportamiento conversacional | N/A | Instrucciones para LLM | Dev |
| `agent/nodes/conversational_agent.py` | Orquestar flujo con tools | Mensajes usuario | Respuestas + tool calls | Dev |

### Data Models and Contracts

**AppointmentStatus Enum (modificado):**
```python
class AppointmentStatus(str, Enum):
    PENDING = "pending"        # Agendada, esperando confirmación (antes: CONFIRMED)
    CONFIRMED = "confirmed"    # Cliente confirmó asistencia (nuevo)
    COMPLETED = "completed"    # Sin cambios
    CANCELLED = "cancelled"    # Sin cambios
    NO_SHOW = "no_show"        # Sin cambios
```

**Appointment Model (campos nuevos):**
```python
class Appointment(Base):
    # Campos existentes...

    # Nuevos campos de tracking
    confirmation_sent_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    notification_failed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
```

**Customer Model (campo nuevo):**
```python
class Customer(Base):
    # Campos existentes...

    chatwoot_conversation_id: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
```

**Índices optimizados:**
```sql
-- Para queries del worker de recordatorios (Epic 2)
CREATE INDEX idx_appointments_confirmation_pending
ON appointments (start_time, confirmation_sent_at)
WHERE status = 'pending';

-- Para buscar citas activas del cliente
CREATE INDEX idx_appointments_customer_active
ON appointments (customer_id, start_time)
WHERE status IN ('pending', 'confirmed');
```

### APIs and Interfaces

**book() Tool - Contrato actualizado:**

```python
@tool
async def book(
    customer_phone: str,
    stylist_id: str,
    service_ids: list[str],
    start_time: str,  # ISO 8601
    first_name: str,
    last_name: str = "",
    notes: str = ""
) -> dict:
    """Crear una cita para el cliente.

    Returns:
        {
            "status": "success" | "error",
            "message": str,  # Mensaje para mostrar al cliente
            "data": {
                "appointment_id": str,
                "start_time": str,
                "end_time": str,
                "stylist_name": str,
                "services": list[str],
                "google_calendar_event_id": str
            } | None
        }
    """
```

**Flujo interno de book():**
1. Validar inputs (customer existe, stylist existe, servicios existen, slot disponible)
2. Calcular duración total de servicios
3. Crear registro en `appointments` con status=PENDING
4. Actualizar `chatwoot_conversation_id` en customer
5. Crear evento en Google Calendar con título `🟡 {first_name} - {service_names}`
6. Guardar `google_calendar_event_id` en appointment
7. Commit transacción
8. Retornar resultado con mensaje de confirmación

**Error handling:**
- Si falla creación en DB: Retornar error, no crear evento Calendar
- Si falla creación en Calendar: Rollback DB, retornar error con opción de reintentar
- Timeout Calendar: 3 segundos, retry 1 vez

### Workflows and Sequencing

**Flujo de Agendamiento Completo:**

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Usuario   │     │   Agente    │     │  Sistema    │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       │ "Quiero cita"     │                   │
       ├──────────────────►│                   │
       │                   │ search_services() │
       │                   ├──────────────────►│
       │                   │◄──────────────────┤
       │ Lista numerada    │                   │
       │◄──────────────────┤                   │
       │                   │                   │
       │ "1" o "corte"     │                   │
       ├──────────────────►│                   │
       │                   │                   │
       │ "¿Agregar más?"   │                   │
       │◄──────────────────┤                   │
       │                   │                   │
       │ "No"              │                   │
       ├──────────────────►│                   │
       │                   │ find_next_avail() │
       │                   ├──────────────────►│
       │                   │◄──────────────────┤
       │ Estilistas+Slots  │                   │
       │◄──────────────────┤                   │
       │                   │                   │
       │ "Ana, mañana 10h" │                   │
       ├──────────────────►│                   │
       │                   │                   │
       │ "¿Nombre?"        │                   │
       │◄──────────────────┤                   │
       │                   │                   │
       │ "María López"     │                   │
       ├──────────────────►│                   │
       │                   │ book()            │
       │                   ├──────────────────►│
       │                   │   → DB INSERT     │
       │                   │   → Calendar API  │
       │                   │◄──────────────────┤
       │ Confirmación 🎉   │                   │
       │◄──────────────────┤                   │
```

**Estados de booking en state.py:**
- `service_selected: str | None` - Servicio(s) seleccionado(s)
- `slot_selected: dict | None` - Slot seleccionado `{stylist_id, start_time, duration}`
- `customer_data_collected: bool` - Datos del cliente recopilados
- `appointment_created: bool` - Cita creada exitosamente

## Non-Functional Requirements

### Performance

| Requisito | Target | Estrategia |
|-----------|--------|------------|
| NFR1: Respuesta bot | <5s | Prompts optimizados, caching de estilistas |
| NFR3: Operaciones Calendar | <3s | Timeout en API calls, retry 1x |
| Búsqueda servicios | <1s | Max 5 resultados por búsqueda |

**Métricas a monitorear:**
- Tiempo total de flujo de agendamiento
- Latencia de llamadas a Google Calendar API
- Tokens por request (objetivo: 2,500-3,000 con caching)

### Security

| Aspecto | Implementación |
|---------|----------------|
| Validación de propiedad | Verificar que customer_phone coincide con el cliente de la conversación |
| Credenciales Calendar | Service account key montado read-only en container |
| Datos sensibles | Phone numbers en formato E.164, no logs de datos personales completos |

**Validación de inputs en book():**
```python
# Validar que el customer existe y pertenece al phone
customer = await get_customer_by_phone(customer_phone)
if not customer:
    return {"status": "error", "message": "Cliente no encontrado"}

# Validar que el stylist existe
stylist = await get_stylist_by_id(stylist_id)
if not stylist:
    return {"status": "error", "message": "Estilista no encontrado"}

# Validar que los servicios existen
for service_id in service_ids:
    service = await get_service_by_id(service_id)
    if not service:
        return {"status": "error", "message": f"Servicio {service_id} no encontrado"}
```

### Reliability/Availability

| Aspecto | Estrategia |
|---------|------------|
| NFR5: Transacción atómica | DB primero, Calendar después; rollback si Calendar falla |
| Retry Calendar | 1 retry con backoff para errores transitorios |
| Error recovery | Mensaje claro al usuario con opción de reintentar |

**Patrón de transacción:**
```python
async with session.begin():
    # 1. Crear appointment en DB
    appointment = Appointment(...)
    session.add(appointment)
    await session.flush()  # Get ID

    try:
        # 2. Crear evento en Calendar
        event_id = await create_calendar_event(...)
        appointment.google_calendar_event_id = event_id
    except GoogleCalendarError as e:
        # Rollback automático por context manager
        raise BookingError(f"Error al crear evento: {e}")

    # 3. Commit si todo OK
```

### Observability

**Logging estructurado:**
```python
logger.info("appointment_created", extra={
    "appointment_id": str(appointment.id),
    "customer_phone": customer_phone,
    "stylist_id": stylist_id,
    "services": service_ids,
    "start_time": start_time,
    "calendar_event_id": event_id
})
```

**Métricas a trackear:**
- `booking_success_count`: Contador de reservas exitosas
- `booking_error_count`: Contador de errores por tipo
- `calendar_api_latency`: Histograma de latencia Calendar
- `booking_flow_duration`: Tiempo total del flujo

**Alertas:**
- Error rate >5% en booking → Alert
- Calendar API latency >3s → Warning

## Dependencies and Integrations

### Dependencies Existentes

| Dependencia | Versión | Propósito |
|-------------|---------|-----------|
| langchain-core | 0.3.0+ | Tool definitions |
| sqlalchemy | 2.0+ | ORM async |
| alembic | 1.13+ | Migrations |
| google-api-python-client | 2.x | Calendar API |
| tenacity | 8.x | Retries |

### Integraciones

| Servicio | Propósito | Auth |
|----------|-----------|------|
| Google Calendar API v3 | Crear eventos con emoji | Service Account |
| PostgreSQL 15+ | Persistencia de citas | Password auth |
| Redis Stack | State checkpointing | No auth (local) |

### Integration Points

**Google Calendar - Crear evento:**
```python
service = build('calendar', 'v3', credentials=credentials)
event = {
    'summary': f'🟡 {customer_name} - {service_name}',
    'description': f'Servicios: {services}\nNotas: {notes}',
    'start': {'dateTime': start_time.isoformat(), 'timeZone': 'Europe/Madrid'},
    'end': {'dateTime': end_time.isoformat(), 'timeZone': 'Europe/Madrid'},
}
created_event = service.events().insert(
    calendarId=stylist.google_calendar_id,
    body=event
).execute()
return created_event['id']
```

## Acceptance Criteria (Authoritative)

### Migración y Modelo de Datos

1. **AC1.1**: La migración de Alembic es reversible y no pierde datos existentes
2. **AC1.2**: El enum `AppointmentStatus` contiene: PENDING, CONFIRMED, COMPLETED, CANCELLED, NO_SHOW
3. **AC1.3**: Todas las citas existentes con status CONFIRMED se migran a PENDING
4. **AC1.4**: Los campos `confirmation_sent_at`, `reminder_sent_at`, `cancelled_at` son nullable
5. **AC1.5**: El índice `idx_appointments_confirmation_pending` existe y es funcional
6. **AC1.6**: El campo `chatwoot_conversation_id` existe en la tabla `customers`

### Herramienta book()

7. **AC2.1**: `book()` crea registro en DB con status=PENDING antes de crear evento Calendar
8. **AC2.2**: El evento de Calendar tiene emoji 🟡 en el título
9. **AC2.3**: El `google_calendar_event_id` se guarda en la cita
10. **AC2.4**: El `chatwoot_conversation_id` se guarda en el customer
11. **AC2.5**: Si falla Calendar, se hace rollback de la transacción DB
12. **AC2.6**: El mensaje de confirmación informa sobre confirmación 48h antes
13. **AC2.7**: El timeout de Calendar es de 3 segundos con 1 retry

### Listas Numeradas

14. **AC3.1**: Los servicios se presentan en formato lista numerada con nombre y duración
15. **AC3.2**: Los estilistas se presentan en lista numerada
16. **AC3.3**: Los horarios disponibles se presentan en lista numerada (max 5)
17. **AC3.4**: El sistema acepta respuestas por número o por texto descriptivo

### Selección Múltiple

18. **AC4.1**: Después de seleccionar un servicio, el sistema pregunta "¿Deseas agregar otro?"
19. **AC4.2**: El sistema muestra desglose con duración total combinada
20. **AC4.3**: El sistema permite agregar hasta 5 servicios por cita

### Datos del Cliente

21. **AC5.1**: Si es cliente nuevo, solicita nombre y apellidos
22. **AC5.2**: Si es cliente recurrente, confirma datos existentes
23. **AC5.3**: El sistema permite agregar notas opcionales a la cita

### Prompts y UX

24. **AC6.1**: El agente mantiene contexto entre mensajes del flujo
25. **AC6.2**: El tono es amigable y profesional en español
26. **AC6.3**: Los mensajes de error son claros y ofrecen opción de reintentar
27. **AC6.4**: El sistema maneja mensajes de audio transcribiéndolos

## Traceability Mapping

| AC | Spec Section | Component/API | Test Idea |
|----|--------------|---------------|-----------|
| AC1.1 | Data Models | `alembic migration` | Test upgrade + downgrade |
| AC1.2 | Data Models | `AppointmentStatus` | Unit test enum values |
| AC1.3 | Data Models | Migration script | Integration test existing data |
| AC1.4 | Data Models | `Appointment` model | Unit test nullable fields |
| AC1.5 | Data Models | PostgreSQL index | Query explain plan |
| AC1.6 | Data Models | `Customer` model | Unit test field exists |
| AC2.1 | Workflows | `book()` | Unit test transaction order |
| AC2.2 | Workflows | Calendar integration | Unit test event title format |
| AC2.3 | Workflows | `book()` | Unit test event_id saved |
| AC2.4 | Workflows | `book()` | Unit test conversation_id saved |
| AC2.5 | Reliability | `book()` | Unit test rollback on Calendar error |
| AC2.6 | Workflows | `book()` | Unit test response message content |
| AC2.7 | Performance | Calendar client | Unit test timeout config |
| AC3.1-3.4 | APIs | Prompts | Integration test numbered lists |
| AC4.1-4.3 | Workflows | Prompts + state | Integration test multi-service |
| AC5.1-5.3 | Workflows | Prompts | Integration test customer data |
| AC6.1-6.4 | Workflows | Agent node | Integration test conversation flow |

## Risks, Assumptions, Open Questions

### Risks

| ID | Tipo | Descripción | Mitigación |
|----|------|-------------|------------|
| R1 | Risk | Migración de enum puede fallar con citas activas | Test en staging con datos reales; migration reversible |
| R2 | Risk | Google Calendar API rate limiting durante uso intensivo | Implementar retry con backoff; monitorear quotas |
| R3 | Risk | Timeout de 3s insuficiente para Calendar en momentos de alta latencia | Monitorear P99 latency; ajustar si necesario |

### Assumptions

| ID | Tipo | Descripción |
|----|------|-------------|
| A1 | Assumption | Todas las citas existentes con CONFIRMED pueden migrarse a PENDING sin afectar operación |
| A2 | Assumption | Los estilistas revisan Google Calendar regularmente para ver citas |
| A3 | Assumption | Los clientes entienden el formato de listas numeradas |
| A4 | Assumption | El servicio de Google Calendar tiene >99% uptime |

### Open Questions

| ID | Tipo | Pregunta | Siguiente Paso |
|----|------|----------|----------------|
| Q1 | Question | ¿Límite máximo de servicios por cita? | Propuesto: 5 servicios; validar con negocio |
| Q2 | Question | ¿Mensaje exacto sobre confirmación 48h? | Definir copy con negocio |
| Q3 | Question | ¿Qué hacer si cliente tiene datos incompletos (solo nombre)? | Propuesto: solicitar apellido; validar |

## Test Strategy Summary

### Test Levels

| Nivel | Cobertura | Herramientas |
|-------|-----------|--------------|
| Unit Tests | 85%+ | pytest, pytest-asyncio |
| Integration Tests | Flujos críticos | pytest, docker-compose |
| Manual Testing | Escenarios edge | WhatsApp real |

### Unit Tests

**Archivos a crear:**
- `tests/unit/test_booking_migration.py`: Test enum values, nullable fields
- `tests/unit/test_booking_tools.py`: Test book() logic, error handling, rollback

**Casos críticos:**
- book() crea cita con status PENDING
- book() crea evento Calendar con emoji correcto
- book() hace rollback si Calendar falla
- book() valida inputs correctamente

### Integration Tests

**Archivos a crear:**
- `tests/integration/test_booking_flow.py`: Test flujo completo de agendamiento

**Escenarios:**
1. Cliente nuevo completa reserva exitosamente
2. Cliente recurrente completa reserva con datos confirmados
3. Cliente selecciona múltiples servicios
4. Error en Calendar hace rollback de DB
5. Cliente responde con número y con texto

### Edge Cases

- Cliente sin nombre (solo teléfono)
- Servicio muy largo que cruza horario de cierre
- Slot seleccionado ya no disponible al momento de book()
- Google Calendar API temporalmente no disponible
- Múltiples servicios con diferentes estilistas (no permitido)

### Coverage Target

- **Mínimo:** 85% para código nuevo
- **Crítico:** 100% para `book()` tool y migración
- **Excluido:** admin/, migrations (excepto logic), tests/

