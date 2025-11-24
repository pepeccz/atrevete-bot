# FSM y LangGraph: Análisis de Armonía - 2025-11-24

## Resumen Ejecutivo

**NO, el sistema de estados de LangGraph y el FSM NO trabajan en armonía completa.** Funcionan en **paralelo con un modelo de "dual persistence"** que introduce problemas arquitectónicos graves:

1. ❌ **Dos sistemas de persistencia independientes** (FSM Redis + LangGraph AsyncRedisSaver)
2. ❌ **Potencial de divergencia** entre el estado FSM y el checkpoint de LangGraph
3. ✅ **Workaround temporal en ADR-010** mediante synchronous flush (tratamiento de síntoma, no solución)
4. ⚠️ **ADR-011 propone consolidación** a única fuente de verdad (solución permanente, pendiente de implementación)

---

## 1. Arquitectura Actual: Dual Persistence

### 1.1 Dos Sistemas Independientes

```
Incoming Message
    ↓
LangGraph StateGraph
    ├─ PERSISTED: ConversationState → AsyncRedisSaver (checkpoint_writes)
    │   Fields: conversation_id, messages, customer_id, slot_selected, etc.
    │   TTL: 15 minutos (AsyncRedisSaver default)
    │   Escritura: ASINCRÓNICA en background
    │
    ├─ conversational_agent node ejecuta
    │   ├─ Carga FSM desde Redis (fsm:{conversation_id})
    │   ├─ Procesa intención
    │   ├─ FSM.transition() valida y cambia estado
    │   └─ FSM.persist() → Redis (fsm:{conversation_id})
    │       ├─ Escritura: SÍNCRONA (await client.set())
    │       ├─ TTL: 24 horas
    │       └─ Almacena: {"state": "...", "collected_data": {...}}
    │
    └─ Retorna estado actualizado a LangGraph
        └─ LangGraph guarda checkpoint ASINCRÓNICO

Problema: FSM y checkpoint pueden divergir si:
- Usuario envía mensaje rápido (antes de que checkpoint se escriba)
- Carga FSM desde Redis key pero checkpoint es stale
- FSM transición es rechazada porque checkpoint tiene state antiguo
```

### 1.2 Tabla Comparativa

| Aspecto | LangGraph Checkpoint | FSM Redis |
|--------|---------------------|-----------|
| **Clave Redis** | `langchain:checkpoint:*` | `fsm:{conversation_id}` |
| **Contenido** | ConversationState completo | {"state": "...", "collected_data": {...}} |
| **Persistencia** | AsyncRedisSaver (async) | JSON string directo (sync await) |
| **TTL** | 15 minutos | 24 horas |
| **Lectura en conversational_agent** | Cargado automáticamente por LangGraph | Manual: `BookingFSM.load()` |
| **Escritura en conversational_agent** | Automática tras retorno del nodo | Manual: `fsm.persist()` |
| **Fuente de Verdad para Intent** | ConversationState.messages | FSM state + collected_data |

---

## 2. Cómo Debería Funcionar (Armonía Completa)

```
┌─────────────────────────────────────────────────────────────┐
│         ÚNICA FUENTE DE VERDAD (Propuesto ADR-011)         │
├─────────────────────────────────────────────────────────────┤
│                  LangGraph Checkpoint                       │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ ConversationState (20 fields)                          │ │
│  ├────────────────────────────────────────────────────────┤ │
│  │ - messages: [...]                                      │ │
│  │ - customer_id, customer_phone, conversation_id         │ │
│  │ - FSM STATE (NEW): {                                   │ │
│  │     state: "SLOT_SELECTION"                            │ │
│  │     collected_data: {...}                              │ │
│  │     last_updated: "2025-11-24T..."                     │ │
│  │   }                                                     │ │
│  │ - (otros campos v3.2)                                  │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│ Escritura: AsyncRedisSaver (una única vez, consistente)    │
│ Lectura: conversational_agent deserialia FSM del checkpoint │
└─────────────────────────────────────────────────────────────┘
```

**En este modelo:**
- FSM no es más una "cosa separada en Redis"
- Es un campo dentro de ConversationState (como `messages` o `customer_id`)
- Garantía: Cuando LangGraph carga checkpoint, FSM está siempre sincronizado
- No hay carrera entre dos escrituras asincrónicas

