# Sprint Change Proposal: Migración a Arquitectura FSM Híbrida

**Fecha:** 2025-11-21
**Autor:** Pepe (facilitado por workflow Correct Course)
**Estado:** Pendiente Aprobación
**Clasificación:** 🔴 MAJOR - Cambio arquitectónico fundamental

---

## 1. Issue Summary

### Problem Statement

Durante la ejecución de **Epic 1** (Corrección del Flujo de Agendamiento), específicamente en **Story 1-5** (Presentación de Estilistas y Disponibilidad), se descubrieron **2 bugs críticos** que revelan un problema arquitectónico fundamental:

| Bug | Descripción | Root Cause |
|-----|-------------|------------|
| **#1: UUID Serialization** | `ensure_customer_exists()` retornaba UUID objects en lugar de strings, causando "INVALID_UUID" al llamar `book()` | Falta de tipado estricto |
| **#2: State Flags Never Updated** | Flags `service_selected`, `slot_selected`, etc. nunca se seteaban; agente siempre detectaba `SERVICE_SELECTION` | Arquitectura LLM-driven sin FSM explícita |

### Core Problem

La arquitectura actual **v3.2** es **LLM-driven**: el modelo controla:
- ✅ Interpretación de intención (NLU) - Apropiado
- ✅ Generación de lenguaje natural - Apropiado
- ❌ Control de flujo de conversación - **Inapropiado**
- ❌ Validación de progreso - **Inapropiado**
- ❌ Decisión de cuándo llamar tools - **Inapropiado**

**Consecuencias:**
- **Frágil:** LLM puede saltarse pasos del booking
- **No debuggeable:** No sabemos el estado real de la conversación
- **No testeable:** Dependemos del razonamiento del LLM
- **No escalable:** Quick fixes se acumulan sin resolver el problema base

### Proposed Solution

Migrar a arquitectura **FSM Híbrida** donde:

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

---

## 2. Impact Analysis

### 2.1 Epic Impact

| Epic | Estado Actual | Impacto | Acción Requerida |
|------|---------------|---------|------------------|
| **Epic 1** | 4/7 done, 1 in-progress | ⚠️ Stories 1-5 a 1-7 bloqueadas | Pausar, completar después de Epic 5 |
| **Epic 2** | contexted (backlog) | 🔴 Bloqueada | Esperar Epic 5 + Epic 1 |
| **Epic 3** | backlog | 🔴 Bloqueada | Esperar Epic 5 + Epic 1 |
| **Epic 4** | backlog | 🟡 Parcialmente afectada | Puede beneficiarse de FSM |
| **Epic 5** | **NUEVA** | 🟢 Foundational | Ejecutar primero |

**Nuevo orden de ejecución:**
```
Epic 5 (FSM) → Epic 1 (completar) → Epic 2 → Epic 3 → Epic 4
```

### 2.2 Story Impact (Epic 1)

| Story | Estado | Impacto |
|-------|--------|---------|
| 1-1 Migración de Estados | ✅ done | Sin impacto |
| 1-2 Corrección book() | ✅ done | Sin impacto |
| 1-3 Lista numerada servicios | ✅ done | Sin impacto |
| 1-4 Selección múltiple | ✅ done | Sin impacto |
| **1-5 Estilistas/Disponibilidad** | ⚠️ in-progress | **PAUSAR** - Se completa en Epic 5 Story 5-6 |
| **1-6 Datos del cliente** | backlog | **PAUSAR** - Se adapta a FSM en Epic 5 Story 5-6 |
| **1-7 Actualización prompts** | backlog | **PAUSAR** - Se adapta a FSM en Epic 5 Story 5-6 |

### 2.3 Artifact Conflicts

