# Módulos — Capabilities Conversacionales

> Cada módulo es UNA conversación posible. Orquesta cores + infra para resolver SU caso de uso. Self-contained: borralo y los demás siguen.

## Capability contract (recordatorio de P7)

Todo módulo implementa el contrato de **7 campos** (formalizado en `agent/core/capability.py` desde E1):

1. `name` — identificador estable para registry y telemetría (ej. `"booking"`).
2. `state_slice` — sub-dict del ConversationState que SOLO esta capability muta.
3. `tools` — lista de tools.
4. `prompt_overlay` — `.md` con guía específica.
5. `pre_loop_resolvers` — resolvers deterministas a correr antes del LLM.
6. `completion_predicate` — `(state) → bool`.
7. `exit_edges` — modos a los que puede transicionar.

---

## Módulo: greeting

**Cuándo se activa**: primer turno de una conversación nueva, o reset explícito por el operador.

### Contrato

| Campo | Valor |
|-------|-------|
| state_slice | `greeting_context` (mínimo: `name_asked`, `name_captured`) |
| tools | (sin tools) — pura narración + extracción Python |
| prompt_overlay | `agent/prompts/modes/greeting.md` (20 líneas) |
| pre_loop_resolvers | `_extract_audience_from_reply` (cuando aplica) |
| completion_predicate | `name_captured == True` o turno 2 (si no se obtuvo) |
| exit_edges | `BOOKING`, `GENERAL`, `APPOINTMENT_MANAGEMENT`, `ESCALATION` |

### Flow

1. Saludo de Maite, pregunta por el nombre.
2. Usuario responde (puede dar nombre, puede ignorar la pregunta y ya pedir algo).
3. Si dio nombre → captura, se acuerda.
4. Inmediatamente cede a otro modo según intent del mensaje.

### Estado actual

- `agent/modes/greeting_mode.py` (417 líneas).
- Captura de nombre embedded acá; debería invocar `cores/customers/create_or_lookup`.

### Bug histórico

