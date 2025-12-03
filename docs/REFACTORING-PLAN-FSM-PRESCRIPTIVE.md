# Plan de Refactoring: FSM Prescriptiva

**Fecha**: 2025-12-03
**Autor**: Claude Code
**Estado**: Propuesta
**Estimación**: 5-7 días de desarrollo

---

## Executive Summary

### Problema Actual

La arquitectura híbrida LLM+FSM tiene un fallo de diseño fundamental:

```
Diseño Declarado (ADR-006):
  LLM (NLU) → Interpreta intención
  FSM       → Controla flujo, decide tools
  Tools     → Ejecuta acciones

Diseño Real:
  LLM (NLU) → Interpreta intención
  FSM       → Valida transiciones (post-hoc)
  LLM       → DECIDE qué tools llamar    ← PROBLEMA
  Tools     → Ejecuta acciones
  FSM       → Valida DESPUÉS de la decisión
```

**El LLM tiene control sobre tool calling.** La FSM solo valida después, lo que causa:
- Hallucinations de booking (LLM dice "reserva confirmada" sin llamar `book()`)
- Salto de pasos (LLM ignora `find_next_available` y alucina horarios)
- Validación reactiva en vez de preventiva

### Solución Propuesta

Transformar la FSM de **sugerente** a **prescriptiva**:

```
Nuevo Diseño:
  LLM (NLU) → Clasifica intent (solo NLU)
  Router    → Separa booking vs non-booking
  FSM       → EJECUTA tools automáticamente (para booking)
  LLM       → Formatea respuesta con resultados de tools
```

**Beneficios:**
- 0% hallucinations (FSM ejecuta, no sugiere)
- Flujo determinista y testeable
- LLM enfocado solo en lenguaje natural
- Eliminación de 4 capas de parches (ADR-012)

---

## Análisis del Estado Actual

### Arquitectura Actual (v4.0)

```
┌─────────────────────────────────────────────────────────────────┐
│                    conversational_agent.py                       │
├─────────────────────────────────────────────────────────────────┤
│  1. FSM.from_dict()          → Cargar estado                    │
│  2. extract_intent()         → LLM clasifica intent             │
│  3. fsm.transition()         → FSM valida transición            │
│  4. llm.ainvoke()            → LLM DECIDE tools (problema)      │
│  5. execute_tool_call()      → Ejecuta tools que LLM decidió    │
│  6. ResponseValidator        → Valida respuesta (reactivo)      │
│  7. StateActionAuditor       → Audita coherencia (parche)       │
│  8. fsm.to_dict()            → Persistir estado                 │
└─────────────────────────────────────────────────────────────────┘
```

### Problemas Identificados

| # | Problema | Ubicación | Impacto |
|---|----------|-----------|---------|
| 1 | `required_tool_call` es solo texto en prompt | `booking_fsm.py:453-464` | LLM puede ignorarlo |
| 2 | Todos los tools siempre disponibles | `conversational_agent.py:235-244` | LLM puede llamar tools inválidos |
| 3 | Validación de tools es reactiva | `tool_validation.py:159-306` | Error después de la decisión |
| 4 | Sub-fases de SLOT_SELECTION opacas | `booking_fsm.py:867-885` | LLM no sabe cuándo buscar horarios |
| 5 | CUSTOMER_DATA phases internas | `booking_fsm.py:689-717` | LLM puede saltar preguntas |
| 6 | Prompts contradicen FSM | `step2_availability.md:39-44` | "Pregunta primero" vs FSM |

### Archivos Afectados

```
agent/
├── nodes/
│   └── conversational_agent.py   # REFACTOR MAYOR (~600 líneas)
├── fsm/
│   ├── booking_fsm.py            # MODIFICAR: add get_required_action()
│   ├── intent_extractor.py       # SIMPLIFICAR: solo NLU
│   ├── tool_validation.py        # ELIMINAR: ya no necesario
│   ├── response_validator.py     # SIMPLIFICAR: solo verificación
│   └── state_action_auditor.py   # ELIMINAR: ya no necesario
├── tools/
│   └── (sin cambios)
├── prompts/
│   ├── core.md                   # SIMPLIFICAR: quitar instrucciones de flujo
│   ├── step1_service.md          # ELIMINAR o convertir a templates
│   ├── step2_availability.md     # ELIMINAR o convertir a templates
│   └── ...
└── state/
    └── schemas.py                # AGREGAR: nuevos campos
```

