# Epic Technical Specification: Rediseño FSM Híbrida para Booking Flow

Date: 2025-11-21
Author: Pepe
Epic ID: 5
Status: Draft

---

## Overview

Este Epic implementa una **FSM Híbrida (Finite State Machine)** para controlar el flujo de booking en Atrévete Bot. La arquitectura actual v3.2 es "LLM-driven", donde el LLM controla tanto la interpretación de intención como el flujo de conversación, lo cual ha producido bugs críticos durante Epic 1 Story 1-5:

1. **Bug de State Flags:** Los flags `service_selected`, `slot_selected`, `customer_data_collected` nunca se actualizaban, causando que el agente siempre detectara estado `SERVICE_SELECTION` y nunca progresara a `BOOKING_EXECUTION`.

2. **Bug de UUID Serialization:** `ensure_customer_exists()` retornaba objetos UUID en lugar de strings, causando errores "INVALID_UUID" al llamar `book()`.

La solución separa responsabilidades: **LLM solo maneja NLU (Natural Language Understanding) y generación de lenguaje**, mientras **FSM controla flujo de conversación, valida progreso y decide cuándo ejecutar tools**. Esto produce un sistema robusto, debuggeable y testeable sin perder la naturalidad conversacional.

## Objectives and Scope

### Objetivos

1. Implementar FSM Controller base con 7 estados del booking flow
2. Integrar LLM + FSM manteniendo naturalidad conversacional
3. Refactorizar tools para trabajar con validación FSM
4. Migrar Epic 1 stories pendientes (1-5, 1-6, 1-7) a nueva arquitectura
5. Resolver bugs críticos encontrados en Story 1-5

### En Alcance (In Scope)

- Diseño y documentación de estados y transiciones FSM
- Implementación de `BookingFSM` class con persistencia Redis
- `IntentExtractor` para extraer intención estructurada del mensaje del usuario
- Refactoring de `conversational_agent.py` para integrar FSM
- Refactoring de tools (`book`, `search_services`, `find_next_available`, etc.) para FSM validation
- Tests unitarios, de integración y end-to-end
- Migración de stories 1-5, 1-6, 1-7 de Epic 1

### Fuera de Alcance (Out of Scope)

- Cambios en modelo de datos PostgreSQL (no se requieren nuevas columnas)
- Nuevos workers o servicios Docker
- Modificaciones a la API FastAPI
- Cambios en integración con Chatwoot o Google Calendar
- Epic 2, 3, 4 features (bloqueados hasta completar Epic 5 + Epic 1)

## System Architecture Alignment

### Componentes Afectados

| Componente | Cambio | Archivos |
|------------|--------|----------|
| FSM Controller | **NUEVO** | `agent/fsm/booking_fsm.py` |
| Intent Extractor | **NUEVO** | `agent/fsm/intent_extractor.py` |
| Conversational Agent | MODIFICAR | `agent/nodes/conversational_agent.py` |
| State Schema | MODIFICAR | `agent/state/schemas.py` |
| Tools | MODIFICAR | `agent/tools/*.py` |
| Prompts | MODIFICAR | `agent/prompts/*.md` |

### Restricciones Arquitectónicas

1. **Redis:** FSM state se persiste en Redis con TTL igual al checkpoint (15 min)
2. **LangGraph:** FSM se integra como paso previo en el nodo `conversational_agent`
3. **OpenRouter:** Sin cambios en integración LLM, solo cambia prompt structure
4. **Backwards Compatibility:** Conversaciones existentes continúan funcionando (FSM defaults to IDLE)

### ADR-006 Reference

Este Epic implementa la decisión arquitectónica **ADR-006: FSM Híbrida para Control de Flujo** documentada en `docs/architecture.md`. La arquitectura separa:

```
┌──────────────┐
│ LLM (NLU)    │ ← Interpreta INTENCIÓN + Genera LENGUAJE
└──────┬───────┘
       ↓
┌──────────────┐
│ FSM Control  │ ← Controla FLUJO + Valida PROGRESO + Decide TOOLS
└──────┬───────┘
       ↓
┌──────────────┐
│ Tool Calls   │ ← Ejecuta ACCIONES validadas
└──────────────┘
```

