# Story 1.2: Corrección de Herramienta book() con Emoji Calendar

Status: ready-for-dev

## Story

As a **cliente**,
I want **que mi reserva se complete exitosamente**,
so that **pueda tener mi cita confirmada en el calendario del estilista**.

## Acceptance Criteria

1. **AC1**: El sistema crea registro en tabla `appointments` con estado PENDING
   - Given el cliente ha seleccionado servicio, estilista y horario
   - When el sistema ejecuta la herramienta `book()`
   - Then se crea registro en BD con status='PENDING'
   - And los campos obligatorios están poblados (customer_id, stylist_id, service_ids, start_time, end_time, first_name)

2. **AC2**: El sistema crea evento en Google Calendar con emoji 🟡 en título
   - Given el registro de cita se creó exitosamente en BD
   - When el sistema llama a Google Calendar API
   - Then se crea evento con título en formato `🟡 {first_name} - {service_name}`
   - And el evento tiene descripción con servicios y notas
   - And la zona horaria es 'Europe/Madrid'

3. **AC3**: El sistema guarda `google_calendar_event_id` en la cita
   - Given el evento de Calendar se creó exitosamente
   - When Calendar API retorna el event_id
   - Then se guarda en campo `google_calendar_event_id` de la cita

4. **AC4**: El sistema guarda `chatwoot_conversation_id` en el customer
   - Given el sistema recibe el conversation_id del contexto
   - When ejecuta book()
   - Then actualiza campo `chatwoot_conversation_id` en la tabla customers

5. **AC5**: El mensaje de confirmación informa sobre confirmación 48h antes
   - Given la cita se creó exitosamente
   - When el sistema retorna respuesta
   - Then el mensaje incluye información sobre confirmación 48h antes
   - And el tono es amigable y profesional en español

6. **AC6**: Se hace rollback de transacción si falla Calendar
   - Given el registro de cita se creó en BD
   - When la creación de evento en Calendar falla
   - Then se hace rollback de la transacción DB
   - And NO queda registro en tabla appointments
   - And se retorna mensaje de error claro con opción de reintentar

## Tasks / Subtasks

- [ ] **Task 1: Analizar error actual en book()** (AC: 1, 6)
  - [ ] 1.1 Leer código actual de `agent/tools/booking_tools.py`
  - [ ] 1.2 Identificar causa del error que impide completar reservas
  - [ ] 1.3 Revisar logs de errores existentes si están disponibles
  - [ ] 1.4 Documentar problema específico y solución propuesta

- [ ] **Task 2: Implementar transacción atómica DB + Calendar** (AC: 1, 2, 3, 6)
  - [ ] 2.1 Refactorizar book() para usar `async with session.begin()` como context manager
  - [ ] 2.2 Crear registro de appointment con status=PENDING
  - [ ] 2.3 Usar `session.flush()` para obtener ID antes de Calendar
  - [ ] 2.4 Llamar a Google Calendar API dentro del bloque transaccional
  - [ ] 2.5 Si Calendar falla, el rollback es automático (no commit)
  - [ ] 2.6 Si Calendar OK, guardar event_id y hacer commit

- [ ] **Task 3: Integrar creación de evento Calendar con emoji** (AC: 2, 3)
  - [ ] 3.1 Crear función helper `create_calendar_event()` en booking_tools.py
  - [ ] 3.2 Formatear título: `f"🟡 {first_name} - {service_names}"`
  - [ ] 3.3 Agregar descripción con lista de servicios y notas del cliente
  - [ ] 3.4 Configurar zona horaria 'Europe/Madrid'
  - [ ] 3.5 Implementar timeout de 3 segundos (NFR3)
  - [ ] 3.6 Implementar retry 1x para errores transitorios con tenacity

- [ ] **Task 4: Guardar chatwoot_conversation_id** (AC: 4)
  - [ ] 4.1 Recibir conversation_id como parámetro en book() (desde estado de conversación)
  - [ ] 4.2 Actualizar campo `chatwoot_conversation_id` en customer si no existe
  - [ ] 4.3 Verificar que el campo se creó en Story 1.1 (migración)

- [ ] **Task 5: Mejorar mensaje de confirmación** (AC: 5)
  - [ ] 5.1 Actualizar response message con información de confirmación 48h
  - [ ] 5.2 Formato sugerido: "¡Cita confirmada! 🎉 Te enviaremos un mensaje 48 horas antes para confirmar tu asistencia."
  - [ ] 5.3 Incluir detalles: fecha, hora, estilista, servicios
  - [ ] 5.4 Tono amigable y profesional en español

