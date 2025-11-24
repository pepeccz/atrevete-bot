# ANÁLISIS: Bug de Selección de Disponibilidad (Slot Selection)

## El Problema en 2 Líneas

El usuario dice **"El 1 de diciembre por la tarde"** → Bot interpreta esto como un **horario específico (15:00)** en lugar de una **solicitud para VER OPCIONES** → Bot **avanza sin mostrar ningún horario disponible real**.

---

## Qué Salió Mal

### ❌ Flujo Actual (v3.2 LLM-Driven):
```
Usuario: "El 1 de diciembre por la tarde"
    ↓ (Intent Extractor - sin acceso a calendario)
Interpreta: SELECT_SLOT intent con start_time="2024-12-01T15:00:00"
    ↓ (FSM valida sintácticamente)
FSM avanza: SLOT_SELECTION → CUSTOMER_DATA
    ↓
Bot pregunta: "Para poder mostrarte los horarios necesito tu nombre..."
    ↓
PROBLEMA: Usuario NUNCA vio opciones disponibles reales
         El horario "15:00" fue adivinado por el LLM
         Sin validar que existe en el calendario
```

### ✅ Flujo Deseado (v4.0 FSM Hybrid):
```
Usuario: "El 1 de diciembre por la tarde"
    ↓ (Intent Extractor - detecta rango vago)
Interpreta: CHECK_AVAILABILITY intent (request para ver opciones)
    ↓ (FSM permite self-loop en SLOT_SELECTION)
Bot llama: check_availability(date="1 diciembre", stylist_id=pilar)
    ↓ (Herramientas consultan calendario REAL)
Bot muestra: 5 horarios disponibles esa tarde
    - 1. Domingo 1 de diciembre - 14:00
    - 2. Domingo 1 de diciembre - 15:30
    - 3. Domingo 1 de diciembre - 17:00
    - ...
    ↓
Usuario selecciona: "el 2"
    ↓
FSM transición: SLOT_SELECTION → CUSTOMER_DATA (ahora SÍ)
    ↓
CORRECTO: Usuario confirmó un horario real
```

---

## Las 3 Causas Raíz

### 1️⃣ Intent Extractor no distingue entre:
- **CHECK_AVAILABILITY**: "El 1 de diciembre **por la tarde**" (rango vago - PEDIR opciones)
- **SELECT_SLOT**: "El 1 de diciembre **a las 15:00**" (hora específica - CONFIRMAR opción)

**El LLM está convirtiendo "tarde" → "15:00" sin validación.**

### 2️⃣ El LLM no tiene acceso al calendario para validar
- Intent Extractor = solo NLU, sin herramientas
- El LLM "adivina" qué hora querría el usuario
- Nunca verifica que esa hora existe en Google Calendar

### 3️⃣ FSM avanza sin validar si el slot existe realmente
- FSM valida SINTÁCTICAMENTE: ¿tiene los campos necesarios? ✓
- FSM NO valida SEMÁNTICAMENTE: ¿existe ese slot en el calendario? ✗

---

## Cómo Se Vería La Solución (4 Pasos)

### Paso 1: Intent Extractor - Distinguir rangos vagos
```python
# Agregar al prompt:
"Si usuario dice rango vago (tarde, mañana, etc.) SIN hora específica
 → intent: CHECK_AVAILABILITY (no SELECT_SLOT)"

# Agregar post-processing:
if "tarde" in start_time or "mañana" in start_time:
    intent_type = CHECK_AVAILABILITY  # Cambiar de SELECT_SLOT
```

### Paso 2: FSM - CHECK_AVAILABILITY es self-loop
```python
BookingState.SLOT_SELECTION: {
    SELECT_SLOT: BookingState.CUSTOMER_DATA,  # Existente
    CHECK_AVAILABILITY: BookingState.SLOT_SELECTION,  # ← NUEVO: no avanza
}
```

### Paso 3: Conversational Agent - Llamar herramientas automáticamente
```python
if intent.type == CHECK_AVAILABILITY:
    # Llamar check_availability o find_next_available
    slots = await check_availability(date="1 diciembre", stylist_id=pilar)

    # Mostrar slots en lista numerada
    response = format_slots(slots)  # "1. 14:00  2. 15:30  ..."
    # FSM state sigue en SLOT_SELECTION
```

### Paso 4: Usuario selecciona
```
Usuario: "el 2"
→ Intent: SELECT_SLOT (del contexto reciente, del slot #2)
→ FSM avanza: SLOT_SELECTION → CUSTOMER_DATA
→ ✓ Correcto, ahora SÍ seleccionó un horario validado
```

---

## Por Qué es "Raíz" y No "Parche"

**Esto es exactamente lo que v4.0 está diseñado a resolver:**

El CLAUDE.md dice:
> "El sistema está migrando de arquitectura **LLM-driven (v3.2) a FSM Hybrid (v4.0)**.
> La arquitectura LLM-driven producía bugs sistemáticos porque el **LLM controlaba flujo** además de NLU."

Este bug de disponibilidad es **ese patrón exacto**:
- ❌ LLM intenta controlar flujo (SELECT_SLOT sin validar)
- ❌ Sin acceso a datos reales (calendario)
- ❌ Sin herramientas de validación
- ✅ FSM Hybrid: LLM = NLU solamente, FSM = control de flujo, Herramientas = validación

---

## Archivo de Análisis Completo

Ver: `/home/pepe/atrevete-bot/docs/analysis-slot-selection-bug-2025-11-24.md`

Contiene:
- Diagrama completo del flujo
- Código exacto de los 4 cambios necesarios
- Test cases para validar la solución
- Impacto arquitectónico