---

## Diseño de la Nueva Arquitectura

### Flujo Principal

```
┌─────────────────────────────────────────────────────────────────┐
│                 conversational_agent.py (NUEVO)                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. LOAD FSM                                                     │
│     fsm = BookingFSM.from_dict(state)                           │
│                                                                  │
│  2. CLASSIFY INTENT (LLM solo NLU)                              │
│     intent = await extract_intent(message, fsm.state)           │
│     # Returns: BOOKING_FLOW, FAQ, GREETING, ESCALATE, etc.      │
│                                                                  │
│  3. ROUTE BY INTENT TYPE                                         │
│     ┌─────────────────────────────────────────────────────────┐ │
│     │ if intent.type in NON_BOOKING_INTENTS:                  │ │
│     │     # LLM responde libremente (FAQs, saludos, etc.)     │ │
│     │     response = await handle_non_booking(message, fsm)   │ │
│     │                                                          │ │
│     │ elif intent.type in BOOKING_INTENTS:                    │ │
│     │     # FSM PRESCRIPTIVA: ejecuta tools automáticamente   │ │
│     │     response = await handle_booking_flow(intent, fsm)   │ │
│     └─────────────────────────────────────────────────────────┘ │
│                                                                  │
│  4. PERSIST FSM                                                  │
│     state["fsm_state"] = fsm.to_dict()                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Handle Non-Booking (LLM Libre)

```python
async def handle_non_booking(
    message: str,
    fsm: BookingFSM,
    state: ConversationState
) -> str:
    """
    Maneja intents que NO afectan el flujo de booking.
    LLM responde libremente con acceso a tools informativos.
    """
    # Tools permitidos para non-booking
    allowed_tools = [query_info, get_customer_history, escalate_to_human]

    # Contexto del FSM para que LLM sepa dónde está el usuario
    fsm_context = f"Usuario está en estado: {fsm.state.value}"
    if fsm.state != BookingState.IDLE:
        fsm_context += f"\nDatos recopilados: {fsm.collected_data}"

    # LLM genera respuesta
    llm = ChatOpenAI(...).bind_tools(allowed_tools)
    response = await llm.ainvoke([
        SystemMessage(content=CORE_PROMPT + fsm_context),
        HumanMessage(content=message)
    ])

    # Ejecutar tools si LLM los llamó
    if response.tool_calls:
        # Solo tools informativos, no afectan FSM
        response = await execute_and_respond(response, llm)

    return response.content
```

### Handle Booking Flow (FSM Prescriptiva)

```python
async def handle_booking_flow(
    intent: Intent,
    fsm: BookingFSM,
    state: ConversationState
) -> str:
    """
    Maneja intents de BOOKING con FSM prescriptiva.
    FSM decide y EJECUTA tools, LLM solo formatea respuesta.
    """
    # 1. FSM valida y ejecuta transición
    result = await fsm.transition(intent)

    if not result.success:
        # Transición rechazada - generar mensaje de error amigable
        return await format_transition_error(result, fsm)

    # 2. FSM determina acción requerida para el nuevo estado
    action = fsm.get_required_action()

    # 3. EJECUTAR TOOL AUTOMÁTICAMENTE (si FSM lo requiere)
    tool_result = None
    if action.tool:
        tool_result = await execute_fsm_tool(action.tool, action.args, fsm)

    # 4. LLM formatea respuesta con los datos del tool
    response = await format_booking_response(
        fsm_state=fsm.state,
        tool_result=tool_result,
        action=action,
        collected_data=fsm.collected_data
    )

    return response
```

### FSM Required Actions (NUEVO)

```python
@dataclass
class FSMAction:
    """Acción que la FSM requiere para el estado actual."""
    tool: str | None           # Tool a ejecutar (None si no requiere)
    args: dict[str, Any]       # Argumentos para el tool
    response_template: str     # Template para formatear respuesta
    next_question: str | None  # Pregunta a hacer al usuario

