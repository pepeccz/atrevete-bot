# Story 5.2: Implementación de FSM Controller Base

Status: done

## Story

As a **desarrollador**,
I want **implementar la clase BookingFSM que controla estados y transiciones del flujo de booking**,
so that **tengamos un controlador robusto que valide el flujo de conversación de manera determinista y testeable**.

## Acceptance Criteria

1. **Given** el módulo FSM
   **When** se importa `agent/fsm/booking_fsm.py`
   **Then** existe la clase `BookingFSM` con enum `BookingState` de 7 estados: IDLE, SERVICE_SELECTION, STYLIST_SELECTION, SLOT_SELECTION, CUSTOMER_DATA, CONFIRMATION, BOOKED

2. **Given** una instancia de `BookingFSM`
   **When** se llama `can_transition(intent)` con una transición válida
   **Then** retorna `True` y cuando se llama con una transición inválida retorna `False`

3. **Given** una instancia de `BookingFSM`
   **When** se llama `transition(intent)` con transición válida
   **Then** actualiza el estado interno, acumula datos en `collected_data`, y retorna `FSMResult` con `success=True`

4. **Given** una instancia de `BookingFSM` con estado en progreso
   **When** se llama `persist()`
   **Then** el estado se guarda en Redis con key `fsm:{conversation_id}` y TTL de 900 segundos (15 min)

5. **Given** un `conversation_id` con estado FSM guardado en Redis
   **When** se llama `BookingFSM.load(conversation_id)`
   **Then** retorna una instancia con el estado y `collected_data` restaurados

6. **Given** un `conversation_id` sin estado FSM en Redis
   **When** se llama `BookingFSM.load(conversation_id)`
   **Then** retorna una nueva instancia en estado IDLE con `collected_data` vacío

7. **Given** cualquier transición de estado (válida o inválida)
   **When** se ejecuta
   **Then** se registra un log INFO con `conversation_id`, estado origen, estado destino, y tipo de intent

8. **Given** el código implementado
   **When** se ejecutan los unit tests
   **Then** hay tests para todas las transiciones válidas (6) + transición cancel universal + casos de error (transiciones inválidas) con coverage >90%

9. **Given** el código implementado
   **When** se ejecuta `mypy --strict agent/fsm/`
   **Then** no hay errores de tipos (código con typing estricto)

## Tasks / Subtasks