| Documento | Conflicto | Acción |
|-----------|-----------|--------|
| `docs/prd.md` | ✅ Ninguno | Sin cambios (FRs se mantienen) |
| `docs/architecture.md` | ⚠️ Desactualizado | Agregar FSM section + ADR-006 |
| `docs/epics.md` | ⚠️ Incompleto | Agregar Epic 5, reordenar |
| `CLAUDE.md` | ⚠️ Desactualizado | Actualizar Architecture Overview |
| `docs/sprint-artifacts/sprint-status.yaml` | ⚠️ Incompleto | Agregar Epic 5 stories |
| `docs/sprint-artifacts/tech-spec-epic-1.md` | ⚠️ Desactualizado | Actualizar con integración FSM |

### 2.4 Technical Impact

| Componente | Cambio Requerido |
|------------|------------------|
| `agent/fsm/` | **NUEVO** - BookingFSM, IntentExtractor |
| `agent/nodes/conversational_agent.py` | Integrar FSM validation |
| `agent/tools/*.py` | Refactorizar para FSM validation |
| `agent/state/schemas.py` | Agregar FSM state fields |
| `tests/unit/test_fsm.py` | **NUEVO** - Tests de FSM |
| `tests/integration/test_fsm_flow.py` | **NUEVO** - Tests de integración |

---

## 3. Recommended Approach

### Selected Path: Direct Adjustment (Opción 1)

**Implementar Epic 5 como trabajo foundational antes de continuar features.**

### Justification

| Criterio | Evaluación |
|----------|------------|
| Resuelve problema de raíz | ✅ Sí - Separa responsabilidades LLM/FSM |
| Esfuerzo de implementación | 🟡 Medio - 2-3 semanas |
| Riesgo técnico | 🟡 Medio - FSM es patrón probado |
| Valor a largo plazo | ✅ Alto - Todas las features se benefician |
| Testabilidad | ✅ Excelente - Tests deterministas |
| Mantenibilidad | ✅ Excelente - Flujos estructurados |

### Alternatives Considered

| Opción | Viabilidad | Razón de Rechazo |
|--------|------------|------------------|
| **Rollback** | ❌ No viable | No resuelve causa raíz, problema resurge |
| **Reduce MVP** | ❌ No viable | MVP ya es mínimo, producto no funcionaría |

### Effort Estimate

| Componente | Duración |
|------------|----------|
| Epic 5 (6 stories) | 2-3 semanas |
| Adaptación Epic 1 (stories 1-5 a 1-7) | 1 semana adicional |
| Actualización documentación | 2-3 días |
| **Total** | **3-4 semanas** |

### Risk Assessment

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|-------------|---------|------------|
| LLM no extrae intención correctamente | Media | Alto | Ejemplos en prompt, validación adicional |
| FSM demasiado rígida | Baja | Alto | Testing extensivo, mensajes de redirección naturales |
| Migración toma más tiempo | Media | Medio | Priorizar solo stories críticas |

---

## 4. Detailed Change Proposals

### 4.1 Epic 5: FSM Híbrida (NUEVO)

**Archivo:** `docs/epics.md` - Agregar después de Epic 4

```markdown
## Epic 5: Rediseño FSM Híbrida para Booking Flow

**Prioridad:** CRÍTICA (Foundation)
**Duración Estimada:** 2-3 semanas
**Dependencias:** Ninguna
**Bloquea:** Epic 1 (stories 1-5, 1-6, 1-7), Epic 2, Epic 3

### Stories

| Story | Título | Duración |
|-------|--------|----------|
| 5-1 | Diseño de FSM States y Transiciones | 2 días |
| 5-2 | Implementación de FSM Controller Base | 3 días |
| 5-3 | Integración LLM + FSM (Intent Extraction) | 3 días |
| 5-4 | Refactorización de Tools con FSM Validation | 3 días |
| 5-5 | Testing End-to-End con FSM | 2 días |
| 5-6 | Migración de Epic 1 Stories a Nueva Arquitectura | 2 días |
```

### 4.2 Architecture Update

**Archivo:** `docs/architecture.md` - Agregar nueva sección y ADR

**Nueva sección: FSM Booking Flow Architecture**