# Mapping de estados a acciones requeridas
STATE_ACTIONS: dict[BookingState, Callable[[BookingFSM], FSMAction]] = {
    BookingState.IDLE: lambda fsm: FSMAction(
        tool=None,
        args={},
        response_template="greeting",
        next_question="¿En qué puedo ayudarte?"
    ),

    BookingState.SERVICE_SELECTION: lambda fsm: FSMAction(
        tool="search_services" if not fsm.collected_data.get("services") else None,
        args={"query": "todos"},  # Mostrar catálogo inicial
        response_template="service_list",
        next_question="¿Qué servicio te gustaría?"
    ),

    BookingState.STYLIST_SELECTION: lambda fsm: FSMAction(
        tool=None,  # Estilistas vienen de contexto estático
        args={},
        response_template="stylist_list",
        next_question="¿Con qué estilista prefieres?"
    ),

    BookingState.SLOT_SELECTION: lambda fsm: FSMAction(
        # SIEMPRE ejecutar find_next_available al entrar
        tool="find_next_available",
        args={
            "stylist_id": fsm.collected_data.get("stylist_id"),
            "service_category": "Peluquería",  # O derivar de servicios
            "max_results": 5
        },
        response_template="slot_list",
        next_question="¿Qué horario te viene mejor?"
    ),

    BookingState.CUSTOMER_DATA: lambda fsm: FSMAction(
        tool=None,
        args={},
        response_template="customer_data_request",
        next_question=_get_customer_data_question(fsm)
    ),

    BookingState.CONFIRMATION: lambda fsm: FSMAction(
        tool=None,
        args={},
        response_template="booking_summary",
        next_question="¿Confirmas la reserva?"
    ),

    BookingState.BOOKED: lambda fsm: FSMAction(
        tool="book",  # EJECUTAR book() automáticamente
        args=_build_book_args(fsm),
        response_template="booking_confirmed",
        next_question=None
    ),
}

def _get_customer_data_question(fsm: BookingFSM) -> str:
    """Retorna la pregunta correcta según la fase de CUSTOMER_DATA."""
    if not fsm.collected_data.get("first_name"):
        return "¿Me puedes dar tu nombre para la reserva?"
    elif not fsm.collected_data.get("notes_asked"):
        return "¿Tienes alguna preferencia o nota especial para tu cita?"
    else:
        return None  # Datos completos, avanzar a CONFIRMATION
```

### Response Formatting (LLM como Formateador)

```python
async def format_booking_response(
    fsm_state: BookingState,
    tool_result: dict | None,
    action: FSMAction,
    collected_data: dict
) -> str:
    """
    LLM formatea respuesta con datos del tool.
    NO decide flujo, solo genera lenguaje natural.
    """
    # Template base según estado
    template = RESPONSE_TEMPLATES[action.response_template]

    # Construir contexto para LLM
    context = {
        "tool_result": tool_result,
        "collected_data": collected_data,
        "next_question": action.next_question
    }

    # LLM formatea (sin tools, solo generación)
    llm = ChatOpenAI(temperature=0.3)  # Sin bind_tools

    prompt = f"""Formatea esta respuesta para el usuario de forma natural y amigable.

TEMPLATE: {template}
DATOS: {json.dumps(context, ensure_ascii=False)}

Reglas:
- Usa español natural y amigable
- Incluye la pregunta final si existe
- No inventes datos - usa solo los proporcionados
- Mantén el tono profesional pero cercano
"""

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    return response.content
```

---

## Plan de Implementación

### Fase 1: Preparación (1 día)

**Objetivo**: Crear estructura base sin romper funcionalidad actual.

#### Tarea 1.1: Crear nuevo módulo de routing
```python
# agent/routing/__init__.py
# agent/routing/intent_router.py
# agent/routing/booking_handler.py
# agent/routing/non_booking_handler.py
```

#### Tarea 1.2: Agregar FSMAction al BookingFSM
```python
# agent/fsm/booking_fsm.py

@dataclass
class FSMAction:
    tool: str | None
    args: dict[str, Any]
    response_template: str
    next_question: str | None

class BookingFSM:
    def get_required_action(self) -> FSMAction:
        """Retorna la acción requerida para el estado actual."""
        action_builder = STATE_ACTIONS.get(self._state)
        if action_builder:
            return action_builder(self)
        return FSMAction(tool=None, args={}, response_template="fallback", next_question=None)
```

#### Tarea 1.3: Definir templates de respuesta
```python
# agent/templates/responses.py

