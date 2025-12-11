# Sprint Change Proposal: Response Coherence Layer para FSM Híbrida

**Fecha:** 2025-11-22
**Autor:** Claude Code + Pepe
**Trigger:** Bug arquitectónico crítico descubierto en Story 5-5 (Testing E2E)
**Tipo de cambio:** Extensión de Epic 5 (FSM Híbrida)
**Severidad:** Crítica (bloquea Epic 5 y cascada a Epics 1-4)
**Workflow:** BMad Method - Correct Course

---

## 1. Resumen Ejecutivo

### Problema Identificado

Durante el testing E2E de Story 5-5, se identificó una **brecha arquitectónica fundamental** en la FSM híbrida v4.0: la FSM valida correctamente los **intents del usuario**, pero **NO valida las respuestas del LLM**.

Esto permite que el LLM "salte" pasos del flujo de booking, generando desincronización entre el estado real de la FSM y lo que el usuario percibe en la conversación.

**Síntomas observados:**
1. Bot muestra lista de estilistas sin confirmar servicios
2. Usuario selecciona estilista → FSM rechaza la transición
3. Bot dice "Déjame buscar horarios..." pero no ejecuta ninguna herramienta
4. Conversación queda colgada

### Solución Propuesta

Implementar un **Response Coherence Layer** usando un enfoque híbrido en 2 fases:
- **Fase 1:** Post-validación de respuestas del LLM (safety net)
- **Fase 2:** FSM Directives ligeras para guiar al LLM (proactivo)

---

## 2. Análisis del Problema Arquitectónico

### 2.1 Gap en la Arquitectura Actual

```
┌─────────────────────────────────────────────────────────────────┐
│                ARQUITECTURA FSM HÍBRIDA v4.0 ACTUAL             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Usuario: "4" (selecciona estilista)                            │
│       ↓                                                         │
│  [Intent Extractor] → select_stylist (confidence 0.98)          │
│       ↓                                                         │
│  [FSM Validation] → ✅/❌ (valida INTENT del usuario)           │
│       ↓                                                         │
│  [LLM genera respuesta] ← FSM context en prompt (SUGERENCIA)    │
│       ↓                                                         │
│  Respuesta al usuario  ← ⚠️ LLM PUEDE IGNORAR estado FSM       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**El problema clave:** Los prompts le SUGIEREN al LLM qué hacer, pero no hay validación de que la RESPUESTA cumpla con el estado FSM.

### 2.2 Evidencia de Logs

```json
{
  "timestamp": "2025-11-22T12:02:12.008429+00:00",
  "level": "WARNING",
  "logger": "agent.fsm.booking_fsm",
  "message": "FSM transition rejected: service_selection -> ? | intent=select_stylist | errors=[\"Transition 'select_stylist' not allowed from state 'service_selection'\"]"
}
```

### 2.3 Puntos de Riesgo Adicionales

| Transición | Riesgo | Escenario Potencial |
|------------|--------|---------------------|
| SERVICE_SELECTION → STYLIST_SELECTION | **Alto** | LLM muestra estilistas sin confirmar servicios |
| STYLIST_SELECTION → SLOT_SELECTION | **Alto** | LLM muestra horarios Y pide datos en misma respuesta |
| SLOT_SELECTION → CUSTOMER_DATA | Medio | LLM avanza a confirmación sin esperar datos |
| CUSTOMER_DATA → CONFIRMATION | **Alto** | LLM ejecuta book() antes de confirmación explícita |

---

## 3. Solución Propuesta: Enfoque Híbrido en 2 Fases

### 3.1 Arquitectura Objetivo

```
┌──────────────────────────────────────────────────────────────────┐
│              ARQUITECTURA FSM HÍBRIDA v4.1 (PROPUESTA)           │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Usuario: mensaje                                                │
│       ↓                                                          │
│  [Intent Extractor] → intent + entities                          │
│       ↓                                                          │
│  [FSM Validation] → Valida INTENT                                │
│       ↓                                                          │
│  [FSM Directive] → {"must_show": [...], "forbidden": [...]}      │
│       ↓                                    (FASE 2)              │
│  [LLM + Directive] → Genera respuesta guiada                     │
│       ↓                                                          │
│  [Response Validator] → Valida coherencia con FSM state          │
│       ↓                        (FASE 1)                          │
│  ✅ Coherente → Usuario                                          │
│  ❌ Incoherente → Regenerar con corrección                       │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 Fase 1: Post-Validación (Story 5-7a) - 2-3 días