```markdown
## FSM Booking Flow Architecture

### Separation of Concerns

| Componente | Responsabilidad |
|------------|-----------------|
| **LLM (NLU)** | Interpreta intención del usuario, genera lenguaje natural |
| **FSM Controller** | Controla flujo, valida transiciones, decide tool calls |
| **Tools** | Ejecutan acciones validadas por FSM |

### FSM States

| Estado | Descripción | Datos Requeridos |
|--------|-------------|------------------|
| IDLE | Sin booking activo | - |
| SERVICE_SELECTION | Seleccionando servicios | - |
| STYLIST_SELECTION | Seleccionando estilista | services[] |
| SLOT_SELECTION | Seleccionando horario | services[], stylist_id |
| CUSTOMER_DATA | Recopilando datos | services[], stylist_id, slot |
| CONFIRMATION | Confirmando booking | services[], stylist_id, slot, customer_data |
| BOOKED | Booking completado | appointment_id |

### Valid Transitions

IDLE → SERVICE_SELECTION (intent: start_booking)
SERVICE_SELECTION → STYLIST_SELECTION (services confirmed)
STYLIST_SELECTION → SLOT_SELECTION (stylist selected)
SLOT_SELECTION → CUSTOMER_DATA (slot selected)
CUSTOMER_DATA → CONFIRMATION (data collected)
CONFIRMATION → BOOKED (user confirms)
ANY → IDLE (intent: cancel_booking)
```

**Nuevo ADR:**

```markdown
### ADR-006: FSM Híbrida para Control de Flujo

**Contexto:** La arquitectura LLM-driven v3.2 produce bugs sistemáticos porque el LLM controla flujo además de NLU.

**Decisión:** Implementar FSM híbrida donde LLM solo maneja NLU y lenguaje, FSM controla flujo.

**Razones:**
- Transiciones deterministas y testeables
- Estado siempre claro y debuggeable
- LLM enfocado en lo que hace bien (lenguaje)
- Validación explícita antes de tool calls

**Consecuencias:**
- Refactoring de conversational_agent.py
- Nueva carpeta agent/fsm/
- Tests más fáciles de escribir y mantener
```

### 4.3 Sprint Status Update

**Archivo:** `docs/sprint-artifacts/sprint-status.yaml`

```yaml
# Agregar Epic 5
development_status:
  # Epic 5: FSM Híbrida (FOUNDATION)
  epic-5: backlog
  5-1-diseno-fsm-states-transiciones: backlog
  5-2-implementacion-fsm-controller-base: backlog
  5-3-integracion-llm-fsm-intent-extraction: backlog
  5-4-refactorizacion-tools-fsm-validation: backlog
  5-5-testing-end-to-end-fsm: backlog
  5-6-migracion-epic-1-stories-fsm: backlog
  epic-5-retrospective: optional

  # Epic 1: Actualizar estados
  1-5-presentacion-de-estilistas-y-disponibilidad: paused  # Was: in-progress
  1-6-recopilacion-de-datos-del-cliente: paused  # Was: backlog
  1-7-actualizacion-de-prompts-para-flujo-completo: paused  # Was: backlog
```

### 4.4 CLAUDE.md Update

**Archivo:** `CLAUDE.md` - Actualizar Architecture Overview

```markdown
### Simplified Tool-Based Architecture (v3.2) → FSM Hybrid Architecture (v4.0)

**IMPORTANTE:** A partir de Epic 5, el sistema usa arquitectura FSM híbrida:

**Componentes:**
1. **LLM (NLU)**: Interpreta intención del usuario, genera lenguaje natural
2. **FSM Controller**: Controla flujo de booking, valida transiciones
3. **Tools**: Ejecutan acciones validadas por FSM

**Flujo:**
1. Usuario envía mensaje
2. LLM extrae intención estructurada
3. FSM valida si transición es permitida
4. Si válida: ejecuta tool (si necesario), transiciona estado
5. Si inválida: LLM genera mensaje de redirección natural
6. LLM genera respuesta basada en nuevo estado FSM

**Archivos clave:**
- `agent/fsm/booking_fsm.py` - FSM Controller
- `agent/fsm/intent_extractor.py` - Intent extraction
- `agent/nodes/conversational_agent.py` - Integración LLM+FSM
```

