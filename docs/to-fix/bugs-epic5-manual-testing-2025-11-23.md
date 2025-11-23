# Bugs Encontrados en Manual Testing Epic 5

**Fecha:** 2025-11-23
**Tester:** Pepe
**Contexto:** Testing del Response Coherence Layer (Stories 5-7a y 5-7b)

---

## Conversación que Reprodujo los Bugs

```
Usuario: Hola
Bot: ¡Hola, Pepe! 😊 Soy Maite, tu asistente virtual de Atrévete Peluquería. ¿En qué puedo ayudarte hoy?

Usuario: Quiero agendar una cita
Bot: Perfecto, Pepe. Para comenzar, ¿qué servicio te gustaría agendar? Puedes decirme, por ejemplo, "corte de cabello", "tinte", "manicura", o cualquier otro servicio que necesites.

Usuario: corte de pelo
Bot: Tenemos estos servicios de corte de pelo disponibles:
1. Cultura de Color (Corto-Medio) (100 min)
2. Cultura de Color (Largo) (110 min)
3. Cultura de Color (Extra) (120 min)
4. Corte de Flequillo (15 min)
5. Corte de Caballero (40 min)
¿Cuál te gustaría agendar? Puedes responder con el número o el nombre del servicio.

Usuario: 5
Bot: Perfecto, Pepe. Has elegido Corte de Caballero que dura 40 minutos. ¿Quieres agregar algún otro servicio o continuamos?

Usuario: Continua  ← BUG #1: No transiciona
Bot: Para seguir con la reserva, necesito que elijas algún otro servicio si deseas, o dime si quieres ver la lista completa de servicios para elegir más. ¿Quieres que te muestre todos los servicios disponibles?

Usuario: No, solo quiero un corte de caballero
Bot: Perfecto, Pepe. Has seleccionado solo el Corte de Caballero. Ahora, dime si quieres que te ayude a elegir estilista para tu cita.

Usuario: Si  ← BUG #2: Reset completo
Bot: ¡Hola! 🌸 Soy el asistente de Atrévete Peluquería. ¿En qué puedo ayudarte hoy? ¿Te gustaría agendar una cita?
```

---

## Bug #1: "Continua" no se detecta como CONFIRM_SERVICES

### Severidad: ALTA

### Descripción
Cuando el usuario dice "Continua" para confirmar que no quiere más servicios, el sistema NO lo reconoce como intent `CONFIRM_SERVICES` y permanece en estado `SERVICE_SELECTION`.

### Ubicación del Código
**Archivo:** `agent/fsm/intent_extractor.py`
**Línea:** ~150

### Código Actual
```python
# Patrones de desambiguación (línea ~150)
"'Sí', 'eso es todo', 'nada más' = confirm_services"
```

### Problema
Los patrones solo incluyen:
- "Sí"
- "eso es todo"
- "nada más"

**Faltan variaciones comunes en español:**
- "Continua" / "Continúa"
- "Adelante"
- "Vamos"
- "Sigamos"
- "Ya está"
- "Solo eso"
- "Nada más, gracias"

### Propuesta de Fix
Ampliar los patrones de desambiguación:
```python
# Patrones de confirmación de servicios
"'Sí', 'eso es todo', 'nada más', 'continua', 'continúa', 'adelante',
'vamos', 'sigamos', 'ya está', 'solo eso', 'listo' = confirm_services"
```

### Impacto
- Usuario queda atrapado en SERVICE_SELECTION
- Flujo de booking no avanza
- Experiencia frustrante

---

## Bug #2: "Si" causa reset completo de la conversación

### Severidad: CRÍTICA

### Descripción
Cuando el usuario responde "Si" a la pregunta "¿quieres elegir estilista?", el bot reinicia completamente la conversación con el saludo inicial, perdiendo todo el contexto.

### Ubicación del Código (Investigar)
**Archivos posibles:**
1. `agent/fsm/intent_extractor.py:143-151` - Ambigüedad en interpretación de "Si"
2. `agent/nodes/conversational_agent.py` - Manejo de transiciones fallidas
3. `agent/fsm/booking_fsm.py` - Persistencia de estado

### Hipótesis de Causa
1. **Ambigüedad de "Si":** En SERVICE_SELECTION, "Si" puede interpretarse como:
   - `CONFIRM_SERVICES` (correcto)
   - `SELECT_STYLIST` (incorrecto si no hay lista de estilistas)
   - `START_BOOKING` (incorrecto - causa reset)

2. **Pérdida de estado FSM:** El estado FSM no se persiste correctamente en Redis entre mensajes.

