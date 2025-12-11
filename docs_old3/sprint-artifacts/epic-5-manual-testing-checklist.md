# Epic 5: Manual Testing Checklist

**Fecha:** 2025-11-23
**Objetivo:** Validar funcionamiento completo de la arquitectura FSM Híbrida v4.1 con Response Coherence Layer

---

## Pre-requisitos

- [ ] Rebuild del agente con cambios de 5-7a y 5-7b: `docker-compose up -d --build agent`
- [ ] Verificar logs del agente: `docker-compose logs -f agent`
- [ ] Tener WhatsApp abierto para testing

---

## Sección A: Casos Base del Flujo FSM (Stories 5-1 a 5-6)

Estos son los 8 casos originales de Story 5-5, re-testeados con el nuevo Response Coherence Layer.

### A1. Happy Path Simple
**Objetivo:** Flujo completo de booking sin interrupciones

| Paso | Acción Usuario | Respuesta Esperada | Estado FSM | ✅/❌ |
|------|----------------|-------------------|------------|-------|
| 1 | "Hola" | Saludo + pregunta qué necesita | IDLE | |
| 2 | "Quiero pedir cita" | Lista de servicios numerada | SERVICE_SELECTION | |
| 3 | "Corte largo" o "1" | Confirma servicio + pregunta si más | SERVICE_SELECTION | |
| 4 | "No, eso es todo" | Lista de estilistas numerada | STYLIST_SELECTION | |
| 5 | "Ana" o "1" | Horarios disponibles numerados | SLOT_SELECTION | |
| 6 | "El primero" o "1" | Solicita nombre | CUSTOMER_DATA | |
| 7 | "Me llamo Juan" | Resumen + confirmación | CONFIRMATION | |
| 8 | "Sí, confirmo" | Cita creada + detalles | BOOKED | |

**Verificar:**
- [ ] Evento creado en Google Calendar con emoji 🟡
- [ ] Respuestas naturales en español
- [ ] NO menciona estilistas antes de confirmar servicios
- [ ] NO menciona horarios antes de seleccionar estilista

**Notas:**
```
_____________________________________________________
```

---

### A2. Múltiples Servicios
**Objetivo:** Acumulación de servicios antes de confirmar

| Paso | Acción Usuario | Respuesta Esperada | ✅/❌ |
|------|----------------|-------------------|-------|
| 1 | "Quiero cita" | Lista servicios | |
| 2 | "Corte largo" | Confirma + pregunta más | |
| 3 | "Tinte raíz" | Confirma ambos + pregunta más | |
| 4 | "Peinado" | Confirma 3 servicios + pregunta más | |
| 5 | "No más" | Lista estilistas | |

**Verificar:**
- [ ] Los 3 servicios aparecen en el resumen final
- [ ] Duración combinada correcta
- [ ] Servicios NO se "olvidan" entre selecciones

**Notas:**
```
_____________________________________________________
```

---

### A3. Cancelar Mid-Flow
**Objetivo:** Usuario cancela durante el flujo de booking

| Paso | Acción Usuario | Respuesta Esperada | ✅/❌ |
|------|----------------|-------------------|-------|
| 1 | "Quiero cita" | Lista servicios | |
| 2 | "Corte largo" | Confirma servicio | |
| 3 | "Cancelar" o "No quiero" | Confirma cancelación, ofrece ayuda | |
| 4 | "Quiero cita" | Empieza de nuevo (IDLE) | |

**Verificar:**
- [ ] FSM resetea a IDLE
- [ ] Datos anteriores NO persisten
- [ ] Puede empezar nuevo booking

**Notas:**
```
_____________________________________________________
```

---

### A4. Out of Order - Confirmar sin servicios
**Objetivo:** Usuario intenta saltar pasos

| Paso | Acción Usuario | Respuesta Esperada | ✅/❌ |
|------|----------------|-------------------|-------|
| 1 | "Quiero confirmar mi cita" | Redirige amablemente a servicios | |
| 2 | "Reservar para mañana a las 10" | Redirige a seleccionar servicio primero | |

**Verificar:**
- [ ] Mensaje de redirección es amigable (no robótico)
- [ ] Guía al paso correcto
- [ ] NO se queda "colgado"

**Notas:**
```
_____________________________________________________
```

---

### A5. Cambiar de Opinión
**Objetivo:** Usuario quiere cambiar servicio ya seleccionado