---

## 5. Implementation Handoff

### Scope Classification

🔴 **MAJOR** - Cambio arquitectónico fundamental que requiere:
- Nuevo Epic (Epic 5)
- Refactoring de componentes existentes
- Actualización de múltiples documentos
- Testing extensivo

### Handoff Recipients

| Rol | Responsabilidad |
|-----|-----------------|
| **Developer (Dev Agent)** | Implementar Epic 5 stories |
| **Scrum Master (SM Agent)** | Actualizar sprint-status.yaml, crear stories |
| **Architect** | Revisar y aprobar cambios de arquitectura |

### Implementation Order

1. **Documentación primero:**
   - [ ] Actualizar `docs/epics.md` con Epic 5
   - [ ] Actualizar `docs/sprint-artifacts/sprint-status.yaml`
   - [ ] Crear `docs/epics/epic-5-rediseño-fsm-hibrida.md` (ya existe)

2. **Epic 5 Stories (en orden):**
   - [ ] Story 5-1: Diseño FSM (documento de especificación)
   - [ ] Story 5-2: FSM Controller Base
   - [ ] Story 5-3: Integración LLM + FSM
   - [ ] Story 5-4: Refactorización Tools
   - [ ] Story 5-5: Testing E2E
   - [ ] Story 5-6: Migración Epic 1

3. **Post-Epic 5:**
   - [ ] Completar Epic 1 (stories 1-5, 1-6, 1-7)
   - [ ] Continuar con Epic 2

### Success Criteria

- [ ] FSM Controller implementado y funcionando
- [ ] LLM + FSM integrados manteniendo naturalidad conversacional
- [ ] Tools refactorizadas con FSM validation
- [ ] Todos los tests pasan (unit + integration + e2e)
- [ ] Bugs de Story 1-5 resueltos
- [ ] Epic 1 completable con nueva arquitectura
- [ ] Documentación técnica actualizada

---

## 6. Approval

### Checklist Pre-Aprobación

- [x] Issue identificado y documentado
- [x] Impacto en épicas analizado
- [x] Conflictos de artefactos identificados
- [x] Opciones evaluadas con justificación
- [x] Approach recomendado con estimación de esfuerzo
- [x] Propuestas de cambio detalladas
- [x] Handoff definido

### Decisión

| Opción | Selección |
|--------|-----------|
| ✅ Aprobar propuesta | Proceder con Epic 5 |
| ⬜ Aprobar con modificaciones | - |
| ⬜ Rechazar | - |
| ⬜ Diferir | - |

**Aprobado por:** Pepe **Fecha:** 2025-11-21

---

## 7. Post-Approval Actions Completed

Los siguientes documentos fueron actualizados automáticamente tras la aprobación:

| Documento | Cambio | Estado |
|-----------|--------|--------|
| `docs/epics.md` | Agregada Epic 5, actualizada secuencia, estados de épicas | ✅ Completado |
| `docs/sprint-artifacts/sprint-status.yaml` | Agregada Epic 5, stories pausadas/bloqueadas | ✅ Completado |
| `docs/architecture.md` | Agregado ADR-006 (FSM Híbrida) | ✅ Completado |
| `CLAUDE.md` | Actualizado Architecture Overview con FSM v4.0 | ✅ Completado |
| `docs/epics/epic-5-rediseño-fsm-hibrida.md` | Ya existía, sin cambios | ✅ Existente |

**Próximo paso:** Ejecutar workflow `epic-tech-context` para Epic 5 y comenzar Story 5-1.

---

*Generado por workflow Correct Course - BMad Method*
*Sprint Change Proposal ID: SCP-2025-11-21-001*