RESPONSE_TEMPLATES = {
    "greeting": "Saluda al usuario y pregunta en qué puede ayudar",
    "service_list": "Muestra lista numerada de servicios: {services}. Pregunta: {next_question}",
    "stylist_list": "Muestra lista de estilistas disponibles. Pregunta: {next_question}",
    "slot_list": "Muestra horarios disponibles: {slots}. Pregunta: {next_question}",
    "customer_data_request": "Pregunta: {next_question}",
    "booking_summary": "Muestra resumen: {summary}. Pregunta: {next_question}",
    "booking_confirmed": "Confirma cita creada: {appointment_details}",
    "fallback": "Responde de forma amigable manteniendo el contexto",
}
```

#### Tarea 1.4: Crear tests de regresión
```bash
# Capturar comportamiento actual antes de refactoring
pytest tests/integration/scenarios/ -v --tb=short > tests/baseline_behavior.txt
```

### Fase 2: Implementar Router (1 día)

**Objetivo**: Separar flujo booking vs non-booking.

#### Tarea 2.1: Simplificar intent_extractor.py
```python
# Reducir a clasificación binaria + entities
class IntentCategory(Enum):
    BOOKING_FLOW = "booking_flow"    # Afecta FSM
    NON_BOOKING = "non_booking"      # No afecta FSM

async def classify_intent(message: str, fsm_state: BookingState) -> tuple[IntentCategory, Intent]:
    """
    Clasifica si el mensaje es parte del flujo de booking o no.
    Retorna categoría + intent detallado.
    """
```

#### Tarea 2.2: Implementar routing en conversational_agent
```python
async def conversational_agent(state: ConversationState) -> dict[str, Any]:
    # ... load FSM ...

    # Clasificar intent
    category, intent = await classify_intent(message, fsm.state)

    # Router
    if category == IntentCategory.NON_BOOKING:
        response = await handle_non_booking(message, fsm, state)
    else:
        response = await handle_booking_flow(intent, fsm, state)

    # ... persist FSM ...
```

### Fase 3: Implementar Booking Handler Prescriptivo (2 días)

**Objetivo**: FSM ejecuta tools automáticamente.

#### Tarea 3.1: Implementar handle_booking_flow
```python
# agent/routing/booking_handler.py

async def handle_booking_flow(
    intent: Intent,
    fsm: BookingFSM,
    state: ConversationState
) -> str:
    # 1. Validar y ejecutar transición
    result = await fsm.transition(intent)

    if not result.success:
        return await format_transition_error(result, fsm)

    # 2. Obtener acción requerida
    action = fsm.get_required_action()

    # 3. Ejecutar tool si requerido
    tool_result = None
    if action.tool:
        tool_result = await execute_fsm_tool(
            tool_name=action.tool,
            args=action.args,
            fsm=fsm
        )

        # Validar resultado del tool
        if not tool_result or tool_result.get("error"):
            return await format_tool_error(action.tool, tool_result, fsm)

    # 4. Formatear respuesta
    response = await format_booking_response(
        fsm_state=fsm.state,
        tool_result=tool_result,
        action=action,
        collected_data=fsm.collected_data
    )

    return response
```

#### Tarea 3.2: Implementar execute_fsm_tool
```python
async def execute_fsm_tool(
    tool_name: str,
    args: dict[str, Any],
    fsm: BookingFSM
) -> dict[str, Any]:
    """
    Ejecuta un tool de forma prescriptiva.
    NO valida permisos - FSM ya decidió que este tool debe ejecutarse.
    """
    tool_map = {
        "search_services": search_services,
        "find_next_available": find_next_available,
        "check_availability": check_availability,
        "book": book,
        # query_info y otros son para non-booking
    }

    tool = tool_map.get(tool_name)
    if not tool:
        logger.error(f"Tool no encontrado: {tool_name}")
        return {"error": "TOOL_NOT_FOUND"}

    try:
        result = await tool.ainvoke(args)
        logger.info(f"FSM tool executed: {tool_name}", extra={"result_keys": list(result.keys()) if isinstance(result, dict) else "non-dict"})
        return result
    except Exception as e:
        logger.error(f"FSM tool failed: {tool_name}", exc_info=True)
        return {"error": str(e)}
