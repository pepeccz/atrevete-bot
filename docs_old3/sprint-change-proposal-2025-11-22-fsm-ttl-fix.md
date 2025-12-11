# Sprint Change Proposal: FSM TTL Synchronization Fix

**Fecha:** 2025-11-22
**Autor:** Pepe + Claude (análisis arquitectónico)
**Prioridad:** CRÍTICA
**Esfuerzo Total Estimado:** Bajo-Medio

---

## 1. Resumen del Problema

### Issue Descubierto
Durante análisis arquitectónico se identificó un **bug de desincronización de estado** entre dos sistemas de persistencia paralelos:

| Sistema | TTL | Propósito |
|---------|-----|-----------|
| LangGraph Checkpoint (AsyncRedisSaver) | 24 horas | Guarda `ConversationState` completo |
| BookingFSM (Redis separado) | **15 minutos** | Guarda estado FSM + collected_data |

### Escenario de Bug
1. Usuario inicia booking a las 10:00, llega a `STYLIST_SELECTION`
2. Usuario cierra WhatsApp
3. A las 10:16, FSM expira en Redis (TTL 15 min)
4. A las 10:30, usuario regresa
5. LangGraph carga checkpoint (válido, <24h) con historial de conversación
6. FSM se inicializa en `IDLE` (porque su key expiró)
7. **RESULTADO:** Bot recuerda conversación pero "olvida" el booking en progreso

### Síntoma Visible
```
Usuario: "Confirmo la cita"
Bot: "¡Hola! ¿En qué puedo ayudarte?" (FSM en IDLE)
```

---

## 2. Análisis de Impacto

### Artefactos Afectados
| Artefacto | Tipo de Cambio | Archivos |
|-----------|---------------|----------|
| BookingFSM | Modificar TTL | `agent/fsm/booking_fsm.py` |
| Architecture | Documentar fix | `docs/architecture.md` (ADR nuevo) |

### FRs Afectados
- FR40: Mantener contexto de conversación
- FR42: Español amigable (impactado por respuestas incoherentes)

### No Afectados
- Flujo de booking (lógica FSM intacta)
- Herramientas existentes
- Checkpointing de LangGraph
- Base de datos

---

## 3. Solución Propuesta

### Nivel 1: Fix Crítico (HACER YA)

#### Fix 1.1: Sincronizar FSM TTL con Checkpoint TTL

**Archivo:** `agent/fsm/booking_fsm.py:26`

```python
# ANTES
FSM_TTL_SECONDS: int = 900  # 15 minutos

# DESPUÉS
FSM_TTL_SECONDS: int = 86400  # 24 horas (sincronizado con AsyncRedisSaver)
```

**Impacto:**
- Elimina 100% de bugs de desincronización por TTL
- Sin cambios en lógica
- 1 línea de código

---

### Nivel 2: Mejora Opcional (CONSIDERAR para futuro)

#### Mejora 2.1: Unificar FSM en ConversationState

**Concepto:** Eliminar el segundo sistema de persistencia moviendo FSM state al state del grafo.

**Cambios requeridos:**

1. **schemas.py** - Añadir campos FSM:
```python
class ConversationState(TypedDict, total=False):
    # ... campos existentes ...

    # FSM State (NEW - unificado con checkpoint)
    fsm_booking_state: str  # BookingState.value
    fsm_collected_data: dict[str, Any]
    fsm_last_updated: str  # ISO 8601
```

2. **booking_fsm.py** - Refactorizar para leer/escribir del state del grafo:
```python
class BookingFSM:
    @classmethod
    def from_state(cls, state: ConversationState) -> "BookingFSM":
        """Carga FSM desde ConversationState en vez de Redis."""
        fsm = cls(state.get("conversation_id", "unknown"))
        fsm._state = BookingState(state.get("fsm_booking_state", "idle"))
        fsm._collected_data = state.get("fsm_collected_data", {})
        return fsm

    def to_state_updates(self) -> dict[str, Any]:
        """Retorna actualizaciones para ConversationState."""
        return {
            "fsm_booking_state": self._state.value,
            "fsm_collected_data": self._collected_data,
            "fsm_last_updated": datetime.now(UTC).isoformat(),
        }
```

