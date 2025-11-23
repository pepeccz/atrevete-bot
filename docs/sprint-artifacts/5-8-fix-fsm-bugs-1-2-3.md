# Story 5.8: Fix FSM Bugs 1, 2 y 3 (Manual Testing 2025-11-23)

Status: done

## Story

As a **sistema FSM híbrido**,
I want **corregir los bugs críticos detectados en el testing manual del 2025-11-23**,
so that **el flujo de booking funcione correctamente sin resets inesperados, reconociendo todas las variaciones naturales del español**.

## Bug Summary

| # | Bug | Severidad | Causa Raíz |
|---|-----|-----------|------------|
| 1 | "Continua" no detectado como CONFIRM_SERVICES | ALTA | Intent synonyms no mapeados |
| 2 | "Si" causa reset completo | CRÍTICA | BOOKED estado terminal sin salida |
| 3 | Guidance/Validator desalineados | MEDIA | Forbidden patterns inconsistentes |

## Root Cause Analysis

Los 3 bugs comparten una **raíz común arquitectónica**:

> **El FSM valida INTENTS del usuario pero no garantiza coherencia de RESPUESTAS del LLM**

```
Usuario → [Intent Extractor] → FSM Valida ✅ → LLM Genera → Sin Constraints ❌ → Usuario
```

### Bug #1: Intent Synonyms

**Problema**: El LLM extraía intents como `"continua"` o `"sigamos"` que no están en el enum `IntentType`, causando fallback a `UNKNOWN`.

**Solución**: Añadir `INTENT_SYNONYMS` dict que normaliza variaciones españolas antes de crear el `Intent` object.

### Bug #2: BOOKED Terminal State

**Problema**: El estado `BOOKED` estaba definido con transiciones vacías (`{}`), pero el comentario decía "auto-resets to IDLE" sin código que lo hiciera.

**Solución**: Implementar auto-reset real: después de transición exitosa a BOOKED, el FSM resetea a IDLE inmediatamente.

### Bug #3: Guidance/Validator Alignment

**Problema**: `ResponseGuidance.forbidden` y `FORBIDDEN_PATTERNS` en el validator no estaban completamente alineados.

**Solución**: Fortalecer la lista de forbidden items en `_GUIDANCE_MAP` y en el guidance dinámico de `SERVICE_SELECTION`.

## Acceptance Criteria

1. **Given** usuario dice "Continua", "Sigamos", "Ya está", "Listo" en estado SERVICE_SELECTION
   **When** el intent extractor procesa el mensaje
   **Then** el intent es normalizado a `CONFIRM_SERVICES` correctamente

2. **Given** booking completado exitosamente (transición a BOOKED)
   **When** la transición se ejecuta
   **Then** el FSM auto-resetea a IDLE con collected_data vacío

3. **Given** FSM en estado SERVICE_SELECTION con servicios seleccionados
   **When** se genera ResponseGuidance
   **Then** la lista forbidden incluye nombres de estilistas específicos (Ana, María, Carlos, Pilar, Laura)

4. **Given** cualquier sinónimo mapeado en INTENT_SYNONYMS
   **When** el LLM retorna ese sinónimo como intent_type
   **Then** es normalizado al IntentType canónico antes de crear el Intent

5. **Given** nueva conversación después de booking completado
   **When** usuario envía nuevo mensaje
   **Then** FSM está en IDLE y permite START_BOOKING

## Tasks / Subtasks

- [x] Task 1: Implementar INTENT_SYNONYMS normalizer (Bug #1)
  - [x] 1.1 Crear `INTENT_SYNONYMS` dict en `agent/fsm/intent_extractor.py`
  - [x] 1.2 Añadir variaciones para `confirm_services`: continua, continúa, sigamos, ya está, solo eso, listo
  - [x] 1.3 Añadir variaciones para `confirm_booking`: confirmo, perfecto, vale, ok, dale
  - [x] 1.4 Modificar `_parse_llm_response()` para normalizar antes de crear Intent
  - [x] 1.5 Actualizar disambiguation hints en `_build_state_context()` con todas las variaciones

- [x] Task 2: Implementar BOOKED auto-reset (Bug #2)
  - [x] 2.1 Modificar `transition()` en `agent/fsm/booking_fsm.py`
  - [x] 2.2 Después de `to_state == BookingState.BOOKED`, resetear a IDLE
  - [x] 2.3 Limpiar collected_data en el auto-reset
  - [x] 2.4 Añadir logging del auto-reset

- [x] Task 3: Alinear Guidance con Validator (Bug #3)
  - [x] 3.1 Actualizar `_GUIDANCE_MAP[SERVICE_SELECTION].forbidden` con nombres de estilistas
  - [x] 3.2 Actualizar guidance dinámico en `get_response_guidance()` cuando hay servicios seleccionados
  - [x] 3.3 Añadir horarios y disponibilidad a forbidden list

- [x] Task 4: Actualizar tests
  - [x] 4.1 Añadir `TestBookedAutoReset` class en `test_booking_fsm.py`
  - [x] 4.2 Añadir `TestIntentSynonymsNormalizer` class en `test_intent_extractor.py`
  - [x] 4.3 Actualizar `test_transition_happy_path_complete` para verificar auto-reset
  - [x] 4.4 Ejecutar tests y verificar que pasan

## Technical Implementation

### Files Modified

| File | Change |
|------|--------|
| `agent/fsm/booking_fsm.py` | Auto-reset BOOKED→IDLE (línea ~227-238), Guidance alignment (línea ~432-457, ~500-510) |
| `agent/fsm/intent_extractor.py` | INTENT_SYNONYMS dict (línea ~35-78), normalization (línea ~318-324), hints (línea ~187-218) |
| `tests/unit/test_booking_fsm.py` | TestBookedAutoReset class (4 tests) |
| `tests/unit/test_intent_extractor.py` | TestIntentSynonymsNormalizer class (9 tests) |

### INTENT_SYNONYMS Dictionary

```python
INTENT_SYNONYMS: dict[str, str] = {
    # confirm_services variations
    "continua": "confirm_services",
    "continúa": "confirm_services",
    "sigamos": "confirm_services",
    "ya está": "confirm_services",
    "solo eso": "confirm_services",
    "listo": "confirm_services",
    # confirm_booking variations
    "confirmo": "confirm_booking",
    "perfecto": "confirm_booking",
    "vale": "confirm_booking",
    "ok": "confirm_booking",
    "dale": "confirm_booking",
    # ... más variaciones
}
```

### BOOKED Auto-Reset Logic

```python
# In transition(), after state update:
if to_state == BookingState.BOOKED:
    logger.info("FSM auto-reset: BOOKED -> IDLE")
    self._state = BookingState.IDLE
    self._collected_data = {}
```

## Test Results

```
88 tests passed (49 booking_fsm + 39 intent_extractor)
- TestBookedAutoReset: 4/4 passed
- TestIntentSynonymsNormalizer: 9/9 passed
```

## Related Documents

- `docs/to-fix/bugs-epic5-manual-testing-2025-11-23.md` - Bug report original
- `docs/sprint-artifacts/5-7a-response-validator.md` - ResponseValidator implementation
- `docs/sprint-artifacts/5-7b-fsm-directives.md` - FSM Directives implementation