- [x] Task 1: Crear estructura del módulo FSM (AC: #1)
  - [x] 1.1 Crear directorio `agent/fsm/`
  - [x] 1.2 Crear `agent/fsm/__init__.py` con exports públicos
  - [x] 1.3 Crear `agent/fsm/booking_fsm.py` con esqueleto de clase
  - [x] 1.4 Implementar `BookingState` enum con 7 estados

- [x] Task 2: Implementar modelos de datos (AC: #1)
  - [x] 2.1 Crear `agent/fsm/models.py` con `Intent`, `IntentType`, `FSMResult` dataclasses
  - [x] 2.2 Definir tipos estrictos con `TypedDict` para `collected_data`
  - [x] 2.3 Validar modelos con mypy

- [x] Task 3: Implementar lógica de transiciones (AC: #2, #3)
  - [x] 3.1 Definir matriz de transiciones válidas como constante
  - [x] 3.2 Implementar `can_transition(intent)` con validación de estado origen y datos requeridos
  - [x] 3.3 Implementar `transition(intent)` con actualización de estado y `collected_data`
  - [x] 3.4 Implementar transición especial `cancel_booking` (ANY → IDLE)
  - [x] 3.5 Implementar `reset()` para limpiar estado

- [x] Task 4: Implementar persistencia Redis (AC: #4, #5, #6)
  - [x] 4.1 Implementar `persist()` con serialización JSON a Redis
  - [x] 4.2 Implementar `load()` classmethod con deserialización
  - [x] 4.3 Configurar TTL de 900 segundos (15 min)
  - [x] 4.4 Manejar caso de key no existente (crear nuevo en IDLE)

- [x] Task 5: Implementar logging (AC: #7)
  - [x] 5.1 Agregar logging INFO en cada transición exitosa
  - [x] 5.2 Agregar logging WARNING en transiciones rechazadas
  - [x] 5.3 Incluir `conversation_id`, `from_state`, `to_state`, `intent_type` en logs

- [x] Task 6: Unit tests (AC: #8)
  - [x] 6.1 Crear `tests/unit/test_booking_fsm.py`
  - [x] 6.2 Tests para cada transición válida (6 transiciones del happy path)
  - [x] 6.3 Tests para transición `cancel_booking` desde cada estado
  - [x] 6.4 Tests para transiciones inválidas (rechazos)
  - [x] 6.5 Tests para `persist()` y `load()` con Redis mock
  - [x] 6.6 Tests para `load()` con key no existente
  - [x] 6.7 Verificar coverage >90% con `pytest --cov=agent/fsm`

- [x] Task 7: Type checking y validación final (AC: #9)
  - [x] 7.1 Ejecutar `mypy --strict agent/fsm/`
  - [x] 7.2 Corregir errores de tipos si los hay
  - [x] 7.3 Agregar docstrings a todas las funciones públicas

## Dev Notes

### Contexto Arquitectónico

Esta story implementa **AC2** del Epic 5 Tech Spec: "BookingFSM Implementado y Funcional". El código debe seguir exactamente la especificación documentada en Story 5-1.

**Referencia primaria:** [Source: docs/architecture/fsm-booking-flow.md] - Especificación completa de estados y transiciones

### Estados FSM a Implementar

```python
class BookingState(str, Enum):
    """Estados del flujo de booking."""
    IDLE = "idle"                               # Sin booking activo
    SERVICE_SELECTION = "service_selection"     # Seleccionando servicios
    STYLIST_SELECTION = "stylist_selection"     # Seleccionando estilista
    SLOT_SELECTION = "slot_selection"           # Seleccionando horario
    CUSTOMER_DATA = "customer_data"             # Recopilando datos cliente
    CONFIRMATION = "confirmation"               # Confirmando booking
    BOOKED = "booked"                          # Booking completado
```

[Source: docs/architecture/fsm-booking-flow.md#BookingState-Enum]

### Transiciones Válidas a Implementar

| Estado Origen | Estado Destino | Intent Requerido | Datos Requeridos |
|---------------|----------------|------------------|------------------|
| IDLE | SERVICE_SELECTION | `start_booking` | - |
| SERVICE_SELECTION | STYLIST_SELECTION | `confirm_services` | `services[]` no vacío |
| STYLIST_SELECTION | SLOT_SELECTION | `select_stylist` | `stylist_id` definido |
| SLOT_SELECTION | CUSTOMER_DATA | `select_slot` | `slot` con fecha/hora |
| CUSTOMER_DATA | CONFIRMATION | `provide_customer_data` | `first_name` definido |
| CONFIRMATION | BOOKED | `confirm_booking` | Todos los datos |
| **ANY** | IDLE | `cancel_booking` | - |

[Source: docs/architecture/fsm-booking-flow.md#Matriz-de-Transiciones]

### Estructura de collected_data

```python
@dataclass
class CollectedData:
    services: list[str] = field(default_factory=list)  # Lista de nombres de servicios
    stylist_id: str | None = None                       # UUID del estilista (como string)
    slot: dict | None = None                            # {start_time, duration_minutes}
    first_name: str | None = None
    last_name: str | None = None
    notes: str | None = None
    appointment_id: str | None = None                   # Después de book()
```

### Redis Key Schema

```
fsm:{conversation_id}    # JSON: {state, collected_data, last_updated}
                         # TTL: 900 segundos (15 min)
```

[Source: docs/sprint-artifacts/tech-spec-epic-5.md#FSM-Redis-Schema]

### Project Structure Notes

- **Nuevo directorio:** `agent/fsm/`
- **Nuevos archivos:**
  - `agent/fsm/__init__.py` - Exports: `BookingFSM`, `BookingState`, `Intent`, `IntentType`, `FSMResult`
  - `agent/fsm/booking_fsm.py` - Clase principal
  - `agent/fsm/models.py` - Dataclasses y enums
- **Tests nuevos:** `tests/unit/test_booking_fsm.py`
- **Dependencias existentes:** Usa `shared/redis_client.py` para conexión Redis

### Testing Standards

**Framework:** pytest + pytest-asyncio (async tests para Redis)
**Coverage target:** >90% para `agent/fsm/`
**Mock strategy:** Usar `fakeredis` o mock de `shared/redis_client.py`

```bash
# Comando para ejecutar tests
DATABASE_URL="postgresql+asyncpg://..." ./venv/bin/pytest tests/unit/test_booking_fsm.py -v --cov=agent/fsm --cov-report=term-missing
```

[Source: docs/sprint-artifacts/tech-spec-epic-5.md#Unit-Tests]

### Learnings from Previous Story

**From Story 5-1-diseno-fsm-states-transiciones (Status: done)**

- **Referencia Autoritativa:** El documento `docs/architecture/fsm-booking-flow.md` contiene la especificación completa de estados, transiciones y validaciones - usar como fuente de verdad
- **7 Estados Definidos:** IDLE → SERVICE_SELECTION → STYLIST_SELECTION → SLOT_SELECTION → CUSTOMER_DATA → CONFIRMATION → BOOKED
- **13 IntentTypes:** Documentados en fsm-booking-flow.md, implementar en `agent/fsm/models.py`
- **Diagrama Mermaid:** El diagrama visual puede servir como referencia rápida para implementación de transiciones
- **Validaciones por Estado:** Documentadas en sección "Validaciones y Reglas de Negocio" - implementar en `can_transition()`

[Source: docs/sprint-artifacts/5-1-diseno-fsm-states-transiciones.md#Dev-Agent-Record]

### References

- [Source: docs/architecture/fsm-booking-flow.md] - Especificación FSM completa (Story 5-1 output)
- [Source: docs/sprint-artifacts/tech-spec-epic-5.md#Detailed-Design] - APIs e interfaces
- [Source: docs/sprint-artifacts/tech-spec-epic-5.md#BookingFSM-Class-Interface] - Interface de la clase
- [Source: docs/epics/epic-5-rediseño-fsm-hibrida.md#Story-5-2] - Definición de la story en epic
- [Source: docs/architecture.md#ADR-006] - Decisión arquitectónica FSM Híbrida

## Dev Agent Record

### Context Reference

- docs/sprint-artifacts/5-2-implementacion-fsm-controller-base.context.xml

### Agent Model Used

Claude Sonnet 4.5 (claude-sonnet-4-5-20250929)

### Debug Log References

- Plan: Implementar BookingFSM siguiendo especificación de fsm-booking-flow.md
- Implementación directa sin bloqueos; todos los ACs verificados con tests

### Completion Notes List

- ✅ Implementado módulo FSM completo en `agent/fsm/` con 3 archivos
- ✅ BookingState enum con 7 estados exactos según especificación
- ✅ IntentType enum con 13 tipos de intención
- ✅ Clase BookingFSM con métodos `can_transition()`, `transition()`, `reset()`, `persist()`, `load()`
- ✅ Persistencia Redis con key `fsm:{conversation_id}` y TTL 900 segundos
- ✅ Logging INFO/WARNING en todas las transiciones
- ✅ 45 unit tests con coverage >97% en agent/fsm/
- ✅ mypy --strict pasa sin errores
- ✅ Fix menor a `shared/redis_client.py` para typing genérico (string annotation)

### File List

**New Files:**
- `agent/fsm/__init__.py` - Module exports
- `agent/fsm/models.py` - IntentType, Intent, FSMResult, CollectedData, SlotData
- `agent/fsm/booking_fsm.py` - BookingFSM class with state machine logic
- `tests/unit/test_booking_fsm.py` - 45 unit tests

**Modified Files:**
- `shared/redis_client.py` - Fixed return type annotation (line 23)

### Change Log

- **2025-11-21:** Story drafted from backlog
- **2025-11-21:** Story implemented - FSM Controller Base complete with all 9 ACs verified
- **2025-11-21:** Senior Developer Review notes appended

---

## Senior Developer Review (AI)

### Reviewer
Pepe

### Date
2025-11-21

### Outcome
**✅ APPROVE**

Todos los acceptance criteria están implementados correctamente. Todos los tasks marcados como completados están verificados con evidencia en el código. Tests pasan al 100% con coverage >97%. Código cumple con mypy --strict.

### Summary

La implementación del FSM Controller Base cumple con todos los requisitos especificados en Story 5-2 y sigue la especificación de `docs/architecture/fsm-booking-flow.md`. El código es limpio, bien documentado, y tiene excelente cobertura de tests.

**Puntos destacados:**
- Implementación completa de 7 estados y 13 tipos de intención
- Matriz de transiciones bien definida con validaciones de datos
- Persistencia Redis correcta con TTL 900s
- Logging estructurado en todas las transiciones
- 45 unit tests con 97.46% coverage

### Key Findings

**LOW Severity:**
- [ ] [Low] Import no usado `CollectedData` en booking_fsm.py (ruff F401) [file: agent/fsm/booking_fsm.py:20]
- [ ] [Low] Usar `datetime.UTC` en lugar de `timezone.utc` para Python 3.11+ style (ruff UP017 x4) [file: agent/fsm/booking_fsm.py:98,164,210,236]

**Advisory Notes:**
- Note: Los issues de ruff son auto-fixables con `ruff check --fix agent/fsm/`
- Note: El cambio en `shared/redis_client.py` (línea 23) es un fix de typing válido

### Acceptance Criteria Coverage

| AC# | Description | Status | Evidence |
|-----|-------------|--------|----------|
| AC1 | Clase BookingFSM con enum BookingState de 7 estados | ✅ IMPLEMENTED | `agent/fsm/models.py:37-46`, `agent/fsm/booking_fsm.py:29-49` |
| AC2 | can_transition() retorna True/False correctamente | ✅ IMPLEMENTED | `agent/fsm/booking_fsm.py:115-146`, tests `TestCanTransition` (7 tests) |
| AC3 | transition() actualiza estado, collected_data, retorna FSMResult | ✅ IMPLEMENTED | `agent/fsm/booking_fsm.py:148-229`, tests `TestTransition` (6 tests) |
| AC4 | persist() guarda en Redis con key fsm:{conv_id} y TTL 900s | ✅ IMPLEMENTED | `agent/fsm/booking_fsm.py:245-268`, `test_persist_saves_to_redis`, `test_persist_uses_900_second_ttl` |
| AC5 | load() restaura estado y collected_data desde Redis | ✅ IMPLEMENTED | `agent/fsm/booking_fsm.py:270-319`, `test_load_restores_state` |
| AC6 | load() crea nueva instancia en IDLE si key no existe | ✅ IMPLEMENTED | `agent/fsm/booking_fsm.py:288-293`, `test_load_creates_new_if_not_found` |
| AC7 | Logging INFO/WARNING en cada transición | ✅ IMPLEMENTED | `agent/fsm/booking_fsm.py:166-172,186-192,215-221,238-242`, tests `TestLogging` (3 tests) |
| AC8 | Unit tests con coverage >90% | ✅ IMPLEMENTED | `tests/unit/test_booking_fsm.py` (45 tests, 97.46% coverage) |
| AC9 | mypy --strict agent/fsm/ sin errores | ✅ IMPLEMENTED | `Success: no issues found in 3 source files` |

**Summary:** 9 of 9 acceptance criteria fully implemented

### Task Completion Validation

| Task | Marked As | Verified As | Evidence |
|------|-----------|-------------|----------|
| Task 1: Crear estructura del módulo FSM | [x] | ✅ VERIFIED | `agent/fsm/__init__.py`, `agent/fsm/booking_fsm.py`, `agent/fsm/models.py` existen |
| Task 1.1: Crear directorio agent/fsm/ | [x] | ✅ VERIFIED | Directorio existe con 3 archivos |
| Task 1.2: Crear __init__.py con exports | [x] | ✅ VERIFIED | `agent/fsm/__init__.py:27-35` exporta 7 símbolos |
| Task 1.3: Crear booking_fsm.py con esqueleto | [x] | ✅ VERIFIED | Archivo existe con 375 líneas |
| Task 1.4: Implementar BookingState enum con 7 estados | [x] | ✅ VERIFIED | `agent/fsm/models.py:37-46` |
| Task 2: Implementar modelos de datos | [x] | ✅ VERIFIED | `agent/fsm/models.py` |
| Task 2.1: Crear models.py con Intent, IntentType, FSMResult | [x] | ✅ VERIFIED | `agent/fsm/models.py:16-111` |
| Task 2.2: Definir tipos estrictos con TypedDict | [x] | ✅ VERIFIED | `CollectedData` y `SlotData` TypedDict en `models.py:49-69` |
| Task 2.3: Validar modelos con mypy | [x] | ✅ VERIFIED | `mypy --strict agent/fsm/` pasa |
| Task 3: Implementar lógica de transiciones | [x] | ✅ VERIFIED | `agent/fsm/booking_fsm.py:52-86,115-229` |
| Task 3.1: Definir matriz de transiciones | [x] | ✅ VERIFIED | `TRANSITIONS` dict en `booking_fsm.py:52-72` |
| Task 3.2: Implementar can_transition() | [x] | ✅ VERIFIED | `booking_fsm.py:115-146` |
| Task 3.3: Implementar transition() | [x] | ✅ VERIFIED | `booking_fsm.py:148-229` |
| Task 3.4: Implementar cancel_booking (ANY→IDLE) | [x] | ✅ VERIFIED | `booking_fsm.py:126-127,161-180` |
| Task 3.5: Implementar reset() | [x] | ✅ VERIFIED | `booking_fsm.py:231-243` |
| Task 4: Implementar persistencia Redis | [x] | ✅ VERIFIED | `booking_fsm.py:245-319` |
| Task 4.1: Implementar persist() | [x] | ✅ VERIFIED | `booking_fsm.py:245-268` |
| Task 4.2: Implementar load() classmethod | [x] | ✅ VERIFIED | `booking_fsm.py:270-319` |
| Task 4.3: Configurar TTL 900 segundos | [x] | ✅ VERIFIED | `FSM_TTL_SECONDS = 900` en `booking_fsm.py:26` |
| Task 4.4: Manejar key no existente | [x] | ✅ VERIFIED | `booking_fsm.py:288-293` |
| Task 5: Implementar logging | [x] | ✅ VERIFIED | INFO en transiciones exitosas, WARNING en rechazadas |
| Task 5.1: Logging INFO en transiciones exitosas | [x] | ✅ VERIFIED | `booking_fsm.py:166-172,215-221,238-242` |
| Task 5.2: Logging WARNING en transiciones rechazadas | [x] | ✅ VERIFIED | `booking_fsm.py:186-192` |
| Task 5.3: Incluir conv_id, from_state, to_state, intent_type | [x] | ✅ VERIFIED | Format strings incluyen todos los campos |
| Task 6: Unit tests | [x] | ✅ VERIFIED | `tests/unit/test_booking_fsm.py` (45 tests) |
| Task 6.1: Crear test_booking_fsm.py | [x] | ✅ VERIFIED | Archivo existe con 584 líneas |
| Task 6.2: Tests para transiciones válidas (6) | [x] | ✅ VERIFIED | `test_transition_happy_path_complete` cubre todas |
| Task 6.3: Tests para cancel_booking desde cada estado | [x] | ✅ VERIFIED | `TestCancelBooking` class (6 tests) |
| Task 6.4: Tests para transiciones inválidas | [x] | ✅ VERIFIED | `test_transition_invalid_*` y `TestValidationErrors` |
| Task 6.5: Tests para persist() y load() con mock | [x] | ✅ VERIFIED | `TestPersistence` class (5 tests) |
| Task 6.6: Tests para load() con key no existente | [x] | ✅ VERIFIED | `test_load_creates_new_if_not_found` |
| Task 6.7: Verificar coverage >90% | [x] | ✅ VERIFIED | 97.46% coverage en agent/fsm/ |
| Task 7: Type checking y validación final | [x] | ✅ VERIFIED | mypy --strict pasa |
| Task 7.1: Ejecutar mypy --strict | [x] | ✅ VERIFIED | `Success: no issues found in 3 source files` |
| Task 7.2: Corregir errores de tipos | [x] | ✅ VERIFIED | Sin errores |
| Task 7.3: Agregar docstrings a funciones públicas | [x] | ✅ VERIFIED | Todas las funciones públicas tienen docstrings |

**Summary:** 35 of 35 completed tasks verified, 0 questionable, 0 falsely marked complete

### Test Coverage and Gaps

- **Unit tests:** 45 tests, 100% pass rate
- **Coverage:** 97.46% para `agent/fsm/`
  - `__init__.py`: 100%
  - `models.py`: 100%
  - `booking_fsm.py`: 97.46% (líneas 144, 358-359 no cubiertas - edge cases menores)
- **Test categories covered:**
  - State enum (3 tests)
  - IntentType enum (3 tests)
  - FSM initialization (3 tests)
  - can_transition (7 tests)
  - transition (6 tests)
  - cancel_booking (6 tests)
  - reset (1 test)
  - persistence (5 tests)
  - logging (3 tests)
  - service accumulation (2 tests)
  - next_action (3 tests)
  - validation_errors (3 tests)

### Architectural Alignment

- ✅ Sigue especificación de `docs/architecture/fsm-booking-flow.md`
- ✅ 7 estados exactos según spec: IDLE, SERVICE_SELECTION, STYLIST_SELECTION, SLOT_SELECTION, CUSTOMER_DATA, CONFIRMATION, BOOKED
- ✅ 13 IntentTypes según spec
- ✅ Matriz de transiciones coincide con spec
- ✅ Redis key pattern `fsm:{conversation_id}` con TTL 900s
- ✅ Usa `shared/redis_client.py` como mandatorio
- ✅ Separación de responsabilidades FSM vs LLM según ADR-006

### Security Notes

- ✅ No hay vulnerabilidades de inyección (no user input directo en queries)
- ✅ JSON serialization segura con `json.dumps/loads`
- ✅ Redis keys usan prefijo namespace `fsm:` (aislamiento correcto)
- ✅ No se almacenan datos sensibles (solo referencias: stylist_id, service names)
- ✅ TTL previene acumulación de datos huérfanos

### Best-Practices and References

- [Python Enum best practices](https://docs.python.org/3.11/howto/enum.html) - Usar `str, Enum` para JSON serialization
- [dataclasses](https://docs.python.org/3.11/library/dataclasses.html) - Pattern usado para Intent, FSMResult
- [TypedDict](https://docs.python.org/3.11/library/typing.html#typing.TypedDict) - Para CollectedData con tipos estrictos
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/) - Para tests async de Redis

### Action Items

**Code Changes Required:**
- [ ] [Low] Remover import no usado `CollectedData` [file: agent/fsm/booking_fsm.py:20]
- [ ] [Low] Usar `datetime.UTC` en lugar de `timezone.utc` (4 ocurrencias) [file: agent/fsm/booking_fsm.py:98,164,210,236]

**Advisory Notes:**
- Note: Ejecutar `ruff check --fix agent/fsm/` para auto-fix de issues de estilo
- Note: El cambio en `shared/redis_client.py` es correcto y no requiere más acción
- Note: Coverage de 97.46% excede el target de 90% - excelente trabajo
