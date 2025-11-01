# Guía de Testing del Sistema de Memoria

Esta guía te explica cómo testear manualmente todos los componentes del sistema de memoria del chatbot Atrévete.

## 🚀 Quick Start

```bash
# Ejecutar script de testing automático
./scripts/test_memory_system.sh
```

---

## 📋 Testing Manual Paso a Paso

### 1. Testing de Ventana FIFO (10 mensajes)

**Objetivo**: Verificar que solo se mantienen los últimos 10 mensajes en memoria.

#### Paso 1: Enviar mensajes de prueba

Envía 15 mensajes a través de WhatsApp (o usa el script de test):

```bash
# Si tienes el script send_test_message.sh
for i in {1..15}; do
    ./scripts/send_test_message.sh "Mensaje de prueba $i"
    sleep 2
done
```

#### Paso 2: Verificar en Redis

```bash
# Conectarse a Redis y ver los checkpoints
docker exec atrevete-redis redis-cli

# En el CLI de Redis:
KEYS langgraph:checkpoint:*
# Deberías ver claves de checkpoint

# Obtener un checkpoint específico (reemplaza KEY_NAME)
GET langgraph:checkpoint:KEY_NAME
```

#### Paso 3: Verificar el estado

```bash
# Usar Python para inspeccionar el checkpoint
docker exec -it atrevete-agent python3 << 'EOF'
from shared.redis_client import get_redis_client
import json
import pickle

client = get_redis_client()

# Buscar checkpoints
keys = client.keys("langgraph:checkpoint:*")
if keys:
    # Obtener el primer checkpoint
    data = client.get(keys[0])
    print(f"Checkpoint encontrado: {keys[0]}")

    # Intentar decodificar
    try:
        checkpoint = pickle.loads(data)
        messages = checkpoint.get("channel_values", {}).get("messages", [])
        total_count = checkpoint.get("channel_values", {}).get("total_message_count", 0)

        print(f"\n📊 ESTADO DE LA CONVERSACIÓN:")
        print(f"  - Mensajes en ventana: {len(messages)}")
        print(f"  - Total de mensajes enviados: {total_count}")
        print(f"\n📝 MENSAJES EN VENTANA:")
        for i, msg in enumerate(messages):
            print(f"  {i+1}. [{msg['role']}]: {msg['content'][:50]}...")
    except Exception as e:
        print(f"Error decodificando: {e}")
EOF
```

**Resultado esperado:**
- ✅ `len(messages)` = 10 (máximo en ventana)
- ✅ `total_message_count` = 30 (15 user + 15 assistant)

---

### 2. Testing de Resúmenes (cada 10 mensajes)

**Objetivo**: Verificar que los resúmenes se generan automáticamente cada 10 mensajes.

#### Paso 1: Enviar 25 mensajes

```bash
# Esto debería generar:
# - 1er resumen a los 20 mensajes totales (10 user + 10 assistant)
# - 2do resumen a los 30 mensajes totales

for i in {1..25}; do
    ./scripts/send_test_message.sh "Mensaje $i: Quiero un corte de pelo"
    sleep 3
done
```

#### Paso 2: Verificar que se generó el resumen

```bash
docker exec -it atrevete-agent python3 << 'EOF'
from shared.redis_client import get_redis_client
import pickle

client = get_redis_client()
keys = client.keys("langgraph:checkpoint:*")

if keys:
    data = client.get(keys[0])
    checkpoint = pickle.loads(data)
    summary = checkpoint.get("channel_values", {}).get("conversation_summary")

    if summary:
        print("✅ RESUMEN ENCONTRADO:")
        print(summary)
    else:
        print("❌ No se encontró resumen (puede ser que aún no se hayan enviado 20 mensajes)")
EOF
```

**Resultado esperado:**
- ✅ Después de 20 mensajes totales: `conversation_summary` existe
- ✅ El resumen contiene información de mensajes antiguos
- ✅ Ventana de mensajes sigue siendo solo 10

---

### 3. Testing de Checkpointing y Recovery

**Objetivo**: Verificar que las conversaciones se recuperan tras un reinicio.

#### Paso 1: Enviar mensaje y anotar conversation_id

```bash
# Enviar un mensaje
./scripts/send_test_message.sh "Hola, quiero una cita"

# Ver los logs para obtener el conversation_id
docker compose logs agent --tail=5 | grep "conversation_id"
```