| Paso | Acción Usuario | Respuesta Esperada | ✅/❌ |
|------|----------------|-------------------|-------|
| 1 | "Quiero cita" | Lista servicios | |
| 2 | "Corte largo" | Confirma servicio | |
| 3 | "No, mejor corte corto" | Cambia servicio | |

**Verificar:**
- [ ] Permite cambio
- [ ] Servicio anterior reemplazado
- [ ] Flujo continúa normalmente

**Notas:**
```
_____________________________________________________
```

---

### A6. FAQ Durante Booking
**Objetivo:** Preguntas informativas no interrumpen el flujo

| Paso | Acción Usuario | Respuesta Esperada | ✅/❌ |
|------|----------------|-------------------|-------|
| 1 | "Quiero cita" | Lista servicios | |
| 2 | "Corte largo" | Confirma servicio | |
| 3 | "¿Cuál es el horario del salón?" | Responde horario + retoma booking | |
| 4 | "No más servicios" | Lista estilistas (NO reinicia) | |

**Verificar:**
- [ ] FAQ respondida correctamente
- [ ] Estado FSM NO se pierde
- [ ] Servicios seleccionados se mantienen

**Notas:**
```
_____________________________________________________
```

---

### A7. Respuesta Numérica
**Objetivo:** Selección por número funciona

| Paso | Acción Usuario | Respuesta Esperada | ✅/❌ |
|------|----------------|-------------------|-------|
| 1 | "Cita" | Lista servicios | |
| 2 | "1" | Primer servicio seleccionado | |
| 3 | "No" | Lista estilistas | |
| 4 | "2" | Segunda estilista seleccionada | |
| 5 | "3" | Tercer horario seleccionado | |

**Verificar:**
- [ ] Números interpretados correctamente en cada estado
- [ ] "1" en servicios ≠ "1" en estilistas (disambiguation)

**Notas:**
```
_____________________________________________________
```

---

### A8. Respuesta Texto
**Objetivo:** Selección por texto funciona

| Paso | Acción Usuario | Respuesta Esperada | ✅/❌ |
|------|----------------|-------------------|-------|
| 1 | "Necesito una cita para teñirme" | Identifica tinte | |
| 2 | "Con María" | Selecciona estilista María | |
| 3 | "El de las once" | Selecciona horario 11:00 | |

**Verificar:**
- [ ] Texto natural interpretado correctamente
- [ ] No requiere coincidencia exacta

**Notas:**
```
_____________________________________________________
```

---

## Sección B: Response Coherence Layer (Stories 5-7a y 5-7b)

Estos casos verifican específicamente el nuevo sistema de validación de respuestas.

### B1. NO Muestra Estilistas en SERVICE_SELECTION
**Objetivo:** Validar FORBIDDEN_PATTERNS de Story 5-7a

| Paso | Acción Usuario | Respuesta Esperada | ✅/❌ |
|------|----------------|-------------------|-------|
| 1 | "Quiero cita" | Lista servicios SIN nombres de estilistas | |
| 2 | "¿Quién me puede atender?" | Explica que primero debe elegir servicio | |

**Verificar:**
- [ ] Respuesta NO menciona: Ana, María, Carlos, Pilar, Laura
- [ ] Respuesta NO muestra horarios específicos
- [ ] Si el LLM intentó mostrar estilistas, debe haberse regenerado

**Logs a revisar:** Buscar "response_coherence" o "regeneration"
```
_____________________________________________________
```

---

### B2. NO Muestra Horarios en STYLIST_SELECTION
**Objetivo:** Validar que no salta pasos

| Paso | Acción Usuario | Respuesta Esperada | ✅/❌ |
|------|----------------|-------------------|-------|
| 1 | "Cita para corte" | Servicios | |
| 2 | "Eso" | Confirma servicio | |
| 3 | "No más" | Lista estilistas SIN horarios | |
| 4 | "¿A qué hora hay hueco?" | Redirige a elegir estilista primero | |

**Verificar:**
- [ ] En paso 3: NO muestra horarios específicos (HH:MM)
- [ ] NO muestra días de la semana con disponibilidad
- [ ] Solo muestra lista de estilistas

**Notas:**
```
_____________________________________________________
```

---

### B3. NO Confirma en SLOT_SELECTION
**Objetivo:** No confirmación prematura