3. **Fallback a GENERAL:** Si `_detect_booking_state()` no encuentra flags de estado activos, carga `general.md` que causa el saludo inicial.

### Investigación Requerida
```bash
# Revisar logs para ver qué intent se detectó
docker-compose logs agent | grep -E "intent|FSM|state=" | tail -50

# Verificar estado en Redis
docker exec atrevete-redis redis-cli KEYS "fsm:*"
```

### Propuesta de Fix
1. Mejorar desambiguación de "Si" basada en contexto de pregunta anterior
2. Verificar que FSM.persist() se llama correctamente
3. Agregar logging detallado cuando se detecta transición a IDLE inesperada

### Impacto
- Pérdida total del progreso del booking
- Usuario debe empezar de nuevo
- Bug crítico que rompe completamente el flujo

---

## Bug #3: Estado BOOKED sin transiciones de salida

### Severidad: MEDIA

### Descripción
El estado `BOOKED` está definido como estado terminal con `{}` (sin transiciones válidas), lo que puede causar problemas si el usuario envía más mensajes después de completar un booking.

### Ubicación del Código
**Archivo:** `agent/fsm/booking_fsm.py`
**Línea:** 78

### Código Actual
```python
TRANSITIONS: ClassVar[dict[BookingState, dict[IntentType, BookingState]]] = {
    # ... otros estados ...
    BookingState.BOOKED: {},  # Terminal state, auto-resets to IDLE
}
```

### Problema
El comentario dice "auto-resets to IDLE" pero **NO hay código que haga eso**.

### Propuesta de Fix
Agregar transición de `BOOKED` a `IDLE`:
```python
BookingState.BOOKED: {
    IntentType.START_BOOKING: BookingState.SERVICE_SELECTION,  # Nueva cita
    IntentType.GREETING: BookingState.IDLE,  # Reset explícito
},
```

O implementar auto-reset después de cierto tiempo (ej: 5 minutos post-booking).

### Impacto
- Conversaciones post-booking pueden quedar "colgadas"
- No afectó directamente este bug (aún no llegó a BOOKED)

---

## Bug #4: Búsqueda de servicios retorna resultados incorrectos

### Severidad: MEDIA

### Descripción
Cuando el usuario pide "corte de pelo", la búsqueda retorna "Cultura de Color" que es un servicio de tinte, no de corte.

### Evidencia
```
Usuario: corte de pelo
Bot: Tenemos estos servicios de corte de pelo disponibles:
1. Cultura de Color (Corto-Medio) (100 min)  ← INCORRECTO - es tinte
2. Cultura de Color (Largo) (110 min)       ← INCORRECTO - es tinte
3. Cultura de Color (Extra) (120 min)       ← INCORRECTO - es tinte
4. Corte de Flequillo (15 min)              ← CORRECTO
5. Corte de Caballero (40 min)              ← CORRECTO
```

### Ubicación del Código
**Archivo:** `agent/tools/search_services.py`

### Problema
La búsqueda fuzzy o por categoría está incluyendo servicios de "Cultura de Color" cuando se busca "corte de pelo".

### Investigación Requerida
- Revisar lógica de `search_services` tool
- Verificar categorización de servicios en base de datos
- Verificar query de búsqueda

### Propuesta de Fix
1. Mejorar filtrado por categoría
2. Excluir servicios de color/tinte cuando se busca "corte"
3. O revisar categorización en BD

### Impacto
- Confusión del usuario al ver opciones irrelevantes
- Posible selección incorrecta de servicio

---

## Resumen de Bugs

| # | Bug | Severidad | Archivo Principal | Status |
|---|-----|-----------|-------------------|--------|
| 1 | "Continua" no detectado | ALTA | intent_extractor.py | Pendiente |
| 2 | "Si" causa reset | CRÍTICA | intent_extractor.py / conversational_agent.py | Pendiente |
| 3 | BOOKED sin salida | MEDIA | booking_fsm.py | Pendiente |
| 4 | Búsqueda servicios incorrecta | MEDIA | search_services.py | Pendiente |

---

## Próximos Pasos

1. [ ] Investigar Bug #2 con logs detallados (más crítico)
2. [ ] Fix Bug #1 - Ampliar patrones de CONFIRM_SERVICES
3. [ ] Fix Bug #2 - Mejorar desambiguación + verificar persistencia
4. [ ] Fix Bug #3 - Agregar transiciones desde BOOKED
5. [ ] Fix Bug #4 - Mejorar búsqueda de servicios
6. [ ] Re-test manual después de fixes
