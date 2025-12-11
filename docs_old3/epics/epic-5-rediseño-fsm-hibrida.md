# Epic 5: Rediseño FSM Híbrida para Booking Flow

**Prioridad:** CRÍTICA (Foundation)
**Duración Estimada:** 2-3 semanas
**Dependencias:** Ninguna
**Bloquea:** Epic 1 (stories 1-6, 1-7), Epic 2, Epic 3

---

## Contexto y Motivación

### Problema Identificado

Durante la ejecución de **Epic 1** (Corrección del Flujo de Agendamiento), se descubrieron **2 bugs críticos** que revelan un problema arquitectónico fundamental:

**Bug #1: UUID Serialization** (Story 1-5)
- `ensure_customer_exists()` retornaba UUID objects en lugar de strings
- Causaba "INVALID_UUID" al llamar `book()` tool
- **Root Cause:** Falta de tipado estricto en funciones que retornan UUIDs

**Bug #2: State Flags Never Updated** (Story 1-5)
- Los flags `service_selected`, `slot_selected`, `customer_data_collected`, `booking_confirmed` nunca se seteaban
- El agente siempre detectaba estado como `SERVICE_SELECTION`, nunca progresaba a `BOOKING_EXECUTION`
- **Root Cause:** Arquitectura "LLM-driven" sin estructura FSM explícita

### Análisis Arquitectónico

La arquitectura actual (v3.2) tiene un **problema conceptual fundamental**:

```
┌─────────────────────────────────────────┐
│ Sistema Actual (v3.2)                   │
├─────────────────────────────────────────┤
│ LLM controla TODO:                      │
│ - Interpreta intención (NLU) ✓          │
│ - Genera lenguaje natural ✓             │
│ - Controla flujo de conversación ✗      │
│ - Valida progreso ✗                     │
│ - Decide cuándo llamar tools ✗          │
└─────────────────────────────────────────┘
         ↓
    PROBLEMAS:
    ❌ Frágil: LLM puede saltarse pasos
    ❌ No debuggeable: No sabemos el estado real
    ❌ No testeable: Dependemos de LLM reasoning
    ❌ Quick fixes acumulándose
```

**Solución:** Separar responsabilidades con **FSM Híbrida**

```
┌──────────────┐
│ LLM (NLU)    │ ← Interpreta INTENCIÓN + Genera LENGUAJE
└──────┬───────┘
       ↓
┌──────────────┐
│ FSM Control  │ ← Controla FLUJO + Valida PROGRESO
└──────┬───────┘
       ↓
┌──────────────┐
│ Tool Calls   │ ← Ejecuta ACCIONES validadas
└──────────────┘
```

### Impacto de NO Hacer Este Rediseño

- ❌ Acumularemos más quick fixes (parches sobre parches)
- ❌ Cada nueva epic (2, 3, 4) tendrá bugs similares
- ❌ Testing end-to-end seguirá siendo difícil
- ❌ Debugging de conversaciones seguirá siendo caótico
- ❌ Velocidad de desarrollo se degradará

### Beneficios del Rediseño

- ✅ **Robusto:** Validación explícita de cada transición
- ✅ **Debuggeable:** Estado actual siempre claro
- ✅ **Testeable:** Cada transición testeable independientemente
- ✅ **Mantenible:** Agregar nuevos estados/transiciones es claro
- ✅ **Confiable:** No depende de LLM reasoning para control de flujo
- ✅ **Natural:** LLM sigue generando mensajes personalizados y naturales

---

## Objetivos de la Epic

1. ✅ Implementar FSM Controller base con estados del booking flow
2. ✅ Integrar LLM + FSM manteniendo naturalidad conversacional
3. ✅ Refactorizar tools para trabajar con FSM validation
4. ✅ Migrar Epic 1 stories pendientes a nueva arquitectura
5. ✅ Resolver bugs críticos encontrados en Story 1-5

---

## User Stories

### Story 5-1: Diseño de FSM States y Transiciones

**Como:** Developer
**Quiero:** Diseñar los estados y transiciones del FSM para el booking flow
**Para que:** Tengamos una especificación clara de cómo debe comportarse el sistema

**Tareas:**
- [ ] Definir estados del booking flow (IDLE, SERVICE_SELECTION, STYLIST_SELECTION, etc.)
- [ ] Mapear transiciones válidas entre estados
- [ ] Documentar validaciones por estado
- [ ] Crear diagrama de estados en Excalidraw
- [ ] Especificar qué datos se recopilan en cada estado

**Acceptance Criteria:**
- Documento `docs/architecture/fsm-booking-flow.md` con especificación completa
- Diagrama visual de estados y transiciones
- Cada transición tiene condiciones de validación definidas
- Cada estado tiene datos requeridos documentados

