# Flujo Interno de la Transacción de Agendamiento

**Última actualización:** 2025-11-13
**Versión del sistema:** v3.2 (Post-eliminación de pagos)

## Resumen Ejecutivo

Este documento describe el flujo técnico interno de cómo el sistema agenda una cita cuando el agente conversacional tiene todos los datos recolectados. El proceso utiliza una **transacción atómica SERIALIZABLE** con validaciones en múltiples capas para garantizar la consistencia de datos entre PostgreSQL y Google Calendar.

**Cambios recientes (Nov 13, 2025):**
- ✅ Corregida inconsistencia en `customer_name` para Google Calendar
- ✅ Eliminada lógica de timeouts/metadata de sistema de pagos
- ✅ Corregida query SQL de `end_time` usando cálculo dinámico
- ✅ Auto-confirmación de todas las citas (sin estado provisional)

---

## 📋 Punto de Partida: Datos Recolectados

Antes de ejecutar la transacción, el agente conversacional ya tiene:

| Campo | Tipo | Origen | Ejemplo |
|-------|------|--------|---------|
| `customer_id` | UUID | DB (Customer table) | `a1b2c3d4-...` |
| `service_ids` | List[UUID] | DB (Services table) | `[uuid1, uuid2]` |
| `stylist_id` | UUID | DB (Stylists table) | `e5ba2088-...` |
| `start_time` | datetime | Usuario (parseado) | `2025-11-18T10:00:00+01:00` |
| `first_name` | str | Usuario (PASO 3) | `"Pepe"` |
| `last_name` | str | Usuario (PASO 3) | `"Cabeza Cruz"` |
| `notes` | str \| None | Usuario (opcional) | `"Alérgico a..."` |

**⚠️ IMPORTANTE**: `first_name` y `last_name` provienen de PASO 3 (datos específicos para esta cita), NO de la tabla Customer en la base de datos. Esto permite que el cliente use un nombre diferente para la cita sin modificar su registro principal.

---

## 🔄 Flujo Completo de la Transacción

### **PASO 0: Confirmación del Usuario**

Antes de ejecutar `book()`, el agente **DEBE mostrar un resumen completo** y esperar confirmación explícita:

```
🗓️ *Martes 18 de noviembre de 2025*
🕐 *10:00* (duración estimada: 60 minutos)
💇‍♀️ Con *Pilar*

📋 Servicios:
- Corte + Peinado (Corto-Medio)

👤 A nombre de: Pepe Cabeza Cruz

¿Confirmas esta reserva?
```

Solo cuando el cliente responde "Sí", "Adelante", "Confirmo", etc., se procede.

### **PASO 1: Llamada a `book()` Tool**

**Ubicación:** `agent/tools/booking_tools.py:236-244`

```python
result = await BookingTransaction.execute(
    customer_id=customer_uuid,
    service_ids=service_uuids,
    stylist_id=stylist_uuid,
    start_time=start_datetime,
    first_name=first_name,        # De parámetros, NO de DB
    last_name=last_name,           # De parámetros, NO de DB
    notes=notes
)
```

La herramienta `book()` delega inmediatamente a `BookingTransaction.execute()`.

---

### **PASO 2: Validaciones PRE-Transacción**

Estas validaciones ocurren **ANTES** de abrir la transacción de base de datos, para fallar rápido sin bloquear recursos.

#### **2.1 Validar Regla de 3 Días**

**Ubicación:** `agent/validators/transaction_validators.py:222-312`
**Función:** `validate_3_day_rule(requested_date: datetime)`

```python
# Validación
now = datetime.now(MADRID_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
requested_date_midnight = requested_date.replace(hour=0, minute=0, second=0, microsecond=0)
days_until = (requested_date_midnight - now).days

if days_until < 3:
    return {
        "valid": False,
        "error_code": "DATE_TOO_SOON",
        "error_message": "Las citas deben agendarse con al menos 3 días de anticipación...",
        "days_until_appointment": days_until
    }
```

**Regla de negocio:** Las citas requieren **mínimo 3 días completos** de aviso.

**Ejemplo:**
- Hoy: Jueves 13 de noviembre
- Primera fecha válida: Lunes 17 de noviembre (4 días después)
- Fecha inválida: Domingo 16 de noviembre (solo 3 días, pero < 3 días completos)

#### **2.2 Validar Consistencia de Categorías**

**Ubicación:** `agent/validators/transaction_validators.py:24-111`
**Función:** `validate_category_consistency(service_ids: list[UUID])`

