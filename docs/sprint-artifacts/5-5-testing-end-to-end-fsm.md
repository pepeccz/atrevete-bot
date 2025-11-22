# Story 5.5: Testing End-to-End con FSM

Status: review

## Story

As a **QA/Developer**,
I want **testear el flujo completo de booking con FSM**,
so that **tengamos confianza de que el sistema funciona correctamente antes de migrar Epic 1**.

## Acceptance Criteria

1. **Given** el flujo completo de booking (IDLE → SERVICE_SELECTION → STYLIST_SELECTION → SLOT_SELECTION → CUSTOMER_DATA → CONFIRMATION → BOOKED)
   **When** se ejecutan los tests end-to-end
   **Then** todos los tests pasan sin errores y el booking se completa exitosamente

2. **Given** una transición inválida (ej: IDLE → CONFIRMATION sin datos)
   **When** el usuario intenta ejecutar esa transición
   **Then** el sistema rechaza la transición con un mensaje amigable y redirige al paso correcto

3. **Given** un error durante la ejecución de una tool (ej: Google Calendar API falla)
   **When** ocurre el error
   **Then** la FSM mantiene su estado anterior (recovery) y el usuario recibe mensaje explicativo sin corrupción de estado

4. **Given** conversaciones "out of order" (ej: usuario intenta confirmar sin seleccionar servicio)
   **When** se detecta el intent fuera de orden
   **Then** el sistema guía al usuario al paso correcto manteniendo naturalidad conversacional

5. **Given** los tests manuales via WhatsApp (8 casos de uso definidos)
   **When** se ejecutan todos los casos
   **Then** todos pasan confirmando naturalidad conversacional y correcto funcionamiento del flujo

6. **Given** los bugs críticos de Epic 1 Story 1-5 (UUID serialization, state flags never updated)
   **When** se ejecutan escenarios que antes causaban esos bugs
   **Then** los bugs están resueltos y el sistema funciona correctamente

7. **Given** todos los tests del Epic 5 (unit, integration, e2e)
   **When** se ejecuta la suite completa
   **Then** 100% de tests pasan con coverage >85% para código nuevo de FSM

8. **Given** la documentación de test cases
   **When** se revisa la documentación
   **Then** incluye todos los casos de prueba, resultados, y evidencia de manual testing

## Tasks / Subtasks

