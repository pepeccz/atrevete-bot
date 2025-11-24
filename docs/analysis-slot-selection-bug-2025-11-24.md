# Análisis Profundo: Bug de Selección de Disponibilidad (Slot Selection)

**Fecha**: 24 de Noviembre de 2025
**Conversación Reportada**: Usuario dice "El 1 de diciembre por la tarde" → Bot avanza sin mostrar horarios
**Severidad**: ALTA (flujo de reserva roto - usuario no puede seleccionar horario específico)

---

## Problema Observado

Usuario: "El 1 de diciembre por la tarde"
Bot responde: "Para poder mostrarte los horarios necesito antes tu nombre para la reserva"

**❌ Lo que sucede:**
1. Bot NO muestra ningún horario disponible
2. Bot avanza directamente a CUSTOMER_DATA (pedir nombre)
3. El slot seleccionado está hardcodeado: `2024-12-01T15:00:00+01:00` (solo "tarde" → "15:00")
4. Usuario nunca confirma qué horario específico quiere

**✅ Lo que debería suceder:**
1. Bot interpreta "1 de diciembre por la tarde" como REQUEST para ver opciones
2. Bot llama `check_availability(date="1 diciembre", stylist_id=pilar_id)`
3. Bot muestra 5 horarios disponibles esa tarde (11:00, 14:00, 15:00, 16:00, 17:00, etc.)
4. Usuario selecciona uno: "el 3" o "el horario de las 14:00"
5. Luego pasa a CUSTOMER_DATA

---

## Raíz del Problema

### Root Cause #1: Intent Extractor está interpretando "tarde" como hora específica

**Dónde**: `agent/fsm/intent_extractor.py` (línea ~800+, prompt building)

**Qué pasa**:
- El LLM recibe el mensaje "El 1 de diciembre por la tarde"
- Está en estado SLOT_SELECTION
- El prompt le dice: "intenciones válidas para este estado: select_slot, check_availability"
- El LLM elige SELECT_SLOT (incorrecto) en lugar de CHECK_AVAILABILITY
- LLM asume que "tarde" = "15:00" (una hora específica)
- Convierte a ISO 8601: `2024-12-01T15:00:00+01:00`

**El bug**: No hay lógica en el prompt que distinga entre:
- **Hora específica**: "10:30", "las 2 de la tarde" (SELECT_SLOT)
- **Rango vago**: "por la tarde", "por la mañana", "en la tarde" (CHECK_AVAILABILITY)

### Root Cause #2: El LLM hardcodea "tarde" sin validar disponibilidad

**Dónde**: Intent extractor prompt y procesamiento de `start_time`

**El problema**:
```python
# Línea 707-720: intent_extractor.py
if "start_time" in entities and "slot" not in entities:
    raw_start_time = entities.pop("start_time")  # "2024-12-01T15:00:00"
    normalized_start_time = _normalize_start_time_timezone(raw_start_time)
    entities["slot"] = {
        "start_time": normalized_start_time,  # ← HARDCODEADO A LAS 15:00
        "duration_minutes": 0,
    }
```

El intent extractor confía en que el LLM extrajo una hora VÁLIDA y DISPONIBLE, pero:
- El LLM NUNCA validó contra el calendario
- El LLM NUNCA llamó a herramientas
- El LLM solo "adivinó" qué hora querría el usuario

### Root Cause #3: El FSM avanza sin validación de disponibilidad real

**Dónde**: `agent/nodes/conversational_agent.py` línea 793-822

```python
if fsm.can_transition(intent):
    fsm_result = fsm.transition(intent)
    # ↓ FSM avanza a CUSTOMER_DATA INMEDIATAMENTE
    # Sin verificar si el slot existe realmente en el calendario
```

El FSM **valida sintácticamente** (¿tiene los campos necesarios?) pero **NO valida semánticamente** (¿existe ese slot realmente?).

### Root Cause #4: No hay retroalimentación del calendario

**Dónde**: Toda la arquitectura está separada