3. **conversational_agent.py** - Usar state en vez de Redis:
```python
# ANTES
fsm = await BookingFSM.load(conversation_id)
# ... proceso ...
await fsm.persist()

# DESPUÉS
fsm = BookingFSM.from_state(state)
# ... proceso ...
fsm_updates = fsm.to_state_updates()
return {**updated_state, **fsm_updates}
```

**Impacto:**
- Elimina sistema de persistencia duplicado
- Un solo TTL (checkpoint TTL)
- Sin posibilidad de desincronización
- Esfuerzo: Medio (refactoring de ~50 líneas)

**Decisión:** Diferir a Epic 6 o implementar después de completar Epic 5 Testing (Story 5-5).

---

### Nivel 3: Mejoras No Críticas (NO HACER AHORA)

| Mejora | Por Qué No |
|--------|-----------|
| PostgresSaver | Redis funciona bien, 10x más rápido |
| add_messages reducer | Helper manual funciona, más control |
| Arquitectura multi-nodo | FSM interno es más simple y testeable |
| Pydantic BookingData | Validación manual existe, bajo ROI |

---

## 4. Plan de Implementación

### Fase 1: Fix Crítico (Inmediato)

| # | Tarea | Archivo | Líneas |
|---|-------|---------|--------|
| 1 | Cambiar FSM_TTL_SECONDS a 86400 | `agent/fsm/booking_fsm.py:26` | 1 |
| 2 | Añadir ADR-007 documentando fix | `docs/architecture.md` | ~15 |
| 3 | Test manual: verificar que FSM persiste >15 min | Manual | - |

**Estimación:** 15 minutos

### Fase 2: Mejora Opcional (Diferida)

| # | Tarea | Estimación |
|---|-------|------------|
| 1 | Añadir campos FSM a ConversationState | 30 min |
| 2 | Refactorizar BookingFSM.load/persist | 1 hora |
| 3 | Actualizar conversational_agent.py | 30 min |
| 4 | Tests unitarios | 1 hora |
| 5 | Tests integración | 1 hora |

**Estimación Total Fase 2:** 4 horas

---

## 5. Criterios de Éxito

### Fix Crítico
- [ ] FSM state persiste después de 20+ minutos de inactividad
- [ ] Usuario que regresa después de 30 min continúa booking donde lo dejó
- [ ] No hay mensajes incoherentes de "Hola" cuando usuario está en medio de booking

### Mejora Opcional (si se implementa)
- [ ] Solo un sistema de persistencia (AsyncRedisSaver)
- [ ] FSM state visible en LangSmith/Langfuse traces
- [ ] Tests pasan con FSM unificado

---

## 6. Riesgos y Mitigación

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|-------------|---------|------------|
| FSM TTL más largo = más memoria Redis | Baja | Bajo | Redis tiene suficiente capacidad |
| Conversaciones zombie 24h | Media | Bajo | Worker archiver limpia después de TTL |

---

## 7. ADR-007: FSM TTL Synchronization

### Contexto
El sistema tiene dos mecanismos de persistencia con TTLs diferentes:
- LangGraph checkpoint: 24h
- BookingFSM: 15 min (originalmente diseñado para sesiones cortas)

### Decisión
Aumentar FSM TTL a 24h para sincronizar con checkpoint TTL.

### Consecuencias
- (+) Elimina bugs de desincronización de estado
- (+) Usuarios pueden continuar bookings después de pausas largas
- (-) Ligeramente más memoria Redis (negligible)
- (!) Considerar unificación completa en futuro (Fase 2)

---

## 8. Aprobación

**Cambio Propuesto:**
- [x] Fix 1.1: FSM TTL → 24h (CRÍTICO, hacer ya)
- [ ] Mejora 2.1: Unificar FSM en state (DIFERIDO a post-Epic 5)

**Scope:** Minor (implementación directa por dev)

---

_Generado por workflow correct-course_
_Fecha: 2025-11-22_