```python
# Fetch all services
stmt = select(Service).where(Service.id.in_(service_ids))
result = await session.execute(stmt)
services = result.scalars().all()

# Extract unique categories
categories = set(service.category for service in services)

if len(categories) > 1:
    return {
        "valid": False,
        "error_code": "CATEGORY_MISMATCH",
        "error_message": "No se pueden mezclar servicios de diferentes categorías...",
        "categories_found": [cat.value for cat in categories]
    }
```

**Regla de negocio:** **NO se permite mezclar servicios de Peluquería + Estética** en la misma cita.

**Razón:** Diferentes equipos especializados, diferentes flujos operativos.

---

### **PASO 3: Inicio de Transacción SERIALIZABLE**

**Ubicación:** `agent/transactions/booking_transaction.py:156-160`

```python
async for session in get_async_session():
    try:
        # Set SERIALIZABLE isolation for this transaction
        await session.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
```

**¿Por qué SERIALIZABLE?**
- **Previene race conditions**: Dos clientes no pueden reservar el mismo slot simultáneamente
- **Garantiza atomicidad**: O TODO se ejecuta o TODO se deshace (no hay "appointments a medias")
- **Consistencia fuerte**: Si la transacción falla, el rollback automático restaura el estado

#### **3.1 Fetch de Servicios y Cálculo de Duración**

**Ubicación:** `agent/transactions/booking_transaction.py:162-182`

```python
# Fetch services
stmt = select(Service).where(Service.id.in_(service_ids))
result = await session.execute(stmt)
services = list(result.scalars().all())

# Validate all services found
if len(services) != len(service_ids):
    # Error: Missing services
    return {"success": False, "error_code": "INVALID_SERVICE_IDS", ...}

# Calculate durations
total_duration = sum(s.duration_minutes for s in services)
duration_with_buffer = total_duration + 10  # 10 min buffer between appointments
```

**Buffer de 10 minutos:** Tiempo entre citas para limpieza y preparación del espacio.

#### **3.2 Fetch de Stylist**

**Ubicación:** `agent/transactions/booking_transaction.py:184-195`

```python
stmt = select(Stylist).where(Stylist.id == stylist_id)
result = await session.execute(stmt)
stylist = result.scalar_one_or_none()

if not stylist:
    return {"success": False, "error_code": "STYLIST_NOT_FOUND", ...}
```

#### **3.3 Validar Disponibilidad de Slot con Row Lock**

**Ubicación:** `agent/validators/transaction_validators.py:113-219`
**Función:** `validate_slot_availability(stylist_id, start_time, duration_minutes, session)`

```python
end_time = start_time + timedelta(minutes=duration_minutes)

# Query with row lock to prevent race conditions
stmt = (
    select(Appointment)
    .where(Appointment.stylist_id == stylist_id)
    .where(Appointment.status.in_(["provisional", "confirmed"]))
    .where(
        # Check for overlap
        (Appointment.start_time < end_time) &
        # Calculate end_time dynamically (no column exists)
        (text("start_time + (duration_minutes || ' minutes')::interval") > start_time)
    )
    .with_for_update()  # 🔒 Row lock
)

result = await session.execute(stmt)
conflicting_appointments = list(result.scalars().all())

if conflicting_appointments:
    return {
        "available": False,
        "error_code": "SLOT_TAKEN",
        "error_message": "El horario seleccionado ya está ocupado...",
        "conflicting_appointment_id": conflict.id
    }
```

**Características clave:**
- **`SELECT FOR UPDATE`**: Bloquea las filas de appointments para prevenir double-booking
- **Cálculo dinámico de `end_time`**: Usa expresión SQL `text()` porque no existe columna `end_time` en el modelo
- **Detecta overlaps**: Verifica si hay appointments que se solapen con `[start_time, end_time]`

**Fix reciente (Nov 13, 2025):**
- ✅ Corregido: Query SQL ahora calcula `end_time` dinámicamente usando PostgreSQL interval arithmetic
- ✅ Eliminado: Lógica de timeouts/metadata del sistema de pagos (código legacy)

---

### **PASO 4: Crear Evento en Google Calendar**

**Ubicación:** `agent/transactions/booking_transaction.py:222-260`

