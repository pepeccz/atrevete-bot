# Story 1.3: Presentación de Servicios en Lista Numerada

Status: ready-for-dev

## Story

As a **cliente**,
I want **ver los servicios disponibles en una lista numerada clara**,
so that **pueda seleccionar fácilmente el servicio que deseo**.

## Acceptance Criteria

1. **AC1**: El agente presenta servicios en formato lista numerada con nombre y duración
   - Given el cliente indica intención de agendar cita
   - When el agente presenta servicios disponibles
   - Then se muestran en formato "1. {Servicio} ({duración} min)"
   - And la lista contiene máximo 5 resultados por búsqueda
   - And cada entrada es clara y legible

2. **AC2**: El sistema acepta respuestas por número o texto descriptivo
   - Given el cliente responde a la lista de servicios
   - When el cliente responde con número (ej: "1") o texto (ej: "corte")
   - Then el sistema identifica el servicio correcto
   - And procede al siguiente paso del flujo

3. **AC3**: La presentación usa tono amigable y profesional en español
   - Given el agente presenta la lista
   - When genera el mensaje
   - Then usa lenguaje natural amigable
   - And mantiene tono profesional
   - And todo el texto está en español

## Tasks / Subtasks

- [ ] **Task 1: Actualizar prompts para listas numeradas de servicios** (AC: 1, 3)
  - [ ] 1.1 Leer prompts actuales: `agent/prompts/step1_general.md` y `agent/prompts/step2_availability.md`
  - [ ] 1.2 Identificar secciones que presentan servicios
  - [ ] 1.3 Modificar instrucciones para formato lista numerada: "1. {nombre} ({duración} min)"
  - [ ] 1.4 Agregar instrucción: máximo 5 resultados por búsqueda
  - [ ] 1.5 Incluir ejemplo de formato esperado en prompt
  - [ ] 1.6 Verificar tono amigable y profesional en español

- [ ] **Task 2: Configurar truncación en search_services tool** (AC: 1)
  - [ ] 2.1 Revisar código actual de `agent/tools/search_services.py`
  - [ ] 2.2 Verificar que max_results esté configurado en 5
  - [ ] 2.3 Confirmar que output incluye nombre y duración
  - [ ] 2.4 Si necesario, ajustar formato de output

- [ ] **Task 3: Implementar parsing flexible de respuestas** (AC: 2)
  - [ ] 3.1 Revisar cómo el agente procesa respuestas de usuario
  - [ ] 3.2 Verificar que LLM puede identificar servicios por número o nombre
  - [ ] 3.3 Agregar instrucción en prompt para aceptar ambos formatos
  - [ ] 3.4 Testear con ejemplos: "1", "opción 1", "corte", "el primero"

- [ ] **Task 4: Testing de presentación de servicios** (AC: 1, 2, 3)
  - [ ] 4.1 Test manual: Solicitar servicios y verificar formato lista numerada
  - [ ] 4.2 Test manual: Responder con número y verificar identificación correcta
  - [ ] 4.3 Test manual: Responder con texto y verificar identificación correcta
  - [ ] 4.4 Test manual: Verificar máximo 5 resultados mostrados
  - [ ] 4.5 Test manual: Verificar tono amigable en español

- [ ] **Task 5: Documentar cambios en prompts** (AC: 1, 3)
  - [ ] 5.1 Actualizar Dev Notes con formato de lista implementado
  - [ ] 5.2 Documentar ejemplos de respuestas aceptadas
  - [ ] 5.3 Agregar referencias a FRs cubiertos

## Dev Notes

### Learnings from Previous Story

**From Story 1-2-correccion-de-herramienta-book-con-emoji-calendar (Status: done)**

**Key Implementations Available:**
- ✅ Booking flow completamente funcional con emoji 🟡 en Calendar
- ✅ Transacción atómica DB → Calendar con rollback automático
- ✅ Mensaje de confirmación incluye info sobre confirmación 48h
- ✅ Estado PENDING implementado correctamente

**Not Directly Relevant to This Story:**
- Esta story se enfoca en prompts y UX, no modifica código Python
- No hay dependencias técnicas con Story 1.2

**Relevant Patterns:**
- Mantener consistencia de tono amigable y profesional en español
- Continuar usando formato claro y estructurado en prompts

[Source: docs/sprint-artifacts/1-2-correccion-de-herramienta-book-con-emoji-calendar.md]

### Contexto Arquitectural

**Componentes Afectados:**

Esta story modifica únicamente **prompts** - no afecta código Python:
- `agent/prompts/step1_general.md` - Presentación inicial de servicios
- `agent/prompts/step2_availability.md` - Presentación durante flujo de disponibilidad

**Herramientas Existentes:**

- `search_services` tool en `agent/tools/search_services.py`:
  - Ya configurado con max_results = 5
  - Output incluye: id, name, duration_minutes, category
  - No requiere modificaciones de código

**Estrategia de Optimización v3.2:**