El flujo es:
1. Usuario da entrada → Intent Extractor (sin acceso a calendario)
2. Intent → FSM (sin acceso a calendario)
3. FSM → Conversational Agent (recién aquí se llaman tools)

**Pero** cuando la intent es SELECT_SLOT, ya es demasiado tarde. El slot está "bloqueado" en la FSM.

---

## Impacto Arquitectónico

```
┌─────────────────────────────────────────┐
│ v3.2 LLM-Driven (PROBLEMA)              │
├─────────────────────────────────────────┤
│ Usuario: "1 de diciembre por la tarde"  │
│         ↓                               │
│ Intent: SELECT_SLOT (WRONG - sin        │
│         validar disponibilidad)         │
│         ↓                               │
│ FSM Transición: SLOT_SELECTION →        │
│                 CUSTOMER_DATA           │
│         ↓                               │
│ Result: Avanza sin mostrar opciones    │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ v4.0 FSM Hybrid (DESEADO)               │
├─────────────────────────────────────────┤
│ Usuario: "1 de diciembre por la tarde"  │
│         ↓                               │
│ Intent: CHECK_AVAILABILITY (RIGHT -     │
│         pide confirmación de opciones)  │
│         ↓                               │
│ FSM Transición: SLOT_SELECTION →        │
│                 SLOT_SELECTION (espera) │
│         ↓                               │
│ Tool Call: find_next_available/         │
│            check_availability           │
│         ↓                               │
│ Show: 5 horarios específicos            │
│         ↓                               │
│ Usuario selecciona: "el 2"              │
│         ↓                               │
│ Intent: SELECT_SLOT (NOW correcto)      │
│         ↓                               │
│ FSM Transición: SLOT_SELECTION →        │
│                 CUSTOMER_DATA           │
└─────────────────────────────────────────┘
```

---

## Diagnosis: Por qué el bug es SISTEMÁTICO

Este es **exactamente el tipo de bug que la arquitectura FSM v4.0 está diseñada a prevenir**:

✅ **Problema identificado en el CLAUDE.md**:
> "El sistema está migrando de arquitectura LLM-driven (v3.2) a FSM Híbrida (v4.0). Epic 5 implementa esta migración."
>
> **Problema con v3.2**: "La arquitectura LLM-driven producía bugs sistemáticos porque el LLM controlaba flujo además de NLU (bugs descubiertos en Epic 1 Story 1-5)."

Este bug de selección de disponibilidad es **exactamente ese patrón**:
- El LLM intenta controlar el flujo (SELECT_SLOT sin validar)
- Sin acceso a datos reales (calendario)
- Sin feedback de herramientas

---

## Solución de Raíz (No Parches)

### Fase 1: Intent Extractor - Distinguir CHECK_AVAILABILITY vs SELECT_SLOT

**Cambio 1a**: Expandir el prompt para ser explícito

```python
# En _build_extraction_prompt(), para SLOT_SELECTION state, agregar:

DISAMBIGUATION_FOR_SLOT_SELECTION = """
REGLA CRÍTICA: Distinguir entre check_availability vs select_slot

CHECK_AVAILABILITY (usuario PIDE ver opciones):
- Usuario dice SOLO una fecha sin hora específica:
  "El 1 de diciembre" (sin especificar qué hora)
  "Para el viernes" (sin especificar qué hora)
  "Por la tarde" (rango vago, no hora específica)
  "Mañana por la tarde" (rango vago)
  "Cuando tengan disponibilidad el 1" (indefinido)

- Usuario describe un rango temporal vago:
  "Por la mañana" (rango: 08:00-14:00)
  "Por la tarde" (rango: 14:00-20:00)
  "A mediodía" (rango: 12:00-14:00)

SELECT_SLOT (usuario SELECCIONA hora específica):
- Usuario dice UN NÚMERO de la lista: "1", "2", "el 3"
  (Busca en CONTEXTO RECIENTE una lista numerada de horarios)

- Usuario dice UNA HORA EXACTA: "10:30", "las 2 de la tarde" (con hora específica)
  (Pero SOLO si la lista anterior tiene esa hora disponible)

IMPORTANTE: "Por la tarde" ≠ "15:00"
- "Por la tarde" es un RANGO (14:00-20:00) → CHECK_AVAILABILITY
- "15:00" o "las 3 de la tarde" es ESPECÍFICO → SELECT_SLOT (si está en lista)

Si usuario pide rango vago + fecha:
→ intent: check_availability
→ entities: {"date": "1 de diciembre", "time_hint": "tarde"}
"""
```