```python
# Build service names
service_names = ", ".join(s.name for s in services)

# Use customer name from PARAMETERS, not database
# This ensures consistency with appointment data
customer_name = f"{first_name} {last_name or ''}".strip()

# Create calendar event
calendar_result = await create_calendar_event(
    stylist_id=str(stylist_id),
    start_time=start_time.isoformat(),
    duration_minutes=duration_with_buffer,
    customer_name=customer_name,
    service_names=service_names,
    status="provisional",  # Always start as provisional
    customer_id=str(customer_id),
    conversation_id=trace_id
)

if not calendar_result.get("success"):
    await session.rollback()
    return {"success": False, "error_code": "CALENDAR_EVENT_FAILED", ...}

google_event_id = calendar_result["event_id"]
```

**Detalles del evento creado:**

```python
# agent/tools/calendar_tools.py:860-878
summary = f"[PROVISIONAL] {customer_name} - {service_names}"
# Ejemplo: "[PROVISIONAL] Pepe Cabeza Cruz - Corte + Peinado (Corto-Medio)"

description = f"""Customer: {customer_name}
Services: {service_names}
Status: provisional
Appointment ID: {appointment_id}
Customer ID: {customer_id}"""

color_id = "5"  # Yellow for provisional
```

**Fix reciente (Nov 13, 2025):**
- ✅ Corregido: Ahora usa `customer_name` de **parámetros** (`first_name`, `last_name`) en vez de hacer query a DB
- **Beneficio**: Garantiza consistencia entre PostgreSQL appointments y Google Calendar events

**¿Por qué crear en Calendar ANTES de insertar en DB?**
- Si Calendar falla, no queremos un appointment en DB sin evento en Calendar
- El rollback de la transacción mantiene consistencia

---

### **PASO 5: Crear Appointment en PostgreSQL**

**Ubicación:** `agent/transactions/booking_transaction.py:268-295`

```python
end_time = start_time + timedelta(minutes=total_duration)

new_appointment = Appointment(
    customer_id=customer_id,
    stylist_id=stylist_id,
    service_ids=service_ids,              # ARRAY of UUIDs
    start_time=start_time,
    duration_minutes=total_duration,       # WITHOUT buffer (60 min)
    status=AppointmentStatus.CONFIRMED,   # Auto-confirm (no payment system)
    google_calendar_event_id=google_event_id,
    first_name=first_name,                # From parameters
    last_name=last_name,                  # From parameters
    notes=notes                           # Optional
)

session.add(new_appointment)
await session.commit()  # ← ATOMICIDAD GARANTIZADA
await session.refresh(new_appointment)
```

**Campos importantes:**
- `status = CONFIRMED`: Todas las citas se auto-confirman (sistema de pagos eliminado Nov 10, 2025)
- `duration_minutes`: Duración **SIN** buffer (el buffer solo se usa para Google Calendar y validaciones)
- `first_name`, `last_name`: Guardados directamente en `appointments` (agregados Nov 13, 2025)

**¿Qué pasa si commit falla?**
- Rollback automático de la transacción
- El evento de Google Calendar queda huérfano (se limpia manualmente o expira)

---

### **PASO 6: Actualizar Evento a "Confirmed" (Verde)**

**Ubicación:** `agent/transactions/booking_transaction.py:297-309`

```python
try:
    await update_calendar_event_status(
        stylist_id=str(stylist_id),
        event_id=google_event_id,
        status="confirmed"
    )
except Exception as calendar_error:
    # Warning only, does not block transaction
    logger.warning(f"Failed to update calendar event to confirmed")
```

**Cambios aplicados:**
- Título: `"[PROVISIONAL]"` → Sin prefijo
- Color: Amarillo (5) → Verde (10)
- Descripción: `Status: provisional` → `Status: confirmed`

**⚠️ IMPORTANTE:** Si este paso falla, **NO se hace rollback**. La cita ya está confirmada en DB, solo el color del evento queda mal.

---

### **PASO 7: Retornar Resultado Exitoso**

**Ubicación:** `agent/transactions/booking_transaction.py:316-328`

```python
return {
    "success": True,
    "appointment_id": str(new_appointment.id),
    "google_calendar_event_id": google_event_id,
    "start_time": start_time.isoformat(),
    "end_time": end_time.isoformat(),
    "duration_minutes": total_duration,
    "customer_id": str(customer_id),
    "stylist_id": str(stylist_id),
    "service_ids": [str(sid) for sid in service_ids],
    "status": "confirmed"
}
```

El agente LLM recibe este resultado y envía mensaje de confirmación al cliente.

---

## 📊 Diagrama del Flujo