- [x] Task 1: Crear tests end-to-end de flujo completo - happy path (AC: #1, #7)
  - [x] 1.1 Crear `tests/integration/test_booking_e2e.py` con test de flujo completo
  - [x] 1.2 Test `test_complete_booking_single_service()`: Un servicio, un estilista, happy path
  - [x] 1.3 Test `test_complete_booking_multiple_services()`: Múltiples servicios con duración combinada
  - [x] 1.4 Test `test_booking_with_returning_customer()`: Cliente existente con historial
  - [x] 1.5 Test `test_booking_with_new_customer()`: Cliente nuevo primera vez

- [x] Task 2: Crear tests de validación de transiciones inválidas (AC: #2, #4)
  - [x] 2.1 Test `test_cannot_confirm_from_idle()`: Intent confirm_booking desde IDLE
  - [x] 2.2 Test `test_cannot_select_slot_without_stylist()`: Saltar STYLIST_SELECTION
  - [x] 2.3 Test `test_cannot_book_without_customer_data()`: Ir a CONFIRMATION sin nombre
  - [x] 2.4 Test `test_redirect_messages_are_natural()`: Verificar mensajes de redirección son amigables
  - [x] 2.5 Test `test_user_guided_to_correct_step()`: FSM guía al paso correcto

- [x] Task 3: Crear tests de recovery de errores (AC: #3)
  - [x] 3.1 Test `test_google_calendar_api_failure_recovery()`: FSM mantiene estado en error de Calendar
  - [x] 3.2 Test `test_database_error_recovery()`: FSM mantiene estado en error de DB
  - [x] 3.3 Test `test_llm_intent_extraction_failure_recovery()`: Intent UNKNOWN no corrompe FSM
  - [x] 3.4 Test `test_tool_execution_error_preserves_fsm_state()`: Error en tool no rompe estado

- [x] Task 4: Crear tests de conversaciones out of order (AC: #4)
  - [x] 4.1 Test `test_out_of_order_confirm_before_services()`: Usuario confirma sin servicios
  - [x] 4.2 Test `test_out_of_order_select_slot_before_stylist()`: Usuario da horario sin estilista
  - [x] 4.3 Test `test_out_of_order_provide_name_at_service_selection()`: Nombre dado demasiado pronto
  - [x] 4.4 Test `test_faq_during_booking_flow()`: Preguntar FAQ sin interrumpir flujo

- [ ] Task 5: Ejecutar manual testing via WhatsApp - 8 casos (AC: #5) **[REQUIRES USER]**
  - [ ] 5.1 Caso M1: Happy path simple (saludar → cita → servicio → estilista → horario → nombre → confirmar)
  - [ ] 5.2 Caso M2: Múltiples servicios (seleccionar 2+ servicios antes de confirmar)
  - [ ] 5.3 Caso M3: Cancelar mid-flow (iniciar booking → cancelar antes de confirmar)
  - [ ] 5.4 Caso M4: Out of order (intentar confirmar sin servicios seleccionados)
  - [ ] 5.5 Caso M5: Cambiar de opinión (seleccionar servicio → querer cambiarlo)
  - [ ] 5.6 Caso M6: FAQ durante booking (preguntar horarios durante flujo)
  - [ ] 5.7 Caso M7: Respuesta numérica (usar números para seleccionar opciones)
  - [ ] 5.8 Caso M8: Respuesta texto (usar texto para seleccionar opciones)
  - [ ] 5.9 Documentar resultados con screenshots/logs

- [x] Task 6: Verificar bugs de Epic 1 Story 1-5 resueltos (AC: #6)
  - [x] 6.1 Test `test_uuid_serialization_bug_resolved()`: ensure_customer_exists retorna strings
  - [x] 6.2 Test `test_state_flags_progression_bug_resolved()`: FSM progresa correctamente entre estados
  - [x] 6.3 Test `test_booking_execution_state_reachable()`: Estado CONFIRMATION/BOOKED es alcanzable
  - [x] 6.4 Verificar que book() se ejecuta con datos completos (no INVALID_UUID)

- [x] Task 7: Ejecutar suite completa y verificar coverage (AC: #7)
  - [x] 7.1 Ejecutar `pytest tests/unit/test_booking_fsm.py tests/unit/test_intent_extractor.py tests/unit/test_tool_validation.py`
  - [x] 7.2 Ejecutar `pytest tests/integration/test_fsm_llm_integration.py tests/integration/test_tools_fsm_validation.py tests/integration/test_booking_e2e.py`
  - [x] 7.3 Ejecutar coverage report: `pytest --cov=agent/fsm --cov-fail-under=85`
  - [x] 7.4 Documentar total de tests y coverage por módulo

- [x] Task 8: Documentar test cases y resultados (AC: #8)
  - [x] 8.1 Crear sección "Test Results" en este story file
  - [x] 8.2 Documentar resultados de tests automatizados
  - [ ] 8.3 Documentar resultados de manual testing con evidencia **[PENDING TASK 5]**
  - [x] 8.4 Crear resumen de bugs encontrados y resueltos

## Dev Notes

### Contexto Arquitectónico

Esta story es la **validación final** de la arquitectura FSM Híbrida implementada en stories 5-1 a 5-4. Es crítica para garantizar que:

1. La FSM funciona end-to-end como se diseñó
2. Los bugs de Epic 1 Story 1-5 están resueltos
3. El sistema está listo para migrar Epic 1 stories pendientes (5-6)

**Arquitectura FSM (ADR-006):**
```
LLM (NLU)      → Interpreta INTENCIÓN + Genera LENGUAJE
FSM Control    → Controla FLUJO + Valida PROGRESO + Decide TOOLS
Tool Calls     → Ejecuta ACCIONES validadas
```

[Source: docs/architecture.md#ADR-006]

### Test Strategy Summary (del Tech Spec)

| Nivel | Scope | Framework | Coverage Target |
|-------|-------|-----------|-----------------|
| Unit | BookingFSM, IntentExtractor, ToolValidation | pytest | 90% |
| Integration | LLM + FSM, Tools + FSM | pytest-asyncio | 85% |
| E2E | Flujo completo booking | pytest + mocks | 80% |
| Manual | WhatsApp real | Manual checklist | 8 casos |

[Source: docs/sprint-artifacts/tech-spec-epic-5.md#Test-Strategy-Summary]

### 8 Manual Test Cases (WhatsApp)

| Caso | Descripción | Pasos | Resultado Esperado |
|------|-------------|-------|-------------------|
| M1 | Happy path simple | Saludar → Pedir cita → Servicio → Estilista → Horario → Nombre → Confirmar | Booking creado, evento Calendar |
| M2 | Múltiples servicios | Pedir cita → 2 servicios → Confirmar servicios → ... | Ambos servicios en booking |
| M3 | Cancelar mid-flow | Iniciar booking → Cancelar antes de confirmar | FSM reset a IDLE |
| M4 | Out of order | Intentar confirmar sin seleccionar servicio | Redirección amigable |
| M5 | Cambiar de opinión | Seleccionar servicio → Querer cambiarlo | Permite cambio |
| M6 | FAQ durante booking | Preguntar horarios durante booking flow | Responde FAQ, mantiene estado |
| M7 | Respuesta numérica | Usar números para seleccionar opciones | Funciona correctamente |
| M8 | Respuesta texto | Usar texto para seleccionar opciones | Funciona correctamente |

[Source: docs/sprint-artifacts/tech-spec-epic-5.md#Manual-Test-Cases]

### Bugs de Epic 1 Story 1-5 a Verificar

**Bug #1: UUID Serialization**
- **Síntoma:** `ensure_customer_exists()` retornaba UUID objects en lugar de strings
- **Causa:** Falta de conversión `str(uuid)` en retorno
- **Verificación:** Test que book() recibe customer_id como string válido

**Bug #2: State Flags Never Updated**
- **Síntoma:** Flags `service_selected`, `slot_selected`, etc. nunca se seteaban
- **Causa:** Arquitectura LLM-driven sin estructura FSM
- **Verificación:** Test que FSM progresa de SERVICE_SELECTION → BOOKED

[Source: docs/epics/epic-5-rediseño-fsm-hibrida.md#Problema-Identificado]

### Project Structure Notes

**Archivos a crear:**
- `tests/integration/test_booking_e2e.py` - Tests end-to-end completos

**Archivos existentes a usar:**
- `tests/unit/test_booking_fsm.py` - 45+ tests de FSM (Story 5-2)
- `tests/unit/test_intent_extractor.py` - 30+ tests de intent extraction (Story 5-3)
- `tests/unit/test_tool_validation.py` - 34 tests de tool validation (Story 5-4)
- `tests/integration/test_fsm_llm_integration.py` - Integration tests LLM + FSM (Story 5-3)
- `tests/integration/test_tools_fsm_validation.py` - 21 tests tools + FSM (Story 5-4)

**Componentes FSM (de stories anteriores):**
- `agent/fsm/booking_fsm.py` - BookingFSM class con 7 estados
- `agent/fsm/intent_extractor.py` - extract_intent() function
- `agent/fsm/tool_validation.py` - validate_tool_call() function
- `agent/fsm/models.py` - Intent, IntentType, FSMResult, BookingState

### Testing Commands

```bash
# Unit tests
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/pytest tests/unit/test_booking_fsm.py tests/unit/test_intent_extractor.py tests/unit/test_tool_validation.py -v

# Integration tests
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/pytest tests/integration/test_fsm_llm_integration.py tests/integration/test_tools_fsm_validation.py -v

# E2E tests
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/pytest tests/integration/test_booking_e2e.py -v

# Coverage report
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/pytest --cov=agent/fsm --cov-report=term-missing --cov-fail-under=85
```

[Source: CLAUDE.md#Testing]

### Learnings from Previous Story

**From Story 5-4-refactorizacion-tools-fsm-validation (Status: done)**

- **Tool validation architecture established:**
  - `TOOL_STATE_PERMISSIONS` matrix defines which tools can run in which FSM states
  - `TOOL_DATA_REQUIREMENTS` validates required data before tool execution
  - `validate_tool_call()` integrated at execute_tool_call level - reuse in e2e tests
- **Files created to USE in e2e tests:**
  - `agent/fsm/tool_validation.py` - Core validation logic
  - `tests/unit/test_tool_validation.py` - 34 unit tests (patterns to follow)
  - `tests/integration/test_tools_fsm_validation.py` - 21 integration tests (patterns to follow)
- **Test patterns established:**
  - Use `BookingFSM("test-conv-id")` for isolated FSM instances
  - Mock external APIs (Google Calendar, Chatwoot) for deterministic tests
  - Assert on FSM state transitions, not just return values
  - Log tool execution with FSM context
- **Coverage baseline:** 93.68% for tool_validation.py - maintain similar level
- **Total tests before this story:** 139 tests (34 unit + 45 FSM + 21 integration + 39 existing)

[Source: docs/sprint-artifacts/5-4-refactorizacion-tools-fsm-validation.md#Dev-Agent-Record]

### Performance Considerations

E2E tests should be marked as `@pytest.mark.slow` to allow selective execution:
```python
@pytest.mark.slow
@pytest.mark.asyncio
async def test_complete_booking_flow():
    ...
```

### References

- [Source: docs/sprint-artifacts/tech-spec-epic-5.md#Test-Strategy-Summary] - Test strategy
- [Source: docs/sprint-artifacts/tech-spec-epic-5.md#Manual-Test-Cases] - Manual test cases
- [Source: docs/architecture/fsm-booking-flow.md] - FSM specification
- [Source: docs/architecture.md#ADR-006] - FSM Hybrid architecture decision
- [Source: docs/epics/epic-5-rediseño-fsm-hibrida.md#Story-5-5] - Story definition
- [Source: docs/sprint-artifacts/5-4-refactorizacion-tools-fsm-validation.md] - Previous story learnings
- [Source: CLAUDE.md#Testing] - Testing standards

## Test Results

### Automated Test Summary

**Total Tests: 170 tests passed**

| Test Suite | File | Tests | Status |
|------------|------|-------|--------|
| Unit - BookingFSM | `tests/unit/test_booking_fsm.py` | 45 | ✅ PASS |
| Unit - IntentExtractor | `tests/unit/test_intent_extractor.py` | 30 | ✅ PASS |
| Unit - ToolValidation | `tests/unit/test_tool_validation.py` | 34 | ✅ PASS |
| Integration - FSM+LLM | `tests/integration/test_fsm_llm_integration.py` | 9 | ✅ PASS |
| Integration - Tools+FSM | `tests/integration/test_tools_fsm_validation.py` | 21 | ✅ PASS |
| E2E - Booking Flow | `tests/integration/test_booking_e2e.py` | 31 | ✅ PASS |

### Coverage Report (agent/fsm/)

| Module | Coverage | Missing Lines |
|--------|----------|---------------|
| `agent/fsm/__init__.py` | 100.00% | - |
| `agent/fsm/booking_fsm.py` | 97.46% | 144, 358-359 |
| `agent/fsm/intent_extractor.py` | 88.37% | 43-45, 194-200, 256 |
| `agent/fsm/models.py` | 100.00% | - |
| `agent/fsm/tool_validation.py` | 93.68% | 351-354, 360-363, 381 |

**FSM Average Coverage: ~95.9%** (Target: 85%) ✅

### E2E Test Cases (tests/integration/test_booking_e2e.py)

#### Task 1: Happy Path Tests (AC #1)
- ✅ `test_complete_booking_single_service` - Full flow IDLE → BOOKED with 1 service
- ✅ `test_complete_booking_multiple_services` - 3 services with combined duration
- ✅ `test_booking_with_returning_customer` - Existing customer with customer_id
- ✅ `test_booking_with_new_customer` - New customer, minimal data (first_name only)

#### Task 2: Invalid Transition Tests (AC #2)
- ✅ `test_cannot_confirm_from_idle` - CONFIRM_BOOKING from IDLE rejected
- ✅ `test_cannot_select_slot_without_stylist` - Skipping steps rejected
- ✅ `test_cannot_book_without_customer_data` - Missing first_name rejected
- ✅ `test_redirect_messages_are_natural` - Error messages are descriptive
- ✅ `test_user_guided_to_correct_step` - next_action provides guidance

#### Task 3: Error Recovery Tests (AC #3)
- ✅ `test_google_calendar_api_failure_recovery` - FSM state preserved on API error
- ✅ `test_database_error_recovery` - FSM state preserved on DB error
- ✅ `test_llm_intent_extraction_failure_recovery` - UNKNOWN intent doesn't corrupt FSM
- ✅ `test_tool_execution_error_preserves_fsm_state` - Tool errors don't change FSM

#### Task 4: Out of Order Tests (AC #4)
- ✅ `test_out_of_order_confirm_before_services` - Premature confirm rejected
- ✅ `test_out_of_order_select_slot_before_stylist` - Wrong order rejected
- ✅ `test_out_of_order_provide_name_at_service_selection` - Early name not saved
- ✅ `test_faq_during_booking_flow` - FAQ doesn't interrupt flow
- ✅ `test_greeting_during_booking_flow` - Greeting doesn't break state

#### Task 6: Bug Verification Tests (AC #6)
- ✅ `test_uuid_serialization_bug_resolved` - IDs stored as strings
- ✅ `test_state_flags_progression_bug_resolved` - All 7 states visited in order
- ✅ `test_booking_execution_state_reachable` - CONFIRMATION/BOOKED reachable
- ✅ `test_book_executes_with_complete_data` - No INVALID_UUID, all data present

#### Additional Tests
- ✅ `test_cancel_from_any_state_resets_to_idle` - Cancel from 5 states (parametrized)
- ✅ `test_services_accumulate_incrementally` - Services added correctly
- ✅ `test_duplicate_services_not_added` - No duplicates
- ✅ `test_persist_and_load_roundtrip` - Redis persistence works
- ✅ `test_load_nonexistent_returns_idle` - New conversation starts in IDLE

### Manual Testing Checklist (Task 5 - AC #5)

**Status: PENDING USER EXECUTION**

The following 8 test cases require manual testing via WhatsApp:

| Caso | Descripción | Estado |
|------|-------------|--------|
| M1 | Happy path simple | ⏳ Pending |
| M2 | Múltiples servicios | ⏳ Pending |
| M3 | Cancelar mid-flow | ⏳ Pending |
| M4 | Out of order | ⏳ Pending |
| M5 | Cambiar de opinión | ⏳ Pending |
| M6 | FAQ durante booking | ⏳ Pending |
| M7 | Respuesta numérica | ⏳ Pending |
| M8 | Respuesta texto | ⏳ Pending |

**Instructions for Manual Testing:**
1. Ensure agent service is running: `docker-compose up -d agent`
2. Send WhatsApp message to salon number
3. Follow test case steps and document results
4. Screenshot or log evidence in this section

### Bugs Found and Resolved

| Bug | Description | Status | Fix Location |
|-----|-------------|--------|--------------|
| Epic 1 Story 1-5 Bug #1 | UUID serialization - `ensure_customer_exists()` returned UUID objects | ✅ Verified Fixed | FSM stores all IDs as strings |
| Epic 1 Story 1-5 Bug #2 | State flags never updated | ✅ Verified Fixed | FSM state transitions are deterministic |
| **Manual Testing Bug #1** | SELECT_SERVICE transition missing - services not accumulated | ✅ **HOTFIXED** | `agent/fsm/booking_fsm.py:59` |

### Bug Found During Manual Testing (2025-11-21)

**Bug #1: SELECT_SERVICE Intent Not in FSM Transitions**

**Discovered:** Durante manual testing caso M1 (Happy path)

**Síntoma:** El bot "olvidaba" los servicios seleccionados. Cuando el usuario seleccionaba servicios, el bot volvía a preguntar qué servicios deseaba.

**Evidencia en logs:**
```
FSM transition rejected: service_selection -> ? | intent=select_service |
errors=["Transition 'select_service' not allowed from state 'service_selection'"]
```

**Root Cause Analysis:**
El diccionario `TRANSITIONS` en `BookingFSM` no incluía `SELECT_SERVICE` como transición válida desde `SERVICE_SELECTION`. Solo tenía:
```python
BookingState.SERVICE_SELECTION: {
    IntentType.CONFIRM_SERVICES: BookingState.STYLIST_SELECTION,
}
```

Cuando el intent extractor retornaba `SELECT_SERVICE` (correcto), la FSM rechazaba la transición porque no estaba definida. Esto causaba que:
1. La transición fallara
2. Los datos (servicios) nunca se acumularan en `collected_data`
3. La lista de servicios permanecía vacía

**Hotfix Aplicado:**
```python
# agent/fsm/booking_fsm.py:57-61
BookingState.SERVICE_SELECTION: {
    IntentType.SELECT_SERVICE: BookingState.SERVICE_SELECTION,  # Self-loop to accumulate
    IntentType.CONFIRM_SERVICES: BookingState.STYLIST_SELECTION,
},
```

**Por qué es un self-loop:** `SELECT_SERVICE` es un intent de "acumulación de datos" - el usuario puede seleccionar múltiples servicios antes de confirmar. La FSM permanece en `SERVICE_SELECTION` pero acumula los servicios en `collected_data["services"]`.

**Tests Automatizados que NO detectaron este bug:**
Los tests unitarios de FSM pasaban porque testeaban transiciones individuales con datos pre-cargados, no el flujo real donde el intent extractor genera `SELECT_SERVICE`.

**Lección Aprendida:**
Los tests E2E con mocks no capturan todos los bugs de integración real. El manual testing via WhatsApp es crítico para validar el flujo end-to-end completo.

**Verificación Post-Fix:**
- ✅ Tests unitarios de FSM siguen pasando (45/45)
- ✅ Agent rebuildeado y deployado
- ⏳ Re-test manual M1 pendiente

## Dev Agent Record

### Context Reference

- docs/sprint-artifacts/5-5-testing-end-to-end-fsm.context.xml

### Agent Model Used

Claude Sonnet 4.5 (claude-sonnet-4-5-20250929)

### Debug Log References

- E2E test execution: `pytest tests/integration/test_booking_e2e.py -v`
- Coverage run: `pytest --cov=agent/fsm --cov-report=term-missing`

### Completion Notes List

- ✅ Created comprehensive E2E test suite with 31 tests covering all ACs
- ✅ All 170 FSM-related tests passing (unit + integration + e2e)
- ✅ Coverage for agent/fsm/ at 95.9% (exceeds 85% target)
- ✅ Bug verification tests confirm Epic 1 Story 1-5 issues resolved
- ⏳ Manual WhatsApp testing pending user execution

### File List

**New Files:**
- `tests/integration/test_booking_e2e.py` - 31 E2E tests for booking flow

**Modified Files:**
- `docs/sprint-artifacts/sprint-status.yaml` - Status: ready-for-dev → in-progress → review
- `docs/sprint-artifacts/5-5-testing-end-to-end-fsm.md` - Test results documented
- `agent/fsm/booking_fsm.py` - **HOTFIX:** Added SELECT_SERVICE self-loop transition (line 59)

### Change Log

- **2025-11-21:** Story drafted from backlog by create-story workflow
- **2025-11-21:** Story context generated, status changed to ready-for-dev
- **2025-11-21:** Task 1-4 completed: Created `test_booking_e2e.py` with 31 E2E tests
- **2025-11-21:** Task 6 completed: Bug verification tests passing
- **2025-11-21:** Task 7 completed: 170 tests passing, FSM coverage 95.9%
- **2025-11-21:** Task 8 completed: Test results documented in story file
- **2025-11-21:** Manual testing M1 revealed critical bug: SELECT_SERVICE not in FSM transitions
- **2025-11-21:** **HOTFIX** applied to `booking_fsm.py` - added SELECT_SERVICE self-loop
- **2025-11-21:** Agent rebuilt and redeployed with fix
- **2025-11-21:** Bug documented retroactively (should have followed BMAD process)