**Cambio 1b**: Detectar ranges vagos en el post-processing

```python
# En _parse_llm_response(), agregar detectión de CHECK_AVAILABILITY:

VAGUE_TIME_RANGES = {
    "tarde": {"start": 14, "end": 20},
    "por la tarde": {"start": 14, "end": 20},
    "mañana": {"start": 8, "end": 20},
    "temprano": {"start": 8, "end": 12},
    "mediodía": {"start": 12, "end": 14},
    "noche": {"start": 20, "end": 23},
}

if intent_type == IntentType.SELECT_SLOT:
    start_time = entities.get("start_time", "").lower()
    slot_time = entities.get("slot_time", "").lower()

    # Check if it's a vague range
    is_vague = any(range_name in start_time.lower() or
                   range_name in slot_time.lower()
                   for range_name in VAGUE_TIME_RANGES.keys())

    if is_vague and not has_selection_number:
        # Convert to CHECK_AVAILABILITY
        intent_type = IntentType.CHECK_AVAILABILITY
        entities = {
            "date": entities.get("date", ""),
            "time_hint": slot_time or start_time
        }
        logger.info(
            f"Converted vague select_slot to check_availability | "
            f"time_hint='{slot_time or start_time}'"
        )
```

### Fase 2: FSM - CHECK_AVAILABILITY no avanza la máquina de estados

**Cambio 2a**: CHECK_AVAILABILITY es self-loop en SLOT_SELECTION

```python
# En booking_fsm.py, línea 69-72:

BookingState.SLOT_SELECTION: {
    IntentType.SELECT_SLOT: BookingState.CUSTOMER_DATA,
    # ✅ NEW: CHECK_AVAILABILITY stays in SLOT_SELECTION to show options
    IntentType.CHECK_AVAILABILITY: BookingState.SLOT_SELECTION,
    IntentType.CANCEL_BOOKING: BookingState.IDLE,
},
```

### Fase 3: Conversational Agent - Manejar CHECK_AVAILABILITY

**Cambio 3a**: Interceptar CHECK_AVAILABILITY y llamar herramientas automáticamente

```python
# En conversational_agent.py, línea 780-885:

if intent.type == IntentType.CHECK_AVAILABILITY:
    # El usuario pidió ver más opciones
    date_hint = intent.entities.get("date", "")
    time_hint = intent.entities.get("time_hint", "")
    stylist_id = fsm.collected_data.get("stylist_id")

    logger.info(
        f"CHECK_AVAILABILITY detected | date={date_hint} | time_hint={time_hint}",
        extra={"conversation_id": conversation_id}
    )

    # Tool call: check_availability (with natural date parsing)
    if date_hint:
        availability_result = await check_availability.ainvoke({
            "service_category": "Peluquería",  # o detect from collected_data
            "date": date_hint,  # "1 de diciembre" - handled by tool
            "stylist_id": stylist_id,
        })
    else:
        # No date specified - use find_next_available
        availability_result = await find_next_available.ainvoke({
            "service_category": "Peluquería",
            "stylist_id": stylist_id,
            "max_results": 5,
        })

    # Format slots for display
    if availability_result.get("slots"):
        slots = availability_result["slots"][:5]
        # LLM will format these in the response
        fsm_context_for_llm = f"""[OPCIONES DE HORARIOS]
Disponibilidad para {fsm.collected_data.get('stylist_name')} el {date_hint}:

{format_slots_for_display(slots)}

Selecciona el número del horario que te conviene."""
    else:
        fsm_context_for_llm = "[SIN DISPONIBILIDAD] No hay horarios disponibles..."

# FSM state stays in SLOT_SELECTION - NO advancement
# User must now respond with SELECT_SLOT (number or specific time)
```