```
┌─────────────────────────────────────────────────────────────────┐
│  USUARIO: "Sí, confirmo la reserva"                            │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  book() → BookingTransaction.execute()                          │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  ✅ VALIDACIÓN 1: Regla de 3 Días                              │
│     ├─ requested_date >= today + 3 días                        │
│     └─ ❌ Si falla: return "DATE_TOO_SOON"                     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  ✅ VALIDACIÓN 2: Consistencia de Categorías                   │
│     ├─ Todos servicios misma categoría                         │
│     └─ ❌ Si falla: return "CATEGORY_MISMATCH"                 │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  🔒 BEGIN TRANSACTION (SERIALIZABLE)                            │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  📋 Fetch Services & Calculate Duration                         │
│     ├─ total_duration = sum(service.duration_minutes)          │
│     └─ duration_with_buffer = total_duration + 10              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  👤 Fetch Stylist                                               │
│     └─ ❌ Si no existe: ROLLBACK + "STYLIST_NOT_FOUND"         │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  🔍 Validate Slot Availability (SELECT FOR UPDATE)              │
│     ├─ Query: Buscar appointments overlapping                  │
│     ├─ 🔒 Row lock para prevenir race conditions               │
│     └─ ❌ Si conflicto: ROLLBACK + "SLOT_TAKEN"                │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  📅 Create Google Calendar Event (Provisional)                  │
│     ├─ Title: "[PROVISIONAL] {name} - {services}"              │
│     ├─ Color: Yellow (5)                                        │
│     ├─ Duration: duration_with_buffer (includes 10 min)        │
│     └─ ❌ Si falla: ROLLBACK + "CALENDAR_EVENT_FAILED"         │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  💾 Insert Appointment into PostgreSQL                          │
│     ├─ status = "CONFIRMED" (auto-confirm)                     │
│     ├─ first_name, last_name (from parameters)                 │
│     ├─ google_calendar_event_id (link to Calendar)             │
│     └─ session.commit() ← ATOMICIDAD                           │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  🟢 Update Calendar Event to "Confirmed"                        │
│     ├─ Remove "[PROVISIONAL]" prefix                           │
│     ├─ Change color: Yellow → Green (10)                       │
│     └─ ⚠️ Si falla: WARNING (no bloquea)                       │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  ✅ COMMIT TRANSACTION                                          │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  📤 Return Success to Agent                                     │
│     {appointment_id, google_event_id, start_time, ...}         │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  💬 Agent sends confirmation to user                            │
│     "¡Perfecto, Pepe! 🎉 Tu cita está confirmada..."           │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🛡️ Garantías de Consistencia

### **1. Atomicidad (ACID)**
- **Nivel de aislamiento:** SERIALIZABLE
- **Garantía:** O TODO se ejecuta (commit) o TODO se deshace (rollback)
- **Beneficio:** No hay "appointments a medias" en la DB

### **2. Row Locking**
- **Mecanismo:** `SELECT FOR UPDATE`
- **Garantía:** Bloquea appointments existentes durante validación
- **Beneficio:** Previene race conditions (dos clientes reservando el mismo slot)

### **3. Validaciones en Capas**
| Capa | Ubicación | Propósito |
|------|-----------|-----------|
| **Pre-transacción** | Validators | Fallar rápido sin bloquear recursos |
| **Dentro de transacción** | BookingTransaction | Validar con locks de DB |
| **Post-commit** | Calendar update | Mejorar UX (color verde) |

### **4. Consistencia de Datos**

**Antes (Bug - Nov 13, 2025):**
```python
# ❌ INCORRECTO
customer = fetch_from_db(customer_id)  # "José Pérez" (nombre viejo)
customer_name = f"{customer.first_name} {customer.last_name}"
# Google Calendar: "José Pérez"
# PostgreSQL appointment: "Pepe Cabeza Cruz"  ← INCONSISTENCIA
```

**Después (Fix - Nov 13, 2025):**
```python
# ✅ CORRECTO
customer_name = f"{first_name} {last_name}"  # De parámetros
# Google Calendar: "Pepe Cabeza Cruz"
# PostgreSQL appointment: "Pepe Cabeza Cruz"  ← CONSISTENCIA
```

---

## ❌ Manejo de Errores

### **Errores con Rollback Automático**

| Error | Código | Acción |
|-------|--------|--------|
| Fecha < 3 días | `DATE_TOO_SOON` | Return antes de transacción |
| Servicios mixtos | `CATEGORY_MISMATCH` | Return antes de transacción |
| Slot ocupado | `SLOT_TAKEN` | ROLLBACK + return error |
| Fallo Google Calendar | `CALENDAR_EVENT_FAILED` | ROLLBACK + return error |
| Servicio no existe | `INVALID_SERVICE_IDS` | Return durante transacción |
| Stylist no existe | `STYLIST_NOT_FOUND` | Return durante transacción |

### **Logging y Trazabilidad**

**Trace ID:** `{customer_id}_{start_time.isoformat()}`

Ejemplo: `a1b2c3d4-e5f6..._2025-11-18T10:00:00+01:00`

**Logs clave:**
```python
logger.info(f"[{trace_id}] Starting booking transaction")
logger.info(f"[{trace_id}] Creating Google Calendar event")
logger.info(f"[{trace_id}] Appointment created and auto-confirmed")
logger.warning(f"[{trace_id}] Slot availability validation failed")
logger.error(f"[{trace_id}] Failed to create Google Calendar event")
```

---

## 📝 Datos Persistidos

### **En PostgreSQL (`appointments` table)**

```sql
INSERT INTO appointments (
    id,                        -- UUID (auto-generated)
    customer_id,               -- UUID (FK → customers)
    stylist_id,                -- UUID (FK → stylists)
    service_ids,               -- UUID[] (ARRAY)
    start_time,                -- TIMESTAMP WITH TIME ZONE
    duration_minutes,          -- INTEGER (60, sin buffer)
    status,                    -- 'confirmed' (auto-confirm)
    google_calendar_event_id,  -- VARCHAR (link to Google)
    first_name,                -- VARCHAR (de parámetros)
    last_name,                 -- VARCHAR (de parámetros)
    notes,                     -- TEXT (opcional)
    created_at,                -- TIMESTAMP (now)
    updated_at                 -- TIMESTAMP (now)
) VALUES (...);
```

### **En Google Calendar**

```yaml
summary: "Pepe Cabeza Cruz - Corte + Peinado (Corto-Medio)"

