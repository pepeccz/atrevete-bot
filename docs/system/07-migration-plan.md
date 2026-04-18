# Plan de Migración: Estado Actual → Target

> Cinco fases. Cada una shippable en aislamiento. Cada una behind feature flag. Sin big-bang. Reversible flip de flag.

## Principios del plan

1. **No rewrite. Evolución.** El código actual tiene 70% de los primitives correctos. Ajustamos los 30% que están en el lugar equivocado o duplicados.
2. **Cada phase es shippable**. Si la siguiente phase no se hace, el sistema sigue funcionando.
3. **Feature flag por capability**. La capability nueva corre en paralelo a la vieja; el flag elige cuál se usa para una conversación dada.
4. **Tests primero**. Todo cambio TIENE que pasar por TDD si el proyecto está en strict TDD mode (que lo está).
5. **Phases largas no se permiten**. Si una phase pasa de 2 semanas, se subdivide.

## Estimación global

**3-4 semanas focused, solo. Behind feature flag desde el día 1.**

| Phase | Duración | Entregables principales |
|-------|----------|--------------------------|
| E1 — Scaffolding | 3-4 días | Abstracciones nuevas en paralelo. Sin cambio de comportamiento. |
| E2 — Portar Booking | 1-1.5 semanas | BookingCapability completa. Bug "¿algo más?" cierra estructuralmente. |
| E3 — Portar AppointmentMgmt | 4-6 días | AppointmentManagementCapability + tools cancel/reschedule completas. |
| E4 — Cleanup físico | 3-5 días | Movimiento de carpetas. Consolidación. Eliminación de legacy. |
| E5 — Probar extensibilidad | 2-3 días | LoyaltyCapability end-to-end. Si requiere tocar booking → arquitectura falló. |

---

## Phase E1 — Scaffolding (3-4 días)

**Objetivo**: introducir las abstracciones nuevas SIN cambiar comportamiento. Todo sigue funcionando con el código viejo.

### Entregables

1. **`agent/core/capability.py`** — clase abstracta `Capability` con el contrato de 6 campos:
   ```
   - state_slice: TypedDict
   - tools: list[Tool]
   - prompt_overlay: Path
   - pre_loop_resolvers: list[Resolver]
   - completion_predicate: Callable[[State], bool]
   - exit_edges: list[ModeName]
   ```

2. **`agent/core/resolvers.py`** — registry de resolvers. Cada resolver es `(user_text: str, state: State) → Optional[StatePatch]`. Telemetría obligatoria estandarizada.

3. **`agent/core/tool_response.py`** — Pydantic `ToolResponse`:
   ```
   ToolResponse:
     status: Literal["ok", "partial", "rejected", "complete"]
     collected: list[str]
     missing: list[str]
     next_step: str
     errors: list[str]
     payload: dict
   ```

4. **`agent/core/status_line.py`** — pre-turn HumanMessage builder que reemplaza `<dynamic_context>` XML en system_message. Construye una línea breve con el estado actual y la añade como HumanMessage justo antes del turno del LLM (NO en system_message cacheado).

5. **Mover `shared/negation_phrases.py` → `infra/resolvers/negation.py`** — primer paso del unbundling de `shared/`. Importadores se actualizan vía rename.

6. **Limpiar dead code**:
   - `agent/fsm/models.py` (legacy v5.x).
   - `agent/prompts/legacy/`.
   - Investigar y eliminar (o documentar): `agent/batching/`, `agent/resilience/`, `agent/validators/` (módulos huérfanos detectados en audit).
   - `shared/email_service.py` si confirmado no usado.
   - `api/services/stripe_service.py` si confirmado removido.

7. **CI gate de imports** — script en `scripts/check_layers.py` que valida con AST:
   - `cores/X/` no importa de `modulos/` ni de `infra/` (excepto excepciones explícitas).
   - `modulos/X/` no importa de `modulos/Y/`.
   - `infra/X/` no importa de `modulos/`.
   - Falla CI si se viola.

### Tests

- Unit tests de las nuevas abstracciones (Capability ABC, ToolResponse Pydantic, Resolver registry).
- Integration test que demuestra: una capability dummy registra un resolver dummy, recibe un input, emite el patch correcto.
- NO se tocan tests existentes. Todo el código viejo sigue corriendo sin cambios.

### Criterio de DONE

- Tests existentes verdes (zero regressions).
- Nuevas abstracciones tienen ≥90% coverage.
- CI gate de imports activo.

### Riesgo

