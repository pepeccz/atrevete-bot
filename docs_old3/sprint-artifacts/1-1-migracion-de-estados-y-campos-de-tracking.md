# Story 1.1: Migración de Estados y Campos de Tracking

Status: done

## Story

As a **desarrollador**,
I want **actualizar el modelo de datos con nuevos estados y campos de tracking**,
so that **el sistema soporte el ciclo completo de confirmación de citas**.

## Acceptance Criteria

1. **AC1**: El enum `AppointmentStatus` tiene valores: PENDING, CONFIRMED, COMPLETED, CANCELLED, NO_SHOW
   - Given el esquema actual de base de datos
   - When se ejecuta la migración de Alembic
   - Then el enum tiene los 5 valores correctos

2. **AC2**: La tabla `appointments` tiene campos timestamp de tracking
   - Given la migración se ejecuta
   - When se inspecciona la tabla
   - Then existen: `confirmation_sent_at`, `reminder_sent_at`, `cancelled_at` (nullable TIMESTAMP WITH TIME ZONE)
   - And existe: `notification_failed` (BOOLEAN default false)

3. **AC3**: La tabla `customers` tiene campo `chatwoot_conversation_id`
   - Given la migración se ejecuta
   - When se inspecciona la tabla
   - Then existe columna `chatwoot_conversation_id` (VARCHAR nullable)

4. **AC4**: Existen índices optimizados para queries del worker
   - Given la migración se ejecuta
   - When se listan los índices
   - Then existe `idx_appointments_confirmation_pending` (parcial: status='pending', confirmation_sent_at IS NULL)
   - And existe `idx_appointments_customer_active` (parcial: status IN ('pending', 'confirmed'))

5. **AC5**: La migración es reversible
   - Given la migración se ha aplicado
   - When se ejecuta `alembic downgrade -1`
   - Then el esquema vuelve al estado anterior sin errores

## Tasks / Subtasks

- [x] **Task 1: Actualizar enum AppointmentStatus** (AC: 1)
  - [x] 1.1 Modificar `database/models.py` - enum con valores: PENDING, CONFIRMED, COMPLETED, CANCELLED, NO_SHOW
  - [x] 1.2 Documentar cambio: CONFIRMED anterior → PENDING (cita agendada esperando confirmación)
  - [x] 1.3 CONFIRMED nuevo = cliente verificó asistencia

- [x] **Task 2: Agregar campos timestamp a appointments** (AC: 2)
  - [x] 2.1 Agregar `confirmation_sent_at: Mapped[datetime | None]` - timestamp envío plantilla 48h
  - [x] 2.2 Agregar `reminder_sent_at: Mapped[datetime | None]` - timestamp envío recordatorio 24h
  - [x] 2.3 Agregar `cancelled_at: Mapped[datetime | None]` - timestamp cancelación
  - [x] 2.4 Agregar `notification_failed: Mapped[bool] = False` - flag si falló envío

- [x] **Task 3: Agregar campo a customers** (AC: 3)
  - [x] 3.1 Agregar `chatwoot_conversation_id: Mapped[str | None]` en Customer model

- [x] **Task 4: Crear migración Alembic** (AC: 1, 2, 3, 4, 5)
  - [x] 4.1 Ejecutar `alembic revision --autogenerate -m "add_confirmation_tracking_fields"`
  - [x] 4.2 Revisar migración generada - verificar cambios de enum
  - [x] 4.3 Agregar SQL manual para índices parciales (autogenerate no los crea bien)
  - [x] 4.4 Verificar función `downgrade()` revierte correctamente

- [x] **Task 5: Crear índices optimizados** (AC: 4)
  - [x] 5.1 Índice `idx_appointments_confirmation_pending`:
    ```sql
    CREATE INDEX idx_appointments_confirmation_pending
    ON appointments (start_time, confirmation_sent_at)
    WHERE status = 'pending';
    ```
  - [x] 5.2 Índice `idx_appointments_customer_active`:
    ```sql
    CREATE INDEX idx_appointments_customer_active
    ON appointments (customer_id, start_time)
    WHERE status IN ('pending', 'confirmed');
    ```

- [x] **Task 6: Testing** (AC: 1-5)
  - [x] 6.1 Aplicar migración: `alembic upgrade head`
  - [x] 6.2 Verificar columnas en DB: `\d appointments`, `\d customers`
  - [x] 6.3 Verificar índices: `\di+ idx_appointments_*`
  - [x] 6.4 Test downgrade: `alembic downgrade -1`
  - [x] 6.5 Test upgrade de nuevo: `alembic upgrade head`
  - [x] 6.6 Crear test unitario para verificar enum values

## Dev Notes

### Contexto Arquitectural

Esta migración implementa los cambios de modelo de datos definidos en ADR-002 y ADR-003:

- **ADR-002 (Renombrar Estados)**: El estado CONFIRMED existente significa "agendada" pero necesitamos distinguir "verificada por cliente". Se renombra a PENDING y se crea nuevo CONFIRMED para citas verificadas.