## Detailed Design

### Services and Modules

| Módulo | Responsabilidad | Inputs | Outputs |
|--------|-----------------|--------|---------|
| `agent/fsm/booking_fsm.py` | Controlador FSM con estados, transiciones y persistencia | `conversation_id`, `intent` | `FSMResult` con estado, datos, siguiente acción |
| `agent/fsm/intent_extractor.py` | Extracción de intención estructurada via LLM | `message`, `fsm_state`, `collected_data` | `Intent` con tipo, entidades, confianza |
| `agent/fsm/__init__.py` | Exports públicos del módulo FSM | - | `BookingFSM`, `BookingState`, `extract_intent` |
| `agent/nodes/conversational_agent.py` | Orquestación LLM + FSM + Tools | `ConversationState` | `dict` con mensaje respuesta |
| `agent/state/schemas.py` | Schema de estado con campos FSM | - | `ConversationState` TypedDict |

### Data Models and Contracts

#### BookingState Enum

```python
class BookingState(str, Enum):
    """Estados del flujo de booking."""
    IDLE = "idle"                         # Sin booking activo
    SERVICE_SELECTION = "service_selection"  # Seleccionando servicios
    STYLIST_SELECTION = "stylist_selection"  # Seleccionando estilista
    SLOT_SELECTION = "slot_selection"        # Seleccionando horario
    CUSTOMER_DATA = "customer_data"          # Recopilando datos cliente
    CONFIRMATION = "confirmation"            # Confirmando booking
    BOOKED = "booked"                        # Booking completado
```

#### Intent Model

```python
@dataclass
class Intent:
    """Intención extraída del mensaje del usuario."""
    type: IntentType           # start_booking, select_service, select_stylist, etc.
    entities: dict[str, Any]   # service_name, stylist_id, slot_time, etc.
    confidence: float          # 0.0 - 1.0
    raw_message: str           # Mensaje original
    requires_tool: bool        # Si necesita ejecutar tool
    tool_name: str | None      # Nombre del tool si aplica
```

#### IntentType Enum

```python
class IntentType(str, Enum):
    """Tipos de intención reconocidos."""
    # Booking flow
    START_BOOKING = "start_booking"
    SELECT_SERVICE = "select_service"
    CONFIRM_SERVICES = "confirm_services"
    SELECT_STYLIST = "select_stylist"
    SELECT_SLOT = "select_slot"
    PROVIDE_CUSTOMER_DATA = "provide_customer_data"
    CONFIRM_BOOKING = "confirm_booking"
    CANCEL_BOOKING = "cancel_booking"

    # General
    GREETING = "greeting"
    FAQ = "faq"
    CHECK_AVAILABILITY = "check_availability"
    ESCALATE = "escalate"
    UNKNOWN = "unknown"
```

#### FSMResult Model

```python
@dataclass
class FSMResult:
    """Resultado de una transición FSM."""
    success: bool
    new_state: BookingState
    collected_data: dict[str, Any]
    next_action: str              # "ask_services", "ask_stylist", "execute_book", etc.
    validation_errors: list[str]  # Errores si transición falló
```

#### FSM Redis Schema

```python
# Key: fsm:{conversation_id}
# TTL: 900 seconds (15 min, igual que checkpoints)
{
    "state": "service_selection",
    "collected_data": {
        "services": ["Corte largo", "Tinte"],
        "stylist_id": null,
        "slot": null,
        "customer_data": null
    },
    "last_updated": "2025-11-21T10:30:00+01:00"
}
```

### APIs and Interfaces

#### BookingFSM Class Interface

```python
class BookingFSM:
    """Controlador FSM para flujo de booking."""

    def __init__(self, conversation_id: str) -> None:
        """Inicializa FSM en estado IDLE."""

    @property
    def state(self) -> BookingState:
        """Estado actual de la FSM."""

    @property
    def collected_data(self) -> dict[str, Any]:
        """Datos recopilados hasta el momento."""

    def can_transition(self, intent: Intent) -> bool:
        """Valida si la transición es permitida desde el estado actual."""

    def transition(self, intent: Intent) -> FSMResult:
        """Ejecuta transición si es válida, retorna resultado."""

    def reset(self) -> None:
        """Resetea FSM a estado IDLE (cancela booking en progreso)."""

    async def persist(self) -> None:
        """Persiste estado en Redis."""

    @classmethod
    async def load(cls, conversation_id: str) -> "BookingFSM":
        """Carga estado desde Redis o crea nuevo en IDLE."""
```