**BAJO**. Es solo añadir abstracciones nuevas + cleanup. Si E2 no se hace, E1 deja el código levemente más limpio y nada más.

---

## Phase E2 — Portar Booking a Capability (1-1.5 semanas)

**Objetivo**: BookingCapability implementa el contrato de 6 campos usando la lógica EXISTENTE de `booking_mode.py`. Behind feature flag `USE_CAPABILITY_BOOKING=true`.

**Bug crítico que se cierra estructuralmente**: "¿algo más?" loop. El estado pasa por la patch pipeline (resolver `is_negation` → patch único) y la entrega es vía `next_step` en tool response, NO via `<flow_hint>` XML. La doble write path desaparece.

### Sub-entregables

#### E2.1 — Cores que booking necesita (3 días)

- `cores/services/` — Service model + audience canonicalization (consolidar `shared/audience_maps.py`) + fuzzy matching (consolidar `_find_similar_services` + `fuzzy_resolver.py`).
- `cores/stylists/` — Stylist model + `get_by_category` (extraer de `booking_mode._load_stylists_by_category`).
- `cores/availability/` — slotting + business_hours validation (consolidar `agent/services/availability_service.py` + `shared/business_hours_validator.py`).
- `cores/appointments/` — `book(customer_id, stylist_id, service_id, start_time, notes?)` operación atómica (extraer de `agent/tools/booking_tools.py:book`).
- `cores/customers/` — `lookup_by_phone`, `create`, `update_preferences_post_booking` (extraer de `customer_memory_service` + `customer_tools`).

Tests: cada core ≥90% coverage. Sin LLM, sin Chatwoot, sin Redis. SQLite in-memory.

#### E2.2 — Resolvers extraídos al registry (1 día)

- `infra/resolvers/audience.py` — extraer `_extract_audience_from_reply` de booking_mode.
- `infra/resolvers/digit_selection.py` — extraer `_resolve_digit_selection`.
- `infra/resolvers/no_preference.py` — extraer `_NO_PREF_PHRASES` matcher.
- Cada resolver con telemetría estandarizada.
- Tests: parametrizados con casos canónicos + variantes con typo + casos negativos.

#### E2.3 — Tools nuevas con ToolResponse contract (2 días)

- `modulos/booking/tools/update_booking.py` — wrap del existente, retorna `ToolResponse`.
- `modulos/booking/tools/check_availability.py` — wrap, invoca `cores/availability/get_slots_for_date`.
- `modulos/booking/tools/book.py` — wrap, invoca `cores/appointments/book`.
- AST-lint test: ningún `errors[]` empieza con verbo imperativo.

#### E2.4 — BookingCapability (2 días)

- `modulos/booking/capability.py` — implementa `Capability` ABC.
- `modulos/booking/state.py` — `BookingContext` TypedDict (mover de `agent/state/schemas.py`).
- `modulos/booking/prompt.md` — mover de `agent/prompts/modes/booking.md`.
- Eliminar `<dynamic_context>` XML del system_message; usar `infra/llm/status_line.py` para inyectar pre-turn HumanMessage.
- DynamicToolsMiddleware filtering: `check_availability` solo visible si no hay `_audience_ambiguity` y hay servicio + estilista + fecha. `book` solo visible si `completion_predicate` retorna True.

#### E2.5 — Feature flag wiring (0.5 día)

- `shared/config.py`: `USE_CAPABILITY_BOOKING: bool = False` (default off).
- `agent/graphs/conversation_flow.py`: branch en build time. Si flag on, usa `BookingCapability`. Si off, usa `BookingMode` viejo.
- Default OFF: ship con flag desactivado, validar en QA, activar gradualmente por conversación (ej. % de roll-out).

#### E2.6 — Tests E2E (1-2 días)

- Smoke test: reserva completa end-to-end con flag ON.
- Test específico del bug histórico: "Hola, quiero cortarme el pelo" → "señora" → "Nada más" debe avanzar a estilista (no loop).
- Comparativa: misma conversación corrida con flag ON vs OFF, mismo resultado funcional (cita creada en DB).

### Criterio de DONE

- 134+ tests existentes de booking siguen verdes con flag OFF.
- Tests nuevos de capability verdes con flag ON.
- Smoke test reserva end-to-end con flag ON: PASS.
- Bug "¿algo más?" reproducible con flag OFF, NO reproducible con flag ON.

### Riesgo

**ALTO**. Es el port más complejo. Mitigación: feature flag + ship a producción con flag OFF + validar exhaustivamente antes de roll-out.

### Honest caveat