- [ ] **Task 6: Manejo de errores y mensajes claros** (AC: 6)
  - [ ] 6.1 Capturar GoogleCalendarError y otras excepciones
  - [ ] 6.2 Retornar dict con status="error", message claro, error_code
  - [ ] 6.3 Mensaje ejemplo: "No pudimos completar tu reserva. Por favor, intenta de nuevo o contacta con el salón."
  - [ ] 6.4 Loggear error con contexto completo para debugging

- [ ] **Task 7: Testing unitario** (AC: 1-6)
  - [ ] 7.1 Test: book() crea cita con status PENDING
  - [ ] 7.2 Test: book() crea evento Calendar con emoji 🟡 correcto
  - [ ] 7.3 Test: book() guarda google_calendar_event_id
  - [ ] 7.4 Test: book() guarda chatwoot_conversation_id en customer
  - [ ] 7.5 Test: book() hace rollback si Calendar falla (mock Calendar error)
  - [ ] 7.6 Test: mensaje de confirmación incluye info 48h
  - [ ] 7.7 Test: timeout de 3s configurado correctamente
  - [ ] 7.8 Verificar cobertura >85% para código nuevo

- [ ] **Task 8: Testing de integración** (AC: 1-6)
  - [ ] 8.1 Test end-to-end: flujo completo de booking con Calendar real (staging)
  - [ ] 8.2 Test: verificar evento aparece en Google Calendar con emoji
  - [ ] 8.3 Test: rollback funciona cuando Calendar API no disponible
  - [ ] 8.4 Test: múltiples servicios se reflejan correctamente en descripción

## Dev Notes

### Learnings from Previous Story

**From Story 1-1-migracion-de-estados-y-campos-de-tracking (Status: done)**

**New Fields Available:**
- `Appointment.confirmation_sent_at` (nullable TIMESTAMP) - Usable para tracking de confirmaciones futuras
- `Appointment.reminder_sent_at` (nullable TIMESTAMP) - Para recordatorios 24h
- `Appointment.cancelled_at` (nullable TIMESTAMP) - Registro de cancelación
- `Appointment.notification_failed` (BOOLEAN default false) - Flag si falló envío de plantilla
- `Customer.chatwoot_conversation_id` (VARCHAR nullable) - **USAR en Task 4 de esta story**

**Enum Updated:**
- `AppointmentStatus.PENDING` = "pending" - **USAR este valor al crear citas** (reemplaza el anterior CONFIRMED)
- `AppointmentStatus.CONFIRMED` = "confirmed" - Reservado para cuando cliente confirme asistencia
- Estados eliminados: PROVISIONAL, EXPIRED

**Database Indexes Created:**
- `idx_appointments_confirmation_pending` - Para queries del worker (Epic 2)
- `idx_appointments_customer_active` - Para buscar citas activas del cliente

**Key Decisions from Story 1.1:**
- Default value en `Appointment.status` cambió a PENDING (antes era PROVISIONAL)
- Migración es reversible (tested upgrade → downgrade → upgrade)
- Campos timestamp son nullable para permitir estados intermedios

**Files to Reference:**
- `database/models.py:68-75` - AppointmentStatus enum
- `database/models.py:362-374` - Appointment model con campos tracking
- `database/models.py:199-202` - Customer model con chatwoot_conversation_id
- `database/alembic/versions/62769e850a51_add_confirmation_tracking_fields.py` - Migración aplicada

### Contexto Arquitectural

**Patrón: Async Confirmation Loop**

Esta story implementa la primera fase del patrón definido en Architecture:

```
PENDING ──[book()]──► confirmation_sent_at=NULL
    │
    │ Worker: 48h antes (Epic 2)
    ▼
PENDING ──[send_template()]──► confirmation_sent_at=NOW
```

**Transacción Atómica (NFR5):**

El patrón de transacción debe seguir la estrategia definida en `docs/architecture.md#Reliability/Availability`:

```python
async with session.begin():
    # 1. Crear appointment en DB
    appointment = Appointment(status=AppointmentStatus.PENDING, ...)
    session.add(appointment)
    await session.flush()  # Obtener ID

    try:
        # 2. Crear evento en Calendar
        event_id = await create_calendar_event(...)
        appointment.google_calendar_event_id = event_id
    except GoogleCalendarError as e:
        # Rollback automático por context manager
        raise BookingError(f"Error al crear evento en Calendar: {e}")

    # 3. Commit si todo OK (automático al salir del context manager)
```

**Tool Response Format:**

Seguir patrón estándar definido en Architecture:

