# Guía de Testing Manual - Sistema de Agendamiento

**Fecha:** 2025-11-01
**Versión:** 1.0 - Testing Parcial
**Estado del Sistema:** 60% Implementado

---

## 🎯 Objetivo

Esta guía te permitirá probar manualmente las funcionalidades implementadas hasta ahora del sistema de agendamiento de citas a través de WhatsApp/Chatwoot.

---

## ⚙️ Prerequisitos

### 1. Servicios Levantados

```bash
# Verificar que todos los servicios estén corriendo
docker-compose ps

# Deberías ver:
# ✅ atrevete-agent (healthy)
# ✅ atrevete-api (healthy)
# ✅ atrevete-postgres (healthy)
# ✅ atrevete-redis (healthy)
# ✅ atrevete-archiver (healthy/starting)
```

### 2. Verificar Logs

```bash
# Ver logs del agente (para debugging durante testing)
docker-compose logs -f agent

# Ver logs de la API (para ver webhooks de Chatwoot)
docker-compose logs -f api
```

### 3. Acceso a Chatwoot

- **URL:** Tu instancia de Chatwoot
- **Account ID:** Configurado en `.env` como `CHATWOOT_ACCOUNT_ID`
- **Webhook Token:** Configurado en `.env` como `CHATWOOT_WEBHOOK_TOKEN`

---

## 🧪 Estado Actual del Sistema

### ✅ LO QUE FUNCIONA (Testeable)

| Componente | Estado | Testeable |
|------------|--------|-----------|
| **Fase 1: Selección de Servicios** | ✅ Completo | ✅ SÍ |
| - Validación de categorías mixtas | ✅ | ✅ SÍ |
| **Fase 2: Disponibilidad** | ✅ Completo | ✅ SÍ |
| - Consulta multi-calendar | ✅ | ✅ SÍ |
| - Priorización de slots | ✅ | ✅ SÍ |
| - Detección de festivos | ✅ | ✅ SÍ |
| - Sugerencia de alternativas | ✅ | ✅ SÍ |
| **Conversational Agent** | ✅ Completo | ✅ SÍ |
| - FAQs | ✅ | ✅ SÍ |
| - Identificación de cliente | ✅ | ✅ SÍ |
| - Detección de intención de reserva | ✅ | ✅ SÍ |

### ❌ LO QUE NO FUNCIONA (No Testeable)

| Componente | Razón |
|------------|-------|
| **Fase 2: Selección de Slot** | ❌ Nodo no conectado al flujo |
| **Fase 3: Datos del Cliente** | ❌ Nodo no conectado al flujo |
| **Fase 4: Reserva Provisional** | ❌ Nodo no conectado al flujo |
| **Fase 4: Payment Link** | ❌ Nodo no conectado al flujo |
| **Payment Processing** | ❌ No implementado |
| **Booking Expiration** | ❌ No implementado |
| **Validación 3 días** | ❌ No integrada |

---

## 📝 Flujos de Testing

---

## FLUJO 1: FAQ - Horarios ✅ FUNCIONAL

### Objetivo
Probar que el bot responde correctamente a preguntas frecuentes usando la base de datos.

### Conversación de Prueba

```
👤 Cliente: "Hola, ¿a qué hora abrís?"

🤖 Respuesta Esperada:
"¡Hola! 🌸 Nuestro horario es:
- Martes a Viernes: 10:00 a 20:00
- Sábado: 09:00 a 14:00
- Lunes y Domingos: Cerrado

¿En qué más puedo ayudarte? 😊"
```

### Variaciones para Probar

```
👤 "¿Qué días estáis cerrados?"
👤 "¿Abrís los domingos?"
👤 "¿Hasta qué hora trabajáis?"
👤 "¿Cuál es vuestro horario?"
```

### Cómo Verificar

1. **Logs del Agent:**
```bash
docker-compose logs agent | grep "get_faqs"
# Deberías ver: "Calling tool: get_faqs"
```

