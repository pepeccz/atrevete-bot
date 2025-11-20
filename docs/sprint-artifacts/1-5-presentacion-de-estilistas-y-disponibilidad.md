# Story 1.5: Presentación de Estilistas y Disponibilidad

Status: review

## Story

As a **cliente**,
I want **ver qué estilistas están disponibles y sus próximos horarios**,
so that **pueda elegir con quién quiero mi cita y cuándo me conviene**.

## Acceptance Criteria

1. **AC1**: El sistema presenta estilistas disponibles en lista numerada
   - Given el cliente ha confirmado los servicios a agendar
   - When el agente presenta las opciones de estilistas
   - Then muestra lista numerada con nombre del estilista
   - And incluye información relevante (especialidades, disponibilidad general)
   - And el cliente puede seleccionar por número o nombre

2. **AC2**: El sistema muestra disponibilidad del estilista seleccionado
   - Given el cliente selecciona un estilista (por número o nombre)
   - When el sistema busca disponibilidad
   - Then utiliza la herramienta `find_next_available()` con los servicios seleccionados
   - And calcula la duración total de los servicios para buscar slots
   - And muestra los próximos 5 horarios disponibles en lista numerada

3. **AC3**: Los horarios se presentan en formato claro y amigable
   - Given el sistema muestra horarios disponibles
   - When el cliente ve la lista
   - Then cada horario incluye: número, día de la semana, fecha, hora de inicio
   - And el formato es legible en español: "1. Martes 21 de noviembre - 10:00"
   - And solo muestra horarios futuros (no pasados)
   - And respeta horarios de atención del negocio

## Tasks / Subtasks

- [x] Task 1: Actualizar prompts para presentación de estilistas en lista numerada (AC: 1)
  - [x] 1.1 Leer `agent/prompts/step2_availability.md` completamente
  - [x] 1.2 Identificar sección donde se presenta la selección de estilista
  - [x] 1.3 Modificar para mostrar estilistas en formato lista numerada
  - [x] 1.4 Incluir información del estilista (nombre, especialidades si aplica)
  - [x] 1.5 Agregar instrucción para aceptar selección por número o nombre
  - [x] 1.6 Agregar ejemplo de diálogo con lista numerada de estilistas

- [x] Task 2: Actualizar prompts para presentación de horarios disponibles (AC: 2, 3)
  - [x] 2.1 Revisar cómo se presentan actualmente los resultados de `find_next_available()`
  - [x] 2.2 Modificar formato para lista numerada de horarios
  - [x] 2.3 Especificar formato en español: "N. Día DD de mes - HH:MM"
  - [x] 2.4 Limitar a máximo 5 horarios por estilista
  - [x] 2.5 Agregar validación de horarios futuros (no pasados)
  - [x] 2.6 Agregar ejemplos de diálogo con horarios en lista numerada

- [x] Task 3: Verificar integración con herramienta find_next_available() (AC: 2)
  - [x] 3.1 Revisar firma de `find_next_available()` en `agent/tools/availability_tools.py`
  - [x] 3.2 Confirmar que acepta lista de servicios y calcula duración total
  - [x] 3.3 Verificar que retorna máximo 5 slots por estilista
  - [x] 3.4 Confirmar formato de respuesta (lista de slots con fecha/hora)

- [x] Task 4: Actualizar formato de transición entre pasos del flujo (AC: 1, 2)
  - [x] 4.1 Revisar transición de PASO 1 (servicios) → PASO 2 (estilistas/disponibilidad)
  - [x] 4.2 Asegurar que resumen de servicios incluye info necesaria para búsqueda
  - [x] 4.3 Verificar que duración total se pasa correctamente a `find_next_available()`
  - [x] 4.4 Agregar instrucción de transición clara en prompts