#### Paso 2: Verificar que el checkpoint existe

```bash
# Buscar el checkpoint en Redis
CONV_ID="3"  # Reemplaza con tu conversation_id
docker exec atrevete-redis redis-cli KEYS "*checkpoint:${CONV_ID}:*"
```

#### Paso 3: Reiniciar el agente

```bash
# Reiniciar el servicio del agente
docker compose restart agent

# Esperar a que inicie
sleep 5
```

#### Paso 4: Enviar otro mensaje

```bash
# Enviar otro mensaje a la MISMA conversación
./scripts/send_test_message.sh "¿Qué horario tenéis?"
```

#### Paso 5: Verificar que la conversación continúa

```bash
# Ver los logs
docker compose logs agent --tail=20

# Deberías ver que el agente:
# 1. Cargó el checkpoint
# 2. Recuperó los mensajes anteriores
# 3. Respondió con contexto completo
```

**Resultado esperado:**
- ✅ El agente responde con contexto de mensajes anteriores
- ✅ `total_message_count` incluye mensajes pre-restart
- ✅ No se perdió información

---

### 4. Testing de Límites de Longitud

**Objetivo**: Verificar que mensajes >2000 chars se truncan.

#### Paso 1: Enviar mensaje muy largo

```bash
# Crear un mensaje de 3000 caracteres
LONG_MESSAGE=$(python3 -c "print('A' * 3000)")

# Enviar (necesitarás usar Chatwoot o modificar el script)
echo "Envía un mensaje de >2000 caracteres a través de WhatsApp"
```

#### Paso 2: Verificar truncación en logs

```bash
# Ver logs del agente
docker compose logs agent --tail=50 | grep "truncating"
```

**Resultado esperado:**
- ✅ Log warning: `Message exceeds 2000 chars`
- ✅ Mensaje truncado a: primeros 800 + `[... X omitidos ...]` + últimos 800
- ✅ No hay error de token overflow

---

### 5. Testing de API de Conversaciones Archivadas

**Objetivo**: Verificar que puedes recuperar conversaciones antiguas.

#### Opción A: Si tienes conversaciones archivadas (>24h)

```bash
# 1. Listar todas las conversaciones archivadas
curl "http://localhost:8000/conversations/?limit=10" | python3 -m json.tool

# 2. Filtrar por teléfono
curl "http://localhost:8000/conversations/?customer_phone=%2B34623226544" | python3 -m json.tool

# 3. Obtener historial completo de una conversación
CONV_ID="wa-msg-123"  # Reemplaza con ID real
curl "http://localhost:8000/conversations/${CONV_ID}/history?limit=50" | python3 -m json.tool

# 4. Paginación
curl "http://localhost:8000/conversations/${CONV_ID}/history?limit=10&offset=10" | python3 -m json.tool
```

#### Opción B: Si NO tienes conversaciones archivadas

```bash
# Simular conversación antigua insertando en PostgreSQL manualmente

docker exec -it atrevete-postgres psql -U atrevete -d atrevete_db

# En PostgreSQL:
SELECT * FROM conversation_history LIMIT 5;

# Si no hay registros, espera 24h o modifica TTL temporalmente
```

**Resultado esperado:**
- ✅ `GET /conversations/` retorna lista de conversaciones
- ✅ `GET /conversations/{id}/history` retorna mensajes completos
- ✅ Paginación funciona correctamente

---

### 6. Testing del Worker de Archivado

**Objetivo**: Verificar que conversaciones >23h se archivan automáticamente.

#### Paso 1: Verificar que el worker está corriendo

```bash
docker compose ps archiver

# Debería mostrar: Up X hours
```

#### Paso 2: Ver logs del worker

```bash
docker compose logs archiver --tail=50

# Buscar mensajes como:
# - "Starting conversation archival run"
# - "Found X expired checkpoints to archive"
# - "Archived X conversations"
```

#### Paso 3: Verificar archivados en PostgreSQL

```bash
docker exec atrevete-postgres psql -U atrevete -d atrevete_db -c "
SELECT
    conversation_id,
    customer_phone,
    created_at,
    LENGTH(checkpoint_data::text) as data_size
FROM conversation_history
ORDER BY created_at DESC
LIMIT 5;
"
```

**Resultado esperado:**
- ✅ Worker ejecutándose cada hora
- ✅ Conversaciones >23h archivadas en PostgreSQL
- ✅ Checkpoints eliminados de Redis tras archivado

