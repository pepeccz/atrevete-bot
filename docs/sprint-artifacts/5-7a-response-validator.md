# Story 5.7a: Response Validator (Post-Validación de Coherencia)

Status: done

## Story

As a **sistema FSM híbrido**,
I want **validar que las respuestas del LLM sean coherentes con el estado actual de la FSM antes de enviarlas al usuario**,
so that **el usuario nunca vea información de estados futuros del booking flow, garantizando sincronización entre lo que el bot dice y el estado real del sistema**.

## Acceptance Criteria

1. **Given** el `ResponseValidator` recibe una respuesta del LLM y el estado actual de la FSM
   **When** evalúa la respuesta
   **Then** retorna un `CoherenceResult` indicando si es coherente, lista de violaciones, hint de corrección y nivel de confianza

2. **Given** la FSM está en estado `SERVICE_SELECTION`
   **When** el LLM genera una respuesta que menciona nombres de estilistas (Ana, María, Carlos, Pilar, Laura) o muestra horarios disponibles
   **Then** el validator detecta la incoherencia y marca `is_coherent = False` con violación específica

3. **Given** la FSM está en estado `STYLIST_SELECTION`
   **When** el LLM genera una respuesta que menciona horarios específicos (HH:MM) o días de la semana
   **Then** el validator detecta la incoherencia y marca `is_coherent = False` con violación específica

4. **Given** la FSM está en estado `SLOT_SELECTION`
   **When** el LLM genera una respuesta que intenta confirmar la cita o menciona datos del cliente sin haberlos recopilado
   **Then** el validator detecta la incoherencia y marca `is_coherent = False`

5. **Given** una respuesta detectada como incoherente (`is_coherent = False`)
   **When** se invoca `regenerate_with_correction()`
   **Then** el sistema regenera una respuesta coherente usando el `correction_hint` y sin superar 1 intento de regeneración

6. **Given** cualquier validación de respuesta
   **When** se ejecuta
   **Then** el tiempo de validación es menor a 100ms (sin I/O de red para patrones)

7. **Given** cualquier llamada al validator
   **When** se ejecuta
   **Then** los logs muestran: estado FSM, respuesta original (truncada), resultado de coherencia, violaciones si las hay

8. **Given** el `ResponseValidator` integrado en `conversational_agent.py`
   **When** se completa el flujo de generación de respuesta
   **Then** la respuesta final enviada al usuario siempre es coherente con el estado FSM

## Tasks / Subtasks