```

#### Tarea 3.3: Implementar format_booking_response
```python
async def format_booking_response(
    fsm_state: BookingState,
    tool_result: dict | None,
    action: FSMAction,
    collected_data: dict
) -> str:
    """
    LLM formatea respuesta SIN control sobre flujo.
    """
    template = RESPONSE_TEMPLATES.get(action.response_template, RESPONSE_TEMPLATES["fallback"])

    # Construir datos para el template
    format_data = {
        "services": _format_services(tool_result) if action.tool == "search_services" else None,
        "slots": _format_slots(tool_result) if action.tool in ["find_next_available", "check_availability"] else None,
        "summary": _format_summary(collected_data) if fsm_state == BookingState.CONFIRMATION else None,
        "appointment_details": _format_appointment(tool_result) if fsm_state == BookingState.BOOKED else None,
        "next_question": action.next_question,
    }

    # LLM formatea
    llm = ChatOpenAI(model="openai/gpt-4.1-mini", temperature=0.3)

    prompt = f"""Genera una respuesta natural para el usuario.

Estado: {fsm_state.value}
Template: {template}
Datos: {json.dumps({k: v for k, v in format_data.items() if v}, ensure_ascii=False, indent=2)}

Reglas:
- Responde en español natural y amigable
- Si hay una lista (servicios, horarios), preséntalos numerados
- Incluye la pregunta final si existe
- NO inventes datos que no estén en los datos proporcionados
- Tono: profesional pero cercano, como una asistente de peluquería amable
"""

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    return response.content
```

### Fase 4: Implementar Non-Booking Handler (0.5 días)

**Objetivo**: LLM libre para FAQs, saludos, etc.

#### Tarea 4.1: Implementar handle_non_booking
```python
# agent/routing/non_booking_handler.py

async def handle_non_booking(
    message: str,
    fsm: BookingFSM,
    state: ConversationState
) -> str:
    """
    Maneja mensajes que NO afectan el flujo de booking.
    LLM responde libremente con tools informativos.
    """
    # Tools permitidos (solo informativos)
    allowed_tools = [query_info, get_customer_history, escalate_to_human]

    # Contexto FSM para que LLM sepa dónde está el usuario
    fsm_context = _build_fsm_context(fsm)

    # Prompt simplificado (sin instrucciones de flujo)
    system_prompt = f"""{CORE_PROMPT_SIMPLIFIED}

{fsm_context}

Puedes usar estas herramientas para responder preguntas:
- query_info: para FAQs, horarios, servicios, políticas
- get_customer_history: para historial del cliente
- escalate_to_human: si el usuario quiere hablar con una persona

Si el usuario quiere hacer una reserva, guíalo de vuelta al flujo de booking.
"""

    llm = ChatOpenAI(...).bind_tools(allowed_tools)

    messages = [
        SystemMessage(content=system_prompt),
        *_convert_history(state.get("messages", [])),
        HumanMessage(content=message)
    ]

    response = await llm.ainvoke(messages)

    # Ejecutar tools si LLM los llamó
    if response.tool_calls:
        messages.append(response)
        for tc in response.tool_calls:
            result = await execute_tool(tc)
            messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))
        response = await llm.ainvoke(messages)

    return response.content
```

### Fase 5: Simplificar y Limpiar (1 día)

**Objetivo**: Eliminar código obsoleto.

#### Tarea 5.1: Eliminar archivos obsoletos
```bash
# Archivos a eliminar o reducir significativamente
rm agent/fsm/state_action_auditor.py  # Ya no necesario
rm agent/fsm/tool_validation.py       # Reemplazado por FSM prescriptiva
# Simplificar response_validator.py   # Solo verificación, no corrección
```

#### Tarea 5.2: Simplificar prompts
```bash
# Eliminar instrucciones de flujo de los prompts
# Los prompts ahora son solo templates de respuesta

# Antes (step1_service.md):
# "PASO 1: PRIMERO llama search_services... LUEGO presenta..."

# Después:
# Solo template de cómo formatear lista de servicios
```

#### Tarea 5.3: Actualizar booking_fsm.py
```python
# Eliminar:
# - get_response_guidance() (reemplazado por get_required_action())
# - ResponseGuidance dataclass
# - _GUIDANCE_MAP