2. **Respuesta del Bot:**
   - ✅ Menciona horarios correctos (martes-viernes 10-20, sábado 9-14)
   - ✅ Menciona que lunes y domingos está cerrado
   - ✅ Tono amigable en español

---

## FLUJO 2: FAQ - Servicios ✅ FUNCIONAL

### Objetivo
Probar que el bot consulta servicios desde la base de datos en tiempo real.

### Conversación de Prueba

```
👤 Cliente: "¿Qué servicios ofrecéis?"

🤖 Respuesta Esperada:
"Ofrecemos servicios de peluquería y estética 💇‍♀️:

**Peluquería:**
- Corte (25€, 30 min)
- Mechas (60€, 120 min)
- Tinte (50€, 90 min)
- Balayage (70€, 150 min)

**Estética:**
- Manicura (20€, 45 min)
- Pedicura (25€, 60 min)
- Bioterapia Facial (40€, 60 min)

¿Te gustaría reservar algún servicio? 😊"
```

### Variaciones

```
👤 "¿Cuánto cuesta un corte?"
👤 "¿Hacéis mechas?"
👤 "Necesito información sobre vuestros servicios de estética"
👤 "¿Cuánto cuesta la manicura?"
```

### Cómo Verificar

1. **Logs:**
```bash
docker-compose logs agent | grep "get_services"
```

2. **Base de Datos (opcional):**
```bash
docker exec -it atrevete-postgres psql -U atrevete -d atrevete_db -c "SELECT name, price_euros, duration_minutes, category FROM services WHERE is_active = true;"
```

---

## FLUJO 3: Identificación de Cliente ✅ FUNCIONAL

### Objetivo
Probar que el bot identifica clientes nuevos vs recurrentes.

### Para Cliente Nuevo

```
👤 Cliente: "Hola, quiero información"

🤖 Respuesta Esperada:
"¡Hola! 👋 Bienvenida a Atrévete. Soy Maite, tu asistente virtual.
¿En qué puedo ayudarte hoy? 😊"
```

### Para Cliente Recurrente (con historial)

```
👤 Cliente: "Hola"

🤖 Respuesta Esperada:
"¡Hola María! 👋 ¡Qué alegría verte de nuevo! 💕
Vi que la última vez te hiciste mechas con Pilar.
¿En qué puedo ayudarte hoy? 😊"
```

### Cómo Verificar

1. **Logs:**
```bash
docker-compose logs agent | grep "get_customer_by_phone"
docker-compose logs agent | grep "returning_customer"
```

2. **Estado en Redis:**
```bash
docker exec -it atrevete-redis redis-cli
> KEYS checkpoint:*
> HGETALL checkpoint:[conversation_id]
```

---

## FLUJO 4: Detección de Intención de Reserva ✅ FUNCIONAL

### Objetivo
Probar que Claude detecta cuando el cliente quiere reservar y llama `start_booking_flow()`.

### Conversación de Prueba

```
👤 Cliente: "Quiero reservar mechas para el viernes"

🤖 Respuesta Esperada:
[El bot detecta intención y llama start_booking_flow()]

"¡Perfecto! 💇 Te ayudo a reservar mechas.

Tenemos varias opciones de mechas:
- Mechas (Corto-Medio): 60€, 120 min
- Mechas (Largo): 70€, 150 min
- Mechas (Extra): 85€, 180 min

¿Cuál te interesa? 😊"
```

### Variaciones

```
👤 "Quiero cita para corte"
👤 "Dame hora para manicura"
👤 "Necesito reservar"
👤 "¿Tenéis disponible para mechas el viernes?"
```

### Cómo Verificar

1. **Logs del Tool Call:**
```bash
docker-compose logs agent | grep "start_booking_flow"
# Deberías ver: Calling tool: start_booking_flow
```