- [x] Task 1: Crear modelos de datos para validación (AC: #1)
  - [x] 1.1 Crear `CoherenceResult` dataclass en `agent/fsm/models.py`
  - [x] 1.2 Agregar campos: `is_coherent: bool`, `violations: list[str]`, `correction_hint: str | None`, `confidence: float`
  - [x] 1.3 Unit tests para CoherenceResult

- [x] Task 2: Implementar ResponseValidator core (AC: #1, #2, #3, #4, #6)
  - [x] 2.1 Crear `agent/fsm/response_validator.py`
  - [x] 2.2 Implementar `FORBIDDEN_PATTERNS` dict mapeando `BookingState` a lista de regex patterns
  - [x] 2.3 Implementar método `validate(response: str, fsm: BookingFSM) -> CoherenceResult`
  - [x] 2.4 Implementar `_check_patterns(response: str, patterns: list[str]) -> list[str]`
  - [x] 2.5 Implementar `_generate_correction_hint(violations: list[str], fsm_state: BookingState) -> str`
  - [x] 2.6 Optimizar para <100ms (compilar regex una sola vez, sin I/O)
  - [x] 2.7 Unit tests cubriendo todos los estados FSM y patrones

- [x] Task 3: Definir patrones prohibidos por estado (AC: #2, #3, #4)
  - [x] 3.1 SERVICE_SELECTION: Prohibir nombres de estilistas, horarios específicos
  - [x] 3.2 STYLIST_SELECTION: Prohibir horarios HH:MM, días de la semana en contexto de disponibilidad
  - [x] 3.3 SLOT_SELECTION: Prohibir confirmación prematura, solicitud de datos cliente
  - [x] 3.4 CUSTOMER_DATA: Prohibir confirmación de cita sin datos completos
  - [x] 3.5 Documentar patrones con ejemplos de violaciones

- [x] Task 4: Implementar regeneración de respuestas (AC: #5)
  - [x] 4.1 Crear función `regenerate_with_correction(messages, correction_hint, fsm) -> str`
  - [x] 4.2 Agregar correction_hint como SystemMessage adicional al LLM
  - [x] 4.3 Implementar límite de 1 regeneración (evitar loops infinitos)
  - [x] 4.4 Logging de regeneraciones con contexto completo
  - [x] 4.5 Unit tests para regeneración exitosa y fallida

- [x] Task 5: Integrar en conversational_agent.py (AC: #8)
  - [x] 5.1 Importar ResponseValidator en `agent/nodes/conversational_agent.py`
  - [x] 5.2 Llamar `validator.validate()` después de generar respuesta LLM
  - [x] 5.3 Si incoherente: llamar `regenerate_with_correction()` una vez
  - [x] 5.4 Si segunda respuesta incoherente: log WARNING y enviar respuesta genérica
  - [x] 5.5 Integration tests del flujo completo

- [x] Task 6: Implementar logging estructurado (AC: #7)
  - [x] 6.1 Agregar logs en `validate()` con contexto FSM
  - [x] 6.2 Log truncado de respuesta (max 200 chars) para debugging
  - [x] 6.3 Log de violaciones con detalles
  - [x] 6.4 Log de métricas: tiempo de validación, regeneraciones necesarias
  - [x] 6.5 Tests que verifican estructura de logs

- [x] Task 7: Testing comprehensivo (AC: #1-8)
  - [x] 7.1 Crear `tests/unit/test_response_validator.py`
  - [x] 7.2 Tests para cada estado FSM con respuestas coherentes e incoherentes
  - [x] 7.3 Tests de rendimiento (<100ms)
  - [x] 7.4 Crear `tests/integration/test_response_coherence.py`
  - [x] 7.5 Integration tests con conversational_agent real
  - [x] 7.6 Coverage >85% para código nuevo

## Dev Notes

### Contexto Arquitectónico

Esta story implementa **Fase 1 del Response Coherence Layer** según el Sprint Change Proposal del 2025-11-22. Es un componente crítico para cerrar la brecha arquitectónica donde la FSM valida intents del usuario pero NO valida las respuestas del LLM.

**Problema que resuelve:**
```
FSM state: SERVICE_SELECTION (servicios no confirmados)
LLM respuesta: "Aquí están las estilistas disponibles: 1. Ana, 2. María..."

→ Usuario selecciona estilista
→ FSM rechaza transición (servicios no confirmados)
→ Conversación queda colgada
```

**Arquitectura del Response Coherence Layer:**
```
Usuario: mensaje
    ↓
[Intent Extractor] → intent + entities
    ↓
[FSM Validation] → Valida INTENT
    ↓
[LLM genera respuesta]
    ↓
[Response Validator] → Valida coherencia con FSM state  ← ESTA STORY
    ↓
✅ Coherente → Usuario
❌ Incoherente → Regenerar con corrección → Usuario
```

[Source: docs/sprint-change-proposal-2025-11-22-response-coherence.md#Sección-3.2]

### Patrones Prohibidos por Estado

| Estado FSM | Patrones Prohibidos | Regex de Detección |
|------------|--------------------|--------------------|
| `SERVICE_SELECTION` | Nombres de estilistas, horarios | `(Ana\|María\|Carlos\|Pilar\|Laura)`, `disponible[s]?\s+(a las\|el\|mañana)` |
| `STYLIST_SELECTION` | Horarios específicos, días | `\d{1,2}:\d{2}`, `(lunes\|martes\|miércoles\|jueves\|viernes\|sábado)` |
| `SLOT_SELECTION` | Confirmación prematura, datos cliente | `(confirmar\|confirmada?\|reservada?)`, `(tu nombre\|tus datos)` |
| `CUSTOMER_DATA` | Confirmación sin datos | `cita (confirmada\|reservada)` (sin first_name en collected_data) |
| `CONFIRMATION` | - (cualquier respuesta válida) | - |

[Source: docs/sprint-change-proposal-2025-11-22-response-coherence.md#Sección-3.2]

### Estrategia de Corrección

```python
# Estructura de CoherenceResult
@dataclass
class CoherenceResult:
    is_coherent: bool
    violations: list[str]        # ["Menciona estilistas en SERVICE_SELECTION"]
    correction_hint: str | None  # "NO menciones estilistas. Solo pregunta sobre servicios."
    confidence: float            # 0.95

# Regeneración con hint
async def regenerate_with_correction(messages, hint, fsm):
    correction_message = SystemMessage(content=f"""
CORRECCIÓN REQUERIDA:
{hint}

Estado FSM actual: {fsm.state.value}
NO violes las restricciones del estado actual.
""")
    messages_with_correction = messages + [correction_message]
    return await llm.ainvoke(messages_with_correction)
```

[Source: docs/sprint-change-proposal-2025-11-22-response-coherence.md#Sección-3.2]

### Project Structure Notes

**Archivos a crear:**
- `agent/fsm/response_validator.py` - Validador de coherencia (~200 líneas)
- `tests/unit/test_response_validator.py` - Tests unitarios (~300 líneas)
- `tests/integration/test_response_coherence.py` - Tests de integración (~200 líneas)

**Archivos a modificar:**
- `agent/fsm/models.py` - Agregar `CoherenceResult` dataclass (+20 líneas)
- `agent/fsm/__init__.py` - Exportar `ResponseValidator`, `CoherenceResult` (+3 líneas)
- `agent/nodes/conversational_agent.py` - Integrar validación post-respuesta (+30 líneas)

**Dependencias existentes a reutilizar:**
- `agent/fsm/booking_fsm.py` - `BookingFSM`, `BookingState` (Story 5-2)
- `agent/fsm/tool_validation.py` - Patrón de validación centralizada (Story 5-4)
- `shared/logging.py` - Logging estructurado

[Source: docs/architecture.md#Project-Structure]

### Performance Considerations

| Métrica | Target | Estrategia |
|---------|--------|------------|
| Validación tiempo | <100ms | Regex precompilados, sin I/O |
| Regeneración tiempo | <3s | Single LLM call con prompt corto |
| Memoria patrones | ~10KB | Dict estático, no instanciar por request |
| Max regeneraciones | 1 | Evitar loops, fallback a respuesta genérica |

[Source: docs/sprint-change-proposal-2025-11-22-response-coherence.md#Sección-6]

### Testing Standards

```python
# Unit test pattern
@pytest.mark.asyncio
async def test_validator_detects_stylist_in_service_selection():
    fsm = BookingFSM("test-conv")
    fsm._state = BookingState.SERVICE_SELECTION

    validator = ResponseValidator()
    response = "Las estilistas disponibles son: 1. Ana, 2. María"

    result = await validator.validate(response, fsm)

    assert result.is_coherent is False
    assert "estilistas" in result.violations[0].lower()
    assert result.correction_hint is not None

# Integration test pattern
@pytest.mark.asyncio
async def test_agent_regenerates_incoherent_response():
    # Setup FSM en SERVICE_SELECTION
    # Mock LLM para retornar respuesta incoherente primero, coherente después
    # Verify regeneración ocurre y respuesta final es coherente
```

[Source: CLAUDE.md#Testing]

### Learnings from Previous Story

**From Story 5-4-refactorizacion-tools-fsm-validation (Status: done)**

- **Validación centralizada:** Story 5-4 estableció el patrón de validación centralizada en `tool_validation.py` con `TOOL_STATE_PERMISSIONS` - SEGUIR MISMO PATRÓN para `FORBIDDEN_PATTERNS`
- **Integración en conversational_agent:** La validación se integra DESPUÉS del flujo existente, no reemplaza - añadir validación post-respuesta de forma similar
- **Estructura de logging:** Usar `log_tool_execution()` como referencia para `log_validation_result()`
- **Tests existentes:** 55 tests (34 unit + 21 integration) para tool_validation - apuntar a cobertura similar
- **Coverage:** 93.68% alcanzado en 5-4, apuntar a >85% para response_validator
- **Archivos creados que reutilizar patterns:**
  - `agent/fsm/tool_validation.py` - Estructura de mapeo estado→reglas
  - `tests/unit/test_tool_validation.py` - Patrón de tests por estado

[Source: docs/sprint-artifacts/5-4-refactorizacion-tools-fsm-validation.md#Dev-Agent-Record]

### References

- [Source: docs/sprint-change-proposal-2025-11-22-response-coherence.md] - Propuesta completa del Response Coherence Layer
- [Source: docs/sprint-artifacts/tech-spec-epic-5.md] - Tech spec de Epic 5 FSM Híbrida
- [Source: docs/epics/epic-5-rediseño-fsm-hibrida.md] - Epic definition
- [Source: docs/architecture.md#ADR-006] - Arquitectura FSM híbrida
- [Source: docs/sprint-artifacts/5-4-refactorizacion-tools-fsm-validation.md#Dev-Agent-Record] - Learnings de story anterior
- [Source: CLAUDE.md#Testing] - Testing standards del proyecto

## Dev Agent Record

### Context Reference

- `docs/sprint-artifacts/5-7a-response-validator.context.xml`

### Agent Model Used

Claude Sonnet 4.5 (claude-sonnet-4-5-20250929)

### Debug Log References

- Validación de coherencia <100ms confirmado en tests de rendimiento
- 60 tests totales (44 unit + 16 integration) pasando

### Completion Notes List

1. **CoherenceResult dataclass** implementada en `agent/fsm/models.py` con campos: `is_coherent`, `violations`, `correction_hint`, `confidence`
2. **ResponseValidator** implementado con patrones regex precompilados para cada estado FSM
3. **FORBIDDEN_PATTERNS** cubre todos los estados: SERVICE_SELECTION, STYLIST_SELECTION, SLOT_SELECTION, CUSTOMER_DATA
4. **Regeneración** limitada a 1 intento con fallback a respuesta genérica
5. **Integración** en `conversational_agent.py` como STEP 6 (post-validación)
6. **Logging estructurado** con FSM context, violations, tiempo de validación
7. **Tests comprehensivos**: 44 unit tests + 16 integration tests pasando

### File List

**Archivos creados:**
- `agent/fsm/response_validator.py` (~500 líneas) - ResponseValidator class, FORBIDDEN_PATTERNS, regenerate_with_correction(), log_coherence_metrics()
- `tests/unit/test_response_validator.py` (~600 líneas) - 44 unit tests para CoherenceResult, patrones, validación, rendimiento, logging
- `tests/integration/test_response_coherence.py` (~400 líneas) - 16 integration tests para FSM integration, regeneración, ciclo completo

**Archivos modificados:**
- `agent/fsm/models.py` (+40 líneas) - CoherenceResult dataclass
- `agent/fsm/__init__.py` (+15 líneas) - Exports para ResponseValidator, CoherenceResult, regenerate_with_correction, FORBIDDEN_PATTERNS, log_coherence_metrics
- `agent/nodes/conversational_agent.py` (+80 líneas) - STEP 6: Response Coherence Validation con regeneración y fallback

## Change Log

- **2025-11-22:** Story drafted from backlog by create-story workflow
- **2025-11-22:** Story implementation completed by dev agent (Claude Sonnet 4.5)