| Paso | Acción Usuario | Respuesta Esperada | ✅/❌ |
|------|----------------|-------------------|-------|
| 1-4 | (llegar a SLOT_SELECTION) | Horarios disponibles | |
| 5 | "El primero" | Solicita nombre, NO confirma cita | |

**Verificar:**
- [ ] Respuesta NO dice "cita confirmada" o "reservada"
- [ ] Solicita datos del cliente antes de confirmar
- [ ] Guidance "PROHIBIDO: confirmación de cita" funcionando

**Notas:**
```
_____________________________________________________
```

---

### B4. Guidance Visible en Respuestas
**Objetivo:** Las directivas proactivas (5-7b) mejoran coherencia

| Test | Descripción | ✅/❌ |
|------|-------------|-------|
| G1 | En SERVICE_SELECTION: pregunta "¿deseas agregar otro servicio?" | |
| G2 | En STYLIST_SELECTION: pregunta "¿con quién te gustaría?" | |
| G3 | En SLOT_SELECTION: pregunta "¿qué horario te viene mejor?" | |
| G4 | En CUSTOMER_DATA: pregunta por nombre | |
| G5 | En CONFIRMATION: muestra resumen y pregunta "¿confirmas?" | |

**Notas:**
```
_____________________________________________________
```

---

### B5. Regeneración Funciona (Caso Edge)
**Objetivo:** Si LLM genera respuesta incoherente, se regenera

Este caso es difícil de provocar intencionalmente, pero verificar en logs:

| Verificación | ✅/❌ |
|--------------|-------|
| En logs: buscar "coherence_validation" | |
| Si hay "is_coherent: false": verificar regeneración | |
| Respuesta final al usuario siempre coherente | |

**Comando para revisar logs:**
```bash
docker-compose logs agent | grep -i "coherence\|regenerat\|violation"
```

**Notas:**
```
_____________________________________________________
```

---

## Sección C: Casos Edge y Robustez

### C1. Conversación Interrumpida (TTL 24h)
**Objetivo:** FSM persiste entre mensajes separados en el tiempo

| Paso | Acción Usuario | Tiempo | ✅/❌ |
|------|----------------|--------|-------|
| 1 | "Quiero cita" | T+0 | |
| 2 | "Corte largo" | T+5min | |
| 3 | (esperar) | T+30min | |
| 4 | "No más servicios" | T+30min | |

**Verificar:**
- [ ] FSM mantiene estado después de 30 minutos
- [ ] Servicios seleccionados persisten
- [ ] TTL de 24h según ADR-007

**Notas:**
```
_____________________________________________________
```

---

### C2. Mensajes Ambiguos
**Objetivo:** Intent extraction maneja ambigüedad

| Mensaje | Estado FSM | Interpretación Esperada | ✅/❌ |
|---------|------------|------------------------|-------|
| "1" | SERVICE_SELECTION | Primer servicio | |
| "1" | STYLIST_SELECTION | Primera estilista | |
| "1" | SLOT_SELECTION | Primer horario | |
| "Sí" | SERVICE_SELECTION | Confirmar servicios | |
| "Sí" | CONFIRMATION | Confirmar booking | |

**Notas:**
```
_____________________________________________________
```

---

### C3. Error Recovery
**Objetivo:** Sistema se recupera de errores

| Escenario | Comportamiento Esperado | ✅/❌ |
|-----------|------------------------|-------|
| Timeout de Google Calendar | Mensaje de error + retry | |
| Intent UNKNOWN | Pide aclaración amablemente | |
| Mensaje vacío o solo emojis | Pide más información | |

**Notas:**
```
_____________________________________________________
```

---

## Resumen de Resultados

| Sección | Casos | Pasados | Fallidos |
|---------|-------|---------|----------|
| A: Flujo FSM Base | 8 | | |
| B: Response Coherence | 5 | | |
| C: Edge Cases | 3 | | |
| **TOTAL** | **16** | | |

---

## Bugs Encontrados

| # | Descripción | Severidad | Story Afectada |
|---|-------------|-----------|----------------|
| 1 | | | |
| 2 | | | |
| 3 | | | |

---

## Notas Adicionales

```
_____________________________________________________________
_____________________________________________________________
_____________________________________________________________
```

---

## Siguiente Paso

Después de completar este testing:
1. Reportar resultados a Bob (Scrum Master)
2. Completar retrospectiva de Epic 5
3. Preparar Epic 2 (Sistema de Confirmación y Recordatorios)