---

## 3. Cómo Funciona Ahora (Realidad Actual)

### 3.1 Flujo Step-by-Step

```
Message: "Quiero una cita para el viernes a las 14:00"

1️⃣  agent/main.py → subscribe_to_incoming_messages()
    └─ Publica a incoming_messages channel
       Inicia graph.ainvoke() con thread_id=conversation_id

2️⃣  agent/graphs/conversation_flow.py
    └─ LangGraph carga checkpoint anterior (si existe)
       ConversationState actual = estado en AsyncRedisSaver

3️⃣  conversational_agent.py → conversational_agent() node
    ┌─ PASO 0: Carga FSM separadamente
    │  fsm = await BookingFSM.load(conversation_id)
    │  → Lee desde Redis key fsm:conversation_id
    │  ✅ Aplica _validate_and_clean_slot() (ADR-008)
    │  → Estado FSM puede estar DIFERENTE de ConversationState
    │
    ├─ PASO 1: Extrae intención (state-aware)
    │  intent = await extract_intent(
    │      message=user_message,
    │      current_state=fsm.state,        ← FSM state (no ConversationState)
    │      collected_data=fsm.collected_data ← FSM data (no ConversationState)
    │  )
    │
    ├─ PASO 2: FSM valida transición
    │  fsm_result = fsm.transition(intent)
    │  if fsm_result.success:
    │      fsm.state = SLOT_SELECTION
    │
    ├─ PASO 3: Ejecuta herramientas si FSM aprueba
    │  Si FSM permite, llama check_availability(), find_next_available(), etc.
    │
    ├─ PASO 4: Persiste FSM (SÍNCRONO)
    │  await fsm.persist()  ← Escribe Redis key fsm:conversation_id
    │                       ← BLOQUEA hasta escribir (pero no garantiza fsync)
    │
    └─ PASO 5: Retorna response al nodo
       return {"messages": [...], ...}

4️⃣  agent/main.py → Checkpoint flush (ADR-010 workaround)
    └─ await asyncio.sleep(0)        ← Yield to event loop
       await asyncio.sleep(0.1)      ← Wait for Redis fsync
       └─ LangGraph escribe checkpoint de forma asincrónica
          AsyncRedisSaver persiste ConversationState

🚨 PROBLEMA: Dos escrituras asincrónicas no coordinadas
   - FSM se persiste "antes" (await en línea 814, 846, 867)
   - Checkpoint se persiste "después" (background en main.py)
   - Pero si usuario envía mensaje en ~100ms, puede cargar FSM stale

5️⃣  Próximo mensaje llega rápido (~500ms)
    └─ graph.ainvoke() carga checkpoint (puede estar stale)
       FSM.load() carga Redis key (probablemente OK)
       ⚠️ Pero si checkpoint aún no se escribió... divergencia
```

### 3.2 Timeline de la Carrera (Race Condition)

```
T=0ms     Usuario dice: "Quiero viernes a las 14:00"
          Mensaje publicado a incoming_messages

T=50ms    graph.ainvoke() inicia
          LangGraph carga checkpoint T-1

T=100ms   conversational_agent node ejecuta
          fsm.persist() → Redis (SÍNCRONO await)
          FSM state actualizado en fsm:conversation_id

T=150ms   conversational_agent retorna
          estado = {"messages": [...], "slot_selected": {...}}

T=200ms   En main.py: await asyncio.sleep(0.1)
          AsyncRedisSaver escribe checkpoint en background
          ← ESTO NO HA COMPLETADO AÚN

T=250ms   Usuario envía: "Confirma mi cita"
          Mensaje publicado a incoming_messages

T=300ms   graph.ainvoke() inicia NUEVO
          LangGraph carga checkpoint
          ⚠️ SI CHECKPOINT AÚNTIENE ESTADO T-1:
             - ConversationState.slot_selected = OLD
             - Pero fsm:conversation_id = NEW (persistido en T=100ms)
             DIVERGENCIA ❌

T=350ms   conversational_agent carga FSM
          fsm = await BookingFSM.load() → Lee fsm:conversation_id NUEVO ✅
          Pero ConversationState en LangGraph es VIEJO ❌

T=400ms   Intent extraction usa fsm.state (CORRECTO)
          Pero conversational_agent también usa ConversationState (VIEJO)
          Posible conflicto o confusión en logic
```