```python
# Éxito
return {
    "status": "success",
    "message": "¡Cita confirmada! 🎉 Te enviaremos un mensaje 48 horas antes...",
    "data": {
        "appointment_id": str(appointment.id),
        "start_time": appointment.start_time.isoformat(),
        "end_time": appointment.end_time.isoformat(),
        "stylist_name": stylist.name,
        "services": [s.name for s in services],
        "google_calendar_event_id": event_id
    }
}

# Error
return {
    "status": "error",
    "message": "No pudimos completar tu reserva. Por favor, intenta de nuevo.",
    "error_code": "CALENDAR_CREATE_FAILED"
}
```

### Google Calendar Integration

**Event Format:**

```python
event = {
    'summary': f'🟡 {first_name} - {", ".join(service_names)}',
    'description': f'Servicios: {service_list}\nNotas: {notes if notes else "Sin notas"}',
    'start': {
        'dateTime': start_time.isoformat(),
        'timeZone': 'Europe/Madrid'
    },
    'end': {
        'dateTime': end_time.isoformat(),
        'timeZone': 'Europe/Madrid'
    }
}
```

**Timeout y Retry:**

Usar `tenacity` para retry con backoff:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=3))
async def create_calendar_event(...):
    # Timeout de 3s (NFR3)
    async with timeout(3):
        service = build('calendar', 'v3', credentials=credentials)
        result = service.events().insert(...).execute()
        return result['id']
```

**Service Account Credentials:**

El archivo `service-account-key.json` está montado en `/app/service-account-key.json` (read-only volume).

Verificar disponibilidad:
```bash
docker exec atrevete-agent ls -la /app/service-account-key.json
```

### Project Structure Notes

**Archivos a Modificar:**
- `agent/tools/booking_tools.py` - Refactorizar book() tool (main work)
- Posiblemente crear helper `agent/tools/calendar_helper.py` si la lógica es extensa

**No Modificar:**
- `database/models.py` - Ya actualizado en Story 1.1
- Prompts - Se actualizarán en Story 1.7

**Alineación con Estructura:**
- Seguir patrón existente de tools: una función `@tool` por herramienta
- Helpers dentro del mismo archivo o módulo separado si reutilizable
- Imports: `from database.connection import get_async_session`

### Testing Strategy

**Cobertura mínima:** 85% para código nuevo (pyproject.toml)

**Unit Tests Críticos:**
- Transacción atómica (mock Calendar API)
- Rollback en error de Calendar
- Formato de emoji en título
- Guardado de event_id y conversation_id

**Integration Tests:**
- Flujo completo con Calendar API real (staging environment)
- Verificar evento aparece en Google Calendar
- Validar emoji 🟡 en título del evento

**Comandos de Testing:**
```bash
# Unit tests para booking
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/pytest tests/unit/test_booking_tools.py -v

# Integration tests
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/pytest tests/integration/test_booking_flow.py -v
```

### FRs Cubiertos

Esta story implementa:
- **FR9**: Crear cita en BD con estado PENDING
- **FR10**: Crear evento en Google Calendar con emoji 🟡
- **FR11**: Mensaje informando sobre confirmación 48h antes
- **FR12**: Mensaje de error claro si falla y opción de reintentar

### NFRs Aplicables

- **NFR3**: Operaciones Calendar <3s (timeout configurado)
- **NFR5**: Transacción DB primero, Calendar después (rollback si falla)
- **NFR10**: Cobertura tests mínima 85%
- **NFR11**: Logs estructurados para debugging

### Comandos de Desarrollo

```bash
# Ver logs del agent worker
docker-compose logs -f agent

# Reiniciar agent tras cambios
docker-compose restart agent

# Ejecutar tests con coverage
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/pytest --cov=agent/tools/booking_tools

# Verificar Google Calendar credentials
docker exec atrevete-agent python -c "from google.oauth2 import service_account; print('Credentials OK')"
```

### References

- [Source: docs/architecture.md#Novel-Pattern-Async-Confirmation-Loop] - Patrón de confirmación asíncrona
- [Source: docs/architecture.md#ADR-002] - Decisión estados PENDING/CONFIRMED
- [Source: docs/architecture.md#Implementation-Patterns] - Tool Response Format
- [Source: docs/architecture.md#Integration-Points] - Google Calendar API contract
- [Source: docs/epics.md#Story-1.2] - Requisitos originales de la story
- [Source: docs/sprint-artifacts/tech-spec-epic-1.md#APIs-and-Interfaces] - Contrato de book() tool
- [Source: docs/sprint-artifacts/1-1-migracion-de-estados-y-campos-de-tracking.md#Dev-Agent-Record] - Learnings de Story 1.1
- [Source: docs/prd.md#FR9-FR12] - Requisitos funcionales relacionados

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2025-11-20 | Story drafted from epics, tech-spec and architecture | SM Agent |

## Dev Agent Record

### Context Reference

- docs/sprint-artifacts/1-2-correccion-de-herramienta-book-con-emoji-calendar.context.xml

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List