2. **Estado del Graph:**
```bash
docker-compose logs agent | grep "booking_intent_confirmed"
# Deberías ver: booking_intent_confirmed=True
```

---

## FLUJO 5: Validación de Categorías Mixtas ✅ FUNCIONAL

### Objetivo
Probar que el bot rechaza combinaciones de servicios de diferentes categorías.

### Conversación de Prueba

```
👤 Cliente: "Quiero mechas y manicura"

🤖 Respuesta Esperada:
"Lo siento, [Nombre] 💕, pero no podemos hacer servicios de **peluquería** y **estética** en la misma cita porque trabajamos con profesionales especializados en cada área.

Tienes dos opciones:
1️⃣ **Reservar ambos servicios por separado**: Primero Mechas y luego Manicura
2️⃣ **Elegir solo uno**: ¿Prefieres Mechas o Manicura?

¿Cómo prefieres proceder? 😊"
```

### Respuestas del Cliente

#### Opción 1: Reservar por separado
```
👤 "Por separado"

🤖 Respuesta Esperada:
"Perfecto 😊. Vamos a reservar primero Mechas. ¿Qué día prefieres?"
```

#### Opción 2: Elegir una categoría
```
👤 "Solo mechas"

🤖 Respuesta Esperada:
"Entendido. Vamos a reservar Mechas. ¿Qué día prefieres?"
```

### Cómo Verificar

1. **Logs:**
```bash
docker-compose logs agent | grep "mixed_category_detected"
docker-compose logs agent | grep "validate_booking_request"
```

2. **Estado:**
```bash
docker-compose logs agent | grep "services_by_category"
```

---

## FLUJO 6: Selección de Servicios - 92 Servicios Individuales ✅ ACTUALIZADO

**NOTA:** El sistema ha sido actualizado para ofrecer **92 servicios individuales** (47 Peluquería + 45 Estética).

Ya no existe el sistema de "packs" con descuentos. Todos los servicios se ofrecen de manera individual con sus precios correspondientes.

### Conversación de Prueba

```
👤 Cliente: "Quiero mechas"

🤖 Respuesta Esperada:
"¡Perfecto! 💇 Tenemos varios tipos de mechas:

**Mechas (Corto-Medio):** 60€, 120 min
**Mechas (Largo):** 70€, 150 min
**Mechas (Extra Largo):** 85€, 180 min

¿Cuál te interesa? 😊"
```

### Cómo Verificar

1. **El bot NO debe mencionar packs ni descuentos**
2. **Debe ofrecer servicios individuales del catálogo**
3. **Los precios deben coincidir con la BD:**

```bash
docker exec -it atrevete-postgres psql -U atrevete -d atrevete_db -c "SELECT name, price_euros, duration_minutes FROM services WHERE name LIKE '%Mechas%' AND is_active = true;"
```

---

## FLUJO 7: Consulta de Disponibilidad ✅ FUNCIONAL

### Objetivo
Probar la consulta multi-calendar y presentación de slots disponibles.

### Conversación de Prueba

```
👤 Cliente: "Quiero mechas para el viernes"
🤖 [Bot ofrece opciones de servicio]

👤 Cliente: "Las mechas largas"

🤖 [Bot confirma servicio]
"Perfecto, mechas largo por 70€ (150 minutos). ¿Para el viernes 8 de noviembre?"

👤 Cliente: "El viernes 8 de noviembre"

🤖 Respuesta Esperada:
[Bot consulta 5 calendarios de Google Calendar]

**Caso 1: Hay Disponibilidad**
"Este viernes tenemos libre:
- 15:00 con Marta
- 17:00 con Pilar
- 18:00 con Carmen

¿Cuál horario prefieres? 😊"

**Caso 2: No Hay Disponibilidad**
"Ese viernes no tenemos disponibilidad 😔.
¿Qué tal el sábado 9 de noviembre o el martes 12 de noviembre?"

**Caso 3: Día Festivo**
"Ese día estamos cerrados por festivo 🎉.
¿Qué tal el jueves 7 de noviembre o el sábado 9 de noviembre?"
```