**Duración Estimada:** 2 días

---

### Story 5-2: Implementación de FSM Controller Base

**Como:** Developer
**Quiero:** Implementar la clase BookingFSM que controla estados y transiciones
**Para que:** Tengamos un controlador robusto que valide el flujo

**Tareas:**
- [ ] Crear `agent/fsm/booking_fsm.py` con clase BookingFSM
- [ ] Implementar estados como Enum
- [ ] Implementar método `transition()` con validación
- [ ] Implementar persistencia de estado en Redis
- [ ] Implementar logging de transiciones
- [ ] Unit tests para todas las transiciones

**Acceptance Criteria:**
- FSM valida transiciones correctamente (rechaza inválidas)
- Estado persiste en Redis entre mensajes
- Logs muestran cada transición claramente
- Tests cubren todos los paths (happy + error)
- Código con mypy strict typing

**Duración Estimada:** 3 días

---

### Story 5-3: Integración LLM + FSM (Intent Extraction)

**Como:** Developer
**Quiero:** Integrar el LLM con FSM para extraer intención sin perder naturalidad
**Para que:** El sistema sea robusto pero siga conversando naturalmente

**Tareas:**
- [ ] Crear `agent/fsm/intent_extractor.py` con función `extract_intent()`
- [ ] LLM extrae intención estructurada del mensaje del usuario
- [ ] FSM valida si intención permite transición
- [ ] LLM genera respuestas naturales basándose en estado FSM
- [ ] Implementar manejo de intenciones "out of order"
- [ ] Integration tests LLM + FSM

**Acceptance Criteria:**
- LLM extrae intención correctamente (>90% accuracy en tests)
- FSM rechaza transiciones inválidas con redirección natural
- Mensajes del bot siguen siendo naturales y personalizados
- Usuario puede expresar intención en lenguaje natural (no comandos)
- Tests con conversaciones reales

**Duración Estimada:** 3 días

---

### Story 5-4: Refactorización de Tools con FSM Validation

**Como:** Developer
**Quiero:** Refactorizar las tools existentes para trabajar con FSM
**Para que:** Las tools solo se ejecuten cuando el estado es válido

**Tareas:**
- [ ] Modificar `execute_tool_call()` para validar estado FSM
- [ ] Cada tool retorna datos estructurados para FSM
- [ ] Tools actualizan estado FSM después de ejecución exitosa
- [ ] Implementar error handling robusto
- [ ] Refactorizar `book()` tool para trabajar con FSM
- [ ] Tests de integración tools + FSM

**Acceptance Criteria:**
- Tools solo se ejecutan si FSM lo permite
- `book()` solo se llama en estado CONFIRMATION con datos completos
- Errors en tools no rompen FSM (recovery automático)
- Logs muestran estado FSM en cada tool call
- Tests cubren casos de error

**Duración Estimada:** 3 días

---

### Story 5-5: Testing End-to-End con FSM

**Como:** QA/Developer
**Quiero:** Testear el flujo completo de booking con FSM
**Para que:** Tengamos confianza de que el sistema funciona correctamente

**Tareas:**
- [ ] Crear tests end-to-end de flujo completo (happy path)
- [ ] Tests de validación de transiciones inválidas
- [ ] Tests de recovery de errores
- [ ] Tests de conversaciones "out of order"
- [ ] Manual testing via WhatsApp (8 casos de uso)
- [ ] Documentar test cases y resultados

**Acceptance Criteria:**
- 100% de tests pasan
- Flujo completo de booking funciona sin errores
- Transiciones inválidas se manejan gracefully
- Manual testing confirma naturalidad conversacional
- Bugs de Epic 1 Story 1-5 están resueltos

**Duración Estimada:** 2 días

---

### Story 5-6: Migración de Epic 1 Stories a Nueva Arquitectura

**Como:** Developer
**Quiero:** Migrar las stories pendientes de Epic 1 a la nueva arquitectura FSM
**Para que:** Podamos completar Epic 1 con el sistema robusto

**Tareas:**
- [ ] Retomar Story 1-5 con FSM (presentación de estilistas y disponibilidad)
- [ ] Adaptar Story 1-6 a FSM (recopilación de datos del cliente)
- [ ] Adaptar Story 1-7 a FSM (actualización de prompts)
- [ ] Validar que bugs críticos están resueltos
- [ ] Actualizar documentación

**Acceptance Criteria:**
- Story 1-5 completa sin bugs
- Stories 1-6, 1-7 funcionan con FSM
- Epic 1 puede marcarse como "done"
- Documentación actualizada

**Duración Estimada:** 2 días

---

## Criterios de Aceptación de la Epic

La Epic 5 estará completa cuando:

1. ✅ FSM Controller implementado y funcionando
2. ✅ LLM + FSM integrados manteniendo naturalidad
3. ✅ Tools refactorizadas para trabajar con FSM
4. ✅ Todos los tests (unit + integration + e2e) pasan
5. ✅ Bugs de Story 1-5 resueltos
6. ✅ Epic 1 completable con nueva arquitectura
7. ✅ Documentación técnica completa

---

## Definición de Done (DoD)

- [ ] Código implementado y mergeado a `master`
- [ ] Tests (unit, integration, e2e) escritos y pasando (>85% coverage)
- [ ] Manual testing via WhatsApp exitoso (8 casos de uso)
- [ ] Documentación técnica actualizada (`docs/architecture/`)
- [ ] Código revisado y aprobado (code review)
- [ ] No hay bugs críticos conocidos
- [ ] Logs demuestran FSM funcionando correctamente

---

## Riesgos y Mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|-------------|---------|------------|
| LLM no extrae intención correctamente | Media | Alto | Agregar ejemplos en prompt, validación adicional |
| FSM demasiado rígida, pierde naturalidad | Baja | Alto | Testing extensivo con usuarios reales |
| Migración de Epic 1 toma más tiempo | Media | Medio | Priorizar solo stories críticas (1-6, 1-7) |
| Bugs en tools refactorizadas | Media | Alto | Tests exhaustivos, rollback plan |

---

## Notas Técnicas

### Arquitectura FSM Propuesta

```python
# agent/fsm/booking_fsm.py
from enum import Enum
from typing import Optional, Dict, Any

class BookingState(Enum):
    IDLE = "idle"
    SERVICE_SELECTION = "service_selection"
    STYLIST_SELECTION = "stylist_selection"
    SLOT_SELECTION = "slot_selection"
    CUSTOMER_DATA = "customer_data"
    CONFIRMATION = "confirmation"
    BOOKED = "booked"

class FSMTransition:
    def __init__(self, from_state: BookingState, to_state: BookingState,
                 condition: callable, required_data: list[str]):
        self.from_state = from_state
        self.to_state = to_state
        self.condition = condition
        self.required_data = required_data

class BookingFSM:
    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.state = BookingState.IDLE
        self.collected_data: Dict[str, Any] = {}
        self.transitions = self._define_transitions()

    def can_transition(self, intent: dict) -> bool:
        """Validate if transition is allowed based on current state and intent."""
        pass

    def transition(self, intent: dict) -> FSMResult:
        """Execute transition if valid, return result with next prompt."""
        pass

    async def persist(self):
        """Persist state to Redis."""
        pass

    @classmethod
    async def load(cls, conversation_id: str) -> "BookingFSM":
        """Load state from Redis."""
        pass
```

### Integración con LangGraph

La FSM se integra en `conversational_agent.py`:

```python
async def conversational_agent(state: ConversationState) -> dict[str, Any]:
    # 1. Load FSM state
    fsm = await BookingFSM.load(state["conversation_id"])

    # 2. LLM extracts intent from user message
    intent = await extract_intent(user_message, fsm.state, fsm.collected_data)

    # 3. FSM validates transition
    if not fsm.can_transition(intent):
        # Generate natural redirect message
        response = await llm_generate_redirect(fsm.state, intent)
        return add_message(state, "assistant", response)

    # 4. FSM allows transition - execute tool if needed
    if intent.requires_tool:
        tool_result = await execute_tool_with_fsm_validation(intent.tool, fsm)

    # 5. FSM transitions to new state
    fsm_result = fsm.transition(intent)
    await fsm.persist()

    # 6. LLM generates natural response
    response = await llm_generate_response(fsm.state, fsm_result, tool_result)
    return add_message(state, "assistant", response)
```

---

## Retrospectiva de Epic 1 (Learnings)

**¿Qué funcionó bien?**
- Stories 1-1 a 1-4 completadas exitosamente
- Testing manual via WhatsApp descubrió bugs críticos
- Documentación de bugs fue clara

**¿Qué NO funcionó bien?**
- Arquitectura v3.2 mostró ser frágil
- State detection basada en flags no funciona
- Quick fixes ocultaban problema arquitectónico
- Debugging de conversaciones muy difícil

**¿Qué aprendimos?**
- LLM no debe controlar flujo, solo interpretar intención
- Necesitamos estructura FSM explícita
- State flags deben reflejar confirmación del usuario, no tool calls
- Testing end-to-end debe ser más temprano en el proceso

**¿Qué haremos diferente en Epic 5?**
- Diseño upfront de FSM antes de implementar
- Tests de integración desde el principio
- Separación clara de responsabilidades (LLM vs FSM)
- Validación robusta en cada paso