# Agregar:
# - FSMAction dataclass
# - STATE_ACTIONS mapping
# - get_required_action() method
```

#### Tarea 5.4: Actualizar conversational_agent.py
```python
# Refactorizar de ~1600 líneas a ~400 líneas:
# - Eliminar: format_guidance_prompt()
# - Eliminar: detect_premature_service_confirmation()
# - Eliminar: _generate_fallback_for_state()
# - Eliminar: ResponseValidator/regeneration logic
# - Eliminar: StateActionAuditor logic
# - Simplificar: execute_tool_call() (solo para non-booking)
```

### Fase 6: Testing y Validación (1.5 días)

**Objetivo**: Asegurar que todo funciona.

#### Tarea 6.1: Tests unitarios para nuevos componentes
```python
# tests/unit/test_intent_router.py
# tests/unit/test_booking_handler.py
# tests/unit/test_non_booking_handler.py
# tests/unit/test_fsm_actions.py
```

#### Tarea 6.2: Tests de integración
```python
# tests/integration/test_prescriptive_booking_flow.py

@pytest.mark.asyncio
async def test_slot_selection_always_calls_find_next_available():
    """FSM DEBE llamar find_next_available al entrar en SLOT_SELECTION."""
    # Setup: Usuario selecciona estilista
    # Assert: find_next_available fue llamado
    # Assert: Respuesta contiene horarios reales
    pass

@pytest.mark.asyncio
async def test_faq_in_middle_of_booking_doesnt_break_flow():
    """FAQ en medio del booking no afecta FSM state."""
    # Setup: Usuario en SLOT_SELECTION
    # Action: Usuario pregunta "¿Cuánto cuesta el tinte?"
    # Assert: FSM sigue en SLOT_SELECTION
    # Assert: Respuesta contiene precio
    # Assert: FSM collected_data intacto
    pass

@pytest.mark.asyncio
async def test_booking_confirmation_requires_actual_booking():
    """No se puede confirmar booking sin llamar book()."""
    # Setup: Usuario en CONFIRMATION
    # Action: Usuario dice "Sí, confirmo"
    # Assert: book() fue llamado
    # Assert: Respuesta contiene appointment_id real
    pass