### Cómo Verificar

1. **Logs de Calendar API:**
```bash
docker-compose logs agent | grep "check_availability"
docker-compose logs agent | grep "multi-calendar query"
docker-compose logs agent | grep "stylists_queried"
```

2. **Performance:**
```bash
# La consulta debería tardar < 8 segundos
docker-compose logs agent | grep "completed in"
```

3. **Verificar en Google Calendar:**
   - Abre los calendarios de tus estilistas
   - Verifica que los slots sugeridos estén realmente libres

---

## FLUJO 8: Cliente Indeciso - Consulta Gratuita ✅ FUNCIONAL

### Objetivo
Probar que el bot ofrece consulta gratuita cuando detecta indecisión.

### Conversación de Prueba

```
👤 Cliente: "No sé qué servicio necesito"

🤖 Respuesta Esperada:
"¡No te preocupes! 😊 Entiendo que elegir el servicio perfecto puede ser complicado.

Te ofrecemos una **Consulta Gratuita de 15 minutos** con una de nuestras expertas.
En la consulta, evaluaremos tu cabello y te recomendaremos el tratamiento ideal para ti.

¿Te gustaría agendar una consulta gratuita? 💕"
```

### Variaciones

```
👤 "No estoy segura qué necesito"
👤 "¿Qué me recomendáis?"
👤 "Es mi primera vez, no sé qué servicio elegir"
```

### Cómo Verificar

```bash
docker-compose logs agent | grep "offer_consultation"
docker-compose logs agent | grep "consultation_service_id"
```

---

## 🛑 FLUJOS QUE NO FUNCIONAN (No Testear Aún)

### ❌ FLUJO 9: Selección de Slot - NO FUNCIONAL

**Razón:** El nodo `handle_slot_selection` NO está conectado al flujo de LangGraph.

**Conversación que NO funcionará:**
```
👤 "15:00 con Marta"
🤖 [No responde o responde genéricamente desde conversational_agent]
```

**Cuándo funcionará:** Después de actualizar `conversation_flow.py` con routing.

---

### ❌ FLUJO 10: Datos del Cliente - NO FUNCIONAL

**Razón:** El nodo `collect_customer_data` NO está conectado.

---

### ❌ FLUJO 11: Pago - NO FUNCIONAL

**Razón:** Los nodos `create_provisional_booking` y `generate_payment_link` NO están conectados, y el `payment_processor` no existe.

---

### ❌ FLUJO 12: Validación de 3 Días - NO FUNCIONAL

**Razón:** La validación NO está integrada en `check_availability`.

**Conversación que NO funcionará:**
```
👤 "Quiero cita para mañana"
🤖 [NO rechaza, intenta buscar disponibilidad]
```

**Debería responder:**
```
🤖 "Por política del salón, las citas deben agendarse con al menos 3 días de antelación 😔.
    El primer día disponible es el jueves 4 de noviembre.
    Para casos urgentes, puedo conectarte con el equipo. ¿Deseas hablar con una persona?"
```

---

## 🐛 Debugging Tips

### 1. Ver Estado de la Conversación

```bash
# Conectar a Redis
docker exec -it atrevete-redis redis-cli

# Ver todas las conversaciones activas
KEYS checkpoint:*

# Ver estado de una conversación específica
HGETALL checkpoint:[conversation_id]

# Ver mensajes de la conversación
HGET checkpoint:[conversation_id] messages
```

### 2. Ver Logs Detallados

```bash
# Logs del agent con timestamp
docker-compose logs -f --timestamps agent

# Filtrar por conversation_id
docker-compose logs agent | grep "conversation_id=test-123"

# Ver solo errores
docker-compose logs agent | grep "ERROR"
```

### 3. Verificar Tool Calls

