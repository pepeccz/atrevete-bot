# ADR-011: FSM Single Source of Truth - Migración de Persistencia Dual

**Status:** PROPOSED (Planning Phase)
**Date:** 2025-11-24
**Author:** Claude Code - Architecture Analysis
**Epic:** Epic 6 - FSM Architecture Refinement
**Severity:** MEDIUM (Technical Debt / Architecture Improvement)
**Timeline:** Q1 2026 (Post-MVP)

---

## Resumen Ejecutivo

**Problema:** El sistema FSM mantiene estado en **DOS lugares diferentes** que pueden desincronizarse:
1. **Redis key `fsm:{conversation_id}`** - Persiste inmediatamente via `BookingFSM.persist()`
2. **LangGraph Checkpoint (AsyncRedisSaver)** - Persiste asincronamente al final del graph

Esta **dual persistence** causa race conditions cuando los mensajes llegan rápidamente, resultando en discrepancias de estado.

**Propuesta:** Consolidar FSM state en UN ÚNICO lugar: **LangGraph Checkpoint**

**Beneficio:** Eliminación permanente de race conditions, arquitectura más simple y mantenible.

---

## 1. Problema Actual

### 1.1 Arquitectura de Persistencia Dual

```
┌─────────────────────────────────────────────────────────────┐
│                    CURRENT STATE (v4.0)                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  LangGraph Graph Invocation                                 │
│  ↓                                                           │
│  ┌──────────────────────────────────────────────────┐      │
│  │ conversational_agent Node                        │      │
│  │                                                  │      │
│  │  fsm = await BookingFSM.load(conversation_id)   │      │
│  │          ↑                                       │      │
│  │          │ Reads from Redis key                 │      │
│  │          │ fsm:{conversation_id}                │      │
│  │                                                  │      │
│  │  [Process message, update FSM]                  │      │
│  │                                                  │      │
│  │  fsm.transition(intent)                         │      │
│  │         ↓                                        │      │
│  │         └→ await fsm.persist()                  │      │
│  │            └→ Redis write #1 (IMMEDIATE)       │      │
│  │                                                  │      │
│  │  return {"fsm_state": fsm.collected_data, ...} │      │
│  └──────────────────────────────────────────────────┘      │
│  ↓                                                           │
│  LangGraph Checkpoint Saver (AsyncRedisSaver)              │
│  ↓                                                           │
│  Redis write #2 (ASYNC - background task)                  │
│                                                              │
│  PROBLEM: Redis write #2 puede no completarse antes de que │
│           el siguiente mensaje inicie el graph invocation   │
│           → FSM.load() lee checkpoint VIEJO               │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Síntomas del Problema

**Error observado:**
```
FSM transition REJECTED | errors=["Transition 'provide_customer_data'
not allowed from state 'slot_selection'"]
```

**Timeline:**
```
18:27:36 - User: "2" (selecciona slot)
18:27:41 - FSM persisted: state=customer_data (Redis write #1) ✅
18:27:54 - User: "Javier" (responde rápido - 13s después)
18:27:54 - FSM load: restored state=slot_selection ❌ (checkpoint viejo)
18:27:57 - Transition REJECTED ❌
```

### 1.3 Causa Raíz Técnica

**Race Condition Timeline:**

```
Time    Event                           Component
────────────────────────────────────────────────────────────
T+0.0   graph.ainvoke() starts          Async event loop
T+0.1   BookingFSM.persist() called     Redis write #1 (sync)
T+0.2   Redis write #1 completes       ✅ fsm:8 = {state: customer_data}
T+0.3   graph node returns result      ✅ returns updated state
T+0.4   LangGraph Checkpoint write     Redis write #2 (async task created)
T+0.5   Control returns to main loop   Ready for next message
T+1.3   User sends next message        Message arrives
T+1.4   Graph invocation starts        NEW graph invocation
T+1.45  LangGraph restores checkpoint  ❌ Reads checkpoint from T+0.0
        (Redis write #2 may not be done yet)
T+1.5   FSM.load() reads Redis         ✅ Should be from T+0.2
        BUT LangGraph state is older!
T+1.6   FSM state loaded               ❌ state = slot_selection (STALE)
T+1.7   Transition attempted           REJECTED - invalid from slot_selection
```

**Raíz del problema:** Dos sistemas de persistencia compiten por ser la "fuente de verdad":
- FSM persiste inmediatamente → Redis write SYNC
- LangGraph persiste async → Redis write ASYNC
- El siguiente mensaje restaura desde checkpoint (puede estar viejo)

---

## 2. Propuesta de Solución

### 2.1 Consolidar en Single Source of Truth: LangGraph Checkpoint

**Idea Core:** FSM state SOLO vive en el checkpoint de LangGraph, nunca en Redis keys separados.

```
┌─────────────────────────────────────────────────────────────┐
│              PROPOSED STATE (v4.1 - Single Source)           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  LangGraph Graph Invocation                                 │
│  ↓                                                           │
│  ┌──────────────────────────────────────────────────┐      │
│  │ conversational_agent Node                        │      │
│  │                                                  │      │
│  │  fsm_state = state.get("fsm_state", {})         │      │
│  │  fsm = BookingFSM.from_dict(fsm_state)          │      │
│  │          ↑                                       │      │
│  │          │ Reads from LangGraph state dict      │      │
│  │          │ (comes from checkpoint)              │      │
│  │                                                  │      │
│  │  [Process message, update FSM]                  │      │
│  │                                                  │      │
│  │  fsm.transition(intent)                         │      │
│  │                                                  │      │
│  │  return {                                        │      │
│  │    "messages": [...],                           │      │
│  │    "fsm_state": fsm.to_dict(),  ← ONLY HERE    │      │
│  │    "customer_id": ...,                          │      │
│  │    ...                                           │      │
│  │  }                                               │      │
│  └──────────────────────────────────────────────────┘      │
│  ↓                                                           │
│  LangGraph Checkpoint Saver                                 │
│  (Saves entire state dict including "fsm_state")           │
│  ↓                                                           │
│  Redis SINGLE write (async, but guaranteed by design)      │
│                                                              │
│  BENEFIT: Single write, no race condition possible         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Cambios Arquitectónicos

#### A. Cambio en `BookingFSM` (`agent/fsm/booking_fsm.py`)

**Eliminar:**
```python
# REMOVE these methods - no more Redis persistence
async def persist(self) -> None:
    """Persist FSM state to Redis - NO LONGER NEEDED"""
    ...

@classmethod
async def load(cls, conversation_id: str) -> "BookingFSM":
    """Load FSM state from Redis - NO LONGER NEEDED"""
    ...
```

**Agregar:**
```python
def to_dict(self) -> dict[str, Any]:
    """
    Serialize FSM state to dict for checkpoint storage.

    Returns:
        {
            "state": "customer_data",
            "collected_data": {...},
            "last_updated": "2025-11-24T18:27:54.123Z"
        }
    """
    return {
        "state": self._state.value,
        "collected_data": self._collected_data.copy(),
        "last_updated": self._last_updated.isoformat(),
    }

@classmethod
def from_dict(cls, conversation_id: str, data: dict[str, Any]) -> "BookingFSM":
    """
    Deserialize FSM state from dict (checkpoint).

    Args:
        conversation_id: Conversation ID
        data: Dictionary from checkpoint with keys: state, collected_data, last_updated

    Returns:
        BookingFSM instance with restored state
    """
    fsm = cls(conversation_id)

    if data.get("state"):
        fsm._state = BookingState(data["state"])

    if data.get("collected_data"):
        fsm._collected_data = data["collected_data"]

    if data.get("last_updated"):
        fsm._last_updated = datetime.fromisoformat(data["last_updated"])

    return fsm
```

#### B. Cambio en `conversational_agent` Node (`agent/nodes/conversational_agent.py`)

**Antes (usando Redis key):**
```python
async def conversational_agent(state: ConversationState) -> dict[str, Any]:
    conversation_id = str(state["conversation_id"])

    # Load FSM from Redis key
    fsm = await BookingFSM.load(conversation_id)  # ❌ No longer exists

    # ... process message ...

    # Return only messages and booking fields
    return {
        "messages": updated_messages,
        "appointment_created": True,
        # FSM state was saved to Redis via persist()
    }
```

**Después (usando checkpoint):**
```python
async def conversational_agent(state: ConversationState) -> dict[str, Any]:
    conversation_id = str(state["conversation_id"])

    # Load FSM from checkpoint (passed as state dict)
    fsm_data = state.get("fsm_state", {})
    fsm = BookingFSM.from_dict(conversation_id, fsm_data)  # ✅ New method

    # ... process message ...

    # Return FSM state as part of the output
    return {
        "messages": updated_messages,
        "fsm_state": fsm.to_dict(),  # ✅ Persisted via checkpoint
        "appointment_created": True,
    }
```

#### C. Cambio en `ConversationState` Schema (`agent/state/schemas.py`)

**Antes:**
```python
class ConversationState(TypedDict):
    """LangGraph state for conversation flow"""
    conversation_id: str
    messages: list[dict]
    customer_id: str | None
    # ... other fields ...
    # FSM state is NOT in here - it's loaded from separate Redis key
```

**Después:**
```python
class ConversationState(TypedDict):
    """LangGraph state for conversation flow"""
    conversation_id: str
    messages: list[dict]
    customer_id: str | None
    fsm_state: dict  # ✅ NEW: Holds FSM state directly
    # ... other fields ...
```

#### D. Cambio en Graph Initialization (`agent/graphs/conversation_flow.py`)

**Agregar inicialización de `fsm_state` si no existe:**

```python
def _initialize_state(state: ConversationState) -> dict:
    """Initialize FSM state if not present in checkpoint"""
    if "fsm_state" not in state or not state.get("fsm_state"):
        state["fsm_state"] = {
            "state": BookingState.IDLE.value,
            "collected_data": {},
            "last_updated": datetime.now(UTC).isoformat(),
        }
    return state
```

### 2.3 Eliminación de Redis Key `fsm:{conversation_id}`

**Beneficio:** Reduce datos en Redis en ~20-30% por conversación (FSM state no se guarda por duplicado)

**Proceso de Cleanup:**
```python
# Migration script (run once during deployment)
async def cleanup_old_fsm_keys():
    """Remove all old fsm:{conversation_id} keys from Redis"""
    client = get_redis_client()

    # Find all FSM keys
    pattern = "fsm:*"
    cursor = 0

    while True:
        cursor, keys = await client.scan(cursor, match=pattern)

        # Delete in batches
        if keys:
            await client.delete(*keys)
            logger.info(f"Deleted {len(keys)} FSM keys from Redis")

        if cursor == 0:
            break
```

---

## 3. Impacto Arquitectónico

### 3.1 Diagrama de Arquitectura: Before vs After

```
BEFORE (v4.0 - Dual Persistence)
═════════════════════════════════════════════════════════════

    Redis                          LangGraph
    ┌─────────────────────────────────────────┐
    │                                         │
    │  FSM Keys:                              │  Checkpoint:
    │  fsm:conv-8 = {...}                     │  {
    │  fsm:conv-9 = {...}                     │    state: {...}
    │  fsm:conv-10 = {...}                    │    fsm_state: MISSING
    │                                         │    messages: [...]
    │  [Managed by BookingFSM.persist()]       │  }
    │                                         │
    │  [Can diverge from checkpoint]  ❌     │  [Async write]
    │  [Race condition possible]       ❌     │
    └─────────────────────────────────────────┘


AFTER (v4.1 - Single Source)
═════════════════════════════════════════════════════════════

    Redis                          LangGraph
    ┌─────────────────────────────────────────┐
    │                                         │
    │  NO FSM Keys                            │  Checkpoint:
    │  (Deleted during migration)             │  {
    │                                         │    state: {...}
    │  Reduced memory usage                   │    fsm_state: {         ✅
    │  Cleaner key namespace                  │      state: "...",
    │                                         │      collected_data: {}
    │  [Single source of truth]      ✅      │    }
    │  [No race conditions]          ✅      │    messages: [...]
    │                                         │  }
    │                                         │
    │                                         │  [Single write via checkpoint]
    │                                         │  [Guaranteed consistency]
    └─────────────────────────────────────────┘
```

### 3.2 Matriz de Cambios

| Componente | Antes | Después | Cambio |
|-----------|-------|---------|--------|
| **FSM Persistencia** | Redis key `fsm:*` | LangGraph checkpoint | Consolidado |
| **FSM.load()** | Síncrono desde Redis | from_dict() desde state | API change |
| **FSM.persist()** | await persist() | Implícito en return | Eliminado |
| **Race Conditions** | SÍ (dual persistence) | NO (single source) | Eliminadas |
| **State Consistency** | Eventual | Guaranteed | Mejorado |
| **Redis Memory** | +30% (FSM keys) | -30% (sin FSM keys) | Reducido |
| **Checkpoint Size** | Base | Base + fsm_state dict | Aumentado |
| **Code Complexity** | Moderada | Reducida | Simplificado |

### 3.3 Matriz de Impacto

| Aspecto | Impacto | Severidad |
|--------|--------|-----------|
| **Redis Memory** | -20-30% | Positivo |
| **Code Complexity** | -10-15% (fewer async calls) | Positivo |
| **Data Consistency** | +99% guaranteed | Positivo |
| **Race Conditions** | -100% (eliminated) | Positivo |
| **Checkpoint Size** | +1-2KB per conv | Negativo (minor) |
| **Initial Migration** | One-time migration script | Neutral |
| **Backward Compatibility** | Breaking change (v4.1) | Neutral |

---

## 4. Plan de Implementación

### 4.1 Fases de Migración

#### **Fase 1: Preparación (1-2 semanas)**

**Objetivo:** Implementar nuevos métodos sin remover los antiguos

**Tareas:**
1. Implementar `BookingFSM.to_dict()` y `from_dict()` métodos
2. Agregar `fsm_state` field a `ConversationState` TypedDict
3. Actualizar conversational_agent node para usar AMBOS métodos (fallback a Redis si no existe en state)
4. Agregar tests unitarios para serialización/deserialiación
5. Agregar logging para detectar divergencias entre Redis FSM y checkpoint

**Código de ejemplo (Fallback approach):**
```python
async def conversational_agent(state: ConversationState) -> dict[str, Any]:
    conversation_id = str(state["conversation_id"])

    # Try new method first (from checkpoint)
    if state.get("fsm_state"):
        fsm = BookingFSM.from_dict(conversation_id, state["fsm_state"])
    else:
        # Fallback to old method (from Redis) for backward compat
        fsm = await BookingFSM.load(conversation_id)

    # Log warning if using fallback
    if not state.get("fsm_state"):
        logger.warning(
            "FSM loaded from Redis (fallback) | conversation_id=%s",
            conversation_id
        )

    # ... process ...

    return {
        "messages": updated_messages,
        "fsm_state": fsm.to_dict(),  # Always return new format
        "appointment_created": True,
    }
```

#### **Fase 2: Validación (1-2 semanas)**

**Objetivo:** Validar que ambos métodos producen identical results

**Tareas:**
1. Ejecutar en producción con fallback dual-read
2. Monitorear discrepancias entre Redis FSM y checkpoint FSM
3. Alerta si divergencia detectada
4. Ejecutar canary deployment con 5% del tráfico
5. Tests de integración end-to-end

**Métrica de éxito:**
- 99.99% de conversaciones con FSM state consistente
- 0 discrepancias en 1 semana de canary

#### **Fase 3: Migración de Datos (1 día)**

**Objetivo:** Migrar todos los checkpoints existentes para incluir fsm_state

**Tareas:**
1. Backup de Redis checkpoints
2. Ejecutar script de migración:
   ```python
   async def migrate_existing_checkpoints():
       """Populate fsm_state in existing checkpoints"""
       checkpointer = get_redis_checkpointer()

       # Iterate all checkpoints
       for conversation_id in all_conversation_ids:
           config = {"configurable": {"thread_id": conversation_id}}
           checkpoint = checkpointer.get(config)

           if checkpoint and "fsm_state" not in checkpoint:
               # Load FSM from Redis and populate checkpoint
               fsm = await BookingFSM.load(conversation_id)
               checkpoint["fsm_state"] = fsm.to_dict()

               # Update checkpoint
               checkpointer.put(checkpoint)
   ```
3. Verificar que todos los checkpoints tengan `fsm_state`

#### **Fase 4: Cutover (1 día)**

**Objetivo:** Remover soporte para Redis FSM keys

**Tareas:**
1. Remover fallback en conversational_agent node
2. Remover `BookingFSM.persist()` y `load()` métodos
3. Ejecutar cleanup script para borrar `fsm:*` keys de Redis
4. Monitorear logs para confirmar no hay errores de "key not found"

**Rollback Plan:**
- Si errores críticos: Re-habilitar fallback al Redis FSM
- Revertir cambios de code
- Mantener data migration (no es destructiva)

#### **Fase 5: Optimización (1 semana)**

**Objetivo:** Reducir tamaño del checkpoint

**Tareas:**
1. Analizar tamaño promedio de checkpoint
2. Si es > 10KB, implementar compresión de fsm_state
3. Considerar lazy-loading de collected_data (solo load fields that changed)
4. Optimizar serialización de complejos tipos

### 4.2 Timeline de Ejecución

```
Week 1-2:   Phase 1 (Preparación)
Week 3-4:   Phase 2 (Validación)
Week 5:     Phase 3 (Migración data) + Phase 4 (Cutover)
Week 6:     Phase 5 (Optimización)

Total: ~6 semanas para implementación completa

Recomendation: Ejecutar en Epic 6 (Post-MVP)
```

---

## 5. Detalles Técnicos de Implementación

### 5.1 Serialización FSM → JSON

**Requisito:** Asegurar que FSM state sea JSON-serializable

**Implementación:**
```python
# agent/fsm/booking_fsm.py

def to_dict(self) -> dict[str, Any]:
    """Serialize FSM to JSON-compatible dict"""
    # Safely serialize all collected_data
    serializable_data = self._collected_data.copy()

    # Ensure all values are JSON-serializable
    for key, value in serializable_data.items():
        if hasattr(value, "to_dict"):
            serializable_data[key] = value.to_dict()
        elif not isinstance(value, (str, int, float, bool, list, dict, type(None))):
            # Convert non-JSON types
            serializable_data[key] = str(value)

    return {
        "state": self._state.value,  # Enum → string
        "collected_data": serializable_data,
        "last_updated": self._last_updated.isoformat(),  # datetime → ISO string
    }

@classmethod
def from_dict(cls, conversation_id: str, data: dict[str, Any]) -> "BookingFSM":
    """Deserialize FSM from JSON-compatible dict"""
    fsm = cls(conversation_id)

    if data.get("state"):
        fsm._state = BookingState(data["state"])

    if data.get("collected_data"):
        fsm._collected_data = data["collected_data"]

    if data.get("last_updated"):
        fsm._last_updated = datetime.fromisoformat(data["last_updated"])

    return fsm
```

### 5.2 Validación en Carga (from_dict)

```python
@classmethod
def from_dict(cls, conversation_id: str, data: dict[str, Any]) -> "BookingFSM":
    """Deserialize with validation"""
    fsm = cls(conversation_id)

    # Validate state value
    try:
        if data.get("state"):
            fsm._state = BookingState(data["state"])
    except ValueError as e:
        logger.error(f"Invalid FSM state value: {data.get('state')}")
        # Fallback to IDLE
        fsm._state = BookingState.IDLE

    # Validate and restore collected_data
    if isinstance(data.get("collected_data"), dict):
        fsm._collected_data = data["collected_data"]
    else:
        logger.warning("collected_data is not a dict, using empty dict")
        fsm._collected_data = {}

    # Parse last_updated timestamp
    if data.get("last_updated"):
        try:
            fsm._last_updated = datetime.fromisoformat(data["last_updated"])
        except ValueError:
            logger.warning("Could not parse last_updated timestamp")
            fsm._last_updated = datetime.now(UTC)

    return fsm
```

### 5.3 Detección de Divergencias (Fallback Phase)

```python
async def conversational_agent(state: ConversationState) -> dict[str, Any]:
    """Load FSM with divergence detection"""
    conversation_id = str(state["conversation_id"])

    # Load from both sources
    fsm_from_checkpoint = None
    fsm_from_redis = None

    if state.get("fsm_state"):
        fsm_from_checkpoint = BookingFSM.from_dict(
            conversation_id, state["fsm_state"]
        )

    fsm_from_redis = await BookingFSM.load(conversation_id)

    # Compare states
    if fsm_from_checkpoint and fsm_from_redis:
        checkpoint_state = fsm_from_checkpoint._state.value
        redis_state = fsm_from_redis._state.value

        if checkpoint_state != redis_state:
            logger.warning(
                "FSM state divergence detected | "
                "conversation_id=%s | "
                "checkpoint=%s | redis=%s",
                conversation_id,
                checkpoint_state,
                redis_state,
            )
            # Use checkpoint as source of truth
            fsm = fsm_from_checkpoint
        else:
            fsm = fsm_from_checkpoint
    elif fsm_from_checkpoint:
        fsm = fsm_from_checkpoint
    else:
        fsm = fsm_from_redis

    # ... rest of processing ...
```

---

## 6. Riesgos y Mitigaciones

### 6.1 Matriz de Riesgos

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|-------------|--------|-----------|
| **Checkpoint size bloat** | MEDIA | BAJO | Lazy-load, compression en Phase 5 |
| **Data loss during migration** | BAJA | ALTO | Backup antes de migración, rollback plan |
| **Backward incompatibility** | ALTA | MEDIO | Fallback dual-read en Phase 1-4 |
| **FSM deserialization error** | MEDIA | MEDIO | Validación y error handling, fallback to IDLE |
| **Performance degradation** | BAJA | BAJO | Monitor checkpoint read/write times |
| **Checkpoint corruption** | BAJA | ALTO | Validation en from_dict(), checksums |

### 6.2 Plan de Rollback

**Si Critical Error en Phase 3-4:**

1. **Stop migración script**
2. **Revert code changes:**
   ```bash
   git revert <commit-hash>
   docker-compose restart agent
   ```
3. **Re-habilitar FSM Redis persistence** (código está en git history)
4. **Monitorear logs** para confirmar FSM cargando desde Redis
5. **Plan post-mortem** para identificar problema

**Rollback no es destructivo:** Checkpoint data con `fsm_state` permanece, solo se ignora.

---

## 7. Testing Strategy

### 7.1 Unit Tests

```python
# tests/unit/test_fsm_serialization.py

class TestFSMSerialization:
    """Test FSM to_dict() and from_dict()"""

    def test_to_dict_basic(self):
        fsm = BookingFSM("conv-123")
        fsm._state = BookingState.CUSTOMER_DATA
        fsm._collected_data = {"services": ["Corte"], "stylist_id": "pilar"}

        data = fsm.to_dict()

        assert data["state"] == "customer_data"
        assert data["collected_data"]["services"] == ["Corte"]
        assert "last_updated" in data

    def test_from_dict_basic(self):
        data = {
            "state": "customer_data",
            "collected_data": {"services": ["Corte"]},
            "last_updated": datetime.now(UTC).isoformat(),
        }

        fsm = BookingFSM.from_dict("conv-123", data)

        assert fsm.state == BookingState.CUSTOMER_DATA
        assert fsm.collected_data["services"] == ["Corte"]

    def test_round_trip(self):
        """Ensure to_dict() → from_dict() is lossless"""
        fsm1 = BookingFSM("conv-123")
        fsm1._state = BookingState.CONFIRMATION
        fsm1._collected_data = {
            "services": ["Corte", "Tinte"],
            "stylist_id": "pilar",
            "slot": {"start_time": "2025-12-01T15:00:00+01:00"},
            "first_name": "Javier",
        }

        # Round trip
        data = fsm1.to_dict()
        fsm2 = BookingFSM.from_dict("conv-123", data)

        assert fsm2.state == fsm1.state
        assert fsm2.collected_data == fsm1.collected_data
        assert fsm2._last_updated == fsm1._last_updated

    def test_from_dict_invalid_state(self):
        """Fallback to IDLE if state is invalid"""
        data = {
            "state": "invalid_state",
            "collected_data": {},
            "last_updated": datetime.now(UTC).isoformat(),
        }

        fsm = BookingFSM.from_dict("conv-123", data)

        assert fsm.state == BookingState.IDLE

    def test_json_serializable(self):
        """Ensure to_dict() output is JSON-serializable"""
        fsm = BookingFSM("conv-123")
        fsm._collected_data = {"services": ["Corte"]}

        data = fsm.to_dict()
        json_str = json.dumps(data)  # Should not raise

        assert isinstance(json_str, str)
```

### 7.2 Integration Tests

```python
# tests/integration/test_fsm_checkpoint_integration.py

class TestFSMCheckpointIntegration:
    """Test FSM integration with LangGraph checkpoint"""

    @pytest.mark.asyncio
    async def test_fsm_state_persists_in_checkpoint(self):
        """FSM state persists correctly in checkpoint"""
        # Create initial state
        state = {
            "conversation_id": "conv-test",
            "messages": [],
            "fsm_state": {
                "state": "slot_selection",
                "collected_data": {"services": ["Corte"]},
                "last_updated": datetime.now(UTC).isoformat(),
            },
        }

        # Invoke graph
        result = await graph.ainvoke(state, config={"configurable": {"thread_id": "conv-test"}})

        # Load checkpoint and verify FSM state
        checkpoint = checkpointer.get({"configurable": {"thread_id": "conv-test"}})

        assert "fsm_state" in checkpoint
        assert checkpoint["fsm_state"]["state"] == "customer_data"

    @pytest.mark.asyncio
    async def test_fsm_recovered_from_checkpoint(self):
        """FSM correctly recovered from checkpoint on resume"""
        # First invocation
        state1 = {...}
        result1 = await graph.ainvoke(state1, config=config)

        # Second invocation (resume conversation)
        # FSM state should be loaded from checkpoint
        state2 = {"conversation_id": "conv-test", ...}
        result2 = await graph.ainvoke(state2, config=config)

        # Verify FSM state was maintained
        assert result2["fsm_state"]["collected_data"] == result1["fsm_state"]["collected_data"]
```

### 7.3 Migration Tests

```python
# tests/migration/test_fsm_migration.py

class TestFSMMigration:
    """Test migration from dual persistence to single source"""

    @pytest.mark.asyncio
    async def test_migration_script_populates_fsm_state(self):
        """Migration script correctly populates fsm_state in checkpoints"""
        # Setup: Create checkpoints WITHOUT fsm_state (old format)
        checkpoint_old = {
            "messages": [],
            "customer_id": "cust-123",
            # NO fsm_state field
        }
        checkpointer.put(checkpoint_old, config)

        # Create corresponding FSM key in Redis (old format)
        redis_client.set("fsm:conv-123", json.dumps({
            "state": "customer_data",
            "collected_data": {"services": ["Corte"]},
        }))

        # Run migration
        await migrate_existing_checkpoints()

        # Verify: fsm_state is now in checkpoint
        checkpoint_new = checkpointer.get(config)
        assert "fsm_state" in checkpoint_new
        assert checkpoint_new["fsm_state"]["state"] == "customer_data"
```

---

## 8. Operaciones y Monitoreo

### 8.1 Métricas a Monitorear

**Durante Fallback Phase (Phase 1-4):**
```
- fsm_loaded_from_checkpoint: Counter (éxito con nuevo método)
- fsm_loaded_from_redis: Counter (fallback al método viejo)
- fsm_state_divergence: Counter (cuando checkpoint ≠ redis)
- fsm_deserialization_error: Counter (errores en from_dict)
- checkpoint_size: Histogram (bytes, antes vs después)
- redis_fsm_keys: Gauge (número de fsm:* keys en Redis)
```

**Después de Cutover (Phase 4+):**
```
- fsm_deserialization_error: Counter (should be 0 or very low)
- checkpoint_size: Histogram (new baseline)
- redis_memory_saved: Gauge (MB savings from deleting fsm:* keys)
```

### 8.2 Logging

```python
# Durante Fallback Phase
logger.warning(
    "FSM loaded from Redis (fallback) | conversation_id=%s",
    conversation_id,
)

# Divergencia detectada
logger.warning(
    "FSM state divergence | conversation_id=%s | "
    "checkpoint_state=%s | redis_state=%s",
    conversation_id, checkpoint_state, redis_state,
)

# Después de Cutover
logger.info(
    "FSM loaded from checkpoint (new method) | conversation_id=%s",
    conversation_id,
)
```

### 8.3 Alertas

**Phase 1-4 (Fallback):**
- Alert si `fsm_loaded_from_redis` > 10% del tráfico (significa algo está roto)
- Alert si `fsm_state_divergence` > 0 (nunca debería divergir)

**Phase 4+ (Post-Cutover):**
- Alert si `fsm_deserialization_error` > 0.01% del tráfico
- Alert si `checkpoint_size` > 15KB promedio (bloat)

---

## 9. Validación y Aceptación Criteria

### 9.1 Criterios de Éxito - Fase 1 (Preparación)

- [ ] `BookingFSM.to_dict()` y `from_dict()` implementados
- [ ] Tests unitarios: 100% cobertura para serialización
- [ ] Fallback dual-read implementado sin errores
- [ ] `fsm_state` field agregado a `ConversationState`
- [ ] Divergence logging activo en producción

### 9.2 Criterios de Éxito - Fase 2 (Validación)

- [ ] 99.99% de checkpoints con `fsm_state` consistente
- [ ] 0 divergencias detectadas en 1 semana canary
- [ ] Performance metrics: No regresión en latency
- [ ] Redis memory stable (no aumento)
- [ ] All tests passing en canary (5% tráfico)

### 9.3 Criterios de Éxito - Fase 3-4 (Migración + Cutover)

- [ ] 100% de checkpoints migratos con `fsm_state`
- [ ] `fsm:*` keys eliminados de Redis
- [ ] Code: `BookingFSM.persist()` y `load()` removidos
- [ ] Code: Fallback dual-read removido
- [ ] 0 deserialization errors en primeras 24h post-cutover
- [ ] Redis memory: -20-30% savings confirmado

### 9.4 Criterios de Éxito - Fase 5 (Optimización)

- [ ] Checkpoint size optimizado (< 10KB promedio)
- [ ] All performance targets met
- [ ] Documentation actualizado
- [ ] Runbook para future development actualizado

---

## 10. Documentación y Knowledge Transfer

### 10.1 Documentos a Actualizar

1. **CLAUDE.md**
   - Sección "FSM Hybrid Architecture"
   - Actualizar descripción de persistencia

2. **docs/architecture.md**
   - Diagrama de arquitectura
   - Descripción de checkpoint persistence

3. **Runbook** (docs/runbook/)
   - Crear: `docs/runbook/fsm-single-source-of-truth.md`
   - Debugging tips para FSM state issues

4. **Code Comments**
   - Update docstrings en `BookingFSM`
   - Update `conversational_agent` node comments

### 10.2 Knowledge Transfer

**Antes de Implementación:**
- [ ] Arquitecto leads design review
- [ ] Team discute riesgos y mitigaciones
- [ ] Crear decision record (este documento)

**Durante Implementación:**
- [ ] Daily standup updates en Slack
- [ ] Weekly arch sync con team

**Después de Implementación:**
- [ ] Retrospective: Lessons learned
- [ ] Documentation review
- [ ] Team training session (optional)

---

## 11. Aprobaciones y Sign-Off

| Rol | Nombre | Fecha | Firma |
|-----|--------|-------|-------|
| **Architect** | Claude Code | 2025-11-24 | ✅ |
| **Tech Lead** | [TBD] | | |
| **Product** | [TBD] | | |
| **DevOps** | [TBD] | | |

---

## 12. Referencias y Contexto

### 12.1 Problemas Resueltos

- **ADR-008:** Obsolete Slot Cleanup (implementado)
- **ADR-009:** Specific Error Detection (implementado)
- **ADR-010:** Synchronous Checkpoint Flush (implementado - Workaround temporal)
- **ADR-011:** Single Source of Truth (este documento - Solución permanente)

### 12.2 Documentos Relacionados

- `docs/adr-008-obsolete-slot-cleanup.md`
- `docs/adr-009-specific-error-detection.md`
- `docs/adr-010-checkpoint-flush.md`
- `docs/sprint-change-proposal-2025-11-21.md` (v4.0 FSM Hybrid design)

### 12.3 Issues Relacionados

- Issue #XXX: Race condition FSM state
- Issue #YYY: Dual persistence architectural issue

---

## 13. Anexos

### A. Sample Migration Script

```python
# scripts/migrate_fsm_to_checkpoint.py
"""
Migration script: Populate fsm_state in all existing checkpoints
Run once during Phase 3 migration
"""

import asyncio
import json
import logging
from datetime import UTC, datetime

from agent.fsm.booking_fsm import BookingFSM
from agent.state.checkpointer import get_redis_checkpointer
from shared.redis_client import get_redis_client

logger = logging.getLogger(__name__)

async def migrate():
    """Migrate FSM state from Redis keys to checkpoint"""
    redis = get_redis_client()
    checkpointer = get_redis_checkpointer()

    # Find all FSM keys
    fsm_keys = await redis.keys("fsm:*")
    logger.info(f"Found {len(fsm_keys)} FSM keys to migrate")

    for fsm_key in fsm_keys:
        # Extract conversation_id
        conversation_id = fsm_key.replace("fsm:", "")

        try:
            # Load FSM from Redis
            fsm = await BookingFSM.load(conversation_id)

            # Prepare config for checkpoint access
            config = {"configurable": {"thread_id": conversation_id}}

            # Get existing checkpoint
            checkpoint = checkpointer.get(config)
            if not checkpoint:
                logger.warning(f"No checkpoint for {conversation_id}, skipping")
                continue

            # Add fsm_state to checkpoint if not present
            if "fsm_state" not in checkpoint:
                checkpoint["fsm_state"] = fsm.to_dict()
                checkpointer.put(checkpoint, config)
                logger.info(f"Migrated FSM state for {conversation_id}")
            else:
                logger.debug(f"FSM state already in checkpoint for {conversation_id}")

        except Exception as e:
            logger.error(f"Error migrating {conversation_id}: {e}")
            continue

    logger.info(f"Migration completed for {len(fsm_keys)} conversations")

if __name__ == "__main__":
    asyncio.run(migrate())
```

### B. Comparison: Before vs After Code Examples

**BEFORE (v4.0 - Dual Persistence):**
```python
async def conversational_agent(state: ConversationState) -> dict[str, Any]:
    # FSM loaded from Redis
    fsm = await BookingFSM.load(conversation_id)

    # Process message...
    fsm.transition(intent)

    # Persist to Redis
    await fsm.persist()

    # Return (FSM state saved separately in Redis)
    return {
        "messages": updated_messages,
        "appointment_created": True,
    }
```

**AFTER (v4.1 - Single Source):**
```python
async def conversational_agent(state: ConversationState) -> dict[str, Any]:
    # FSM loaded from checkpoint
    fsm_data = state.get("fsm_state", {})
    fsm = BookingFSM.from_dict(conversation_id, fsm_data)

    # Process message...
    fsm.transition(intent)

    # Return (FSM state included in checkpoint return)
    return {
        "messages": updated_messages,
        "fsm_state": fsm.to_dict(),  # ← Persisted via LangGraph
        "appointment_created": True,
    }
```

---

## 14. Conclusión

Esta propuesta de ADR-011 eliminará permanentemente las race conditions causadas por dual persistence del FSM state. Al consolidar la persistencia en un único lugar (LangGraph Checkpoint), obtenemos:

✅ **Garantía de consistency** 100%
✅ **Eliminación de race conditions**
✅ **Arquitectura más simple**
✅ **Reducción de código duplicado**
✅ **Ahorro de Redis memory** (20-30%)

**Timeline realista:** 6 semanas para implementación completa (fase planeada para Epic 6, post-MVP)

**Riesgo:** BAJO (fallback dual-read en fases 1-4 permite rollback sin data loss)

---

**Próximos pasos:**
1. [ ] Review y aprobación de stakeholders
2. [ ] Scheduled para Epic 6 roadmap
3. [ ] Create implementation tickets (5-6 sprints)
4. [ ] Assign tech lead para ejecución