#### Intent Extractor Interface

```python
async def extract_intent(
    message: str,
    current_state: BookingState,
    collected_data: dict[str, Any],
    conversation_history: list[dict]
) -> Intent:
    """
    Extrae intención estructurada del mensaje usando LLM.

    El LLM recibe contexto del estado actual para interpretar
    mensajes ambiguos correctamente (e.g., "1" en SERVICE_SELECTION
    vs "1" en SLOT_SELECTION).
    """
```

#### Tool Validation Decorator

```python
def requires_fsm_state(*allowed_states: BookingState):
    """
    Decorator que valida estado FSM antes de ejecutar tool.

    Usage:
        @requires_fsm_state(BookingState.CONFIRMATION)
        async def book(...) -> dict:
            ...
    """
```

### Workflows and Sequencing

#### Flujo Principal: Mensaje → Respuesta

```
Usuario envía mensaje
        │
        ▼
┌─────────────────────────────┐
│ 1. Load FSM State           │
│    BookingFSM.load(conv_id) │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│ 2. Extract Intent           │
│    extract_intent(msg, fsm) │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│ 3. Validate Transition      │
│    fsm.can_transition(int)  │
└─────────────┬───────────────┘
              │
        ┌─────┴─────┐
        │           │
        ▼           ▼
   [VÁLIDA]    [INVÁLIDA]
        │           │
        ▼           ▼
┌───────────┐ ┌─────────────────┐
│ 4a. Exec  │ │ 4b. LLM genera  │
│ Transition│ │ redirect msg    │
│ + Tool    │ │ (naturalidad)   │
└─────┬─────┘ └────────┬────────┘
      │                │
      ▼                │
┌───────────┐          │
│ 5. Persist│          │
│ FSM State │          │
└─────┬─────┘          │
      │                │
      ▼                ▼
┌─────────────────────────────┐
│ 6. LLM genera respuesta     │
│    natural basada en estado │
└─────────────┬───────────────┘
              │
              ▼
        Respuesta al usuario
```

#### Transiciones de Estado Válidas

```
IDLE ──────────────────────► SERVICE_SELECTION
     (intent: start_booking)

SERVICE_SELECTION ─────────► STYLIST_SELECTION
     (intent: confirm_services, services[] not empty)

STYLIST_SELECTION ─────────► SLOT_SELECTION
     (intent: select_stylist, stylist_id set)

SLOT_SELECTION ────────────► CUSTOMER_DATA
     (intent: select_slot, slot set)

CUSTOMER_DATA ─────────────► CONFIRMATION
     (intent: provide_customer_data, first_name set)

CONFIRMATION ──────────────► BOOKED
     (intent: confirm_booking, all data valid)

ANY STATE ─────────────────► IDLE
     (intent: cancel_booking)
```

#### Ejemplo: Happy Path Booking

| Paso | Estado FSM | Mensaje Usuario | Intent | Tool | Respuesta Bot |
|------|------------|-----------------|--------|------|---------------|
| 1 | IDLE | "Quiero pedir cita" | start_booking | search_services | "¡Hola! Te muestro los servicios..." |
| 2 | SERVICE_SELECTION | "Corte largo" | select_service | - | "Agregado. ¿Algo más?" |
| 3 | SERVICE_SELECTION | "No, eso es todo" | confirm_services | - | "Estilistas disponibles: 1. Ana..." |
| 4 | STYLIST_SELECTION | "Ana" | select_stylist | find_next_available | "Horarios de Ana: 1. Lunes 10:00..." |
| 5 | SLOT_SELECTION | "El lunes a las 10" | select_slot | - | "¿Tu nombre?" |
| 6 | CUSTOMER_DATA | "María García" | provide_customer_data | - | "Confirma: María, Corte largo, Ana, Lun 10:00" |
| 7 | CONFIRMATION | "Sí, confirmo" | confirm_booking | book | "¡Reservado! Te esperamos..." |
| 8 | BOOKED → IDLE | - | - | - | (auto-reset) |