```bash
# Ver qué tools se están llamando
docker-compose logs agent | grep "Calling tool:"

# Ver resultados de tools
docker-compose logs agent | grep "Tool result:"
```

### 4. Verificar Base de Datos

```bash
# Conectar a PostgreSQL
docker exec -it atrevete-postgres psql -U atrevete -d atrevete_db

# Ver servicios activos (92 servicios individuales - sin packs)
SELECT name, price_euros, category, duration_minutes FROM services WHERE is_active = true ORDER BY category, name;

# Ver estilistas activas
SELECT name, category FROM stylists WHERE is_active = true;

# Ver appointments (cuando se implementen)
SELECT * FROM appointments WHERE status = 'provisional';
```

### 5. Reiniciar Sistema Limpio

```bash
# Si algo va mal, reiniciar todo
docker-compose down -v  # ⚠️ BORRA TODOS LOS DATOS
docker-compose up -d --build

# Esperar 10 segundos para que se inicialice
sleep 10

# Verificar estado
docker-compose ps
```

---

## 📊 Checklist de Testing

### Antes de Cada Sesión de Testing

- [ ] Servicios Docker levantados (`docker-compose ps`)
- [ ] Agent healthy (`docker-compose ps | grep agent`)
- [ ] Logs del agent accesibles (`docker-compose logs -f agent`)
- [ ] Chatwoot configurado con webhook correcto
- [ ] Google Calendar API configurada y accesible

### Durante el Testing

- [ ] Documentar cada flujo probado
- [ ] Capturar logs de errores
- [ ] Anotar comportamientos inesperados
- [ ] Verificar tiempos de respuesta

### Después del Testing

- [ ] Revisar logs en busca de warnings/errors
- [ ] Verificar estado de Redis (conversaciones activas)
- [ ] Verificar llamadas a Google Calendar API (quotas)
- [ ] Documentar bugs encontrados

---

## 🎯 Resumen de Testing Actual

### ✅ FUNCIONA (Probar esto):

1. **FAQs:**
   - Horarios
   - Servicios
   - Precios
   - Ubicación
   - Políticas

2. **Identificación:**
   - Cliente nuevo vs recurrente
   - Historial de citas

3. **Booking - Fase 1:**
   - Detección de intención
   - Validación de categorías mixtas
   - ~~Sugerencia de packs~~ (ELIMINADO)
   - ~~Respuesta a pack~~ (ELIMINADO)

4. **Booking - Fase 2 (parcial):**
   - Consulta de disponibilidad multi-calendar
   - Detección de festivos
   - Sugerencia de fechas alternativas

5. **Features Especiales:**
   - Consulta gratuita para indecisos
   - Escalación a humano

### ❌ NO FUNCIONA (No probar):

1. **Booking - Fase 2 (final):**
   - Selección de slot específico

2. **Booking - Fase 3:**
   - Recopilación de datos del cliente
   - Confirmación de nombre
   - Notas del cliente

3. **Booking - Fase 4:**
   - Creación de reserva provisional
   - Generación de payment link
   - Procesamiento de pago
   - Confirmación post-pago
   - Timeout de pago

4. **Validaciones:**
   - Antelación mínima de 3 días
   - Buffer de 10 minutos (se valida pero no está en el flujo)

---

## 📞 Soporte

Si encuentras problemas durante el testing:

1. **Captura logs:**
```bash
docker-compose logs agent > agent-logs.txt
docker-compose logs api > api-logs.txt
```

2. **Reporta el issue con:**
   - Conversación exacta (input del cliente + respuesta del bot)
   - Logs relevantes
   - Estado esperado vs estado actual
   - Timestamp del error

3. **Consulta documentación:**
   - `agendar-cita-architecture.md` - Arquitectura
   - `agendar-cita-implementation-status.md` - Estado actual
   - `CLAUDE.md` - Comandos de desarrollo

---

**Última actualización:** 2025-11-01
**Versión:** 1.0 - Testing Parcial (60% sistema implementado)
