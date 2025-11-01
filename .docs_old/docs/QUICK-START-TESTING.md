# 🚀 Quick Start - Testing del Sistema de Memoria

## ⚡ Testing Rápido (5 minutos)

### 1. Verificar que todo está corriendo

```bash
docker compose ps
```

Deberías ver todos los servicios como `healthy` o `running`.

### 2. Ejecutar el script de testing automático

```bash
./scripts/test_memory_system.sh
```

Este script te guiará por todas las verificaciones automáticamente.

---

## 📱 Enviar Mensajes de Prueba

### Opción 1: A través de WhatsApp/Chatwoot

Envía mensajes directamente desde WhatsApp al número conectado. El bot procesará automáticamente los mensajes.

### Opción 2: Usando el script de test (si existe)

```bash
# Si tienes un script de envío de mensajes
./scripts/send_test_message.sh "Hola, quiero una cita"
```

### Opción 3: Simular webhook de Chatwoot directamente

```bash
# Enviar POST directamente al webhook
curl -X POST "http://localhost:8000/webhook/chatwoot/j6gzStex3yw16AXBgzq3ARTq" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "message_created",
    "message_type": "incoming",
    "conversation": {
      "id": 999,
      "contact_last_seen_at": "2025-10-30T14:00:00Z"
    },
    "sender": {
      "phone_number": "+34623226544",
      "name": "Test User"
    },
    "content": "Hola, quiero una cita"
  }'
```

---

## 🔍 Verificar Mensajes en Memoria

### Ver checkpoints en Redis

```bash
# Conectarse a Redis
docker exec -it atrevete-redis redis-cli

# En Redis CLI:
KEYS langgraph:checkpoint:*
# Verás las claves de los checkpoints

# Salir
exit
```

### Ver cuántos mensajes hay en la ventana

```bash
# Python script rápido para inspeccionar
docker exec -it atrevete-agent python3 << 'EOF'
from shared.redis_client import get_redis_client
import pickle

client = get_redis_client()
keys = list(client.keys("langgraph:checkpoint:*:checkpoint"))

if keys:
    data = client.get(keys[0])
    checkpoint = pickle.loads(data)
    state = checkpoint.get("channel_values", {})
    messages = state.get("messages", [])
    total = state.get("total_message_count", 0)

    print(f"✅ Conversación encontrada!")
    print(f"   Mensajes en ventana: {len(messages)}")
    print(f"   Total de mensajes: {total}")
    print(f"\n   Últimos 3 mensajes:")
    for msg in messages[-3:]:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")[:60]
        print(f"   - [{role}]: {content}...")
else:
    print("⚠️ No hay conversaciones activas")
EOF
```

---

## 🔎 Testing de API de Conversaciones

### 1. Listar conversaciones archivadas

```bash
curl "http://localhost:8000/conversations/" | python3 -m json.tool
```

### 2. Buscar por teléfono

```bash
PHONE="+34623226544"
curl "http://localhost:8000/conversations/?customer_phone=%2B${PHONE:1}" | python3 -m json.tool
```

### 3. Ver historial completo

```bash
# Primero obtén un conversation_id de la lista
CONV_ID="3"  # Reemplaza con un ID real

curl "http://localhost:8000/conversations/${CONV_ID}/history" | python3 -m json.tool
```

---

## 📊 Ver Logs en Tiempo Real

### Ver logs del agente

```bash
# Logs en tiempo real
docker compose logs -f agent

# Buscar eventos específicos
docker compose logs agent | grep "Added.*message"
docker compose logs agent | grep "total_message_count"
docker compose logs agent | grep "Summarization triggered"
```

### Ver logs de la API

```bash
docker compose logs -f api
```

---

## ✅ Checklist Rápido

Verifica estos puntos para asegurar que todo funciona:

- [ ] Todos los servicios están `healthy`
- [ ] Puedes enviar mensajes al bot
- [ ] El bot responde correctamente
- [ ] Los checkpoints aparecen en Redis
- [ ] La API responde en `/health`
- [ ] La documentación de API está en `/docs`

---

## 🐛 Problemas Comunes

### "Los endpoints de /conversations/ no funcionan"

**Solución:**
```bash
# Verificar que el archivo existe en el contenedor
docker exec atrevete-api ls -la /app/api/routes/

# Si no está conversations.py, rebuild:
docker compose build --no-cache api
docker compose restart api
```

### "No veo mensajes en Redis"

**Solución:**
```bash
# Verificar que Redis está corriendo
docker compose logs redis --tail=10

# Verificar que el agente está conectado
docker compose logs agent | grep "Redis"
```

### "El bot no responde"

**Solución:**
```bash
# Ver logs del agente
docker compose logs agent --tail=50

# Verificar que el agente está escuchando
docker compose logs agent | grep "Subscribed to"
```

---

## 📚 Más Documentación

- **Guía completa de testing**: `docs/MEMORY-SYSTEM-TESTING.md`
- **Script automático**: `./scripts/test_memory_system.sh`
- **API Docs**: http://localhost:8000/docs

---

## 💡 Tips

1. **Para testing rápido de ventana FIFO**:
   - Envía 15 mensajes
   - Verifica que solo quedan 10 en Redis
   - Verifica que `total_message_count` = 30

2. **Para testing de resúmenes**:
   - Envía 25 mensajes (50 totales con respuestas)
   - Debería generar 4 resúmenes (cada 10 mensajes)
   - Verifica con: `docker compose logs agent | grep "Summarization triggered"`

3. **Para testing de recovery**:
   ```bash
   # Envía un mensaje
   # Reinicia el agente
   docker compose restart agent
   # Envía otro mensaje
   # Deberías ver la conversación continuar
   ```

---

¿Necesitas ayuda? Ejecuta:
```bash
./scripts/test_memory_system.sh
```