## Non-Functional Requirements

### Performance

| Requisito | Target | Estrategia | Ref PRD |
|-----------|--------|------------|---------|
| Latencia FSM load/persist | < 50ms | Redis in-memory, JSON serialization | NFR1 |
| Latencia intent extraction | < 2s | Prompt optimizado, OpenRouter caching | NFR1 |
| Respuesta total bot | < 5s | FSM + Intent + LLM response parallelizable | NFR1 |
| Memory footprint FSM | < 1KB/conversation | Solo datos esenciales en Redis | - |

**Optimizaciones específicas:**
- FSM state es JSON pequeño (~500 bytes), carga/persiste en <10ms
- Intent extraction usa prompt corto (~800 tokens) con contexto mínimo
- LLM response generation reutiliza cache de OpenRouter (>1024 tokens cached)

### Security

| Requisito | Implementación | Ref PRD |
|-----------|----------------|---------|
| FSM state isolation | Key por conversation_id, no cross-access | - |
| Intent validation | LLM no ejecuta tools directamente, FSM valida | - |
| Tool authorization | Decorator `@requires_fsm_state` previene ejecución no autorizada | - |
| Data sanitization | Entities extraídas se validan antes de usar en tools | - |

**Consideraciones:**
- FSM no almacena datos sensibles (phone, payment), solo referencias (stylist_id, service_name)
- Redis keys usan namespace `fsm:` separado de checkpoints
- No hay nuevos endpoints expuestos (FSM es interno al agent)

### Reliability/Availability

| Requisito | Estrategia | Ref PRD |
|-----------|------------|---------|
| FSM state recovery | Si Redis falla, FSM defaults to IDLE (graceful degradation) | NFR4 |
| Intent extraction fallback | Si LLM falla, intent = UNKNOWN, bot pide reformular | NFR4 |
| Transition failure handling | FSM no cambia estado si tool falla, permite retry | NFR4 |
| Backwards compatibility | Conversaciones existentes sin FSM state inician en IDLE | NFR4 |

**Recovery patterns:**
```python
# Si Redis no tiene FSM state para conversation_id
fsm = await BookingFSM.load(conv_id)  # Returns new FSM in IDLE state

# Si intent extraction falla
try:
    intent = await extract_intent(...)
except LLMError:
    intent = Intent(type=IntentType.UNKNOWN, ...)
    # Bot responde: "No entendí, ¿puedes reformular?"
```

### Observability

| Signal | Tipo | Formato | Propósito |
|--------|------|---------|-----------|
| `fsm.state_transition` | Log INFO | `{conv_id, from_state, to_state, intent_type}` | Tracking de flujo |
| `fsm.transition_rejected` | Log WARNING | `{conv_id, current_state, intent_type, reason}` | Debug de rechazos |
| `fsm.load_time_ms` | Metric | Histogram | Performance monitoring |
| `intent.extraction_time_ms` | Metric | Histogram | LLM latency tracking |
| `intent.confidence` | Metric | Histogram | Accuracy monitoring |
| `fsm.state_distribution` | Metric | Gauge | Estado actual por conversación |

**Logging examples:**
```python
logger.info("fsm.state_transition", extra={
    "conversation_id": conv_id,
    "from_state": "service_selection",
    "to_state": "stylist_selection",
    "intent_type": "confirm_services",
    "services_count": 2
})

logger.warning("fsm.transition_rejected", extra={
    "conversation_id": conv_id,
    "current_state": "idle",
    "intent_type": "confirm_booking",
    "reason": "cannot_confirm_without_booking_in_progress"
})
```

## Dependencies and Integrations

### Dependencias de Proyecto (Sin Cambios)

Este Epic **no requiere nuevas dependencias**. Utiliza las existentes:

