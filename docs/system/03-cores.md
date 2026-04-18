# Cores — Dominio Puro del Salón

> Las entidades, invariantes y operaciones del salón. Sin LLM, sin Chatwoot, sin Redis. Si lo borrás, el salón sigue siendo el salón.

## Principios de un core

1. **Sin dependencias de infra externa** salvo DB (que es persistencia del propio dominio).
2. **Lenguaje del negocio**: nombres en español del salón cuando aplique (`Estilista`, `Cita`), o inglés técnico cuando es sintaxis (`Customer.first_name`).
3. **Invariantes hardcoded**: si una regla del salón es inquebrantable (ej. una cita no puede empezar fuera de business_hours), vive acá.
4. **Operaciones atómicas**: book, cancel, reschedule son transacciones DB. Si fallan, el estado debe quedar consistente.
5. **Testeable sin Postgres real**: SQLite in-memory o repository mock.

---

## Core: customers

**Responsabilidad**: identidad del cliente, lookup por teléfono, historial de citas, preferencias persistentes entre conversaciones.

### Entidades

- `Customer` — primary key UUID. Phone único. Incluye `first_name`, `last_name`, `created_at`.
- `CustomerPreferences` (o memoria similar) — store persistente con servicios y estilistas favoritos extraídos de bookings anteriores.

### Operaciones

- `lookup_by_phone(phone) → Customer | None`
- `create(phone, first_name, last_name?) → Customer`
- `update_preferences(customer_id, last_service, last_stylist)`
- `get_preferences(customer_id) → CustomerPreferences | None`
- `get_recent_appointments(customer_id, limit=N) → list[Appointment]`

### Invariantes

- Un teléfono → un solo customer.
- `first_name` requerido para confirmar booking. Captura en flow.
- Preferencias se actualizan SOLO post-booking exitoso. Una cita cancelada no actualiza preferencias.

### Estado actual (referencias en código)

- `database/models.py` — modelo `Customer` con relaciones a `Appointment`.
- `agent/services/customer_memory_service.py` — Store API (LangGraph) para preferencias.
- `agent/tools/customer_tools.py` — `manage_customer()` para captura de nombre.

### Anti-patrones a corregir

- Captura de nombre embedded en booking flow (debería ser core operation invocada por la capability).
- Customer memory write embebido en `booking_mode._post_tool_result` (`booking_mode.py:708-725`). Debería ser `customers.update_preferences_post_booking()`.

---

## Core: services

**Responsabilidad**: catálogo de servicios del salón, su audiencia (señora/caballero/niño/bebé), duración estimada, precio, categoría.

### Entidades

- `Service` — UUID. Nombre canónico ("CORTE LARGO SEÑORA"), `audience` (enum), `duration_minutes`, `price`, `category` (HAIRDRESSING / AESTHETICS / BOTH), `active`.
- `ServiceFamily` — agrupa variantes con la misma raíz semántica ("Corte" → 4 variantes por audience). NO existe hoy como entidad explícita; está implícito en `audience_maps.py`.

### Operaciones

- `get_active_catalog() → list[Service]` — para inyectar en prompt.
- `find_by_canonical_name(name) → Service | None`
- `find_audience_variants(base_name) → list[Service]` — usado para desambiguación.
- `canonicalize_audience(user_text) → AudienceCategory | None` — actualmente en `shared/audience_maps.py:canonicalize_audience()`.
- `fuzzy_match(user_text) → list[Service]` — actualmente disperso entre `booking_data_tools.py:_find_similar_services` y `fuzzy_resolver.py`.

### Invariantes

- Cada Service tiene exactamente UNA audience.
- Servicios "Corte" sin audience canónica → ambigüedad → requiere disambiguation flow.
- Catálogo se carga desde DB; no hay servicios hardcoded en código.

### Estado actual

- `database/models.py:Service` — modelo SQLAlchemy.
- `shared/audience_maps.py` — `AUDIENCE_HINT_MAP`, `canonicalize_audience()`. **Esto es DOMINIO en `shared/` → violación de P8.**
- `agent/prompts/catalog_builder.py` — construye string del catálogo para prompt.
- `agent/tools/booking_data_tools.py:_find_similar_services` — fuzzy match duplicado.
- `agent/modes/booking_mode.py:_resolve_service_category` — query directa a `database.models.Service` desde modo.

### Anti-patrones a corregir

- `shared/audience_maps.py` debe vivir en `cores/services/`.
- `_find_similar_services` y `fuzzy_resolver.py` deben unificarse en `cores/services/fuzzy.py`.
- `booking_mode._resolve_service_category` debe ser `services.find_category(name)`.

---

## Core: stylists

**Responsabilidad**: las 5 estilistas, sus especialidades, sus horarios, su disponibilidad base.

### Entidades

- `Stylist` — UUID. `name`, `specialties` (list de `ServiceCategory`), `active`, `gcal_calendar_id`, `gcal_credentials_id`.
- `BusinessHours` — horario del salón (no de cada estilista; el salón abre/cierra a horas fijas).
- `Holiday` — fechas en que el salón cierra entero.

### Operaciones

- `get_active_stylists() → list[Stylist]`
- `get_stylists_by_category(category) → list[Stylist]` — qué estilistas pueden hacer un servicio dado.
- `get_business_hours(weekday) → BusinessHours | None`
- `is_business_day(date) → bool`

### Invariantes

- 5 estilistas activas (canónico actual). Diseño debe soportar N.
- Una estilista puede tener múltiples especialidades.
- Si todas las estilistas tienen `category = HAIRDRESSING`, una solicitud de AESTHETICS retorna lista vacía (no falla; el flow debe escalar o sugerir alternativa).

### Estado actual