- **ADR-003 (Campos Timestamp vs JSONB)**: Se usan campos timestamp dedicados para tracking de notificaciones. Ventajas: queries simples con índices, idempotencia natural (IS NULL), auditoría clara.

### Patrón de Confirmación Asíncrona

Los nuevos campos soportan el patrón "Async Confirmation Loop":

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

### Índices Parciales

Los índices son parciales (condicionales) para optimizar queries del worker:

- `idx_appointments_confirmation_pending`: Solo citas PENDING sin confirmación enviada
- `idx_appointments_customer_active`: Solo citas activas (PENDING o CONFIRMED)

PostgreSQL usará estos índices solo cuando las queries incluyan las mismas condiciones WHERE.

### Project Structure Notes

- **Archivo principal**: `database/models.py` - modificar enum y modelos
- **Migración**: `alembic/versions/` - nueva migración autogenerada + índices manuales
- **Sin conflictos**: No modifica archivos existentes de forma disruptiva

### Transición de Datos Existentes

Si hay citas existentes con status CONFIRMED (v3.2), deben migrarse a PENDING:
```sql
-- En la migración
UPDATE appointments SET status = 'pending' WHERE status = 'confirmed';
```

### Testing Strategy

El coverage mínimo de 85% aplica. Tests requeridos:
- Unit test para enum values
- Integration test para migración up/down
- Verificar que Django Admin (managed=False) sigue funcionando

### Comandos de Desarrollo

```bash
# Crear migración
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/alembic revision --autogenerate -m "add_confirmation_tracking_fields"

# Aplicar migración
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/alembic upgrade head

# Verificar
PGPASSWORD="changeme_min16chars_secure_password" psql -h localhost -U atrevete -d atrevete_db -c "\d appointments"
```

### References

- [Source: docs/architecture.md#ADR-002] - Decisión de renombrar estados
- [Source: docs/architecture.md#ADR-003] - Decisión de campos timestamp
- [Source: docs/architecture.md#Data-Architecture] - Modelo de datos completo
- [Source: docs/architecture.md#Novel-Pattern-Async-Confirmation-Loop] - Patrón de confirmación
- [Source: docs/epics.md#Story-1.1] - Requisitos originales
- [Source: docs/prd.md#FR9-FR11] - FRs relacionados con estados

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2025-11-19 | Story drafted from epics and architecture | SM Agent |
| 2025-11-20 | Story implemented and tested | Dev Agent (Amelia) |

## Dev Agent Record

### Context Reference

- docs/sprint-artifacts/1-1-migracion-de-estados-y-campos-de-tracking.context.xml

### Agent Model Used

claude-sonnet-4-5-20250929 (Sonnet 4.5)

### Debug Log References

**Implementation Plan:**
1. Modificar database/models.py: AppointmentStatus enum (PENDING, CONFIRMED, COMPLETED, CANCELLED, NO_SHOW)
2. Agregar campos timestamp a Appointment model (confirmation_sent_at, reminder_sent_at, cancelled_at, notification_failed)
3. Agregar chatwoot_conversation_id a Customer model
4. Generar migración Alembic autogenerada
5. Revisar migración y agregar índices parciales manualmente
6. Aplicar migración y verificar en DB
7. Tests: enum values, campos nullable, índices, upgrade/downgrade

**Key Issues Resolved:**
- Default value en Appointment.status cambiado de PROVISIONAL → PENDING
- Migración autogenerada incluía eliminación de tablas Django Admin (removed)
- Índices parciales agregados manualmente en upgrade()
- Downgrade function simplificada (elimina Django tables code)

### Completion Notes List

✅ **Story 1.1 completada exitosamente**

**Cambios implementados:**
- AppointmentStatus enum actualizado: `pending`, `confirmed`, `completed`, `cancelled`, `no_show` (eliminados: `provisional`, `expired`)
- Appointment model: 4 campos nuevos de tracking (`confirmation_sent_at`, `reminder_sent_at`, `cancelled_at`, `notification_failed`)
- Customer model: campo `chatwoot_conversation_id` agregado
- Migración Alembic reversible creada y aplicada
- 2 índices parciales optimizados para queries del worker

**Validación:**
- ✅ Migración aplicada exitosamente (upgrade → downgrade → upgrade)
- ✅ 8/8 tests unitarios PASSED (100% código nuevo)
- ✅ Campos verificados en DB vía psql
- ✅ Índices parciales verificados y funcionales
- ✅ Enum values correctos en PostgreSQL

**Archivos modificados:**
- `database/models.py`: Enum + campos tracking (lines 68-75, 362-374, 199-202)
- `database/alembic/versions/62769e850a51_add_confirmation_tracking_fields.py`: Migración completa

**Tests creados:**
- `tests/unit/test_appointment_status_migration.py`: 8 tests unitarios

### File List

- database/models.py
- database/alembic/versions/62769e850a51_add_confirmation_tracking_fields.py
- tests/unit/test_appointment_status_migration.py