| Dependencia | Versión | Uso en Epic 5 |
|-------------|---------|---------------|
| `langgraph` | >=0.6.7 | Orquestación de agent (sin cambios) |
| `langchain` | >=0.3.0 | LLM integration para intent extraction |
| `langchain-openai` | >=0.3.0 | OpenRouter API client |
| `redis` | >=5.0.0 | Persistencia FSM state |
| `pydantic` | >=2.9.0 | Validación de Intent, FSMResult models |

### Integraciones Externas

| Servicio | Impacto Epic 5 | Cambios Requeridos |
|----------|----------------|-------------------|
| OpenRouter (LLM) | Intent extraction usa nueva prompt | Solo prompt changes |
| Redis Stack | Nueva key namespace `fsm:*` | Sin cambios de configuración |
| Google Calendar | Sin cambios | - |
| Chatwoot | Sin cambios | - |
| PostgreSQL | Sin cambios | - |

### Integración Interna: FSM ↔ LangGraph

```python
# agent/graphs/conversation_flow.py
# FSM se integra DENTRO del nodo conversational_agent, no como nodo separado

async def conversational_agent(state: ConversationState) -> dict[str, Any]:
    # 1. Load FSM (from Redis)
    fsm = await BookingFSM.load(state["conversation_id"])

    # 2. Extract intent (via LLM)
    intent = await extract_intent(
        message=state["messages"][-1]["content"],
        current_state=fsm.state,
        collected_data=fsm.collected_data,
        conversation_history=state["messages"]
    )

    # 3. FSM validates and transitions
    if fsm.can_transition(intent):
        result = fsm.transition(intent)
        await fsm.persist()
    else:
        result = FSMResult(success=False, ...)

    # 4. LLM generates response based on FSM state
    response = await generate_response(fsm.state, result, intent)

    return add_message(state, "assistant", response)
```

### Redis Key Schema

```
# FSM state keys
fsm:{conversation_id}          # JSON con state + collected_data
                               # TTL: 900s (15 min)

# Existing checkpoint keys (sin cambios)
checkpoint:{thread_id}         # LangGraph checkpoint
checkpoint_writes:{thread_id}  # LangGraph writes
```

## Acceptance Criteria (Authoritative)

### AC1: FSM States y Transiciones Documentadas
- Documento `docs/architecture/fsm-booking-flow.md` existe con especificación completa
- Diagrama visual de estados y transiciones incluido
- Cada transición tiene condiciones de validación definidas
- Cada estado tiene datos requeridos documentados

### AC2: BookingFSM Implementado y Funcional
- Clase `BookingFSM` en `agent/fsm/booking_fsm.py` implementada
- 7 estados definidos como Enum: IDLE, SERVICE_SELECTION, STYLIST_SELECTION, SLOT_SELECTION, CUSTOMER_DATA, CONFIRMATION, BOOKED
- Método `can_transition()` valida transiciones correctamente
- Método `transition()` ejecuta transiciones y actualiza `collected_data`
- Estado persiste en Redis con TTL 15 min
- Unit tests cubren todas las transiciones (happy + error paths)

### AC3: Intent Extraction Funcional
- Función `extract_intent()` en `agent/fsm/intent_extractor.py` implementada
- LLM extrae intención estructurada con >90% accuracy en tests
- Contexto de estado FSM se usa para disambiguar mensajes (e.g., "1" significa diferente cosa en cada estado)
- Fallback a `IntentType.UNKNOWN` si extracción falla
- Integration tests con conversaciones reales

### AC4: Integración LLM + FSM Mantiene Naturalidad
- Mensajes del bot son naturales y personalizados (no robóticos)
- Usuario puede expresar intención en lenguaje natural (no comandos)
- Transiciones inválidas se redirigen con mensajes amigables
- Manual testing via WhatsApp confirma naturalidad conversacional

### AC5: Tools Refactorizadas con FSM Validation
- Decorator `@requires_fsm_state` implementado
- `book()` tool solo ejecutable en estado CONFIRMATION
- Tools retornan datos estructurados para FSM
- Errors en tools no rompen FSM (recovery automático)
- Logs muestran estado FSM en cada tool call

### AC6: Bugs de Epic 1 Story 1-5 Resueltos
- Bug de state flags: FSM controla estado, no flags en ConversationState
- Bug de UUID serialization: `ensure_customer_exists()` retorna strings
- Flujo completo de booking funciona sin errores

