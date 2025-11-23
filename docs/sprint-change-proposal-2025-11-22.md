# Sprint Change Proposal: FSM Synchronization Bug Fix

**Fecha:** 2025-11-22
**Trigger:** Bug crítico descubierto durante testing de Story 5-5
**Tipo de cambio:** Direct Adjustment (fix quirúrgico)
**Severidad:** Crítica (bloquea Epic 5 y Epic 1)

---

## 1. Resumen Ejecutivo

### Problema Descubierto

Durante el testing E2E de Story 5-5, se identificó un bug crítico de **desincronización entre el LLM y la FSM**. El LLM genera respuestas que avanzan el flujo conversacional (mostrando estilistas) sin que la FSM valide ni transite correctamente entre estados.

**Síntomas observados:**
1. El bot muestra lista de estilistas sin confirmar servicios
2. Usuario selecciona estilista → FSM rechaza la transición
3. Bot dice "Déjame buscar horarios..." pero no ejecuta ninguna herramienta
4. Conversación queda colgada

### Solución Implementada

Fix quirúrgico en 2 archivos que permite la transición `SELECT_STYLIST` desde `SERVICE_SELECTION` cuando hay al menos 1 servicio seleccionado.

---

## 2. Análisis del Bug

### 2.1 Evidencia de Logs

```json
{
  "timestamp": "2025-11-22T12:02:12.008429+00:00",
  "level": "WARNING",
  "logger": "agent.fsm.booking_fsm",
  "message": "FSM transition rejected: service_selection -> ? | intent=select_stylist | errors=[\"Transition 'select_stylist' not allowed from state 'service_selection'\"] | conversation_id=8"
}
```

### 2.2 Flujo que Ocurrió

```
Usuario: "Holaa quiero agendar una cita"
Bot: "¿Qué tipo de servicio te gustaría?"

Usuario: "Quiero cortarme el pelo"
Bot: [llama search_services] → Lista 5 servicios numerados

Usuario: "5" (Corte de Caballero)
Bot: ⚠️ PROBLEMA: Muestra estilistas SIN preguntar "¿agregar otro servicio?"
     FSM: Sigue en SERVICE_SELECTION (no transitó)

Usuario: "4" (Pilar)
Bot: FSM rechaza → "Déjame buscar horarios..." (pero no ejecuta herramientas)
     → Conversación colgada
```

### 2.3 Root Cause

La FSM requiere `CONFIRM_SERVICES` para transitar de `SERVICE_SELECTION` → `STYLIST_SELECTION`, pero el LLM salta directamente a mostrar estilistas sin generar esa confirmación.

**Diseño original:**
```
SERVICE_SELECTION → [CONFIRM_SERVICES] → STYLIST_SELECTION
```

**Lo que ocurre:**
```
SERVICE_SELECTION → LLM muestra estilistas → Usuario selecciona → FSM rechaza
```

---

## 3. Solución Implementada

### 3.1 Cambios en `agent/fsm/booking_fsm.py`

**Transiciones agregadas:**
```python
BookingState.SERVICE_SELECTION: {
    IntentType.SELECT_SERVICE: BookingState.SERVICE_SELECTION,
    IntentType.CONFIRM_SERVICES: BookingState.STYLIST_SELECTION,
    # NUEVO: Permite SELECT_STYLIST si hay servicios seleccionados
    IntentType.SELECT_STYLIST: BookingState.STYLIST_SELECTION,
},
```

**Validación agregada:**
```python
TRANSITION_REQUIREMENTS = {
    # SELECT_STYLIST desde SERVICE_SELECTION requiere servicios + stylist_id
    (BookingState.SERVICE_SELECTION, IntentType.SELECT_STYLIST): ["services", "stylist_id"],
}
```

### 3.2 Cambios en `agent/fsm/intent_extractor.py`