**Objetivo:** Detectar y corregir respuestas incoherentes antes de enviarlas al usuario.

**Componentes nuevos:**

```python
# agent/fsm/response_validator.py

@dataclass
class CoherenceResult:
    is_coherent: bool
    violations: list[str]
    correction_hint: str | None
    confidence: float

class ResponseValidator:
    """Valida coherencia entre respuesta LLM y estado FSM."""

    # Patrones prohibidos por estado
    FORBIDDEN_PATTERNS: dict[BookingState, list[str]] = {
        BookingState.SERVICE_SELECTION: [
            r"(Ana|María|Carlos|Pilar|Laura)",  # Nombres de estilistas
            r"disponible[s]?\s+(a las|el|mañana)",  # Horarios
        ],
        BookingState.STYLIST_SELECTION: [
            r"\d{1,2}:\d{2}",  # Horarios específicos
            r"(lunes|martes|miércoles|jueves|viernes)",  # Días
        ],
        # ... más estados
    }

    async def validate(
        self,
        response: str,
        fsm: BookingFSM
    ) -> CoherenceResult:
        """Valida que la respuesta sea coherente con el estado FSM."""
        pass
```

**Integración en conversational_agent.py:**

```python
# Después de línea 686 (response generada)
from agent.fsm.response_validator import ResponseValidator

validator = ResponseValidator()
coherence = await validator.validate(assistant_response, fsm)

if not coherence.is_coherent:
    logger.warning(
        f"Response incoherent with FSM state | violations={coherence.violations}"
    )
    # Regenerar con corrección
    assistant_response = await regenerate_with_correction(
        langchain_messages,
        coherence.correction_hint,
        fsm
    )
```

### 3.3 Fase 2: FSM Directives (Story 5-7b) - 2-3 días

**Objetivo:** Guiar proactivamente al LLM sobre qué debe/no debe mostrar.

**Componentes nuevos:**

```python
# agent/fsm/booking_fsm.py (extensión)

@dataclass
class ResponseGuidance:
    must_show: list[str]      # Elementos obligatorios
    must_ask: str | None      # Pregunta obligatoria
    forbidden: list[str]      # Elementos prohibidos
    context_hint: str         # Contexto para el LLM

class BookingFSM:
    # ... código existente ...

    def get_response_guidance(self) -> ResponseGuidance:
        """Genera directiva de respuesta basada en estado actual."""

        guidance_map = {
            BookingState.SERVICE_SELECTION: ResponseGuidance(
                must_show=["lista de servicios"] if not self.collected_data.get("services") else [],
                must_ask="¿Deseas agregar otro servicio?",
                forbidden=["estilistas", "horarios", "confirmación"],
                context_hint="Usuario está seleccionando servicios. NO mostrar estilistas aún."
            ),
            BookingState.STYLIST_SELECTION: ResponseGuidance(
                must_show=["lista de estilistas disponibles"],
                must_ask="¿Con quién te gustaría la cita?",
                forbidden=["horarios específicos", "datos del cliente"],
                context_hint="Usuario debe elegir estilista. NO mostrar horarios aún."
            ),
            # ... más estados
        }

        return guidance_map.get(self.state, ResponseGuidance(...))
```

**Inyección en prompt:**

```python
# En conversational_agent.py, después de cargar FSM
guidance = fsm.get_response_guidance()

guidance_prompt = f"""
DIRECTIVA FSM (OBLIGATORIO):
- Estado actual: {fsm.state.value}
- DEBES mostrar: {', '.join(guidance.must_show) or 'nada específico'}
- DEBES preguntar: {guidance.must_ask or 'nada específico'}
- PROHIBIDO mostrar: {', '.join(guidance.forbidden)}
- Contexto: {guidance.context_hint}

⚠️ CRÍTICO: Viola la directiva = respuesta será rechazada y regenerada.
"""

langchain_messages.append(SystemMessage(content=guidance_prompt))
```

---

## 4. Impacto en Sprint

### 4.1 Stories Afectadas

| Story | Estado Anterior | Estado Post-Fix | Acción |
|-------|-----------------|-----------------|--------|
| 5-5 Testing E2E | bloqueada | desbloqueada | Esperar 5-7 |
| 5-6 Migration Epic 1 | bloqueada | desbloqueada | Esperar 5-5 |
| **5-7a Response Validator** | **NUEVA** | in_progress | Fase 1 |
| **5-7b FSM Directives** | **NUEVA** | pending | Fase 2 |