Según Architecture (Optimizaciones v3.2):
- Tool output truncation: `search_services` ya retorna máximo 5 resultados
- Output simplificado: Campo `id` removido para reducir tokens
- Esta story aprovecha estas optimizaciones existentes

**Pattern: Numbered Lists for UX (FR38)**

De Architecture:
- Todas las selecciones deben usar listas numeradas
- El sistema acepta respuestas por número o texto (FR39)
- El LLM (GPT-4.1-mini) tiene capacidad natural de entender ambos formatos

### Project Structure Notes

**Archivos a Modificar:**
- `agent/prompts/step1_general.md` - Agregar instrucciones para formato lista numerada
- `agent/prompts/step2_availability.md` - Idem si presenta servicios

**NO Modificar:**
- `agent/tools/search_services.py` - Ya configurado correctamente
- Código Python - Esta story es solo prompts

**Alineación con Estructura:**
- Mantener organización modular de prompts (1 archivo por estado)
- Seguir convenciones de formato markdown existentes
- No duplicar instrucciones entre archivos

### Prompt Design Guidelines

**Formato de Lista Numerada:**

```
Tenemos estos servicios disponibles:

1. Corte de Caballero (30 min)
2. Tinte Completo (90 min)
3. Mechas (120 min)
4. Manicura (45 min)
5. Peinado (30 min)

¿Cuál te gustaría agendar? Puedes responder con el número o el nombre del servicio.
```

**Instrucciones para LLM:**

En los prompts, agregar sección explícita:

```markdown
## Presentación de Servicios

CRITICAL: Cuando presentes servicios, SIEMPRE usa formato lista numerada:
- Formato: "{número}. {nombre del servicio} ({duración} min)"
- Máximo 5 servicios por mensaje
- Invita al cliente a responder con número o nombre
- Ejemplo: "1. Corte de Caballero (30 min)"
```

**Aceptación de Respuestas:**

El LLM debe entender múltiples formatos:
- Número: "1", "2", "opción 3"
- Texto: "corte", "el primero", "mechas"
- Mixed: "quiero el 2", "me gustaría el corte"

No requiere código adicional - capacidad natural del LLM.

### Testing Strategy

**Testing Manual (No Unit Tests):**

Esta story modifica solo prompts, por lo tanto:
- ✅ Testing manual conversacional
- ❌ NO requiere unit tests automatizados
- ✅ Verificación de formato y tono

**Casos de Prueba:**

1. **Test: Presentación de servicios**
   - Input: "Quiero agendar una cita"
   - Expected: Lista numerada con 5 servicios máximo
   - Verify: Formato "1. {Servicio} ({duración} min)"

2. **Test: Selección por número**
   - Input: "1" o "Opción 1"
   - Expected: Sistema identifica servicio correctamente
   - Verify: Procede a siguiente paso sin confusión

3. **Test: Selección por texto**
   - Input: "Corte" o "Quiero el corte"
   - Expected: Sistema identifica servicio por fuzzy match
   - Verify: Procede correctamente

4. **Test: Tono y lenguaje**
   - Verify: Mensajes en español amigable y profesional
   - Verify: No usa lenguaje robótico o excesivamente formal

**Comandos de Testing:**

```bash
# Testing manual vía WhatsApp (recomendado)
# 1. Enviar mensaje: "Quiero una cita"
# 2. Verificar formato de lista numerada
# 3. Probar respuestas: "1", "corte", "el primero"

# Verificar prompts actualizados
cat agent/prompts/step1_general.md | grep -A 10 "lista numerada"
cat agent/prompts/step2_availability.md | grep -A 10 "lista numerada"

# Reiniciar agent para aplicar cambios en prompts
docker-compose restart agent
```

### FRs Cubiertos

Esta story implementa:
- **FR1**: Sistema presenta servicios en lista numerada
- **FR38**: Todas las selecciones usan listas numeradas
- **FR39**: Sistema acepta respuestas por número o texto

**Nota:** FR38 y FR39 son de UX general, esta story los implementa específicamente para servicios.

### NFRs Aplicables

- **NFR1**: Respuesta bot <5s - Listas numeradas reducen tokens y latencia
- **NFR10**: Cobertura tests 85% - NO aplica (solo prompts, testing manual)
- **NFR11**: Logs estructurados - NO aplica (sin cambios de código)

### Referencias

- [Source: docs/prd.md#FR1] - Servicios en lista numerada
- [Source: docs/prd.md#FR38-FR39] - UX con listas numeradas
- [Source: docs/epics.md#Story-1.3] - Requisitos originales
- [Source: docs/architecture.md#Optimizations-v3.2] - Tool output truncation
- [Source: docs/sprint-artifacts/tech-spec-epic-1.md#Detailed-Design] - Módulos afectados

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2025-11-20 | Story drafted from epics, tech-spec, architecture, and previous story learnings | SM Agent (create-story workflow) |

## Dev Agent Record

### Context Reference

- `docs/sprint-artifacts/1-3-presentacion-de-servicios-en-lista-numerada.context.xml`

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