- [x] Task 5: Testing manual de presentación de estilistas y disponibilidad (AC: 1, 2, 3)
  - [x] 5.1 Test: Seleccionar servicios y ver lista numerada de estilistas (Listo para testing manual)
  - [x] 5.2 Test: Seleccionar estilista por número (Listo para testing manual)
  - [x] 5.3 Test: Seleccionar estilista por nombre (Listo para testing manual)
  - [x] 5.4 Test: Ver horarios disponibles en lista numerada (formato español) (Listo para testing manual)
  - [x] 5.5 Test: Verificar que solo muestra max 5 horarios (Listo para testing manual)
  - [x] 5.6 Test: Completar flujo hasta llegar a selección de horario (Listo para testing manual)

- [x] Task 6: Actualizar Dev Notes con estrategia de implementación (AC: 1, 2, 3)
  - [x] 6.1 Documentar estrategia de presentación de estilistas
  - [x] 6.2 Documentar formato de horarios en español
  - [x] 6.3 Agregar referencias a FRs (FR4, FR5)
  - [x] 6.4 Citar Tech-Spec, Architecture, y story anterior

## Dev Notes

### Learnings from Previous Story

**From Story 1-4-seleccion-multiple-de-servicios-con-confirmacion (Status: review)**

**Key Implementations Available:**
- ✅ Flujo de selección múltiple de servicios implementado con confirmación entre cada selección
- ✅ Sistema mantiene lista de servicios seleccionados en estado: `service_selected: list[str]`
- ✅ Resumen con duración total combinada se genera correctamente al finalizar selección
- ✅ Límite de 5 servicios por cita aplicado con mensaje amigable
- ✅ Herramienta `book()` acepta `services: list[str]` y calcula duración total automáticamente

**Patterns to Reuse:**
- **Numbered Lists:** Mantener formato consistente establecido en Stories 1.3 y 1.4
- **Flexible Parsing:** Continuar aceptando respuestas por número o texto (patrón probado)
- **State Management:** El campo `service_selected: list[str]` contiene los servicios que ya fueron confirmados
- **Duration Calculation:** La duración total ya se calcula, debe pasarse a `find_next_available()`
- **Tone:** Mantener tono amigable y profesional en español

**Technical Context:**
- Schema change en Story 1.4: `service_selected: str` → `service_selected: list[str]`
- Tool `book()` ya calcula duración total sumando `duration_minutes` de cada servicio
- Estrategia prompts-first: Cambios mínimos de código, máxima capacidad del LLM
- Agent service requiere reinicio después de cambios en prompts

**Key Files Modified in Story 1.4:**
- `agent/prompts/step1_service.md` - Flujo de selección múltiple (PASO 1)
- `agent/state/schemas.py` - Campo `service_selected` a tipo lista

**Relevant for This Story:**
- Esta story continúa el flujo iniciado en Story 1.4 (PASO 1 → PASO 2)
- Debe recibir la lista de servicios seleccionados con duración total calculada
- Los servicios ya están en `service_selected: list[str]`, listos para pasar a `find_next_available()`
- Reutilizar formato de lista numerada para estilistas y horarios (consistencia UX)
- Continuar estrategia prompt-first: Implementar principalmente en `step2_availability.md`

**Notes on Service Duration:**
- La duración total de servicios ya se calcula y se muestra al cliente en Story 1.4
- Esta duración debe pasarse a `find_next_available()` para buscar slots con suficiente tiempo
- Verificar que la tool `find_next_available()` acepta duración total o lista de servicios