### 4.2 Epic 5 - Scope Actualizado

```
Epic 5: FSM Híbrida (FOUNDATION) - SCOPE EXTENDIDO

COMPLETADAS:
✅ 5-1: Diseño FSM States
✅ 5-2: FSM Controller Base
✅ 5-3: LLM + FSM Integration
✅ 5-4: Refactorización Tools

NUEVAS (Response Coherence Layer):
🔴 5-7a: Response Validator (Fase 1) - 2-3 días
🔴 5-7b: FSM Directives (Fase 2) - 2-3 días

DESBLOQUEADAS DESPUÉS DE 5-7:
⏳ 5-5: Testing E2E
⏳ 5-6: Migración Epic 1
```

### 4.3 Timeline Impact

| Escenario | Duración Original | Duración Nueva | Delta |
|-----------|-------------------|----------------|-------|
| Epic 5 | 2-3 semanas | 3-4 semanas | +1 semana |
| Story 5-5 | 2 días | 2 días (sin cambio) | 0 |
| Story 5-6 | 2 días | 2 días (sin cambio) | 0 |

**Timeline total:** +4-6 días de desarrollo para Story 5-7 (a + b)

---

## 5. Propuestas de Cambio Detalladas

### 5.1 Cambios en Architecture Document

**Archivo:** `docs/architecture.md`

**Sección a agregar después de ADR-006:**

```markdown
### ADR-007: Response Coherence Layer (2025-11-22)

**Contexto:** ADR-006 establece FSM híbrida donde FSM valida intents del usuario.
Sin embargo, no especifica validación de respuestas del LLM, permitiendo que
el LLM genere respuestas incoherentes con el estado FSM.

**Decisión:** Implementar Response Coherence Layer con 2 componentes:
1. ResponseValidator: Post-validación de respuestas (safety net)
2. ResponseGuidance: Directivas proactivas para guiar al LLM

**Arquitectura:**
[Diagrama incluido arriba]

**Consecuencias:**
- Respuestas siempre coherentes con estado FSM
- Latencia adicional ~200ms en caso de regeneración
- Logs mejorados para debugging de coherencia
- Sistema más robusto y predecible
```

### 5.2 Cambios en Epic 5 Document

**Archivo:** `docs/epics/epic-5-rediseño-fsm-hibrida.md`

**Agregar Story 5-7:**

```markdown
### Story 5-7: Response Coherence Layer

**Como:** Sistema
**Quiero:** Garantizar que las respuestas del LLM sean coherentes con el estado FSM
**Para que:** El usuario nunca vea información de un estado futuro

**Subtareas:**

**5-7a: Response Validator (Fase 1)**
- [ ] Crear `agent/fsm/response_validator.py`
- [ ] Implementar `CoherenceResult` dataclass
- [ ] Implementar `ResponseValidator.validate()`
- [ ] Implementar `regenerate_with_correction()`
- [ ] Integrar en `conversational_agent.py`
- [ ] Unit tests para validator
- [ ] Integration tests

**5-7b: FSM Directives (Fase 2)**
- [ ] Crear `ResponseGuidance` dataclass
- [ ] Implementar `fsm.get_response_guidance()`
- [ ] Inyectar guidance en prompt del LLM
- [ ] Actualizar validator para usar guidance
- [ ] Tests de coherencia con guidance

**Acceptance Criteria:**
- [ ] LLM no puede mostrar opciones de estados futuros
- [ ] Sistema detecta respuestas incoherentes en <100ms
- [ ] Regeneración corrige incoherencias exitosamente
- [ ] Logs muestran coherencia verificada en cada respuesta
- [ ] Tests cubren todos los estados FSM
- [ ] Latencia promedio aumenta <200ms

**Duración Estimada:** 4-6 días total (2-3 días cada fase)
```

### 5.3 Nuevos Archivos a Crear

| Archivo | Propósito | Líneas Est. |
|---------|-----------|-------------|
| `agent/fsm/response_validator.py` | Validación de coherencia | ~200 |
| `agent/fsm/response_guidance.py` | Directivas de respuesta | ~150 |
| `tests/unit/test_response_validator.py` | Tests del validator | ~300 |
| `tests/unit/test_response_guidance.py` | Tests de guidance | ~200 |

### 5.4 Archivos a Modificar