Si durante E2 descubrís que un state invariant del booking no encaja en el contrato de 6 campos, **STOP**. No fuerces. El contrato es hipótesis; el flow real es ground truth. Re-diseñá el contrato o rechazalo y iterá distinto.

---

## Phase E3 — Portar AppointmentManagement (4-6 días)

**Objetivo**: AppointmentManagementCapability completa. Migra del legacy `_run_agentic_loop` a `create_agent` + middleware. Tools de cancel/reschedule completas (hoy parciales).

### Entregables

1. **`cores/appointments/` ampliado**: `cancel(appointment_id, reason?)`, `reschedule(appointment_id, new_start_time, new_stylist_id?)`, `find_by_customer(customer_id, status_filter?)`.
2. **Resolvers compartidos**: `is_affirmation` (NUEVO, simétrico a is_negation), `is_abort` (NUEVO).
3. **Tools nuevas**:
   - `modulos/appointment_management/tools/lookup_appointments.py`
   - `modulos/appointment_management/tools/confirm_cancellation.py`
   - `modulos/appointment_management/tools/execute_cancellation.py`
   - `modulos/appointment_management/tools/confirm_reschedule.py`
   - `modulos/appointment_management/tools/execute_reschedule.py`
4. **AppointmentManagementCapability** — implementa contrato.
5. **Eliminar ToolMessage imperativos** (lines 407-466 en `appointment_management_mode.py` viejo) — reemplazar por visibility gates + descriptive next_step.
6. **Feature flag**: `USE_CAPABILITY_APPOINTMENT_MGMT`.

### Criterio de DONE

- Tests existentes verdes con flag OFF.
- Smoke tests de cancelación + reagendamiento end-to-end con flag ON.
- Reuso del 100% de los resolvers compartidos (audience, negation, affirmation, digit_selection).

### Riesgo

**MEDIO**. El flow es más simple que booking (3 pasos vs 8), y ya tenemos el patrón de E2 validado.

---

## Phase E4 — Cleanup físico (3-5 días)

**Objetivo**: ahora que las capabilities funcionan en paralelo, **mover físicamente las carpetas** y eliminar el código viejo.

### E4 deferred tasks (from E1 dead-code investigation, 2026-04-18)

The following candidates were investigated in E1 and found to be non-deletable without additional runtime evidence:

- **Investigate and delete `agent/resilience/*` if confirmed dead.** Conditions for deletion: (1) zero static importers outside the package (already confirmed by grep), (2) zero runtime invocations over ≥7 days in production (add temporary logging to verify), (3) no middleware or dependency-injection wires these classes indirectly. If all three conditions met: delete in a single commit. If not: MOVE to `infra/resilience/` and wire into active use.

Full investigation report: `docs/system/e1-dead-code-investigation.md`.

### Entregables

1. **Mover infra**: middleware, prompts loader, intent-router, state, redis client, chatwoot client, gcal services. Ver `06-current-vs-target.md` para mapeo exacto.
2. **Mover cores restantes**: customer memory service, confirmation service.
3. **Consolidar `database/models.py`**: dividir en `cores/*/models.py` con declarative base compartido en `infra/database/base.py`. **OJO**: las migrations Alembic deben seguir funcionando. No tocar nombres de tablas.
4. **Mover seeds**: `database/seeds/services.py` → `cores/services/seeds.py`, etc.
5. **Eliminar código legacy**:
   - `agent/modes/booking_mode.py` viejo.
   - `agent/modes/appointment_management_mode.py` viejo.
   - Default flags ON.
   - Eliminar conditional branching en `conversation_flow.py`.
6. **Mover tests análogamente** a la nueva estructura.
7. **Actualizar `CLAUDE.md`, `AGENTS.md`** y todas las referencias.

### Criterio de DONE

- Imports check pasa.
- Todos los tests verdes.
- Smoke test E2E pasa.
- Build de docker compose levanta sin errores.
- Deploy a staging exitoso.

### Riesgo

**ALTO** (mucho rename). Mitigación: hacer en commits chicos por subsistema (un commit = una infra movida + sus imports actualizados + tests verdes). Nunca un commit gigante.

---

## Phase E5 — Probar extensibilidad (2-3 días)

**Objetivo**: validar que la arquitectura cumple su promesa. Añadir una capability NUEVA end-to-end sin tocar las existentes.

### Capability candidata: `loyalty`

Funcionalidad: usuario pregunta "cuántos puntos tengo?" → bot responde con sus puntos actuales y próxima recompensa.

### Entregables