### Fase 4: Validación de SELECT_SLOT

**Cambio 4a**: SELECT_SLOT requiere validar contra las opciones mostradas

```python
# En intent_extractor.py, agregar validation de que el slot es válido:

if intent_type == IntentType.SELECT_SLOT:
    # Si selection_number está presente, debe ser de la lista mostrada
    selection_number = entities.get("selection_number")
    if selection_number:
        # Validar que el número está en rango
        # (Esto ya lo hace indirectamente el contexto, pero podemos ser explícitos)
        pass

    # Si start_time está presente, debe ser ISO 8601 con timezone
    start_time = entities.get("start_time")
    if start_time:
        # Ensure proper timezone format
        start_time = _normalize_start_time_timezone(start_time)
        entities["start_time"] = start_time
```

---

## Implementación: Prioridad y Pasos

### Paso 1 (CRÍTICO - Hoy): Intent Extractor Fix
- [ ] Agregar prompt disam biguation para CHECK_AVAILABILITY vs SELECT_SLOT
- [ ] Agregar detección de rangos vagos en post-processing
- [ ] Test: "El 1 de diciembre por la tarde" → CHECK_AVAILABILITY intent

### Paso 2 (CRÍTICO - Hoy): FSM Fix
- [ ] Confirmar que CHECK_AVAILABILITY es self-loop en SLOT_SELECTION
- [ ] Test: FSM no avanza cuando intent es CHECK_AVAILABILITY

### Paso 3 (HOY): Conversational Agent
- [ ] Implementar interceptación de CHECK_AVAILABILITY
- [ ] Llamar automáticamente a check_availability/find_next_available
- [ ] Generar respuesta con opciones numeradas
- [ ] Test: Usuario ve 5 horarios disponibles

### Paso 4 (HOY): Validación End-to-End
- [ ] Test: "El 1 de diciembre por la tarde" → muestra opciones → usuario selecciona
- [ ] Test: "Mañana por la tarde" → muestra opciones
- [ ] Test: "El 3" (número) → SELECT_SLOT directo (sin CHECK_AVAILABILITY)

---

## Testing

### Test Case 1: Rango vago sin fecha
```
Usuario: "Por la tarde"
Esperado: CHECK_AVAILABILITY con time_hint="tarde"
→ find_next_available() con max_results=5
→ Mostrar 5 slots próximos en horas de tarde
```

### Test Case 2: Fecha + rango vago
```
Usuario: "El 1 de diciembre por la tarde"
Esperado: CHECK_AVAILABILITY con date="1 diciembre", time_hint="tarde"
→ check_availability(date="1 diciembre", stylist_id=pilar_id)
→ Mostrar slots disponibles ese día en horas de tarde
→ Usuario selecciona número
```

### Test Case 3: Fecha + hora específica
```
Usuario: "El 1 de diciembre a las 15:00"
Esperado: SELECT_SLOT directo (si 15:00 es válido)
→ FSM avanza a CUSTOMER_DATA
```

### Test Case 4: Número de lista
```
Usuario: [después de ver opciones] "3"
Esperado: SELECT_SLOT con selection_number=3
→ Buscar 3er horario en contexto reciente
→ FSM avanza a CUSTOMER_DATA
```

---

## Notas Finales

**Este bug NO es un "parche fácil"** porque es arquitectónico:
- El intent_extractor no tiene contexto del calendario
- El LLM no puede validar disponibilidad sin herramientas
- El FSM necesita permitir CHECK_AVAILABILITY como estado intermedio

**La solución es alinearse con v4.0 FSM Hybrid**:
- Separar NLU (intent extraction) de validación (herramientas)
- FSM controla el flujo (CHECK_AVAILABILITY → espera → SELECT_SLOT)
- Herramientas validan datos (check_availability antes de SELECT_SLOT)

**Impacto positivo**:
✅ Flujo determinista y testeble
✅ Usuario ve opciones reales antes de confirmar
✅ No hay slots "mágicos" inventados por el LLM
✅ Soporta todos los casos: fechas vagas, rangos, números, etc.