- `database/models.py:Stylist` — modelo.
- `database/seeds/stylists.py` — seed de 5 estilistas.
- `shared/business_hours_validator.py` — validación de horario.
- `shared/stylist_cache.py` — caché en Redis.
- `agent/modes/booking_mode.py:_load_stylists_by_category` (líneas 467-469) — query directa a DB desde modo. **Violación P9.**

### Anti-patrones a corregir

- `_load_stylists_by_category` debe ser `stylists.get_by_category(category)` invocado por la capability.
- Caché debe estar en `cores/stylists/cache.py` o como decorator del query service, no como módulo aparte en `shared/`.

---

## Core: availability

**Responsabilidad**: dado un servicio, una estilista (o todas), una fecha → calcular slots libres. Detectar conflictos. Manejar holds (slots reservados temporalmente durante la conversación).

### Entidades

- `Slot` (in-memory) — `{stylist_id, start_time, end_time, available: bool}`.
- `BlockingEvent` — eventos que bloquean slots (vacaciones de estilista, eventos privados).
- `Hold` (futuro / parcial) — reserva temporal para evitar race condition entre dos clientes pidiendo el mismo slot.

### Operaciones

- `get_slots_for_date(service, date, stylist=None) → list[Slot]`
- `get_next_available(service, from_date, stylist=None, max_lookahead_days=14) → Slot | None`
- `is_slot_available(stylist_id, start_time, end_time) → bool`
- `create_hold(slot, conversation_id, ttl_minutes=15)` (futuro)
- `release_hold(hold_id)` (futuro)

### Invariantes

- Slots se calculan respetando: business_hours del salón, holidays, BlockingEvents de la estilista, citas existentes (status `HOLD`, `PENDING`, `CONFIRMED`).
- Granularidad de slot = duración del servicio (no un grid fijo).
- `get_next_available` lookahead máximo: 14 días por default.

### Estado actual

- `agent/services/availability_service.py` — lógica core (slotting, conflict detection, holiday checking).
- `agent/tools/availability_tools.py` — `check_availability()` tool del LLM.
- `agent/tools/calendar_tools.py` — read/write GCal (mirror).
- `shared/business_hours_validator.py` — validación.

### Anti-patrones a corregir

- `availability_service` está en `agent/services/`. Es CORE puro: debe vivir en `cores/availability/`.
- `availability_tools.py` (la tool LLM) sí pertenece a la capability `booking`, NO al core. Separar.

---

## Core: appointments

**Responsabilidad**: book, cancel, reschedule. Transacciones atómicas que afectan DB + push a GCal.

### Entidades

- `Appointment` — UUID. `customer_id`, `stylist_id`, `service_id`, `start_time`, `end_time`, `status` (HOLD / PENDING / CONFIRMED / COMPLETED / CANCELLED / NO_SHOW), `notes`, `confirmation_sent_at`.
- `AppointmentStatusHistory` (opcional) — auditoría de cambios de estado.

### Operaciones

- `book(customer_id, stylist_id, service_id, start_time, notes?) → Appointment` — atómico: insert DB + push GCal. Si GCal falla, retry async; DB es fuente de verdad.
- `cancel(appointment_id, reason?) → Appointment` — set status CANCELLED + push GCal.
- `reschedule(appointment_id, new_start_time, new_stylist_id?) → Appointment` — atómico: update DB + push GCal.
- `confirm(appointment_id)` — invocado 48h antes vía worker (`confirmation_worker.py`).
- `mark_no_show(appointment_id)` — invocado por worker o admin.

### Invariantes

- No se puede `book` si `is_slot_available` retorna False.
- No se puede `book` sin `customer_first_name` registrado.
- Cancelar una cita CONFIRMED dispara notificación al cliente.
- DB es fuente de verdad. GCal es push-only mirror; si la sync falla, no se rolea back la DB.

### Estado actual

- `database/models.py:Appointment`, `AppointmentStatus` enum.
- `agent/tools/booking_tools.py:book` — la tool del LLM que invoca el booking.
- `agent/services/cancellation_service.py` — cancelación.
- `agent/services/reschedule_service.py` — reagendamiento.
- `agent/services/confirmation_service.py` — confirmación 48h.
- `agent/services/gcal_push_service.py` — push a GCal.
- `agent/workers/confirmation_worker.py`, `gcal_sync_worker.py` — async workers.

### Anti-patrones a corregir

- `cancellation_service`, `reschedule_service`, `confirmation_service` viven en `agent/services/`. Son CORE puro: deben vivir en `cores/appointments/`.
- `booking_tools.py:book` (la tool LLM) pertenece a la capability `booking`. La operación atómica `appointments.book()` vive en el core; la tool LLM la invoca.

---

## Reglas de cross-core

Los cores **PUEDEN** depender unos de otros, pero con justificación:

| Core | Depende legítimamente de |
|------|--------------------------|
| `customers` | (ninguno) — es raíz |
| `services` | (ninguno) — es raíz |
| `stylists` | `services` (especialidades referencian categorías) |
| `availability` | `stylists`, `services`, `appointments` (lee citas existentes para detectar conflictos) |
| `appointments` | `customers`, `stylists`, `services`, `availability` (valida slot antes de book) |

**Anti-pattern**: customers depender de appointments. Si necesitás "citas de un customer", lo expone `appointments.find_by_customer(customer_id)`, no `customers.get_appointments()`.

## Tests de cores

- 100% testeables sin LLM, sin Chatwoot, sin Redis.
- Postgres es opcional: SQLite in-memory para unit tests.
- Cobertura objetivo: ≥90% en cores (es lógica de negocio crítica).

## Próximos pasos

Ver `06-current-vs-target.md` para el mapping archivo-por-archivo de qué se mueve a qué core, y `07-migration-plan.md` Phase E2 (port booking) y Phase E3 (port appointment management).
