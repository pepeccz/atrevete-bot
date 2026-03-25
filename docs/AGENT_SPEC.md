# AGENT_SPEC.md — Especificación de Comportamiento del Agente de Reservas

**Versión**: 1.0  
**Arquitectura**: BookingMode (LLM-driven, agentic loop — ex "v7")  
**Fecha**: Marzo 2026  
**Archivos clave**: `agent/modes/booking_mode.py`, `agent/modes/booking_context.py`, `agent/modes/tool_extractors.py`, `agent/prompts/modes/booking.md`

---

## Índice

- [A. Estado del Agente — BookingContext](#a-estado-del-agente--bookingcontext)
- [B. Contrato de Cada Tool](#b-contrato-de-cada-tool)
- [C. Flujo de Estados Lógico](#c-flujo-de-estados-lógico)
- [D. Reglas de No-Regresión](#d-reglas-de-no-regresión)
- [E. Casos Límite Documentados](#e-casos-límite-documentados)
- [F. Invariantes del Sistema](#f-invariantes-del-sistema)
- [G. Gaps Detectados](#g-gaps-detectados)

---

## A. Estado del Agente — BookingContext

### Descripción general

`BookingContext` es un dataclass definido en `agent/modes/booking_context.py`. Se serializa a `mode_context` en el estado de LangGraph al final de cada turno y se rehidrata al inicio del siguiente vía `BookingContext.from_mode_context()`. No hay FSM explícita: el LLM lee el contexto dinámico construido por `_build_dynamic_context()` y decide qué hacer a continuación.

### Campos del contexto

#### Grupo 1: Servicio primario

| Campo | Tipo | Requerido para `book()` | Poblado por | Descripción |
|-------|------|------------------------|-------------|-------------|
| `service_id` | `str \| None` | Indirecto (vía `selected_services`) | `extract_service_fields` | UUID del servicio resuelto |
| `service_name` | `str \| None` | No (se usa `selected_services`) | `extract_service_fields` | Nombre display del servicio primario |
| `service_category` | `str \| None` | No (requerido para `check_availability`) | `extract_service_fields` | `"Peluquería"` o `"Estética"` |
| `service_duration_minutes` | `int \| None` | No | `extract_service_fields` | Duración del servicio, usada en `find_next_available` |
| `service_family` | `str \| None` | No | `extract_service_fields` | Familia de servicio para reglas de combinación |

#### Grupo 2: Lista de servicios

| Campo | Tipo | Requerido para `book()` | Poblado por | Descripción |
|-------|------|------------------------|-------------|-------------|
| `selected_services` | `list[str]` | **SÍ** | `extract_service_fields`, `_pre_tool_call` | Lista de nombres de servicios. Es la lista inyectada en `book()`. Primer elemento = servicio primario. |
| `selected_services_details` | `list[dict]` | No | `_upsert_service_detail` | Detalles de descripción/duración para render en prompt. Máximo 5 entradas. |

#### Grupo 3: Estilista

| Campo | Tipo | Requerido para `book()` | Poblado por | Descripción |
|-------|------|------------------------|-------------|-------------|
| `stylist_id` | `str \| None` | **SÍ** (UUID real) | `_pre_tool_call` vía `slot_index`, o `extract_slot_fields` (auto-set cuando todos los slots son del mismo estilista) | UUID de la estilista. NUNCA puede ser un string conversacional como "cualquiera". |
| `stylist_name` | `str \| None` | No | `extract_slot_fields`, `extract_stylist_fields` | Nombre display de la estilista. Solo para render. |

#### Grupo 4: Slots ofrecidos / seleccionado

| Campo | Tipo | Requerido para `book()` | Poblado por | Descripción |
|-------|------|------------------------|-------------|-------------|
| `offered_slots` | `list[dict] \| None` | **SÍ** (precondición indirecta) | `extract_slot_fields` | Lista de slots ofrecidos al usuario. Incluye `full_datetime`, `stylist_id`, `stylist_name`. Se borra en SLOT_TAKEN. Si es `None`, `book()` queda bloqueado por la guarda `NO_OFFERED_SLOTS`. |
| `selected_slot` | `dict \| None` | No (book usa slot_index) | No se usa en v7 activo — legacy | Slot seleccionado explícitamente. En la arquitectura actual el LLM pasa `slot_index` y `_pre_tool_call` resuelve. |

#### Grupo 5: Cliente

| Campo | Tipo | Requerido para `book()` | Poblado por | Descripción |
|-------|------|------------------------|-------------|-------------|
| `customer_name` | `str \| None` | **SÍ** (gate duro) | `extract_customer_fields`, `_pre_tool_call` (name-only bypass), `_extract_name_from_conversation` | Nombre del cliente. Se parte en first_name/last_name al llamar `book()`. No puede ser `"cliente"` o vacío. |
| `customer_id` | `str \| None` | **SÍ** (gate duro) | `extract_customer_fields`, `_resolve_customer_from_state` | UUID del cliente. Siempre inyectado desde context, nunca del LLM. |

#### Grupo 6: Opcionales

| Campo | Tipo | Requerido para `book()` | Poblado por | Descripción |
|-------|------|------------------------|-------------|-------------|
| `notes` | `str \| None` | No | LLM → `book()` directamente | Notas de la cita. |

#### Grupo 7: Disambiguación

| Campo | Tipo | Requerido | Poblado por | Descripción |
|-------|------|-----------|-------------|-------------|
| `pending_clarifications` | `list[dict]` | No | `extract_service_fields` Shape 2 | Cola de clarificaciones pendientes por eje (audience, hair_density, hair_length). Se consume vía `resolve_pending_clarification()`. |
| `candidate_services` | `list[dict]` | No | `extract_service_fields` Shape 3 | Candidatos fuzzy cuando hay múltiples matches sin clarificación posible. El LLM presenta opciones al usuario. |

#### Grupo 8: Hints de contexto

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `service_audience_hint` | `str \| None` | Valor de audiencia inferido: `"adult_female"`, `"adult_male"`, `"child_male"`, `"child_female"`, `"baby"`. Inyectado en `search_services` vía `_pre_tool_call`. |
| `prefetched_stylists` | `list[dict]` | Lista de estilistas pre-cargadas cuando ya hay servicio pero no estilista. Evita un round-trip LLM. |
| `soonest_any_slot` | `str \| None` | Resumen textual del slot más próximo de cualquier estilista. Para render en prompt. |
| `recurrent_stylist_hint` | `str \| None` | Estilista habitual del cliente (desde historial). Solo display. |

#### Grupo 9: Recomendaciones

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `pending_recommendations` | `list[str]` | Nombres de servicios complementarios sugeridos. Máximo 1 vez por flujo. |
| `recommendations_shown` | `bool` | Evita repetir la sección de recomendaciones en el prompt. |
| `recommendations_declined` | `bool` | Evita repreguntar si el usuario ya declinó. |

#### Grupo 10: Control de fallos y circuit breakers

| Campo | Tipo | Umbral | Descripción |
|-------|------|--------|-------------|
| `book_failure_count` | `int` | ≥3 → excluye `book` del loop | Contador de intentos fallidos de `book()`. Se resetea en nueva disponibilidad. |
| `manage_customer_failure_count` | `int` | ≥2 → excluye `manage_customer` del loop | Contador de fallos de `manage_customer`. |
| `needs_availability_refresh` | `bool` | `True` → bloquea `book()` | Activado por `SLOT_TAKEN`. Bloqueador hasta que se obtenga disponibilidad fresca. |

#### Grupo 11: Locks y gates de confirmación

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `services_locked` | `bool` | Activado en el PRIMER intento real de `book()` (éxito o fallo, no rechazos). Impide que un retry SLOT_TAKEN sobreescriba `selected_services`. En modo locked, `extract_service_fields` solo hace append de servicios nuevos. |
| `confirmation_shown` | `bool` | Gate duro. `True` solo cuando: (a) el LLM mostró un resumen de confirmación Y (b) el usuario respondió afirmativamente. Detectado por `_detect_confirmation_exchange()`. Sin esto, `book()` queda bloqueado con `CONFIRMATION_NOT_SHOWN`. |

#### Grupo 12: Internal (no serializado)

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `_booking_completed` | `bool` | `True` tras `book()` exitoso. Dispara transición a GENERAL y reset de campos transitorios. No se persiste en `mode_context`. |

### Orden de recolección de datos

El orden es **flexible** (el LLM se adapta si la usuaria da datos fuera de orden), pero el orden **recomendado** definido en `booking.md` es:

1. Servicio → `search_services`
2. Estilista → `list_stylists` o pre-cargado
3. Fecha/hora → `check_availability` o `find_next_available`
4. Nombre del cliente → captura conversacional o `manage_customer`
5. Notas (opcional)
6. Resumen + confirmación
7. `book()`

### Qué significa `services_locked`

`services_locked` se activa en el primer intento real de `book()` (el primer call que no es rechazado por una guarda). Su propósito es proteger `selected_services` durante un retry SLOT_TAKEN: si el slot está tomado y se debe buscar nueva disponibilidad, el LLM no debe re-resolver los servicios (podrían cambiar). En modo locked, `extract_service_fields` solo **agrega** servicios nuevos a la lista; no sobreescribe `service_id`, `service_name` ni otros campos escalares.

---

## B. Contrato de Cada Tool

### B.1 `search_services`

**Archivo**: `agent/tools/search_services.py`

**Precondición**: El LLM identificó un servicio que la usuaria quiere reservar. Llamar una vez POR CADA servicio, nunca con múltiples servicios combinados en un solo query.

**Inputs requeridos**:
- `query: str` — nombre del servicio en lenguaje natural (ej: `"corte de pelo"`)
- `audience: str | None` — audiencia opcional (`"adult_female"`, etc.). Inyectado automáticamente por `_pre_tool_call` desde `service_audience_hint`.

**Outputs posibles**:

| Shape | Clave raíz | Descripción | Acción del agente |
|-------|-----------|-------------|-------------------|
| Shape 1 | `resolved_service` | Servicio resuelto sin ambigüedad | Almacenar en ctx, continuar con el flujo |
| Shape 2 | `clarification_needed` | Ambigüedad por eje (audience, hair_density, hair_length) | Preguntar el eje faltante al usuario |
| Shape 3 | `services: list` | Múltiples candidatos fuzzy | Si 1 resultado → auto-resolve. Si >1 → presentar opciones |
| Error | `error: str` | Fallo de DB o query vacía | Informar al usuario, no reintentar automáticamente |

**Post-procesamiento**: `extract_service_fields()` en `tool_extractors.py`.

**NUNCA**:
- Combinar múltiples servicios en un solo query (`"corte y tinte"` → incorrecto)
- Re-llamar si `services_locked=True` para re-resolver el servicio primario
- Ignorar `clarification_needed` y asumir un servicio

---

### B.2 `list_stylists`

**Archivo**: `agent/tools/info_tools.py`

**Precondición**: El servicio ya está resuelto y se necesita presentar opciones de estilista. Normalmente no es necesario llamarlo si `prefetched_stylists` ya está en el contexto.

**Inputs requeridos**:
- `type: "services"` — no es el parámetro correcto. En realidad se usa el tool `list_stylists` directo con `category: str`.

> **Nota**: `list_stylists` está en `info_tools.py` y es un tool LangChain separado de `query_info`. Acepta `category: str` (nombre de la categoría).

**Outputs posibles**:

| Clave | Descripción | Acción del agente |
|-------|-------------|-------------------|
| `stylists: list` | Lista de estilistas con `name`, `id`, `next_slot_summary` | Presentar al usuario. Nunca inventar nombres. |
| `error: str` | Fallo de DB | Informar al usuario, continuar con datos disponibles |

**Post-procesamiento**: `extract_stylist_fields()` → puebla `prefetched_stylists`.

**NUNCA**:
- Inventar nombres de estilistas que no aparecen en el resultado
- Asignar `stylist_id` manualmente desde el nombre sin confirmación del usuario

---

### B.3 `check_availability`

**Archivo**: `agent/tools/availability_tools.py`

**Precondición**: La usuaria tiene una fecha concreta en mente y ya se resolvió el servicio (para tener `service_category`).

**Inputs requeridos**:
- `service_category: str` — `"Peluquería"` o `"Estética"`
- `date: str` — fecha en lenguaje natural o ISO 8601
- `time_range: str | None` — opcional: `"morning"`, `"afternoon"`, `"HH:MM-HH:MM"`
- `stylist_id: str | None` — UUID de estilista preferida (si ya fue elegida)

**Outputs posibles**:

| Caso | Descripción | Acción del agente |
|------|-------------|-------------------|
| `available_slots: [...]` no vacío | Slots disponibles en la fecha solicitada | Almacenar en `offered_slots`, mostrar al usuario con numeración fija |
| `available_slots: []` + `date_too_soon: true` | Fecha viola regla de 3 días | Explicar la regla, sugerir `find_next_available` |
| `available_slots: []` + `holiday_detected: true` | Día festivo | Informar y ofrecer otra fecha |
| `available_slots: []` sin flags | No hay disponibilidad ese día | Ofrecer `find_next_available` |
| `error: str` | Fallo de servicio | NO reintentar. Informar, ofrecer alternativa o derivar a humano |

**Post-procesamiento**: `extract_slot_fields()` → puebla `offered_slots`.

**NUNCA**:
- Re-llamar si `offered_slots` ya tiene slots y la usuaria no pidió nueva fecha
- Asumir disponibilidad sin llamar este tool o `find_next_available`
- Pasar `stylist_id` como string no-UUID (ej: `"cualquiera"`)

---

### B.4 `find_next_available`

**Archivo**: `agent/tools/availability_tools.py`

**Precondición**: La usuaria no tiene fecha concreta o `check_availability` devolvió vacío.

**Inputs requeridos**:
- `service_category: str`
- `stylist_id: str | None` — si se pasa un UUID de estilista, el resultado v4.2 incluye `soonest_any` (el slot más próximo de cualquier estilista) + `selected_stylist_slots` (opciones de esa estilista)
- `start_date: str | None` — fecha preferida opcional, respeta regla de 3 días
- `service_duration_minutes: int | None` — duración exacta del servicio para spacing correcto
- `max_days_to_search: int` — por defecto 10

**Outputs posibles** (v4.2):

| Clave | Descripción |
|-------|-------------|
| `soonest_any` | Slot más próximo con cualquier estilista. `is_different_stylist: bool` |
| `selected_stylist_slots` | Hasta 3 slots de la estilista elegida |
| `available_stylists` | Formato legacy (backwards compat) |
| `substitution_made: true` | La fecha solicitada viola 3 días, se sustituyó por mínimo válido |

**Post-procesamiento**: `extract_slot_fields()` — maneja ambas formas (legacy y v4.2).

**Acción del agente**: Presentar slots con formato numerado. Mencionar si el slot más próximo es de otra estilista (oportunidad de elegir entre rapidez vs estilista preferida).

**NUNCA**:
- Usar este tool si la usuaria ya eligió fecha concreta
- Ignorar el campo `substitution_made` sin explicar por qué cambia la fecha

---

### B.5 `manage_customer`

**Archivo**: `agent/tools/customer_tools.py`

**Precondición**:
- `action="get"`: Para buscar si el cliente ya existe por teléfono
- `action="create"`: Para crear cliente nuevo. Requiere que `customer_id` no esté ya en contexto
- `action="update"`: Para actualizar notas. **NUNCA para guardar solo el nombre** (interceptado por `_pre_tool_call` con `NAME_STORED_DIRECTLY`)

**Inputs requeridos**:
- `action: "get" | "create" | "update"`
- `phone: str` — número de teléfono del cliente (cualquier formato, se normaliza a E.164)
- `data: dict | None` — para create: `{first_name, last_name?, notes?}`. Para update: `{customer_id, first_name?, last_name?, notes?}`

**Outputs posibles**:

| Acción | Caso | Output | Acción del agente |
|--------|------|--------|-------------------|
| `get` | Encontrado | `{id, phone, first_name, last_name, ...}` | Almacenar `customer_id`, `customer_name`. |
| `get` | No encontrado | `{exists: false, phone, message}` | Llamar `create` con nombre y teléfono |
| `create` | Éxito | `{id, phone, first_name, last_name, ...}` | Almacenar `customer_id`, `customer_name` |
| `create` | Duplicado (IntegrityError) | Fallback silencioso → devuelve datos del existente (comportamiento interno de `_create_customer`) | Tratar como get exitoso |
| `update` | Éxito | `{success: true, customer_id, first_name, last_name}` | Actualizar nombre en ctx |
| `update` | No encontrado | `{error: "Customer not found", customer_id}` | Intentar `create` en su lugar |
| Cualquier | Error DB | `{error: str, details?: str}` | NO exponer el mensaje al usuario. Incrementa `manage_customer_failure_count`. Si ≥2 fallos → continuar sin guardar, informar que habrá ajuste verbal |
| Name-only | Interceptado por `_pre_tool_call` | `{rejected: true, error_code: "NAME_STORED_DIRECTLY"}` | El nombre ya fue guardado en `ctx.customer_name`. Continuar el flujo sin volver a llamar manage_customer |

**Post-procesamiento**: `extract_customer_fields()`.

**NUNCA**:
- Exponer mensajes de error técnico al usuario (ej: "Error en la base de datos")
- Llamar con `action="update"` solo para guardar first_name/last_name (será rechazado)
- Reintentar con los mismos datos si ya falló
- Usar `action="update"` con un `customer_id` distinto al del contexto (será rechazado con `STALE_CUSTOMER_ID`)

---

### B.6 `book`

**Archivo**: `agent/tools/booking_tools.py`

**Esta es la tool más crítica del sistema. Tiene múltiples guardas en `_pre_tool_call` antes de ejecutarse.**

**Precondiciones (gates duros en `_pre_tool_call`)**:

| Gate | Error code | Condición de rechazo |
|------|-----------|---------------------|
| Sin slots ofrecidos | `NO_OFFERED_SLOTS` | `ctx.offered_slots` está vacío o None |
| Refresh pendiente | `NEEDS_AVAILABILITY_REFRESH` | `ctx.needs_availability_refresh = True` (post SLOT_TAKEN) |
| Sin servicios | `NO_SELECTED_SERVICES` | `ctx.selected_services` está vacío |
| Sin nombre | `NO_CUSTOMER_NAME` | `ctx.customer_name` es None o `"cliente"` |
| Sin customer_id | `NO_CUSTOMER_ID` | `ctx.customer_id` es None |
| Sin confirmación | `CONFIRMATION_NOT_SHOWN` | `ctx.confirmation_shown = False` |

**Inputs del LLM** (todos opcionales si se pasa `slot_index`):
- `slot_index: int` — **PREFERIDO**: índice 1-based del slot elegido de `## Horarios ofrecidos`
- `stylist_id: str` — auto-resuelto desde `offered_slots[slot_index-1]` si se pasa `slot_index`
- `start_time: str` — auto-resuelto desde `offered_slots[slot_index-1].full_datetime` si se pasa `slot_index`

**Inputs inyectados por `_pre_tool_call`** (nunca del LLM):
- `customer_id` — siempre del contexto
- `first_name` / `last_name` — split desde `ctx.customer_name`
- `services` — siempre de `ctx.selected_services`

**Outputs posibles**:

| Caso | Descripción | Acción del agente |
|------|-------------|-------------------|
| `success: true` + `appointment_id` | Reserva exitosa | Mostrar confirmación con fecha, hora, estilista, servicios. Transición a GENERAL. |
| `error_code: "SLOT_TAKEN"` | Slot ya ocupado | Limpiar `offered_slots`, activar `needs_availability_refresh=True`, llamar `check_availability` / `find_next_available`, ofrecer nuevos slots. NO reintentar `book()` automáticamente. |
| `error_code: "DATE_TOO_SOON"` | Viola regla de 3 días | Explicar la regla, sugerir nueva fecha. |
| `error_code: "CATEGORY_MISMATCH"` | Servicios de categorías incompatibles | Explicar la restricción al usuario. |
| `error_code: "AMBIGUOUS_SERVICE"` | Nombre de servicio ambiguo en DB | Llamar `search_services` para resolver, luego reintentar. |
| `error_code: "SERVICES_NOT_FOUND"` | No se encontraron los servicios | Verificar nombres con `search_services`. |
| `error_code: "BOOKING_ERROR"` | Error inesperado | NO reintentar. Informar al usuario, ofrecer contactar al salón. |
| Rechazado por gate | `{rejected: true, error_code: ...}` | Ver tabla de gates. El LLM debe resolver la condición faltante antes de reintentar. |

**Validación del `BookSchema`**: El schema valida que `stylist_id` y `customer_id` sean UUIDs válidos. Si el LLM pasa un string no-UUID (ej: `"cualquiera"`), Pydantic rechaza con `ValueError` antes de llegar a `_pre_tool_call`.

**NUNCA**:
- Llamar sin haber mostrado el resumen de confirmación
- Llamar sin que el usuario haya dicho explícitamente que confirma
- Reintentar automáticamente tras un fallo (excepto SLOT_TAKEN con nueva disponibilidad)
- Decir al usuario que la reserva está hecha sin `success: true`
- Copiar `stylist_id` o `start_time` manualmente del historial; usar siempre `slot_index`

---

### B.7 `query_info`

**Archivo**: `agent/tools/info_tools.py`

**Precondición**: Usuario pregunta por información general del salón (servicios, horarios, ubicación, FAQs).

**Inputs requeridos**:
- `type: "services" | "faqs" | "hours" | "location"`
- `filters: dict | None` — opcional
- `max_results: int` — por defecto 10

**NUNCA**: Usar para resolver el servicio de la reserva (usar `search_services` para eso).

---

## C. Flujo de Estados Lógico

> **Nota**: BookingMode es LLM-driven. Los "estados" que siguen son el flujo **esperado** por el sistema, no estados de código. El LLM lee `## Datos recogidos` / `## Datos que faltan` del SystemMessage dinámico y decide qué hacer.

```
INICIO (transición desde GREETING o router)
│
│  Pre-resolvers ejecutados antes de cada turno:
│  • _resolve_customer_from_state() → inyecta customer_name/id desde state
│  • _resolve_audience_hint() → inyecta service_audience_hint
│  • resolve_pending_clarification() → auto-resuelve clarificaciones por eje
│  • _detect_confirmation_exchange() → detecta resumen + confirmación del usuario
│  • _check_special_intents() → detecta cancel/escalate (fast-path sin LLM)
│
▼
[A] RECOGER SERVICIO
│  • LLM llama search_services(query=..., audience=<hint auto-inyectado>)
│  • Shape 1 (resolved_service) → ctx.service_name, service_id, selected_services
│  • Shape 2 (clarification_needed) → ctx.pending_clarifications → preguntar eje
│  • Shape 3 (services list) → presentar candidatos
│  • Si múltiples servicios: llamar search_services una vez por servicio en el mismo turno
│
▼
[B] RECOGER ESTILISTA
│  • Si ctx.prefetched_stylists ya tiene datos → presentar sin tool call
│  • Si no → llamar list_stylists(category=...)
│  • Usuario elige o dice "cualquiera" → ctx.stylist_id = UUID elegido o None
│  • Si "cualquiera": stylist_id queda None hasta resolución por slot
│
▼
[C] CONSULTAR DISPONIBILIDAD
│  • Si usuario dio fecha concreta → check_availability(service_category, date, stylist_id?)
│  • Si usuario es flexible → find_next_available(service_category, stylist_id?, service_duration_minutes?)
│  • Resultado → ctx.offered_slots (lista numerada, orden determinístico por full_datetime)
│  • Si stylist_id estaba None y todos los slots son del mismo estilista
│    → extract_slot_fields auto-asigna ctx.stylist_id
│  • Si date_too_soon → explicar regla 3 días, sugerir otra fecha
│  • Si holiday → informar y ofrecer otra fecha
│  • Si available_slots vacío → ofrecer find_next_available o nueva fecha
│
▼
[D] RECOGER NOMBRE (si ctx.customer_name es None)
│  • LLM pregunta: "¿A nombre de quién sería la cita?"
│  • Usuario responde → _extract_name_from_conversation() captura el nombre
│  • Si el LLM intenta llamar manage_customer(create, data={first_name}) →
│    _pre_tool_call intercepta con NAME_STORED_DIRECTLY
│  • manage_customer solo es necesario para obtener customer_id (si no hay uno del state)
│  • Cuando no hay customer_id:
│    LLM llama manage_customer(get, phone) → si no existe: manage_customer(create, phone, {first_name})
│    → ctx.customer_id = UUID resultante
│
▼
[E] NOTAS (opcional, una vez)
│  • LLM ofrece campo de notas de forma natural y sin insistir
│
▼
[F] RESUMEN + GATE DE CONFIRMACIÓN
│  • Cuando TODOS los datos requeridos están completos:
│    - service (ctx.selected_services no vacío)
│    - stylist (ctx.stylist_id no None)
│    - slots (ctx.offered_slots no vacío)
│    - customer_name (no None ni "cliente")
│    - customer_id (no None)
│  • LLM muestra resumen con marcadores reconocibles:
│    "📋 *Resumen de tu cita:* ..."  ← _CONFIRMATION_SUMMARY_MARKERS detecta "resumen de tu cita"
│  • LLM PARA AQUÍ. No llama book() en este turno.
│  • _detect_confirmation_exchange() en el SIGUIENTE turno:
│    Detecta assistant(resumen) + user(afirmativo) → ctx.confirmation_shown = True
│
▼
[G] book() — TURNO DE CONFIRMACIÓN
│  • LLM llama book(slot_index=N)
│  • _pre_tool_call verifica todos los gates
│  • Si pasa todos → BookingTransaction.execute() con SERIALIZABLE isolation
│  • Éxito → ctx._booking_completed = True → transición a GENERAL
│  • Fallo SLOT_TAKEN → limpiar offered_slots, needs_availability_refresh=True → volver a [C]
│  • Otro fallo → no reintentar, informar, ofrecer alternativas
│
▼
FIN (transición a GENERAL o ESCALATION)
```

### Transiciones de estado

| Desde | Hacia | Disparador | Código |
|-------|-------|-----------|--------|
| BOOKING | GENERAL | `ctx._booking_completed = True` | `_build_response()` → `transition_mode(state, "GENERAL")` |
| BOOKING | GENERAL | Frase de cancelación detectada | `_check_special_intents()` |
| BOOKING | ESCALATION | Frase de escalación detectada | `_check_special_intents()` |
| BOOKING | ESCALATION | `awaiting_human = True` en mode_context | Entrada a `handle()`, fast-path |
| Cualquier | BOOKING | Router detecta intent `book` | `conversation_flow.py` router |

### Backtrack paths

| Situación | Retroceso a |
|-----------|------------|
| SLOT_TAKEN | [C] consultar disponibilidad (con `needs_availability_refresh=True`) |
| Usuario cambia estilista después del resumen | [C] o [B] según lo que pide |
| Usuario cambia servicio antes de confirmar | [A] con `services_locked=False` (si aún no se intentó book()) |
| Usuario dice "no" en confirmación | Preguntar qué quiere cambiar, adaptar sin reiniciar |
| manage_customer falla 2 veces | Continuar flujo sin guardar nombre, informar verbalmente |

---

## D. Reglas de No-Regresión

Estas reglas **NUNCA** deben romperse. Están basadas en los bugs reales del historial de commits.

1. **NR-01 — Sin loops de nombre**: El agente NO puede preguntar el nombre más de 2 veces en total. Si `_extract_name_from_conversation()` captura el nombre, el agente NO llama `manage_customer` solo para guardarlo. *(Fix: `_pre_tool_call` intercepta name-only manage_customer con `NAME_STORED_DIRECTLY`)*

2. **NR-02 — Sin book() sin confirmación explícita**: `book()` NUNCA se ejecuta sin que `ctx.confirmation_shown = True`. La gate `CONFIRMATION_NOT_SHOWN` rechaza el intento y le pide al LLM que muestre el resumen primero. El LLM muestra el resumen y **PARA**. Solo en el turno siguiente, con la confirmación del usuario, se llama `book()`.

3. **NR-03 — Sin alucinación de disponibilidad**: El agente NO puede confirmar un horario sin haber llamado `check_availability` o `find_next_available` y recibido un slot real. La gate `NO_OFFERED_SLOTS` bloquea `book()` si `offered_slots` es None o vacío.

4. **NR-04 — Sin errores técnicos de manage_customer expuestos**: Si `manage_customer` falla, el agente dice algo como "hubo un problema menor pero seguimos con tu reserva". NUNCA muestra el mensaje técnico de error (`details`, stack trace, etc.). El código de error `manage_customer_failure_count` es internal.

5. **NR-05 — Sin slots estancados tras SLOT_TAKEN**: Cuando `book()` devuelve `SLOT_TAKEN`, `extract_booking_result()` limpia `offered_slots = None` y activa `needs_availability_refresh = True`. El agente DEBE llamar `check_availability` o `find_next_available` antes de poder llamar `book()` de nuevo. La gate `NEEDS_AVAILABILITY_REFRESH` bloquea `book()` hasta entonces.

6. **NR-06 — Sin pérdida del segundo servicio en multi-servicio**: Para múltiples servicios, el agente llama `search_services` una vez por cada servicio en el MISMO turno. `selected_services` es una lista acumulativa. `services_locked` protege la lista una vez que se inicia `book()`. En modo locked, `extract_service_fields` solo hace append, no sobreescribe. `_pre_tool_call` siempre inyecta `ctx.selected_services` completo en `book().services`.

7. **NR-07 — Sin stylist_id no-UUID**: `BookSchema` valida que `stylist_id` sea un UUID válido (o el sentinel `__RESOLVE_FROM_SLOT__`). `_pre_tool_call` siempre resuelve `stylist_id` desde `offered_slots[slot_index-1]`, nunca desde lo que el LLM pase directamente.

8. **NR-08 — Sin pérdida de intento de reserva en GREETING→BOOKING**: `_resolve_customer_from_state()` inyecta `customer_name` y `customer_id` desde el state global al inicio de cada turno. El router/greeting guarda el `service_audience_hint` en `mode_context` para que BookingMode lo recupere vía `_resolve_audience_hint()`.

9. **NR-09 — Sin customer_id inventado**: `_pre_tool_call` SIEMPRE sobreescribe `customer_id` con `ctx.customer_id` antes de llamar `book()`. El LLM nunca puede inventar o heredar un customer_id del historial de conversación.

10. **NR-10 — Sin reintentar book() automáticamente**: Tras cualquier fallo de `book()` (excepto SLOT_TAKEN con nueva disponibilidad), el agente informa al usuario y ofrece opciones. NO llama `book()` de nuevo en el mismo turno ni en el siguiente sin nueva interacción del usuario.

11. **NR-11 — Sin sobreescritura de slots mientras están activos**: `extract_slot_fields()` incluye una guarda: si `ctx.offered_slots` ya tiene slots y `needs_availability_refresh=False`, no sobreescribe aunque el LLM llame `check_availability` durante la recolección del nombre. Solo `needs_availability_refresh=True` (post SLOT_TAKEN) permite la sobreescritura.

12. **NR-12 — Sin presentar slots reordenados**: `_build_offered_slots_section()` ordena los slots por `full_datetime` + `stylist_name` y guarda el orden ordenado de vuelta en `ctx.offered_slots`. El número que el LLM muestra al usuario DEBE coincidir con el índice en `ctx.offered_slots` para que `slot_index` resuelva correctamente.

13. **NR-13 — Sin cancelación accidental de reserva en curso**: Las `_SOFT_CANCEL_PHRASES` ("no me interesa", "mejor no", "paso") solo se tratan como cancelación cuando `has_active_context = False` (i.e., `selected_services` vacío Y `pending_clarifications` vacío). Si hay una reserva en progreso, estas frases son respuestas válidas a preguntas de clarificación.

14. **NR-14 — Circuit breaker real para book()**: Si `book_failure_count >= 3`, el tool `book` es **excluido** de la lista de tools disponibles en `get_tools()`. El LLM no puede llamarlo aunque quiera.

15. **NR-15 — Sin book() con confirmation_shown=False por "sí" prematuro**: `_detect_confirmation_exchange()` incluye una guarda `_is_booking_data_complete()` que requiere que servicio, estilista, slots y cliente estén presentes antes de activar `confirmation_shown`. Un "sí" a "¿Para dama?" no activa el gate.

---

## E. Casos Límite Documentados

### E.1 Cliente nuevo sin customer_id

**Descripción**: La usuaria inicia una conversación por primera vez y no tiene registro en la base de datos.

**Flujo esperado**:
1. `_resolve_customer_from_state()` no encuentra `customer_id` en el state global.
2. El LLM recolecta el nombre durante el flujo.
3. Cuando se necesita `customer_id` (antes de `book()`), el LLM llama:
   - `manage_customer(action="get", phone=<teléfono>)` → devuelve `{exists: false}`
   - `manage_customer(action="create", phone=<teléfono>, data={first_name, ...})` → devuelve `{id: UUID, first_name, ...}`
4. `extract_customer_fields()` puebla `ctx.customer_id` y `ctx.customer_name`.
5. `book()` puede proceder.

**Qué ha fallado históricamente**:
- El LLM llamaba `manage_customer(action="create", data={first_name="Ana"})` sin teléfono → fallaba con `"Invalid phone number format"`.
- El LLM llamaba `manage_customer` en bucle porque `customer_id` no aparecía en el contexto dinámico tras un fallo.

---

### E.2 Múltiples servicios en una sola solicitud

**Descripción**: La usuaria dice "quiero un corte y un tinte" en un solo mensaje.

**Flujo esperado**:
1. El LLM llama `search_services("corte")` Y `search_services("tinte")` en el **mismo turno** (loop agentic).
2. `extract_service_fields()` construye `selected_services = ["Corte de Dama", "Tinte Color"]` con el primero como servicio primario.
3. `check_availability` se llama con `service_category` del servicio primario.
4. `_pre_tool_call` inyecta la lista completa `ctx.selected_services` en `book().services`.

**Qué ha fallado históricamente**:
- El LLM pasaba `search_services("corte y tinte")` en un solo call → resultado ambiguo.
- Tras SLOT_TAKEN, el segundo servicio se perdía porque `extract_service_fields` sobreescribía `selected_services` con el resultado de una nueva llamada → fix: `services_locked=True` tras el primer `book()`.
- `_pre_tool_call` no inyectaba `selected_services` → book() se llamaba con lista incompleta.

---

### E.3 SLOT_TAKEN después de confirmar

**Descripción**: La usuaria confirma un slot, el agente llama `book()`, pero el slot ya fue tomado por otra persona.

**Flujo esperado**:
1. `book()` devuelve `{success: false, error_code: "SLOT_TAKEN"}`.
2. `extract_booking_result()` limpia `ctx.offered_slots = None`, `ctx.selected_slot = None`, activa `ctx.needs_availability_refresh = True`. Incrementa `book_failure_count`.
3. El agente informa a la usuaria: "El horario elegido ya fue tomado. Buscamos otro."
4. El agente llama `check_availability` o `find_next_available` → nuevos slots → `extract_slot_fields()` limpia `needs_availability_refresh=False`.
5. El agente muestra los nuevos slots con nueva numeración. La usuaria elige. Se repite confirmación → `book()`.

**Qué ha fallado históricamente**:
- El LLM re-ofrecía los mismos slots del historial de conversación (estaban en los mensajes previos del AIMessage). `needs_availability_refresh=True` bloquea `book()` pero el LLM mostraba slots del historial como si fueran válidos.
- `selected_services` se perdía durante el retry porque `extract_service_fields` sobreescribía antes del `services_locked` fix.
- Timezone mismatch entre el `full_datetime` del slot y lo que BookingTransaction esperaba → `SLOT_TAKEN` falso positivo.

---

### E.4 Nombre del cliente no proporcionado

**Descripción**: Llega el momento de la confirmación pero `ctx.customer_name` sigue siendo None.

**Flujo esperado**:
1. Gate `NO_CUSTOMER_NAME` bloquea `book()`.
2. El LLM pregunta: "¿A nombre de quién sería la cita?"
3. La usuaria responde con su nombre.
4. `_extract_name_from_conversation()` extrae el nombre del mensaje si cumple los patrones.
5. Si el LLM intenta `manage_customer(create, data={first_name})` → `_pre_tool_call` intercepta con `NAME_STORED_DIRECTLY` y guarda directamente en `ctx.customer_name`.
6. `book()` puede proceder.

**Qué ha fallado históricamente**:
- El LLM entraba en bucle preguntando el nombre más de 2 veces porque `_extract_name_from_conversation()` no disparaba (la condición `_previous_assistant_asked_for_name()` no se cumplía).
- `manage_customer` fallaba con la llamada name-only y el LLM lo reintentaba en bucle.

---

### E.5 manage_customer falla

**Descripción**: La llamada a `manage_customer` devuelve un error de base de datos.

**Flujo esperado**:
1. `extract_customer_fields()` detecta `result.get("error")` → incrementa `manage_customer_failure_count`.
2. Si es el **primer fallo**: el agente informa de forma amigable y ofrece reintentar.
3. Si `manage_customer_failure_count >= 2`: el tool es excluido de `get_tools()` en el turno siguiente. El prompt muestra el warning "⚠️ No se pudo guardar el nombre (falló 2 veces)". El agente continúa con los datos disponibles y pide confirmación verbal al llegar.
4. El agente NUNCA expone el mensaje de error técnico al usuario.

**Qué ha fallado históricamente**:
- El agente mostraba el texto de error raw de manage_customer al usuario.
- El agente entraba en bucle reintentando manage_customer indefinidamente.

---

### E.6 No hay disponibilidad para la estilista elegida

**Descripción**: La usuaria eligió una estilista específica pero no tiene slots disponibles en los próximos días.

**Flujo esperado**:
1. `find_next_available(service_category, stylist_id=<uuid>)` devuelve `selected_stylist_slots = []` pero sí devuelve `soonest_any` con otra estilista.
2. El agente presenta el `soonest_any` como opción más próxima (con nota de que es otra estilista) + los slots de la estilista elegida (si tiene aunque sea tardíos).
3. Le pregunta a la usuaria: "La próxima disponibilidad con [estilista] es [fecha tardía]. ¿Preferís esa fecha o podría atenderte [otra estilista] antes el [fecha próxima]?"
4. Si la usuaria acepta otra estilista: `ctx.stylist_id` y `ctx.stylist_name` se actualizan con el slot elegido.

**Qué ha fallado históricamente**:
- El agente no usaba el campo `soonest_any` y presentaba la búsqueda como "sin disponibilidad".

---

### E.7 Usuario cancela a mitad del flujo

**Descripción**: La usuaria dice "dejalo" o "olvidalo" durante el proceso de reserva.

**Flujo esperado**:
1. `_check_special_intents()` detecta la frase en `_CANCEL_PHRASES` (fast-path, sin LLM).
2. La negación se verifica: "no quiero cancelar" → `_CANCEL_NEGATION_TOKENS` → no es cancelación.
3. Si es cancelación real: `transition_mode(state, "GENERAL")` con mensaje "Entendido, cancelamos la reserva. ¿Puedo ayudarte en algo más? 😊"
4. `mode_context` se resetea (via `__reset__` sentinel de `transition_mode`).

**Qué ha fallado históricamente**:
- Frases como "mejor no" durante una clarificación de audiencia se interpretaban como cancelación. Fix: `_SOFT_CANCEL_PHRASES` solo activa si `has_active_context = False`.

---

### E.8 Usuario da servicio + estilista + fecha en un solo mensaje

**Descripción**: "Quiero un corte con Pilar el viernes a las 10"

**Flujo esperado**:
1. Router detecta intent `book` y transiciona a BOOKING.
2. `_resolve_audience_hint()` puede extraer hint del mensaje.
3. El LLM en el mismo turno llama:
   - `search_services("corte")`
   - `list_stylists()` o usa prefetch para identificar el UUID de Pilar
   - `check_availability(service_category, "viernes", time_range="10:00-10:30", stylist_id=<uuid-pilar>)`
4. Si hay slot → mostrar confirmación en el mismo turno.
5. Esperar confirmación del usuario → `book()`.

**Qué ha fallado históricamente**:
- El LLM procesaba un dato por turno en lugar de usar multiple tool calls en el mismo turno.
- La intención se perdía al pasar de GREETING a BOOKING (el `implicit_service_hint` no se propagaba correctamente).

---

### E.9 Usuario dice "cualquiera" para la estilista

**Descripción**: La usuaria no tiene preferencia de estilista.

**Flujo esperado**:
1. `ctx.stylist_id` queda `None` (no se asigna a string "cualquiera").
2. El agente llama `find_next_available(service_category, stylist_id=None)` para mostrar disponibilidad general.
3. `extract_slot_fields()` — si todos los slots del resultado son del mismo estilista, auto-asigna `ctx.stylist_id`.
4. Si hay slots de múltiples estilistas, `ctx.stylist_id` queda None y será resuelto desde `offered_slots[slot_index-1]` en `_pre_tool_call`.

**Qué ha fallado históricamente**:
- El LLM pasaba `stylist_id="cualquiera"` a `book()` → `BookSchema.validate_uuid_format` fallaba.
- El LLM pasaba `stylist_id=""` → same.

---

### E.10 Primer turno del bot (EU AI Act disclosure)

**Descripción**: El agente tiene obligación de identificarse como IA al inicio de la conversación.

**Flujo esperado**:
1. `_maybe_prepend_intro()` en `_build_response()` verifica `state.get("ai_disclosure_sent")`.
2. En el primer turno donde `ai_disclosure_sent = False`, prepende el mensaje de disclosure al response.
3. Setea `ai_disclosure_sent = True` en el state.

---

## F. Invariantes del Sistema

Estas son condiciones que el código **siempre** mantiene. Si alguna se rompe, hay un bug.

1. **`book()` es el ÚNICO mecanismo para confirmar una reserva**. No existe ningún otro camino en el código que cree un `Appointment` en la base de datos.

2. **`offered_slots` DEBE ser `None` o una lista de slots reales con `full_datetime` y `stylist_id`**. Nunca contiene slots fabricados o del historial de mensajes. La serialización en `CLEARABLE_NONE_FIELDS` garantiza que un `None` explícito sobreescriba el valor anterior en `merge_dicts`.

3. **`customer_id` en `book()` SIEMPRE viene de `ctx.customer_id`**, que a su vez viene de `manage_customer` exitoso o de `state.customer_id`. El LLM nunca puede inyectar un `customer_id` directo en el llamado.

4. **`confirmation_shown` solo puede ser `True` si `_is_booking_data_complete()` retorna `True`**. Esto garantiza que el gate no se activa prematuramente.

5. **`services_locked = True` solo se activa en el primer `book()` no-rechazado**. Los rechazos de `_pre_tool_call` (ToolCallRejection) no cuentan como intentos reales y no activan el lock.

6. **El orden de slots en `ctx.offered_slots` es el mismo que el LLM muestra al usuario**. `_build_offered_slots_section()` ordena y guarda de vuelta en `ctx.offered_slots`. `slot_index` resuelve contra ese orden.

7. **`needs_availability_refresh = False` SOLO cuando se recibe nueva disponibilidad**. `extract_slot_fields()` limpia este flag al almacenar nuevos slots. No hay otra forma de limpiar este flag.

8. **El `book_failure_count` se resetea cuando se obtiene nueva disponibilidad** (`extract_slot_fields` hace `ctx.book_failure_count = 0`). Esto permite intentar `book()` nuevamente tras un SLOT_TAKEN con slots frescos.

9. **El contexto dinámico (`_build_dynamic_context`) se reconstruye en cada turno** y se puede actualizar mid-loop via `_refresh_dynamic_context()` cuando `manage_customer` o `search_services` actualizan `ctx` durante el agentic loop.

10. **La transición de modo SIEMPRE usa `transition_mode()`** que aplica el sentinel `__reset__: True` en `mode_context` para que `merge_dicts` limpie datos stale del modo anterior.

---

## G. Gaps Detectados

Comparación entre este spec y el código actual. Severidad: P0=crítico/datos corruptos, P1=bug de flujo frecuente, P2=degradación de experiencia.

> **Estado**: Todos los 10 gaps detectados han sido cerrados. Tests en `tests/unit/test_gap_fixes_p1.py` (GAP-04/06/09/10) y `tests/unit/test_gap_fixes_p2.py` (P0/GAP-01/02/03/05/07/08).

---

### GAP-01: `selected_slot` no se puebla en la arquitectura actual — ✅ CERRADO

- **Archivo**: `agent/modes/booking_mode.py:667-680` (`_pre_tool_call`)
- **Fix**: `_pre_tool_call` ahora popula `ctx.selected_slot` cuando resuelve `slot_index` → `stylist_id + start_time`. El slot incluye `date`, `time`, `full_datetime`, `stylist_id`, `stylist_name`.
- **Test**: `test_gap_fixes_p2.py::TestGap01SelectedSlotPopulated`
- **Severidad original**: P1

---

### GAP-02: `list_stylists` tool excluida del TOOL_EXTRACTORS — ✅ CERRADO

- **Archivo**: `agent/modes/tool_extractors.py:723`
- **Fix**: `list_stylists` registrada en `TOOL_EXTRACTORS` → `extract_stylist_fields`. Los resultados se almacenan en `ctx.prefetched_stylists`.
- **Test**: `test_gap_fixes_p2.py::TestGap02ListStylistsInExtractors`
- **Severidad original**: P1

---

### GAP-03: `query_info` excluida del TOOL_EXTRACTORS — ✅ CERRADO

- **Archivo**: `agent/modes/tool_extractors.py:580-596, 728`
- **Fix**: `query_info` registrada en `TOOL_EXTRACTORS` → `extract_query_info_fields` (no-op documentado). Previene log noise de "no extractor" y provee hook para futura extracción.
- **Test**: `test_gap_fixes_p2.py::TestGap03QueryInfoInExtractors`
- **Severidad original**: P2

---

### GAP-04: `stylist_name` no se popula desde `list_stylists` vía agentic loop — ✅ CERRADO

- **Archivo**: `agent/modes/booking_mode.py:1210-1247` (`_try_resolve_stylist_from_message`)
- **Fix**: Post-agentic-loop, `_try_resolve_stylist_from_message()` scans the user message for stylist name matches against `ctx.prefetched_stylists`. Sets both `stylist_id` and `stylist_name`.
- **Test**: `test_gap_fixes_p1.py::TestGap04TryResolveStylistFromMessage`
- **Severidad original**: P1

---

### GAP-05: Circuit breaker de `book` requiere `_ctx` inicializado antes de `get_tools()` — ✅ CERRADO

- **Archivo**: `agent/modes/booking_mode.py:220-248`
- **Fix**: `get_tools()` usa `getattr(self, "_ctx", None)` con fallback graceful. Si `_ctx` no existe, devuelve TODOS los tools (incluido `book`) en vez de crashear. Comentario docstring explica el riesgo y la mitigación.
- **Test**: `test_gap_fixes_p2.py::TestGap05CircuitBreakerResilience`
- **Severidad original**: P2 (riesgo latente, no bug activo)

---

### GAP-06: `_detect_confirmation_exchange` solo escanea las últimas 4 mensajes — ✅ CERRADO

- **Archivo**: `agent/modes/booking_mode.py` (`_detect_confirmation_exchange`)
- **Fix**: Ventana ampliada a 10 mensajes. Permite hasta 8 mensajes intermedios entre el resumen y la confirmación del usuario.
- **Test**: `test_gap_fixes_p1.py::TestGap06ConfirmationDetectionWindow`
- **Severidad original**: P1

---

### GAP-07: `_extract_name_from_conversation` solo activa si el último mensaje del asistente preguntó el nombre — ✅ CERRADO

- **Archivo**: `agent/modes/booking_mode.py:1249-1301`
- **Fix**: Sistema de 2 tiers. Tier 1 (structured patterns: "me llamo X", "soy X", "mi nombre es X") corre SIEMPRE — alta precisión, sin falsos positivos. Tier 2 (bare name pattern: "María") solo corre cuando el bot preguntó por el nombre.
- **Test**: `test_gap_fixes_p2.py::TestGap07NameExtractionTwoTier`
- **Severidad original**: P2

---

### GAP-08: `needs_availability_refresh` no se persiste correctamente cuando `offered_slots=None` — ✅ CERRADO

- **Archivo**: `agent/modes/booking_context.py:215-228`
- **Estado**: Verificado como NO bug. `False` pasa el filtro `v is not None and v != [] and v != {}` → se serializa correctamente. `True` es truthy → también se serializa. Ambos valores hacen round-trip correcto. Tests de regresión agregados para prevenir roturas futuras.
- **Test**: `test_gap_fixes_p2.py::TestGap08NeedsAvailabilityRefreshPersistence`
- **Severidad original**: P2 (riesgo latente, no bug activo)

---

### GAP-09: No hay guard para `stylist_id = None` antes de `book()` sin `slot_index` — ✅ CERRADO

- **Archivo**: `agent/modes/booking_mode.py:684-730` (`_pre_tool_call`)
- **Fix**: Cuando `slot_index` es None, `_pre_tool_call` valida que el `stylist_id` pasado directamente aparezca en `offered_slots`. Si no existe → `STALE_STYLIST_ID` rejection con mensaje descriptivo.
- **Test**: `test_gap_fixes_p1.py::TestGap0910BookSentinelAndStaleStylistId`
- **Severidad original**: P1

---

### GAP-10: `book()` puede ser llamado con `stylist_id = "__RESOLVE_FROM_SLOT__"` si no hay `slot_index` y el LLM omite `stylist_id` — ✅ CERRADO

- **Archivo**: `agent/modes/booking_mode.py:691-710` (`_pre_tool_call`)
- **Fix**: `_pre_tool_call` intercepta el sentinel `__RESOLVE_FROM_SLOT__` antes de que llegue a `book()`. Devuelve `MISSING_SLOT_INDEX` rejection con mensaje actionable en vez del críptico `INVALID_UUID`.
- **Test**: `test_gap_fixes_p1.py::TestGap0910BookSentinelAndStaleStylistId`
- **Severidad original**: P1

---

*Documento generado por exploración directa del código fuente en Marzo 2026.*  
*Total de gaps detectados: **10** — todos cerrados ✅*  
*Tests: `test_gap_fixes_p1.py` (22 tests) + `test_gap_fixes_p2.py` (36 tests) = 58 tests*