---

## 4. Impacto Real: ¿Qué Falla?

### 4.1 Escenarios Problemáticos

**Escenario 1: Transición FSM rechazada con "stale checkpoint"**
```
Estado Real FSM:       SLOT_SELECTION (acaba de transicionar)
Estado en Checkpoint:  CUSTOMER_DATA (viejo)

Usuario envía rápido:  "Confirma mi cita"
Intención extraída:    CONFIRM_BOOKING
FSM.transition():      CUSTOMER_DATA → BOOKED rechazado ❌
                       (La transición no existe en TRANSITIONS tabla)

Error: FSM state CUSTOMER_DATA cannot transition on CONFIRM_BOOKING
```

### 4.2 Síntomas Observados (Por Qué Creaste ADR-010)

De los logs recientes:
```
[FSM transition REJECTED]
[state=CUSTOMER_DATA, intent=CONFIRM_BOOKING]
[message: "La transición no es válida"]
```

Causa raíz: El checkpoint había sido cargado en CUSTOMER_DATA (viejo)
cuando FSM había ya avanzado a SLOT_SELECTION (nuevo).

---

## 5. Soluciones Implementadas vs Permanentes

### 5.1 ADR-010: Synchronous Checkpoint Flush (Workaround)

**Qué hace:**
```python
# En agent/main.py líneas 146-178
result = await graph.ainvoke(state, config=config)

# ADR-010 workaround:
await asyncio.sleep(0)      # Yield control
await asyncio.sleep(0.1)    # Espera a que fsync complete en Redis
```

**Por qué NO es solución permanente:**
- ❌ No elimina el problema, solo reduce su frecuencia
- ❌ Agrega latencia artificial (100ms por mensaje)
- ❌ Dos sistemas aún persisten de forma independiente
- ❌ El 0.1s es arbitrario (podría no ser suficiente en carga alta)
- ✅ Es un alivio temporal mientras se implementa ADR-011

### 5.2 ADR-011: Single Source of Truth (Solución Permanente)

**Propuesta:** Consolidar FSM dentro de ConversationState

```python
# En agent/state/schemas.py (nueva estructura)
class ConversationState(TypedDict):
    # ... campos existentes ...

    # NEW: Consolidated FSM state
    fsm_state: dict[str, Any] = {
        "state": "SLOT_SELECTION",              # BookingState.SLOT_SELECTION.value
        "collected_data": {
            "services": ["CORTE LARGO"],
            "stylist_id": "001",
            "slot": {"start_time": "...", "duration": 30},
            "first_name": "María"
        },
        "last_updated": "2025-11-24T10:30:00+01:00"
    }
```

**Implementación:**

```python
# En conversational_agent.py
async def conversational_agent(state: ConversationState) -> dict:
    conversation_id = state["conversation_id"]

    # ANTES (ADR-010):
    # fsm = await BookingFSM.load(conversation_id)  ← Lee de Redis separado

    # DESPUÉS (ADR-011):
    fsm_data = state.get("fsm_state", {})
    fsm = BookingFSM.from_dict(conversation_id, fsm_data)  ← Deserialize from state

    # ... lógica igual ...

    # Procesa intención, transición, etc.

    # PERSISTE (única fuente):
    state["fsm_state"] = fsm.to_dict()  ← Serialize back to state
    return state  ← LangGraph persiste TODO en checkpoint (una sola escritura)
```

**Ventajas:**
- ✅ Una sola fuente de verdad (LangGraph checkpoint)
- ✅ Elimina carrera entre dos sistemas
- ✅ Consistencia garantizada: cuando carga checkpoint, FSM está en sync
- ✅ Reduce latencia (sin necesidad de sleep(0.1))
- ✅ Debuggeable: ver FSM state en checkpoint visualizers

---

## 6. Status Actual: Armonía Parcial

### 6.1 Lo Que Funciona ✅

1. **FSM valida intenciones correctamente** (intent_extractor.py mejorado)
   - Distingue "tarde" (CHECK_AVAILABILITY) de "15:00" (SELECT_SLOT)
   - State-aware intent extraction usando fsm.state

2. **FSM limpia slots obsoletos** (booking_fsm.py mejorado)
   - Detecta y limpia slots con fechas en el pasado
   - Reseta a SLOT_SELECTION si slot viola 3-día rule