### AC7: Tests Completos y Pasando
- Unit tests para BookingFSM (todas las transiciones)
- Unit tests para intent extraction
- Integration tests LLM + FSM
- End-to-end tests de flujo completo
- Coverage >85% para código nuevo
- Todos los tests pasan en CI

### AC8: Epic 1 Stories Migradas
- Story 1-5 completada con FSM
- Story 1-6 adaptada a FSM
- Story 1-7 adaptada a FSM
- Epic 1 puede marcarse como "done"

## Traceability Mapping

| AC | Spec Section | Component(s) | Test Strategy |
|----|--------------|--------------|---------------|
| AC1 | Detailed Design > Data Models | `docs/architecture/fsm-booking-flow.md` | Review: documento existe y completo |
| AC2 | Detailed Design > APIs/Interfaces | `agent/fsm/booking_fsm.py` | Unit: test_booking_fsm.py (all transitions) |
| AC3 | Detailed Design > APIs/Interfaces | `agent/fsm/intent_extractor.py` | Unit + Integration: test_intent_extractor.py |
| AC4 | Workflows > Happy Path | `agent/nodes/conversational_agent.py` | Manual: 8 casos via WhatsApp |
| AC5 | Detailed Design > Tool Validation | `agent/tools/*.py` | Unit: test_tools_fsm_validation.py |
| AC6 | Overview (bugs) | `agent/fsm/*`, `agent/tools/customer_tools.py` | E2E: test_booking_flow_e2e.py |
| AC7 | NFR > Observability | `tests/` | CI: pytest --cov-fail-under=85 |
| AC8 | Objectives > Scope | Epic 1 stories | Manual: verificar stories completadas |

### PRD FR Coverage

| PRD FR | Epic 5 Coverage | Notes |
|--------|-----------------|-------|
| FR1-FR12 (Agendamiento) | Indirectamente | FSM controla flujo, FR1-4 ya implementados en Epic 1 |
| FR38 (Listas numeradas) | Indirectamente | FSM no cambia presentación, solo controla flujo |
| FR39 (Respuestas número/texto) | AC3, AC4 | Intent extraction maneja ambos formatos |
| FR40 (Contexto conversación) | AC2 | FSM persiste estado entre mensajes |

### Story to AC Mapping

| Story | ACs Cubiertos |
|-------|---------------|
| 5-1: Diseño FSM States | AC1 |
| 5-2: Implementación FSM Controller | AC2 |
| 5-3: Integración LLM + FSM | AC3, AC4 |
| 5-4: Refactorización Tools | AC5 |
| 5-5: Testing E2E | AC6, AC7 |
| 5-6: Migración Epic 1 | AC8 |

## Risks, Assumptions, Open Questions

### Risks

| ID | Riesgo | Probabilidad | Impacto | Mitigación |
|----|--------|--------------|---------|------------|
| R1 | LLM no extrae intención correctamente en casos edge | Media | Alto | Agregar ejemplos en prompt, validación adicional, fallback a UNKNOWN |
| R2 | FSM demasiado rígida pierde naturalidad conversacional | Baja | Alto | Testing extensivo con usuarios reales, prompts para redirecciones naturales |
| R3 | Migración de Epic 1 toma más tiempo del estimado | Media | Medio | Priorizar solo stories críticas (1-5, 1-6, 1-7), scope reducido |
| R4 | Bugs en tools refactorizadas causan regresiones | Media | Alto | Tests exhaustivos, rollback plan, feature flag para FSM |
| R5 | Redis TTL causa pérdida de estado en conversaciones largas | Baja | Medio | TTL configurable, warning logs cuando estado cerca de expirar |

### Assumptions

| ID | Asunción | Validación |
|----|----------|------------|
| A1 | OpenRouter/GPT-4.1-mini puede extraer intención estructurada con accuracy suficiente | Probar con 50+ mensajes reales antes de integración |
| A2 | Redis Stack está disponible y configurado correctamente | Ya funciona para checkpoints, mismo setup |
| A3 | Estado FSM de 7 estados es suficiente para el booking flow | Basado en análisis de Epic 1 stories y PRD |
| A4 | Conversaciones no duran más de 15 minutos (TTL Redis) | Estadísticas de conversaciones existentes confirman |
| A5 | Usuarios aceptarán redirecciones cuando intenten acciones fuera de orden | Manual testing validará UX |