---

### 7. Testing de Error Handling

**Objetivo**: Verificar que errores no rompen el sistema.

#### Test A: Checkpoint corrupto

```bash
# Corromper un checkpoint en Redis
docker exec atrevete-redis redis-cli SET "langgraph:checkpoint:test:corrupt" "INVALID_DATA"

# Enviar mensaje con ese conversation_id
# El sistema debería:
# 1. Detectar el error
# 2. Loggear el error
# 3. Enviar mensaje de fallback al usuario
# 4. Continuar funcionando
```

#### Test B: Redis caído

```bash
# Detener Redis temporalmente
docker compose stop redis

# Intentar enviar mensaje
# Debería fallar gracefully y loggear error

# Reiniciar Redis
docker compose start redis
```

**Resultado esperado:**
- ✅ Error loggeado
- ✅ Usuario recibe mensaje de error amigable
- ✅ Sistema no crashea

---

## 📊 Verificación de Métricas

### Checkpoints en Redis

```bash
# Contar checkpoints
docker exec atrevete-redis redis-cli DBSIZE

# Ver TTL de un checkpoint
docker exec atrevete-redis redis-cli TTL "langgraph:checkpoint:KEY"
```

### Conversaciones archivadas

```bash
# Contar conversaciones en PostgreSQL
docker exec atrevete-postgres psql -U atrevete -d atrevete_db -c "
SELECT COUNT(*) as total_archived FROM conversation_history;
"

# Tamaño total de datos archivados
docker exec atrevete-postgres psql -U atrevete -d atrevete_db -c "
SELECT pg_size_pretty(pg_total_relation_size('conversation_history'));
"
```

---

## 🐛 Troubleshooting

### Problema: Endpoints de API no funcionan

```bash
# Verificar que conversations.py está en el contenedor
docker exec atrevete-api ls -la /app/api/routes/

# Si no está, rebuild:
docker compose build --no-cache api
docker compose restart api
```

### Problema: Resúmenes no se generan

```bash
# Verificar que total_message_count se incrementa
docker compose logs agent | grep "total_message_count"

# Si no aparece, verificar que nodos usan add_message()
docker compose logs agent | grep "Added.*message"
```

### Problema: Checkpoints no persisten

```bash
# Verificar inicialización de Redis indexes
docker compose logs agent | grep "Redis indexes initialized"

# Verificar salud de Redis
docker compose logs redis --tail=20
```

---

## ✅ Checklist de Verificación Completa

- [ ] Ventana FIFO mantiene solo 10 mensajes
- [ ] `total_message_count` se incrementa correctamente
- [ ] Resúmenes se generan cada 10 mensajes (20, 30, 40...)
- [ ] Checkpoints se guardan en Redis tras cada mensaje
- [ ] Checkpoints tienen TTL de 24h
- [ ] Conversación se recupera tras restart del agente
- [ ] Mensajes >2000 chars se truncan con warning
- [ ] Worker de archivado corre cada hora
- [ ] Conversaciones >23h se archivan a PostgreSQL
- [ ] API `/conversations/` funciona
- [ ] API `/conversations/{id}/history` funciona
- [ ] Error handling funciona (checkpoints corruptos)
- [ ] Todos los servicios están healthy

---

## 📞 Comandos Útiles Rápidos

```bash
# Ver estado completo
docker compose ps

# Ver logs en tiempo real
docker compose logs -f agent api

# Conectar a Redis
docker exec -it atrevete-redis redis-cli

# Conectar a PostgreSQL
docker exec -it atrevete-postgres psql -U atrevete -d atrevete_db

# Rebuild todo desde cero
docker compose down
docker compose build --no-cache
docker compose up -d

# Verificar salud
curl http://localhost:8000/health | python3 -m json.tool
```

---

## 🎯 Testing de Carga

Para testing de carga y stress:

```bash
# Enviar 100 mensajes concurrentes
for i in {1..100}; do
    (./scripts/send_test_message.sh "Mensaje $i" &)
done

# Monitorear uso de recursos
docker stats

# Verificar que no hay pérdida de mensajes
docker compose logs agent | grep "Message received" | wc -l
docker compose logs agent | grep "Message published" | wc -l
# Deberían ser iguales
```

---

Necesitas ayuda con alguna parte específica del testing? Ejecuta:
```bash
./scripts/test_memory_system.sh
```