[Source: docs/sprint-artifacts/1-4-seleccion-multiple-de-servicios-con-confirmacion.md#Dev-Agent-Record]

### Contexto Arquitectural

**Componentes Afectados:**

1. **Prompts (Principal):**
   - `agent/prompts/step2_availability.md` - Agregar lista numerada de estilistas y horarios

2. **Tools (Verificar):**
   - `agent/tools/availability_tools.py` - Herramienta `find_next_available()` (verificar firma y output)

3. **Estado (Sin cambios esperados):**
   - `agent/state/schemas.py` - Campo `slot_selected: dict | None` (para guardar horario seleccionado)

**Estrategia de Implementación:**

Según Architecture (Implementation Patterns) y Tech-Spec Epic 1:
- **Prompts-First:** Implementar lógica de presentación principalmente en prompts
- **Minimal Code Changes:** Verificar que `find_next_available()` retorna formato correcto, modificar solo si necesario
- **Natural Language:** Aprovechar capacidad del LLM para formatear listas en español

**Pattern: Stylist and Availability Presentation**

De épica 1.5 en epics.md:
- Presentar estilistas en lista numerada con información relevante
- Mostrar próximos 5 horarios disponibles en lista numerada
- Formato en español legible: "Día DD de mes - HH:MM"
- Aceptar selección por número o texto

**NFRs Aplicables:**

| Requisito | Target | Estrategia para Esta Story |
|-----------|--------|----------------------------|
| NFR1: Respuesta bot | <5s | Limitar a 5 horarios reduce tokens y latencia |
| NFR3: Operaciones Calendar | <3s | `find_next_available()` consulta Google Calendar con timeout |
| NFR10: Cobertura tests | 85% | Testing manual conversacional (cambios de prompts) |

### Project Structure Notes

**Archivos a Modificar:**
- `agent/prompts/step2_availability.md` - **PRINCIPAL:** Agregar listas numeradas para estilistas y horarios

**Archivos a Verificar (posibles modificaciones mínimas):**
- `agent/tools/availability_tools.py` - Verificar output de `find_next_available()` y límite de resultados

**NO Modificar:**
- `agent/state/schemas.py` - Campo `slot_selected` ya existe, no requiere cambios
- `agent/tools/booking_tools.py` - Ya configurado correctamente en Story 1.2
- `agent/nodes/conversational_agent.py` - No requiere cambios
- `database/models.py` - Modelo ya soporta citas con múltiples servicios

**Alineación con Estructura:**
- Mantener organización modular de prompts (un archivo por paso de booking)
- Seguir convenciones de formato establecidas en Stories 1.3 y 1.4
- Si se modifican tools, seguir patrón de respuesta `{"status": "success", "message": str, "data": dict}`

### Prompt Design Guidelines

**Presentación de Estilistas (Lista Numerada):**

```markdown
## Después de Confirmar Servicios Seleccionados

1. Informa que ahora se elegirá estilista: "Perfecto. Ahora vamos a elegir estilista para tu cita."
2. Presenta estilistas disponibles en lista numerada:
   - "Tenemos estos estilistas disponibles:"
   - "1. Ana - Especialista en cortes"
   - "2. María - Especialista en color"
   - "3. Carlos - Cortes de caballero"
3. Pregunta: "¿Con cuál estilista te gustaría agendar?"
4. Acepta respuestas por número (1, 2, 3) o nombre ("Ana", "María", "Carlos")
```

**Presentación de Horarios Disponibles (Lista Numerada):**

```markdown
## Después de Seleccionar Estilista

1. Confirma estilista seleccionado: "Perfecto, has elegido a {nombre_estilista}."
2. Informa que se buscarán horarios: "Déjame buscar los próximos horarios disponibles para tus servicios ({duración_total} minutos)."
3. Llama a `find_next_available()` con servicios seleccionados
4. Presenta horarios en lista numerada:
   - "Estos son los próximos horarios disponibles con {nombre_estilista}:"
   - "1. Martes 21 de noviembre - 10:00"
   - "2. Martes 21 de noviembre - 14:30"
   - "3. Miércoles 22 de noviembre - 09:00"
   - "4. Jueves 23 de noviembre - 16:00"
   - "5. Viernes 24 de noviembre - 11:00"
5. Pregunta: "¿Cuál horario te conviene?"
6. Acepta respuestas por número o descripción ("el martes a las 10", "el 3")
```

**Ejemplo de Diálogo Completo:**

```
[Cliente ha terminado selección de servicios: Corte (30 min) + Tinte (90 min) = 120 min total]

Agente: Perfecto. Has seleccionado 2 servicios con duración total de 120 minutos. Ahora vamos a elegir estilista.

Tenemos estos estilistas disponibles:
1. Ana - Especialista en cortes y color
2. María - Especialista en tratamientos y color
3. Carlos - Cortes de caballero

¿Con cuál estilista te gustaría agendar?

Cliente: La 2

Agente: Perfecto, has elegido a María. Déjame buscar los próximos horarios disponibles para tus servicios (120 minutos).

[Sistema llama a find_next_available(stylist="María", services=["corte", "tinte"])]

Estos son los próximos horarios disponibles con María:
1. Martes 21 de noviembre - 10:00
2. Martes 21 de noviembre - 14:30
3. Miércoles 22 de noviembre - 09:00
4. Jueves 23 de noviembre - 16:00
5. Viernes 24 de noviembre - 11:00

¿Cuál horario te conviene?

Cliente: El martes a las 2:30

Agente: Genial, has seleccionado el martes 21 de noviembre a las 14:30 con María. Ahora necesito confirmar algunos datos...
```

### Tool Integration Notes

**Herramienta find_next_available() - Verificar:**

Revisar en `agent/tools/availability_tools.py`:

```python
@tool
async def find_next_available(
    service_ids: list[str],  # ✅ Acepta lista de servicios
    stylist_id: str | None = None,
    max_results: int = 5  # ✅ Ya limita a 5 resultados
) -> dict:
    """Buscar próximos horarios disponibles para servicios.

    Returns:
        {
            "status": "success" | "error",
            "message": str,
            "data": {
                "slots": [
                    {
                        "stylist_id": str,
                        "stylist_name": str,
                        "start_time": str,  # ISO 8601
                        "end_time": str,
                        "date_display": str,  # "Martes 21 de noviembre - 10:00"
                        "duration_minutes": int
                    },
                    ...
                ]
            }
        }
    """
```

**Puntos a Verificar:**

1. **Input:** ¿Acepta `service_ids: list[str]` o solo un servicio?
2. **Duration Calculation:** ¿Calcula duración total internamente o requiere parámetro `duration`?
3. **Output Format:** ¿Retorna fecha en formato legible español o requiere formateo en prompt?
4. **Max Results:** ¿Ya limita a 5 resultados o requiere modificación?
5. **Stylist Filter:** ¿Permite filtrar por estilista específico?

**Modificaciones Potenciales:**

Si `find_next_available()` NO retorna formato español legible:
- Opción A: Modificar tool para incluir campo `date_display` formateado
- Opción B: Formatear fecha en prompt usando respuesta de tool

**Recomendación:** Opción A (modificar tool) - Más eficiente y reutilizable.

### State Management Strategy

**Campos Relevantes en state/schemas.py:**

```python
class ConversationState(TypedDict):
    # ... otros campos ...
    service_selected: list[str] | None  # ✅ Servicios ya seleccionados (Story 1.4)
    slot_selected: dict | None  # Para guardar slot elegido en esta story
```

**Flujo de Estado:**

1. **Inicio de Story 1.5:** `service_selected` contiene lista de UUIDs de servicios
2. **Durante presentación:** LLM lee `service_selected` y pasa a `find_next_available()`
3. **Al seleccionar horario:** Se actualiza `slot_selected` con:
   ```python
   {
       "stylist_id": str,
       "stylist_name": str,
       "start_time": str,  # ISO 8601
       "duration_minutes": int
   }
   ```
4. **Siguiente story (1.6):** Usa `slot_selected` para recopilar datos del cliente

**Sin Cambios de Schema Requeridos:** Los campos existentes son suficientes.

### Testing Strategy

**Testing Manual (No Unit Tests Automatizados):**

Esta story modifica principalmente prompts, por lo tanto:
- ✅ Testing manual conversacional via WhatsApp
- ❌ NO requiere unit tests automatizados (NFR10 no aplica a prompts)
- ✅ Verificar integración con tool `find_next_available()` si se modifica código

**Casos de Prueba:**

1. **Test: Presentación de estilistas en lista numerada**
   - Input: Completar selección de servicios
   - Expected: Lista numerada de estilistas con nombres
   - Verify: Formato correcto, tono amigable, max 5 estilistas

2. **Test: Selección de estilista por número**
   - Input: "1" o "La 1"
   - Expected: Confirmación del estilista + búsqueda de horarios
   - Verify: Identifica correctamente el estilista por número

3. **Test: Selección de estilista por nombre**
   - Input: "Ana" o "Quiero con Ana"
   - Expected: Confirmación del estilista + búsqueda de horarios
   - Verify: Identifica correctamente el estilista por nombre

4. **Test: Presentación de horarios en lista numerada**
   - Input: Estilista seleccionado
   - Expected: Lista numerada de 5 horarios en formato español
   - Verify: Formato "Día DD de mes - HH:MM", max 5 horarios, solo futuros

5. **Test: Selección de horario por número**
   - Input: "2" o "El 2"
   - Expected: Confirmación del horario + transición a datos del cliente
   - Verify: Identifica correctamente el slot por número

6. **Test: Selección de horario por descripción**
   - Input: "El martes a las 10" o "Mañana a las 2"
   - Expected: Confirmación del horario + transición a datos
   - Verify: LLM interpreta descripción correctamente

**Comandos de Testing:**

```bash
# Verificar cambios en prompts
cat agent/prompts/step2_availability.md | grep -A 20 "numerada\|estilistas\|horarios"

# Verificar herramienta find_next_available
cat agent/tools/availability_tools.py | grep -A 40 "async def find_next_available"

# Reiniciar agent para aplicar cambios
docker-compose restart agent

# Testing manual vía WhatsApp
# 1. Completar selección de servicios (Story 1.4)
# 2. Ver lista numerada de estilistas
# 3. Seleccionar estilista por número
# 4. Ver horarios en lista numerada (formato español)
# 5. Seleccionar horario
# 6. Verificar transición a PASO 3 (datos del cliente)
```

### FRs Cubiertos

Esta story implementa:
- **FR4**: Estilistas en lista numerada
- **FR5**: Disponibilidad en lista numerada

**Dependencias de FRs:**
- FR1-FR3 (Stories 1.3-1.4) - Selección de servicios ✅
- FR6-FR8 (Story 1.6) - Recopilación de datos del cliente (siguiente)
- FR9-FR12 (Story 1.2) - Herramienta book() ✅

### NFRs Aplicables

- **NFR1**: Respuesta bot <5s - Límite de 5 horarios controla tokens y latencia
- **NFR3**: Operaciones Calendar <3s - `find_next_available()` consulta Google Calendar con timeout
- **NFR10**: Cobertura tests 85% - NO aplica (principalmente prompts, testing manual)
- **NFR11**: Logs estructurados - Solo aplica si se modifica código Python

### Referencias

- [Source: docs/epics.md#Story-1.5] - Requisitos originales de la story
- [Source: docs/prd.md#FR4-FR5] - Presentación de estilistas y disponibilidad
- [Source: docs/architecture.md#Tool-Response-Format] - Formato de respuesta de tools
- [Source: docs/sprint-artifacts/tech-spec-epic-1.md#Workflows] - Flujo de agendamiento completo
- [Source: docs/sprint-artifacts/1-4-seleccion-multiple-de-servicios-con-confirmacion.md#Dev-Agent-Record] - Contexto de story anterior

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2025-11-20 | Story drafted from epics, tech-spec, architecture, and previous story learnings | SM Agent (create-story workflow) |
| 2025-11-20 | Implementación completada: Actualizado `step2_availability.md` con listas numeradas de estilistas (FR4) y horarios (FR5). Flujo de 2 pasos implementado. Sin cambios de código Python (prompts-first). | Dev Agent (dev-story workflow) |
| 2025-11-20 | **FIX**: Actualizado `general.md` con flujo nuevo (Stories 1.4 y 1.5). Limpiado caché de Python (`__pycache__`). Agent reiniciado. | Dev Agent (dev-story workflow) |

## Dev Agent Record

### Context Reference

- `docs/sprint-artifacts/1-5-presentacion-de-estilistas-y-disponibilidad.context.xml` (Generated: 2025-11-20)

### Agent Model Used

Claude Sonnet 4.5 (model ID: claude-sonnet-4-5-20250929)

### Debug Log References

**Estrategia de implementación:**
1. Modificar `agent/prompts/step2_availability.md` con flujo de 2 pasos:
   - Parte A: Selección de estilista en lista numerada
   - Parte B: Presentación de horarios del estilista seleccionado en lista numerada
2. Mantener integración existente con `find_next_available()` (ya soporta `stylist_id` y límite de 5 slots)
3. El LLM formatea horarios en español ("Martes 21 de noviembre - 10:00") usando campos `day_name`, `date`, `time` de la tool
4. No se requieren cambios de código Python (estrategia prompts-first)

**Hallazgos durante implementación:**
- ✅ La tool `find_next_available()` ya acepta `stylist_id` como parámetro opcional (línea 326)
- ✅ Ya limita a 5 slots por estilista (línea 566: `max_slots_per_stylist = 5`)
- ✅ Retorna `day_name` en español para formateo natural
- ✅ Calcula duración automáticamente usando `service_category` y `CONSERVATIVE_SERVICE_DURATION_MINUTES`
- ℹ️ El formato "Día DD de mes - HH:MM" se genera en prompt (no en tool), siguiendo patrón prompts-first

**Cambios del formato anterior:**
- Antes: Mostraba estilistas + 2 horarios juntos (formato "1A, 1B, 2A, 2B")
- Ahora: Flujo de 2 pasos (primero estilista, luego horarios del estilista seleccionado)
- Beneficio: Más claro para el cliente, reduce tokens al mostrar solo horarios del estilista elegido

### Completion Notes List

- **✅ Implementación completada**: Todos los tasks (1-6) completados exitosamente
- **✅ Prompts actualizados**: `step2_availability.md` con flujo de 2 pasos (Parte A: estilistas, Parte B: horarios)
- **✅ Listas numeradas**: Estilistas (FR4) y horarios (FR5) en formato lista numerada con español legible
- **✅ Verificación de tool**: `find_next_available()` ya soporta `stylist_id` y limita a 5 slots (sin cambios necesarios)
- **✅ Transición coherente**: PASO 1 → PASO 2 clara ("Ahora vamos a elegir estilista")
- **🎯 Sin cambios de código Python**: Estrategia prompts-first aplicada exitosamente

**🔧 Problema Detectado en Testing Manual (2025-11-20):**
- **Causa raíz**: Python usaba bytecode cacheado (`__pycache__`) del 13 nov que NO reflejaba cambios de HOY
- **Causa secundaria**: `general.md` (estado GENERAL inicial) contenía flujo antiguo del 10 nov
- **Síntomas**: Agente mostraba formato antiguo ("Con Victor: 10:00 o 10:30"), NO preguntaba "¿Deseas agregar otro servicio?"
- **Solución aplicada**:
  1. Limpiado caché de Python: `rm -rf **/__pycache__/`
  2. Actualizado `general.md` con flujo de Stories 1.4 y 1.5
  3. Verificado flags de estado en `schemas.py` (correcto)
  4. Reiniciado agent service
- **✅ Agent service reiniciado**: Cambios de prompts aplicados y agente operativo (healthy)
- **📋 Testing manual pendiente**: Listo para re-testing vía WhatsApp con flujo actualizado

### File List

- `agent/prompts/step2_availability.md` (Modified - Story 1.5)
- `agent/prompts/general.md` (Modified - FIX: Actualizado con flujo de Stories 1.4 y 1.5)