### Open Questions

| ID | Pregunta | Propietario | Fecha Límite | Decisión |
|----|----------|-------------|--------------|----------|
| Q1 | ¿Debe FSM persistir en PostgreSQL además de Redis para auditoría? | Dev | Story 5-2 | **No** - Redis suficiente, logs proveen auditoría |
| Q2 | ¿Cómo manejar múltiples bookings simultáneos del mismo cliente? | Dev | Story 5-2 | **FSM única por conversación** - cliente debe terminar uno antes de empezar otro |
| Q3 | ¿Intent extraction debe usar modelo diferente (más barato) que response generation? | Dev | Story 5-3 | **Mismo modelo** (GPT-4.1-mini) - simplifica implementación, costo aceptable |
| Q4 | ¿Feature flag para rollback a arquitectura v3.2 si FSM falla? | Dev | Story 5-4 | **Sí** - `FSM_ENABLED=true/false` en config |

## Test Strategy Summary

### Test Levels

| Nivel | Scope | Framework | Coverage Target |
|-------|-------|-----------|-----------------|
| Unit | BookingFSM, IntentExtractor, models | pytest | 90% |
| Integration | LLM + FSM, Tools + FSM | pytest-asyncio | 85% |
| E2E | Flujo completo booking | pytest + mocks | 80% |
| Manual | WhatsApp real | Manual checklist | 8 casos |

### Unit Tests

**`tests/unit/test_booking_fsm.py`**
```python
# Transitions válidas
def test_idle_to_service_selection_on_start_booking()
def test_service_selection_to_stylist_on_confirm_services()
def test_stylist_selection_to_slot_on_select_stylist()
def test_slot_selection_to_customer_data_on_select_slot()
def test_customer_data_to_confirmation_on_provide_data()
def test_confirmation_to_booked_on_confirm_booking()
def test_any_state_to_idle_on_cancel()

# Transitions inválidas
def test_cannot_confirm_booking_from_idle()
def test_cannot_select_slot_without_stylist()
def test_cannot_skip_customer_data()

# Persistence
def test_fsm_persist_to_redis()
def test_fsm_load_from_redis()
def test_fsm_load_creates_new_if_not_exists()
```

**`tests/unit/test_intent_extractor.py`**
```python
def test_extract_start_booking_intent()
def test_extract_select_service_by_name()
def test_extract_select_service_by_number()
def test_extract_confirm_services()
def test_extract_select_stylist()
def test_extract_select_slot()
def test_extract_customer_data_full_name()
def test_extract_confirm_booking()
def test_extract_cancel_booking()
def test_extract_faq_intent()
def test_extract_unknown_intent()
def test_context_aware_disambiguation()  # "1" en diferentes estados
```

### Integration Tests

**`tests/integration/test_fsm_llm_integration.py`**
```python
async def test_full_booking_flow_happy_path()
async def test_booking_with_service_change()
async def test_booking_cancelled_mid_flow()
async def test_invalid_transition_redirects_gracefully()
async def test_tool_error_does_not_break_fsm()
```

### E2E Tests

**`tests/integration/scenarios/test_booking_e2e.py`**
```python
async def test_complete_booking_single_service()
async def test_complete_booking_multiple_services()
async def test_booking_with_returning_customer()
async def test_booking_with_new_customer()
```

### Manual Test Cases (WhatsApp)

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

### Coverage Requirements

```toml
# pyproject.toml
[tool.coverage.report]
fail_under = 85

# Archivos nuevos Epic 5 deben tener >90%
# agent/fsm/booking_fsm.py
# agent/fsm/intent_extractor.py
```

### CI Pipeline

```yaml
# Existing pytest command with coverage
DATABASE_URL="..." ./venv/bin/pytest \
  --cov=agent/fsm \
  --cov-fail-under=85 \
  -m "not slow"
```