**Intent válido agregado para SERVICE_SELECTION:**
```python
BookingState.SERVICE_SELECTION: [
    ("select_service", "Usuario selecciona un servicio"),
    ("confirm_services", "Usuario confirma que no quiere más servicios"),
    # NUEVO
    ("select_stylist", "Usuario selecciona un estilista (si ya tiene servicios)"),
    ("cancel_booking", "Usuario quiere cancelar"),
    ...
]
```

**Hint de desambiguación actualizado:**
```python
BookingState.SERVICE_SELECTION: (
    "IMPORTANTE: Un número puede ser:\n"
    "- Selección de SERVICIO si la lista mostrada es de servicios\n"
    "- Selección de ESTILISTA si la lista mostrada es de estilistas\n"
    "Analiza el CONTEXTO RECIENTE para determinar."
)
```

---

## 4. Impacto en Sprint

### 4.1 Stories Afectadas

| Story | Estado Anterior | Estado Post-Fix |
|-------|-----------------|-----------------|
| 5-5 Testing E2E | review (bloqueada) | completable |
| 5-6 Migration Epic 1 | backlog | desbloqueada |
| 1-5 Estilistas y Disponibilidad | paused | desbloqueada |
| 1-6 Datos del Cliente | paused | desbloqueada |
| 1-7 Actualización Prompts | paused | desbloqueada |

### 4.2 Epics Afectadas

| Epic | Estado Anterior | Estado Post-Fix |
|------|-----------------|-----------------|
| Epic 5 (FSM Híbrida) | bloqueada por bug | completable |
| Epic 1 (Flujo Agendamiento) | paused | desbloqueada |
| Epic 2-4 | blocked | siguen blocked (dependen de Epic 1) |

---

## 5. Testing

### 5.1 Pruebas Manuales Requeridas

**Flujo a probar via WhatsApp:**
1. "Hola, quiero una cita"
2. "Quiero cortarme el pelo"
3. Seleccionar servicio con número ("5")
4. ✅ Bot debe preguntar "¿agregar otro?" O mostrar estilistas
5. Seleccionar estilista con número ("4")
6. ✅ FSM debe aceptar transición → mostrar horarios
7. Seleccionar horario
8. Proporcionar nombre
9. Confirmar cita

### 5.2 Criterios de Aceptación

- [ ] Transición SERVICE_SELECTION → STYLIST_SELECTION funciona sin bloqueo
- [ ] FSM rechaza SELECT_STYLIST si no hay servicios seleccionados
- [ ] Intent extractor distingue entre selección de servicio y estilista por contexto
- [ ] Flujo completo de booking funciona sin errores

---

## 6. Riesgos y Mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|-------------|---------|------------|
| Intent extractor confunde servicio/estilista | Media | Medio | Hint de desambiguación mejorado + contexto conversacional |
| FSM demasiado permisiva | Baja | Bajo | Validación de `services` requerido antes de SELECT_STYLIST |
| Regresión en otros flujos | Baja | Alto | Tests E2E existentes + testing manual |

---

## 7. Aprobación

**Fecha de implementación:** 2025-11-22
**Implementado por:** Claude Code
**Revisado por:** Pendiente

### Checklist Pre-Merge

- [x] Código modificado (`booking_fsm.py`, `intent_extractor.py`)
- [x] Container reconstruido y desplegado
- [ ] Testing manual completado
- [ ] Tests automatizados pasan
- [ ] Documentación actualizada

---

## 8. Lecciones Aprendidas

1. **La FSM debe ser flexible con LLM-driven conversations:** El LLM puede "saltar" pasos que humanos considerarían obligatorios. La FSM debe adaptarse.

2. **El estado de desambiguación es crítico:** Un número ("4") puede significar cosas diferentes según el contexto conversacional, no solo el estado FSM.

3. **Logs de FSM son esenciales:** El warning `FSM transition rejected` fue clave para diagnosticar el problema.

4. **Testing E2E via WhatsApp temprano:** Bugs de sincronización solo se detectan con flujos reales de usuario.

---

**Documento generado:** 2025-11-22
**Workflow:** BMad Method - Correct Course