3. **Errores son manejados mejor** (conversational_agent.py mejorado)
   - DATE_TOO_SOON resetea FSM y limpia slot
   - Response validator checks FSM state coherence

4. **Checkpoint flush reduce incidentes** (main.py ADR-010)
   - 0.1s delay reduce pero NO elimina race condition
   - 80% menos transiciones rechazadas (estimado)

### 6.2 Lo Que Aún Es Problemático ❌

1. **Dual Persistence sigue existiendo**
   - FSM en fsm:{conversation_id}
   - Checkpoint en checkpoint_writes:*
   - Dos escrituras asincrónicas no coordinadas

2. **Divergencia sigue siendo posible**
   - Si usuario envía 2+ mensajes rápido (<100ms)
   - Checkpoint puede estar stale respecto a FSM

3. **Sin garantías formales de sincronización**
   - "Sleep 0.1s" es heurística, no garantía
   - Bajo carga alta o network latency, insuficiente

4. **Complejidad arquitectónica**
   - Nodo debe cargar FSM manualmente desde Redis
   - ConversationState no incluye FSM state
   - Dos "fuentes de verdad" (confuso para mantenimiento)

---

## 7. Hoja de Ruta: Cuando Se Implementa ADR-011

### Phase 1: Preparación (1-2 semanas)
- [ ] Agregar `to_dict()` y `from_dict()` a BookingFSM
- [ ] Actualizar conversational_agent para usar dual-read (fallback)
- [ ] Agregar `fsm_state` field a ConversationState

### Phase 2: Validación (1-2 semanas)
- [ ] Canary deployment con 10% tráfico
- [ ] Logging divergence detection
- [ ] Monitor para transiciones rechazadas

### Phase 3: Migración de Datos (1 día)
- [ ] Script para rellenar `fsm_state` en checkpoints existentes
- [ ] Validar datos migrados

### Phase 4: Cutover (1 día)
- [ ] Remover `fsm:{conversation_id}` Redis keys
- [ ] Remover `BookingFSM.load()` call separado
- [ ] Limpiar código de dual-persistence

### Phase 5: Optimización (1 semana)
- [ ] Reducir tamaño checkpoint (comprensión)
- [ ] Ajustar TTL a 24h (alineado con FSM)
- [ ] Performance testing bajo carga

**Timeline total:** 6 semanas (scheduled Epic 6)

---

## 8. Conclusión: Respuesta a tu pregunta

### ¿Trabajan en armonía?

```
Respuesta corta: No, todavía no.

Respuesta larga:

✅ MEJOR QUE ANTES:
   - Intent extractor es más inteligente (vague terms)
   - FSM valida y limpia slots obsoletos
   - Error handling es más robusto
   - Synchronous flush (ADR-010) reduce incidentes

❌ AÚNNO PERFECTO:
   - Dual persistence sigue existiendo
   - Race conditions aún posibles (aunque raras con ADR-010)
   - No hay garantía formal de sincronización
   - Arquitectura es "parcialmente armoniosa"

✨ PRÓXIMO PASO (ADR-011):
   - Consolidar FSM dentro de ConversationState
   - Una sola fuente de verdad (LangGraph checkpoint)
   - Armonía COMPLETA
   - Scheduled Epic 6
```

### Diagnóstico Técnico

El sistema actual está en un estado de **transición arquitectónica**:

- **v3.2 (Actual):** LLM-driven con herramientas, FSM como co-sistema independiente
- **v4.0 (Target):** FSM-driven con LLM para NLU, FSM integrado en checkpoint

Los cambios de Epic 5 (commit 3366117) movieron el sistema más cerca de v4.0:
- Mejoró intent extraction (FSM aware)
- Mejoró FSM validations (slot freshness)
- Mejoró error handling (FSM state resets)

Pero la arquitectura fundamental sigue siendo dual-persistence. ADR-011 propone consolidar a una única fuente, completando la migración a v4.0 híbrida verdadera.

---

## 9. Referencias

- **ADR-010:** Synchronous Checkpoint Flush (workaround implementado)
- **ADR-011:** Single Source of Truth Migration (propuesta, pendiente)
- **Epic 5:** FSM Bug Fixes (commit 3366117) ✅ completado
- **Epic 6:** FSM-LangGraph Consolidation (pendiente)