Hubo un cambio (#986 verify-report) para REMOVER la pregunta explícita de nombre cuando el customer ya existe en DB (lookup por phone). Si vuelve a aparecer, está pidiendo nombre a alguien que ya conocemos.

---

## Módulo: booking

**El módulo más complejo del sistema. La razón por la que existe el bot.**

**Cuándo se activa**: usuario expresa intención de reservar ("quiero cortarme el pelo", "una cita para el martes", etc.).

### Contrato

| Campo | Valor |
|-------|-------|
| state_slice | `booking_context` (TypedDict, 25+ fields, ver `agent/state/schemas.py:34-90`) |
| tools | `update_booking`, `check_availability`, `book` |
| prompt_overlay | `agent/prompts/modes/booking.md` (214 líneas) |
| pre_loop_resolvers | `is_negation`, `_extract_audience_from_reply`, `_resolve_digit_selection`, `_NO_PREF_PHRASES` (no-pref stylist) |
| completion_predicate | `_booking_completed == True` (set después de `book` exitoso) |
| exit_edges | `GENERAL` (cita confirmada), `ESCALATION` (fallo crítico) |

### Flow (state machine implícita)

```
Paso 1   Servicio (con desambiguación de audience si aplica)
Paso 1B  ¿Algo más? (negación → avanza; afirmación → vuelve a Paso 1)
Paso 2   Estilista (con opción "sin preferencia")
Paso 3   Fecha (lenguaje natural)
Paso 4   Slot (selección por dígito o por hora)
Paso 5   Notas (OPCIONAL — no bloquea)
Paso 6   Nombre (si no estaba)
Paso 7   Confirmación final
Paso 8   book() → cita creada
```

### Tools de la capability

| Tool | Cuándo se invoca | Qué retorna |
|------|------------------|-------------|
| `update_booking` | Después de cada respuesta del usuario, para persistir lo capturado | `{success, collected, missing, next_step, errors, _booking_context_patch}` |
| `check_availability` | Cuando ya hay servicio + estilista + fecha (visible solo si no hay `_audience_ambiguity`) | `{available_slots, total_duration_minutes, alternative_dates}` |
| `book` | Cuando `_booking_complete()` retorna True (visible solo entonces) | `{status: "ok", appointment_id, start_time, end_time}` |

### Resolvers críticos

- **`is_negation`** — `infra/resolvers/negation.py` (movido desde `shared/negation_phrases.py` en E1). Determinista, fuzzy match difflib 0.86. Resuelve "Nada más", "Ya está", "No", "Nope". Pre-loop. **Patrón canónico de P3.**
- **`_extract_audience_from_reply`** — `booking_mode.py:132-169`. Detecta "señora", "caballero", "niño", "bebé". Setea `service_audience_hint` y limpia `_audience_ambiguity` atómicamente.
- **`_resolve_digit_selection`** — `booking_mode.py`. Detecta "la 1", "el segundo", "esa". Setea `selected_slot_index`.

### Middleware stack (orden importa)

```
ToolChoiceMiddleware       (config-driven: ALWAYS_FORCE / FORCE_AFTER_SERVICE / NEVER_FORCE)
DynamicToolsMiddleware     (filtra tools según booking_context)
NodeBridgeMiddleware       (delega _pre_tool_call / _post_tool_result)
DedupToolCallMiddleware    (evita repetir misma call con mismos args)
FinalTextRecoveryMiddleware(si loop termina sin texto y hubo tool_results, re-invoca sin tools)
TokenTrackingMiddleware    (telemetría billing)
```

### Bug histórico: "¿algo más?" loop (recurrente, 5+ iteraciones)

**Síntoma observado en producción 2026-04-17 21:30**:

```
Pepe:    Hola, quiero cortarme el pelo
Maite:   ¿es para señora, caballero, niño/a o bebé?
Pepe:    señora!
Maite:   Perfecto, te apunto un corte de pelo para señora. ¿Quieres añadir algo más?
Pepe:    Nada mas
Maite:   Genial, te apunto un corte de pelo para señora. ¿Quieres añadir algo más?
Pepe:    No
Maite:   Perfecto, te apunto un corte de pelo para señora. ¿Quieres añadir algo más?
```

**Causa estructural** (audit #4005 + verificación auditoría 2026-04-18):

1. `is_negation()` clasifica "Nada mas" / "No" como negación → setea `add_more_asked = True` pre-loop (línea 394).
2. Pero el flow_hint en el prompt sigue mostrando "Pendiente: preguntar ¿algo más?" porque el LLM lo lee del system_message cacheado, no del state actualizado.
3. El LLM, viendo el flow_hint stale, vuelve a preguntar.
4. Loop.

**Por qué SDD `booking-flow-architectural-map` (commit 8bacfa3) NO lo cerró del todo**:

Cerró el leak de `notas` en `_build_flow_hint` (W1), pero `add_more_asked` puede tener una variante similar. **No verificado en esta documentación; pendiente confirmar en próximo SDD cycle.**

**Por qué la migración a capability contract lo cierra estructuralmente**:

- El estado se entrega vía **tool response next_step** + **tool visibility filtering**, NO vía XML cacheado en system_message.
- `_build_flow_hint` desaparece como concepto; reemplazado por `next_step` que el LLM lee del último tool result.
- Una sola write path para `add_more_asked` (`is_negation` resolver → patch). No hay rendering paralelo en `_build_flow_hint` y `_build_response`.

### Estado actual

- `agent/modes/booking_mode.py` (800 líneas) — TODO mezclado.
- `agent/tools/booking_data_tools.py:update_booking` — la tool principal.
- `agent/tools/availability_tools.py:check_availability`.
- `agent/tools/booking_tools.py:book`.
- `agent/prompts/modes/booking.md` (214 líneas).
- `agent/prompts/dynamic_context.py` — flow_hint, audience hints, etc.

### Anti-patrones a corregir (top 5)

1. Queries directas a `database.models` (`booking_mode.py:467, 488`).
2. Resolvers inline en el modo en lugar de en registry (`_extract_audience_from_reply`, `_negation_resolver`).
3. Lógica de "¿algo más?" repartida entre prompt + flag + flow_hint (write path doble).
4. Customer memory write embebido en `_post_tool_result` (`:708-725`).
5. Alias `self._booking_context = self._mode_context` (`:319-320`) — confusión semántica.

---

## Módulo: appointment-management

**Cuándo se activa**: usuario quiere ver, cancelar o reagendar una cita existente.

### Contrato

| Campo | Valor |
|-------|-------|
| state_slice | `appointment_context` (in-memory bag, no TypedDict formal) |
| tools | `manage_appointments` (read), tools de cancel/reschedule (parciales) |
| prompt_overlay | `agent/prompts/modes/appointment_management.md` (26 líneas) |
| pre_loop_resolvers | (faltan) — debería usar `is_negation`, `is_affirmation`, `_resolve_digit_selection` |
| completion_predicate | acción ejecutada (cancel done o reschedule done) |
| exit_edges | `GENERAL`, `ESCALATION` |

### Estado actual

- `agent/modes/appointment_management_mode.py` (800 líneas) — **aún usa `_run_agentic_loop` legacy**, no `create_agent` + middleware.
- `agent/tools/appointment_management_tools.py` — read implementado, cancel/reschedule parciales.
- `agent/services/cancellation_service.py`, `reschedule_service.py` — operaciones core.

### Anti-patrones (heredados + propios)

- Loop legacy v5.x — necesita port a `create_agent` (M7 deferido).
- Duplica listas de phrases afirmativas/negativas (vs `shared/negation_phrases.py`).
- Sin `DynamicToolsMiddleware` — visibilidad de tools hardcoded.
- ToolMessage con errores imperativos detectados en líneas 407-466 (#3906) — viola P5.

### Migración

En el plan: Phase E3. Después de portar booking, es candidato directo al mismo capability contract con resolvers compartidos.

---

## Módulo: general

**Cuándo se activa**: FAQs, info de horarios, precios, ubicación, descripción de servicios.

### Contrato

| Campo | Valor |
|-------|-------|
| state_slice | (stateless) |
| tools | (sin tools) — el catálogo va en el prompt |
| prompt_overlay | `agent/prompts/modes/general.md` (29 líneas) |
| pre_loop_resolvers | (ninguno) |
| completion_predicate | siempre completa al primer turno |
| exit_edges | `BOOKING`, `APPOINTMENT_MANAGEMENT`, `GREETING` |

### Estado actual

- `agent/modes/general_mode.py` (196 líneas) — el más simple.
- Catálogo de servicios + horarios inyectados en el prompt.

### Risk

Si el catálogo crece mucho, este modo va a inflar tokens en cada turno. En ese caso, considerar tools de query (`get_services`, `get_business_hours`) en lugar de inyección directa.

---

## Módulo: escalation

**Cuándo se activa**: el bot detecta que NO puede resolver (3 errores seguidos, frase explícita "quiero hablar con una persona", urgencia detectada).

### Contrato

| Campo | Valor |
|-------|-------|
| state_slice | `escalation_context` (paso de FSM) |
| tools | `escalate` (solo dispara la notificación) |
| prompt_overlay | `agent/prompts/modes/escalation.md` (61 líneas) |
| pre_loop_resolvers | (FSM Python pura, no usa LLM para decidir) |
| completion_predicate | escalation marcada en DB + notificación enviada |
| exit_edges | (terminal — el operador toma la conversación) |

### Estado actual

- `agent/modes/escalation_mode.py` (400 líneas) — FSM pura, sin LLM para decisiones.
- `agent/tools/escalation_tools.py:escalate` — marca la conversación como escalada.
- `agent/services/escalation_service.py` — crea registro DB + notifica al operador.

### Razón de ser

Cumplimiento EU AI Act: el bot debe ser capaz de ceder a humano transparente y sin fricción cuando el usuario lo pida o cuando no pueda resolver.

---

## Tabla resumen

| Módulo | LOC actual | Tools | Resolvers | Prompt | Migration phase |
|--------|-----------|-------|-----------|--------|-----------------|
| greeting | 417 | 0 | 1 | 20 líneas | E4 (cleanup) |
| booking | 800 | 3 | 4 | 214 líneas | **E2 (primer port)** |
| appointment-mgmt | 800 | 1+ | (faltan) | 26 líneas | **E3 (segundo port)** |
| general | 196 | 0 | 0 | 29 líneas | E4 (cleanup) |
| escalation | 400 | 1 | 0 | 61 líneas | E4 (cleanup) |

## Cómo añadir un módulo nuevo (test de extensibilidad)

Ejemplo: `loyalty` module.

1. Crear `agent/modes/loyalty_mode.py` que implemente el contrato de 6 campos.
2. Añadir entrada en `agent/routing/intent_router.py` para clasificar el intent.
3. Crear `agent/prompts/modes/loyalty.md`.
4. Si necesita tools nuevas, crearlas en `agent/tools/loyalty_tools.py`.
5. Si necesita data del salón, invocar `cores/customers/get_loyalty_points()`.

**Test**: si añadir loyalty requiere TOCAR booking, appointment-mgmt o cualquier otro módulo → la arquitectura falló. Stop.

## BookingContext Field Ownership Registry

> Establecido en SDD `booking-migration-cleanup` (B.3.10). Cada campo tiene exactamente UN escritor autorizado.
> Aplicado via AST lint: `scripts/check_booking_state_writes.py` (unit test: `tests/unit/test_no_direct_booking_context_writes.py`).

### Canal de escritura

| Canal | Descripción |
|-------|-------------|
| **pre-loop resolver** | `apply_resolver_patch(bc, resolver_wrapper(...))` — antes del LLM loop, en `handle()` |
| **update_booking patch** | `_post_tool_result[update_booking]` aplica `result["_booking_context_patch"]` |
| **_post_tool_result[book]** | Único escritor para campos de confirmación de reserva |
| **informational pre-fill** | Escrito en `handle()` pre-loop vía `apply_resolver_patch` (fuentes de estado externas) |
| **async DB cache** | `_resolve_service_category()` — escribe en `_resolve_service_category` (allow-listed) |

### Tabla de propietarios

| Campo | Escritor autorizado | Canal |
|-------|---------------------|-------|
| `confirmed` | `resolve_confirmation` | pre-loop resolver |
| `_confirmation_shown` | gate `SHOW_CONFIRMATION` en `handle()` | informational pre-fill |
| `add_more_asked` | `resolve_add_more_negation` | pre-loop resolver |
| `selected_slot` | `resolve_digit_selection` (pre-loop) y `update_booking` (slot_index branch) | pre-loop resolver + update_booking patch |
| `last_stylist` | `resolve_stylist_selection` (pre-loop) y `update_booking` (stylist_name branch) | pre-loop resolver + update_booking patch |
| `customer_name` | `update_booking` (customer_first_name branch) | update_booking patch |
| `customer_first_name` | `update_booking` | update_booking patch |
| `customer_last_name` | `update_booking` | update_booking patch |
| `notes` | `update_booking` (notes branch) | update_booking patch |
| `notes_state` | `update_booking` (notes branch) | update_booking patch |
| `last_services` | `update_booking` (services branch) | update_booking patch |
| `last_total_duration_minutes` | `update_booking` (services branch via DB lookup) | update_booking patch |
| `last_service_category` | `_resolve_service_category()` (async DB cache) | async DB cache |
| `offered_slots` | `_post_tool_result[check_availability]` (único receptor de slots) | post-tool result |
| `no_preference_stylist` | `update_booking` (stylist_name = "sin preferencia") | update_booking patch |
| `service_audience_hint` | `update_booking` (service_audience_hint branch) | update_booking patch |
| `_audience_ambiguity` | `update_booking` (services branch + audience_hint clear) | update_booking patch |
| `_booking_completed` | `_post_tool_result[book]` | post-tool result (book) |
| `booked_appointment_id` | `_post_tool_result[book]` (via `update_booking` patch, si aplica) | post-tool result (book) |
| `_suggested_customer_name` | `resolve_customer_from_state` | informational pre-fill |
| `customer_id` | `resolve_customer_from_state` | informational pre-fill |
| `opening_booking_request` | `handle()` pre-loop via `apply_resolver_patch` | informational pre-fill |
| `_offered_stylists` | `handle()` pre-loop via `apply_resolver_patch` (from `_get_stylists_for_services`) | informational pre-fill |
| `pending_disambiguations` | `update_booking` | update_booking patch |

### Reglas de invariante (verificadas por AST lint)

1. **Zero** `booking_context[k] = v` directos en `handle()` fuera de `apply_resolver_patch`.
2. **Zero** `ctx[k] = v` en `update_booking` tool body — solo `patch[k] = v`.
3. **Zero** escrituras de `last_services`, `last_stylist`, `last_total_duration_minutes` en `_post_tool_result[check_availability]`.
4. Funciones allow-listeadas (permitidas por contrato): `apply_resolver_patch`, `_post_tool_result`, `_resolve_customer_from_state`, `_resolve_service_category`, `_pre_tool_call`.

---

## Referencias

- `01-architecture-principles.md` (P5, P6, P7) — contrato y reglas.
- `03-cores.md` — qué cores expone el dominio.
- `05-infra.md` — qué adaptadores usan los módulos.
- `06-current-vs-target.md` — mapeo del estado actual.
- `07-migration-plan.md` — Phase E2-E5.