1. **`cores/loyalty/`**: model `LoyaltyAccount`, operación `get_points(customer_id)`.
2. **`modulos/loyalty/`**: capability + tool + prompt.
3. **Una entrada nueva en `infra/intent-router/keyword_map.py`**: keywords "puntos", "loyalty", "recompensas".
4. **Tests E2E**.

### Criterio de SUCCESS

Si añadir loyalty requiere TOCAR booking, appointment-management o cualquier otro módulo → **la arquitectura falló**. Re-evaluar contrato.

Si NO toca otros módulos → success.

### Riesgo

**BAJO** (es el test final, no una migración). Si falla, las phases previas necesitan iteración.

---

## Riesgos transversales

### Riesgo 1: Production live

El sistema está en producción. Cualquier deploy puede romper conversaciones reales con clientes.

**Mitigación**:
- Feature flag por capability.
- Roll-out gradual: 5% → 25% → 50% → 100% de conversaciones nuevas.
- Métrica de éxito: `mode.completion_rate` no baja vs baseline.
- Rollback inmediato: flip flag a OFF.

### Riesgo 2: Drift de specs vs código

Mientras hacemos la migración, pueden ocurrir cambios urgentes en el código viejo (bugfixes en prod). Esos cambios deben portarse al código nuevo.

**Mitigación**:
- Durante phases E2-E3, congelar features nuevas en el código viejo. Solo bugfixes.
- Cada bugfix en el código viejo dispara una task: portar al código nuevo en la misma PR.

### Riesgo 3: Tests existentes que asumen estructura vieja

Hay 254 archivos de test. Muchos importan de `agent.modes.booking_mode`, `shared.audience_maps`, etc. Cuando movamos archivos, esos tests rompen.

**Mitigación**:
- Phase E4 (cleanup físico) incluye explícitamente mover tests + actualizar imports.
- Pre-E4 mantener compatibility shims (re-exports) si es necesario para no romper imports.

### Riesgo 4: Descubrir un invariant que rompe el contrato

Posibilidad real durante E2: el booking flow tiene una idiosincrasia que NO encaja en el contrato de 6 campos.

**Mitigación**:
- Si pasa: STOP. No forzar el contrato. Re-evaluar: ¿el contrato debe ampliarse a 7 campos? ¿O es un caso especial que justifica un escape hatch documentado?
- Decisión documentada en SDD change.

---

## Cómo se mide el éxito

| Métrica | Baseline (hoy) | Target post-E5 |
|---------|----------------|----------------|
| LOC en `agent/modes/booking_mode.py` | 800 | 0 (eliminado) — equivalente split entre capability + cores |
| LOC en `agent/modes/appointment_management_mode.py` | 800 | 0 (eliminado) |
| Modes accediendo `database.models` directo | 4+ casos | 0 |
| Tests unit cores con SQLite (sin Postgres real) | 0 | ≥90% coverage de cores |
| Bug "¿algo más?" reproducible | Sí | No (cierra estructural en E2) |
| Resolvers en registry vs inline | ~20% en registry | 100% en registry |
| Tools que retornan `ToolResponse` Pydantic | 0% | 100% |
| Capabilities que cumplen contrato de 6 campos | 0/5 | 5/5 |
| Tiempo para añadir una capability nueva | indeterminado (iteración por iteración) | 2-3 días (probado en E5) |

---

## Próximos pasos inmediatos

Cuando arranquemos la migración (no en este doc, en otra sesión):

1. **Pre-flight**: levantar el repo, correr `pytest` baseline, anotar count de fails (~234 baseline conocido).
2. **Crear branch `feat/architecture-migration-e1`**.
3. **Iniciar SDD change `e1-scaffolding`** vía `/sdd-new`.
4. Ejecutar phases secuenciales. Cada phase = un SDD change.

## Referencias

- `00-overview.md` — qué es el sistema.
- `01-architecture-principles.md` — los 10 principios.
- `02-layers.md` — cores/modulos/infra/ui.
- `03-cores.md` — cores en detalle.
- `04-modulos.md` — módulos en detalle.
- `05-infra.md` — infra en detalle.
- `06-current-vs-target.md` — mapping archivo-por-archivo.
- Engram: `sdd/agent-architecture-holistic/industry-research` (ID 4008) — fundamentación industrial.
- Engram: `sdd/agent-architecture-holistic/codebase-audit` (ID 4005) — audit detallado.
- Engram: `sdd/booking-flow-architectural-map/archive-report` (ID 3981) — último SDD cycle, fixes parciales del bug.
