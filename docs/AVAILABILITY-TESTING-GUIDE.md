# Guía de Testing: Flujo de Disponibilidad de Citas

## 📋 Índice

1. [Requisitos Previos](#requisitos-previos)
2. [Actualización de Estilistas](#actualización-de-estilistas)
3. [Test Automatizado](#test-automatizado)
4. [Test Manual](#test-manual)
5. [Validación de Resultados](#validación-de-resultados)
6. [Troubleshooting](#troubleshooting)

---

## 1. Requisitos Previos

### Servicios Activos

Todos los contenedores Docker deben estar corriendo:

```bash
docker compose ps

# Deberías ver:
# - agent (running)
# - api (running)
# - redis (running)
# - postgres (running)
# - chatwoot (opcional)
```

### Base de Datos Configurada

```bash
# Verificar conexión a la base de datos
docker compose exec postgres psql -U atrevete -d atrevete_db -c "SELECT COUNT(*) FROM stylists;"

# Deberías ver al menos 6 estilistas activos
```

### Google Calendar Configurado

```bash
# Verificar que la service account esté configurada
ls -la /path/to/service-account-key.json

# Verificar variable de entorno
docker compose exec agent env | grep GOOGLE_APPLICATION_CREDENTIALS
```

### Datos Seed Actualizados

```bash
# Verificar que los servicios existen
docker compose exec postgres psql -U atrevete -d atrevete_db -c "SELECT name, category FROM services WHERE is_active = true;"

# Deberías ver servicios como:
# - Mechas (Hairdressing)
# - Corte (Hairdressing)
# - Pack "Mechas + Corte"
```

---

## 2. Actualización de Estilistas

### Paso 1: Actualizar Base de Datos

Ejecuta el script de actualización para configurar los 6 estilistas con sus Google Calendar IDs reales:

```bash
# Ejecutar script de actualización
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
./venv/bin/python scripts/update_stylists_db.py
```

**Responde "yes" cuando se te pida confirmación.**

El script:
- Muestra los estilistas actuales
- Desactiva todos los estilistas existentes (is_active=False)
- Crea/actualiza los 6 nuevos estilistas:
  - **Victor** (Hairdressing)
  - **Ana** (Hairdressing)
  - **Marta** (Hairdressing)
  - **Ana Maria** (Hairdressing)
  - **Pilar** (Hairdressing)
  - **Rosa** (Aesthetics)
- Muestra el estado final

### Paso 2: Verificar Actualización

```bash
# Verificar estilistas en la base de datos
docker compose exec postgres psql -U atrevete -d atrevete_db -c \
"SELECT id, name, category, is_active, LEFT(google_calendar_id, 40) as calendar_id_preview FROM stylists ORDER BY name;"
```

**Deberías ver:**
- 6 estilistas con `is_active = true`
- Calendar IDs que terminan en `@group.calendar.google.com`
- 5 en categoría Hairdressing, 1 en Aesthetics

---

## 3. Test Automatizado

### Ejecutar Test Script

El test automatizado simula el flujo completo desde intención de reserva hasta recibir slots disponibles:

```bash
# Ejecutar test
./venv/bin/python scripts/test_availability_flow.py
```

### Qué Hace el Test

El script envía 2 mensajes automáticamente:

**Mensaje 1:** "Quiero reservar mechas y corte para el viernes"
- ✅ Detecta intención de reserva
- ✅ Activa flujo transaccional (Tier 2)
- ✅ Ofrece pack "Mechas + Corte"

**Mensaje 2:** "Sí, me interesa el pack"
- ✅ Acepta el pack
- ✅ Valida servicios (misma categoría)
- ✅ Consulta disponibilidad en Google Calendar
- ✅ Presenta slots disponibles

### Output Esperado

```
🧪 BOOKING AVAILABILITY FLOW TEST
================================================================================

📋 Test Configuration:
   Conversation ID: test-availability-1730288000
   Customer Phone: +34623226544
   Customer Name: Test User

📤 STEP: 1. Booking Intent Detection
💬 Sending message: "Quiero reservar mechas y corte para el viernes"
✅ Message published to Redis

🎯 EXPECTED BEHAVIOR:
   1. conversational_agent detects booking intent
   2. Claude calls start_booking_flow() tool
   3. State: booking_intent_confirmed = True
   ...

📤 STEP: 2. Pack Suggestion
🎯 EXPECTED BEHAVIOR:
   1. suggest_pack node executes
   2. Calculates savings (60€ vs 85€ = 25€)
   ...

📤 STEP: 3. Pack Acceptance
💬 Sending message: "Sí, me interesa el pack"
...

📤 STEP: 5. Availability Check (Google Calendar)
🎯 EXPECTED BEHAVIOR:
   1. check_availability node executes
   2. Queries Google Calendar for 5 stylists in PARALLEL
   3. Returns available slots
   ...

✅ TEST SEQUENCE COMPLETE
```

---

## 4. Test Manual

Si prefieres probar manualmente, sigue esta secuencia:

### Opción A: Con Script Bash

```bash
# Mensaje 1: Intención de reserva
./scripts/send_test_message.sh "+34623226544" \
  "Quiero reservar mechas y corte para el viernes" \
  "test-manual-001" \
  "Pepe"

# Espera ~5 segundos, verifica respuesta del bot

# Mensaje 2: Aceptar pack
./scripts/send_test_message.sh "+34623226544" \
  "Sí, me interesa el pack" \
  "test-manual-001" \
  "Pepe"

# Espera ~10 segundos, verifica disponibilidad presentada
```

### Opción B: Con Python Script

```python
#!/usr/bin/env python3
import asyncio
import json
import redis.asyncio as redis

async def send_test():
    client = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

    payload = {
        "conversation_id": "test-manual-002",
        "customer_phone": "+34623226544",
        "message_text": "Quiero reservar mechas para el viernes",
        "customer_name": "Test User"
    }

    await client.publish("incoming_messages", json.dumps(payload))
    await client.aclose()

asyncio.run(send_test())
```

### Opción C: Con Redis CLI

```bash
# Mensaje 1
redis-cli PUBLISH incoming_messages '{
  "conversation_id": "test-redis-003",
  "customer_phone": "+34623226544",
  "message_text": "Quiero mechas y corte para el viernes",
  "customer_name": "Pepe"
}'

# Esperar respuesta del bot...

# Mensaje 2
redis-cli PUBLISH incoming_messages '{
  "conversation_id": "test-redis-003",
  "customer_phone": "+34623226544",
  "message_text": "Sí, quiero el pack",
  "customer_name": "Pepe"
}'
```

---

## 5. Validación de Resultados

### 5.1 Monitorear Logs en Tiempo Real

Abre 2 terminales:

**Terminal 1: Agent Logs (Flujo principal)**
```bash
docker compose logs agent -f --tail 50 | \
grep -E '(Booking intent|start_booking_flow|suggest_pack|validate_booking|check_availability|available_slots|prioritized_slots)'
```

**Terminal 2: Google Calendar API Calls**
```bash
docker compose logs agent -f --tail 50 | \
grep -E '(Google Calendar|Fetching calendar|calendar events|fetch_calendar_events)'
```

### 5.2 Verificar Estado en Redis

```bash
# Ver estado completo de la conversación
redis-cli --raw GET "conversation:test-availability-<timestamp>" | python -m json.tool

# Buscar campos clave:
# - booking_intent_confirmed: true
# - requested_services: [UUID list]
# - pack_id: UUID
# - available_slots: [array of slots]
# - prioritized_slots: [top 3 slots]
```

### 5.3 Verificar Respuesta del Bot

El bot debe responder algo como:

```
¡Perfecto! He revisado la disponibilidad para el viernes.

📅 Tenemos las siguientes opciones disponibles:

✅ 10:00 - Marta (3h)
✅ 15:30 - Victor (3h)
✅ 17:00 - Ana (3h)

¿Cuál de estos horarios te viene mejor?
```

### 5.4 Validación Técnica (Checklist)

- [ ] **Booking Intent Detected**
  ```bash
  # Buscar en logs:
  docker compose logs agent | grep "Booking intent confirmed"
  ```

- [ ] **start_booking_flow() Called**
  ```bash
  docker compose logs agent | grep "start_booking_flow"
  ```

- [ ] **Pack Suggested**
  ```bash
  docker compose logs agent | grep -E '(suggest_pack|Pack suggestion)'
  ```

- [ ] **Pack Accepted**
  ```bash
  docker compose logs agent | grep "Pack response: accept"
  ```

- [ ] **Services Validated**
  ```bash
  docker compose logs agent | grep "Validation passed"
  ```

- [ ] **Google Calendar Queried**
  ```bash
  docker compose logs agent | grep "Fetching calendar events"
  # Deberías ver 5 llamadas (una por cada estilista de peluquería)
  ```

- [ ] **Slots Generated**
  ```bash
  docker compose logs agent | grep "available_slots"
  ```

- [ ] **Top 3 Slots Prioritized**
  ```bash
  docker compose logs agent | grep "prioritized_slots"
  ```

---

## 6. Troubleshooting

### Problema: "No stylists found for category Hairdressing"

**Causa:** Estilistas no actualizados en la base de datos.

**Solución:**
```bash
# Verificar estilistas
docker compose exec postgres psql -U atrevete -d atrevete_db -c \
"SELECT name, category, is_active FROM stylists;"

# Si no hay activos, ejecutar update script
DATABASE_URL="..." ./venv/bin/python scripts/update_stylists_db.py
```

### Problema: "Google Calendar API Error: 404"

**Causa:** Calendar ID incorrecto o calendario no compartido con service account.

**Solución:**
1. Verificar calendar IDs en DB:
```bash
docker compose exec postgres psql -U atrevete -d atrevete_db -c \
"SELECT name, google_calendar_id FROM stylists WHERE is_active = true;"
```

2. Verificar que cada calendario esté compartido con la service account email:
   - Abrir Google Calendar
   - Ir a configuración del calendario
   - Compartir con: `service-account@project.iam.gserviceaccount.com`
   - Permisos: "Ver todos los detalles de eventos"

### Problema: "Service 'mechas' not found"

**Causa:** Servicios no seeded en la base de datos.

**Solución:**
```bash
# Verificar servicios
docker compose exec postgres psql -U atrevete -d atrevete_db -c \
"SELECT id, name, category FROM services WHERE name ILIKE '%mecha%' OR name ILIKE '%corte%';"

# Si no existen, ejecutar seed de servicios
DATABASE_URL="..." ./venv/bin/python database/seeds/services.py
```

### Problema: "No available slots found"

**Causa:** Todos los slots están ocupados o no hay horarios de negocio en la fecha solicitada.

**Solución:**
1. Verificar horarios de negocio:
   - Lunes-Viernes: 10:00-20:00
   - Sábado: 10:00-14:00
   - Domingo: Cerrado

2. Verificar si la fecha es festivo:
```bash
docker compose logs agent | grep "holiday_detected"
```

3. Probar con una fecha diferente:
```bash
# Probar con "el lunes próximo" o fecha específica
./scripts/send_test_message.sh "+34623226544" \
  "Quiero reservar mechas para el lunes" \
  "test-monday-001" \
  "Pepe"
```

### Problema: "Bot no responde"

**Causa:** Agent container no está corriendo o Redis no está conectado.

**Solución:**
```bash
# Verificar containers
docker compose ps

# Reiniciar agent si es necesario
docker compose restart agent

# Ver logs de agent
docker compose logs agent --tail 50

# Verificar Redis
redis-cli ping
# Debe responder: PONG
```

### Problema: "Pack no se ofrece"

**Causa:** Pack no existe en la base de datos o no contiene los servicios solicitados.

**Solución:**
```bash
# Verificar packs
docker compose exec postgres psql -U atrevete -d atrevete_db -c \
"SELECT id, name, price_euros, included_service_ids FROM packs WHERE is_active = true;"

# Verificar que existe un pack con mechas + corte
# Si no, ejecutar seed de packs
DATABASE_URL="..." ./venv/bin/python database/seeds/packs.py
```

---

## 7. Secuencias de Test Adicionales

### Test: Solo Estética

```bash
./scripts/send_test_message.sh "+34623226544" \
  "Quiero reservar bioterapia para mañana" \
  "test-aesthetics-001" \
  "Pepe"
```

**Esperado:**
- Consulta solo a Rosa (única estilista de estética)
- Presenta slots de Rosa

### Test: Múltiples Servicios de Peluquería

```bash
./scripts/send_test_message.sh "+34623226544" \
  "Necesito mechas, corte y tratamiento para el sábado" \
  "test-multi-services-001" \
  "Pepe"
```

**Esperado:**
- Ofrece pack si existe
- Valida categoría (todos Hairdressing)
- Consulta 5 estilistas de peluquería
- Considera horario limitado del sábado (10:00-14:00)

### Test: Categorías Mezcladas (Debe Fallar Validación)

```bash
# Mensaje 1
./scripts/send_test_message.sh "+34623226544" \
  "Quiero mechas y bioterapia" \
  "test-mixed-001" \
  "Pepe"

# Mensaje 2 (después de que bot pida aclaración)
./scripts/send_test_message.sh "+34623226544" \
  "Quiero reservar por separado" \
  "test-mixed-001" \
  "Pepe"
```

**Esperado:**
- Detecta categorías mezcladas (Hairdressing + Aesthetics)
- Ofrece opciones: reservar por separado, elegir una categoría, cancelar
- Si elige "por separado", crea 2 bookings pendientes

### Test: Mismo Día (Buffer 1 hora)

```bash
# Ejecutar durante horario de negocio
./scripts/send_test_message.sh "+34623226544" \
  "Necesito mechas para hoy" \
  "test-same-day-001" \
  "Pepe"
```

**Esperado:**
- Marca is_same_day = True
- Filtra slots con menos de 1 hora de antelación
- Solo muestra slots después de [hora actual + 1 hora]

---

## 8. Comandos Útiles

### Ver Estado de Redis

```bash
# Listar todas las conversaciones
redis-cli KEYS "conversation:*"

# Ver conversación específica
redis-cli --raw GET "conversation:test-availability-123" | python -m json.tool
```

### Ver Logs Completos de un Test

```bash
# Por conversation_id
docker compose logs agent | grep "test-availability-123"

# Por customer_phone
docker compose logs agent | grep "+34623226544"
```

### Limpiar Redis (Opcional)

```bash
# Eliminar una conversación específica
redis-cli DEL "conversation:test-availability-123"

# Eliminar todas las conversaciones de test (¡CUIDADO!)
redis-cli KEYS "conversation:test-*" | xargs redis-cli DEL
```

### Verificar Google Calendar Directamente

```python
# Script rápido para verificar acceso a calendarios
import sys
sys.path.insert(0, "/home/pepe/atrevete-bot")

from agent.tools.calendar_tools import fetch_calendar_events
import asyncio
from datetime import datetime, timedelta

async def test():
    calendar_id = "02ac48c0...@group.calendar.google.com"  # Victor
    start = datetime.now()
    end = start + timedelta(days=7)

    events = await fetch_calendar_events(calendar_id, start, end)
    print(f"Events found: {len(events)}")
    for event in events[:5]:
        print(f"  - {event.get('summary')}: {event.get('start')}")

asyncio.run(test())
```

---

## 9. Métricas de Éxito

Un test exitoso debe cumplir:

- ✅ Tiempo de respuesta < 10 segundos (desde mensaje hasta slots presentados)
- ✅ Al menos 1 slot disponible encontrado
- ✅ Máximo 3 slots priorizados presentados al usuario
- ✅ Consulta a TODOS los estilistas de la categoría correcta
- ✅ Formato de respuesta natural en español
- ✅ Sin errores en logs de agent
- ✅ Sin errores de Google Calendar API

---

## 10. Próximos Pasos

Una vez que el flujo de disponibilidad funcione correctamente:

1. **Epic 4 - Story 4.1**: Implementar creación de cita provisional
2. **Epic 4 - Story 4.2**: Bloquear slot en Google Calendar (provisional, amarillo)
3. **Epic 4 - Story 4.3**: Generar payment link de Stripe
4. **Epic 4 - Story 4.4**: Worker de timeout para liberar slots
5. **Epic 4 - Story 4.5**: Procesar webhook de Stripe y confirmar cita

---

**Última actualización:** 2025-10-30
**Versión:** 1.0
**Autor:** Claude Code