description: |
  Customer: Pepe Cabeza Cruz
  Services: Corte + Peinado (Corto-Medio)
  Status: confirmed
  Appointment ID: a1b2c3d4-e5f6-...
  Customer ID: f7g8h9i0-j1k2-...

start:
  dateTime: "2025-11-18T10:00:00+01:00"
  timeZone: "Europe/Madrid"

end:
  dateTime: "2025-11-18T11:10:00+01:00"  # +70 min (60 + 10 buffer)
  timeZone: "Europe/Madrid"

colorId: "10"  # Green (confirmed)
calendarId: "pilar@atrevete.com"  # Calendario específico de Pilar
```

---

## 🔧 Correcciones Recientes (Nov 13, 2025)

### **Fix #1: Query SQL de `end_time`**

**Problema:** `Appointment.end_time` no existe como columna, causaba `AttributeError`.

**Solución:**
```python
# Antes (❌)
(Appointment.end_time > start_time)

# Después (✅)
(text("start_time + (duration_minutes || ' minutes')::interval") > start_time)
```

**Archivo:** `agent/validators/transaction_validators.py:174`

### **Fix #2: Lógica de metadata/timeout**

**Problema:** Código legacy del sistema de pagos intentaba acceder a `appointment.metadata` (campo inexistente).

**Solución:** Eliminada toda la lógica de timeouts (líneas 181-214 originales). Simplificado a:
```python
conflicting_appointments = list(result.scalars().all())
# Todos los appointments retornados son conflictos
```

**Archivo:** `agent/validators/transaction_validators.py:179-186`

### **Fix #3: Inconsistencia `customer_name`**

**Problema:** Google Calendar usaba nombre de DB, PostgreSQL usaba nombre de parámetros.

**Solución:**
```python
# Eliminado (líneas 225-239)
customer = fetch_from_db(customer_id)
customer_name = f"{customer.first_name} {customer.last_name}"

# Reemplazado con (línea 227)
customer_name = f"{first_name} {last_name or ''}".strip()
```

**Archivo:** `agent/transactions/booking_transaction.py:227`

---

## 📚 Referencias

- **Transacción principal:** `agent/transactions/booking_transaction.py`
- **Validadores:** `agent/validators/transaction_validators.py`
- **Herramienta de booking:** `agent/tools/booking_tools.py`
- **Google Calendar integration:** `agent/tools/calendar_tools.py`
- **Modelo de datos:** `database/models.py` (líneas 340-380)

---

**Documentación relacionada:**
- [QUICK-CONTEXT.md](../QUICK-CONTEXT.md) - Onboarding de 5 minutos
- [booking/flow.md](../03-features/booking/flow.md) - Flujo conversacional (⚠️ desactualizado)
- [current-state.md](./current-state.md) - Estado actual del sistema