```

#### Tarea 6.3: Tests de regresión
```bash
# Comparar con baseline capturado en Fase 1
pytest tests/integration/scenarios/ -v --tb=short > tests/new_behavior.txt
diff tests/baseline_behavior.txt tests/new_behavior.txt
```

#### Tarea 6.4: Test manual con escenarios reales
```
Escenario 1: Happy path completo
Escenario 2: FAQ en medio del booking
Escenario 3: Fecha inválida (3-day rule)
Escenario 4: Cambio de servicio en medio del booking
Escenario 5: Cancelación en cualquier punto
```

---

## Comparación: Antes vs Después

### Flujo de SLOT_SELECTION

**Antes (Sugerente):**
```
1. Usuario selecciona estilista → FSM transiciona a SLOT_SELECTION
2. FSM genera ResponseGuidance con required_tool_call="find_next_available"
3. Guidance se inyecta en prompt como texto
4. LLM PUEDE ignorarlo y alucinar horarios
5. ResponseValidator intenta detectar hallucination
6. Si detecta, regenera respuesta (latencia extra)
7. StateActionAuditor verifica coherencia (más latencia)
```

**Después (Prescriptiva):**
```
1. Usuario selecciona estilista → FSM transiciona a SLOT_SELECTION
2. FSM.get_required_action() retorna {tool: "find_next_available", args: {...}}
3. Sistema EJECUTA find_next_available automáticamente
4. LLM formatea resultado (no decide flujo)
5. Respuesta garantizada con horarios reales
```

### Manejo de FAQ en Booking

**Antes:**
```
1. Usuario en SLOT_SELECTION pregunta "¿Cuánto cuesta el tinte?"
2. intent_extractor clasifica como FAQ
3. FSM no transiciona (non-booking intent)
4. LLM genera respuesta... pero tiene todos los tools disponibles
5. LLM podría accidentalmente llamar find_next_available
6. O podría olvidar el contexto del booking
```

**Después:**
```
1. Usuario en SLOT_SELECTION pregunta "¿Cuánto cuesta el tinte?"
2. classify_intent() retorna NON_BOOKING
3. Router envía a handle_non_booking()
4. LLM solo tiene acceso a query_info (tool informativo)
5. LLM responde FAQ con contexto: "El tinte cuesta X. ¿Qué horario prefieres para tu cita?"
6. FSM state intacto
```

---

## Riesgos y Mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| Regresión en flujo existente | Media | Alto | Tests de regresión exhaustivos |
| LLM formateo inconsistente | Baja | Medio | Templates estructurados + validación |
| Latencia por doble LLM call | Media | Bajo | Caché de clasificación + paralelización |
| Edge cases no cubiertos | Media | Medio | Tests manuales + logging detallado |

---

## Métricas de Éxito

### Antes (Baseline)

| Métrica | Valor Actual | Fuente |
|---------|--------------|--------|
| Hallucinations de booking | ~5-10% estimado | Logs |
| Latencia por regeneración | +500ms cuando ocurre | Logs |
| Líneas de código defensivo | ~600 líneas | Conteo |
| Tests de parches (ADR-012) | 4 capas | Código |

### Después (Target)

| Métrica | Target | Cómo Medir |
|---------|--------|------------|
| Hallucinations de booking | 0% | Todos los bookings tienen appointment_id |
| Latencia por regeneración | 0ms | No hay regeneración |
| Líneas de código defensivo | ~100 líneas | Solo verificación, no corrección |
| Tests de parches | 0 capas | Eliminados |

---

## Cronograma Propuesto

| Día | Fase | Tareas |
|-----|------|--------|
| 1 | Preparación | 1.1-1.4: Estructura base, FSMAction, templates, baseline |
| 2 | Router | 2.1-2.2: Simplificar intent_extractor, implementar routing |
| 3-4 | Booking Handler | 3.1-3.3: handle_booking_flow prescriptivo |
| 4 | Non-Booking | 4.1: handle_non_booking con LLM libre |
| 5 | Limpieza | 5.1-5.4: Eliminar código obsoleto |
| 6-7 | Testing | 6.1-6.4: Tests unitarios, integración, regresión, manual |

---

## Decisiones Pendientes

1. **¿Mantener sub-fases de SLOT_SELECTION?**
   - Opción A: Eliminar, siempre mostrar horarios al entrar
   - Opción B: Mantener pero hacer explícitas vía FSMAction
   - **Recomendación**: Opción A (simplificar)

2. **¿Cómo manejar cambio de servicio en medio del booking?**
   - Opción A: Permitir volver a SERVICE_SELECTION
   - Opción B: Requerir cancelar y empezar de nuevo
   - **Recomendación**: Opción A con confirmación

3. **¿Caché para clasificación de intent?**
   - Si mensaje es idéntico al anterior, reusar clasificación
   - **Recomendación**: No, demasiado complejo para poco beneficio

---

## Aprobación

- [ ] Revisado por: _______________
- [ ] Aprobado para implementación: _______________
- [ ] Fecha de inicio: _______________

---

## Anexo: Archivos a Modificar (Resumen)

### Crear Nuevos
```
agent/routing/__init__.py
agent/routing/intent_router.py
agent/routing/booking_handler.py
agent/routing/non_booking_handler.py
agent/templates/responses.py
tests/unit/test_intent_router.py
tests/unit/test_booking_handler.py
tests/integration/test_prescriptive_booking_flow.py
```

### Modificar Significativamente
```
agent/nodes/conversational_agent.py   # ~1600 → ~400 líneas
agent/fsm/booking_fsm.py              # +get_required_action(), -get_response_guidance()
agent/fsm/intent_extractor.py         # Simplificar a clasificación binaria
```

### Eliminar o Reducir
```
agent/fsm/state_action_auditor.py     # Eliminar
agent/fsm/tool_validation.py          # Eliminar (FSM prescriptiva)
agent/fsm/response_validator.py       # Reducir a verificación simple
agent/prompts/step1_service.md        # Convertir a template o eliminar
agent/prompts/step2_availability.md   # Convertir a template o eliminar
agent/prompts/step3_customer.md       # Convertir a template o eliminar
agent/prompts/step4_confirmation.md   # Convertir a template o eliminar
agent/prompts/step4_booking.md        # Convertir a template o eliminar
agent/prompts/step5_post_booking.md   # Convertir a template o eliminar
```