| Archivo | Cambios | Líneas Delta |
|---------|---------|--------------|
| `agent/fsm/booking_fsm.py` | Agregar `get_response_guidance()` | +50 |
| `agent/fsm/models.py` | Agregar `ResponseGuidance`, `CoherenceResult` | +30 |
| `agent/fsm/__init__.py` | Exportar nuevos componentes | +5 |
| `agent/nodes/conversational_agent.py` | Integrar validator y guidance | +40 |

---

## 6. Riesgos y Mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| Validator genera falsos positivos | Media | Medio | Threshold de confianza ajustable, logging detallado |
| Latencia excesiva por regeneraciones | Baja | Medio | Cache de patrones, limit de 1 regeneración |
| Guidance demasiado restrictivo | Baja | Alto | Testing extensivo, feedback loop |
| LLM ignora guidance | Baja | Medio | Validator como safety net |

---

## 7. Criterios de Éxito

### Definition of Done para Story 5-7

- [ ] ResponseValidator implementado y testeado
- [ ] ResponseGuidance implementado y testeado
- [ ] Integración en conversational_agent funcional
- [ ] Tests unitarios con >90% coverage
- [ ] Tests de integración pasan
- [ ] Manual testing via WhatsApp confirma coherencia
- [ ] Logs muestran validación en cada respuesta
- [ ] Documentación actualizada (Architecture, Epic 5)
- [ ] No hay regresiones en flujos existentes

### Métricas de Éxito Post-Implementación

| Métrica | Target | Medición |
|---------|--------|----------|
| Tasa de coherencia | >99% | Logs de validator |
| Regeneraciones necesarias | <5% | Logs de validator |
| Latencia adicional | <200ms promedio | Métricas de respuesta |
| Bugs de desincronización | 0 | Testing E2E |

---

## 8. Plan de Implementación

### Semana 1: Fase 1 (Response Validator)

| Día | Tarea | Entregable |
|-----|-------|------------|
| 1 | Diseño detallado + models | `response_validator.py` scaffold |
| 2 | Implementar validator core | `validate()` funcional |
| 3 | Implementar regeneración | `regenerate_with_correction()` |
| 3-4 | Integración + tests | PR ready for review |

### Semana 2: Fase 2 (FSM Directives)

| Día | Tarea | Entregable |
|-----|-------|------------|
| 1 | Diseño guidance por estado | `ResponseGuidance` completo |
| 2 | Implementar `get_response_guidance()` | FSM extendido |
| 3 | Inyección en prompts | Integración completa |
| 3-4 | Tests + refinamiento | PR ready for review |

### Post-Implementación

- Story 5-5 (Testing E2E): 2 días
- Story 5-6 (Migración Epic 1): 2 días
- Epic 5 completada y Epics 1-4 desbloqueadas

---

## 9. Handoff Plan

### Scope Classification: **Moderate**

El cambio requiere:
- Desarrollo de nuevos componentes (dev team)
- Actualización de documentación técnica (dev team)
- NO requiere cambios en PRD o backlog de producto

### Handoff Recipients

| Rol | Responsabilidad |
|-----|-----------------|
| **Developer (Claude Code)** | Implementar Story 5-7a y 5-7b |
| **Pepe (QA/Owner)** | Validar implementación via WhatsApp testing |
| **Architecture Doc** | Actualizar con ADR-007 |

### Next Steps Inmediatos

1. ✅ Aprobar este Sprint Change Proposal
2. ⏳ Crear Story 5-7 en sprint tracking
3. ⏳ Comenzar implementación Fase 1 (Response Validator)
4. ⏳ Testing iterativo durante desarrollo
5. ⏳ Completar Fase 2 (FSM Directives)
6. ⏳ Retomar Story 5-5 (Testing E2E)

---

## 10. Aprobación

**Estado:** ✅ APROBADO

**Aprobado por:** Pepe
**Fecha de aprobación:** 2025-11-22

### Checklist Pre-Aprobación

- [x] Problema claramente identificado y documentado
- [x] Impacto en epics y artifacts analizado
- [x] Opciones evaluadas con pros/cons
- [x] Solución recomendada con justificación
- [x] Plan de implementación detallado
- [x] Riesgos identificados con mitigaciones
- [x] Criterios de éxito definidos
- [x] **Aprobación de Pepe**

---

**Documento generado:** 2025-11-22
**Workflow:** BMad Method - Correct Course
**Versión:** 1.0
