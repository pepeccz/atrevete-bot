#!/bin/bash
# Script de testing manual del sistema de memoria
# Uso: ./scripts/test_memory_system.sh

set -e

PHONE="+34623226544"  # Tu número de teléfono de prueba
API_URL="http://localhost:8000"

echo "========================================="
echo "TEST DEL SISTEMA DE MEMORIA - ATRÉVETE BOT"
echo "========================================="
echo ""

# Colores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Función para esperar respuesta
wait_for_response() {
    echo -e "${YELLOW}⏳ Esperando 3 segundos para que el agente procese...${NC}"
    sleep 3
}

echo "📋 PARTE 1: TESTING DE MENSAJES Y VENTANA FIFO"
echo "=============================================="
echo ""

echo "1️⃣ Enviando mensaje de prueba al bot..."
echo "   (Este mensaje debería iniciar una nueva conversación)"
echo ""

# Nota: Para enviar mensajes necesitas usar el webhook de Chatwoot
# O usar el script send_test_message.sh si existe

read -p "Presiona ENTER para continuar con tests de API..."
echo ""

echo "📋 PARTE 2: TESTING DE API DE CONVERSACIONES ARCHIVADAS"
echo "========================================================"
echo ""

echo "2️⃣ Listando todas las conversaciones archivadas..."
echo "   GET /conversations/"
echo ""
RESPONSE=$(curl -s "$API_URL/conversations/?limit=5")
echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
echo ""

if echo "$RESPONSE" | grep -q "conversations"; then
    echo -e "${GREEN}✅ Endpoint funciona correctamente${NC}"
else
    echo -e "${RED}❌ Error: Endpoint no responde correctamente${NC}"
fi
echo ""

read -p "Presiona ENTER para continuar..."
echo ""

echo "3️⃣ Listando conversaciones de un cliente específico..."
echo "   GET /conversations/?customer_phone=$PHONE"
echo ""
RESPONSE=$(curl -s "$API_URL/conversations/?customer_phone=$(echo $PHONE | sed 's/+/%2B/g')")
echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
echo ""

read -p "Presiona ENTER para continuar..."
echo ""

echo "4️⃣ Intentando obtener historial de una conversación..."
echo "   (Necesitas un conversation_id válido)"
echo ""
read -p "Ingresa un conversation_id (o presiona ENTER para omitir): " CONV_ID

if [ ! -z "$CONV_ID" ]; then
    echo ""
    echo "   GET /conversations/$CONV_ID/history?limit=10"
    echo ""
    RESPONSE=$(curl -s "$API_URL/conversations/$CONV_ID/history?limit=10")
    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
    echo ""

    if echo "$RESPONSE" | grep -q "messages"; then
        echo -e "${GREEN}✅ Historial recuperado correctamente${NC}"
        TOTAL=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('total_messages', 0))" 2>/dev/null || echo "0")
        echo "   Total de mensajes en el archivo: $TOTAL"
    else
        echo -e "${YELLOW}⚠️  Conversación no encontrada en archivo (normal si <24h)${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Omitido - no hay conversation_id${NC}"
fi
echo ""

read -p "Presiona ENTER para continuar..."
echo ""

echo "📋 PARTE 3: VERIFICACIÓN DE CHECKPOINTS EN REDIS"
echo "================================================"
echo ""

echo "5️⃣ Verificando checkpoints en Redis..."
echo "   Buscando claves de checkpoint..."
echo ""

CHECKPOINT_COUNT=$(docker exec atrevete-redis redis-cli KEYS "langgraph:checkpoint:*" | wc -l)
echo "   Checkpoints encontrados: $CHECKPOINT_COUNT"
echo ""

if [ $CHECKPOINT_COUNT -gt 0 ]; then
    echo -e "${GREEN}✅ Sistema de checkpointing activo${NC}"
    echo ""
    echo "   Mostrando primeras 5 claves de checkpoint:"
    docker exec atrevete-redis redis-cli KEYS "langgraph:checkpoint:*" | head -5
else
    echo -e "${YELLOW}⚠️  No hay checkpoints (normal si no hay conversaciones activas)${NC}"
fi
echo ""

read -p "Presiona ENTER para continuar..."
echo ""

echo "6️⃣ Verificando TTL de checkpoints (deben expirar en 24h)..."
echo ""
FIRST_KEY=$(docker exec atrevete-redis redis-cli KEYS "langgraph:checkpoint:*" | head -1)
if [ ! -z "$FIRST_KEY" ]; then
    TTL=$(docker exec atrevete-redis redis-cli TTL "$FIRST_KEY")
    TTL_HOURS=$((TTL / 3600))
    echo "   TTL de checkpoint: ${TTL}s (~${TTL_HOURS}h restantes)"

    if [ $TTL -gt 0 ] && [ $TTL -le 86400 ]; then
        echo -e "${GREEN}✅ TTL configurado correctamente (<24h)${NC}"
    else
        echo -e "${YELLOW}⚠️  TTL inesperado: $TTL${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  No hay checkpoints para verificar TTL${NC}"
fi
echo ""

read -p "Presiona ENTER para continuar..."
echo ""

echo "📋 PARTE 4: VERIFICACIÓN DE WORKER DE ARCHIVADO"
echo "==============================================="
echo ""

echo "7️⃣ Verificando estado del worker de archivado..."
echo ""

ARCHIVER_STATUS=$(docker compose ps archiver --format json | python3 -c "import sys, json; print(json.load(sys.stdin).get('State', 'unknown'))" 2>/dev/null || echo "unknown")
echo "   Estado del archiver: $ARCHIVER_STATUS"

if [ "$ARCHIVER_STATUS" = "running" ]; then
    echo -e "${GREEN}✅ Worker de archivado activo${NC}"
else
    echo -e "${RED}❌ Worker de archivado no está corriendo${NC}"
fi
echo ""

echo "8️⃣ Verificando conversaciones archivadas en PostgreSQL..."
echo ""

ARCHIVED_COUNT=$(docker exec atrevete-postgres psql -U atrevete -d atrevete_db -t -c "SELECT COUNT(*) FROM conversation_history;" 2>/dev/null | tr -d ' ')
echo "   Conversaciones archivadas: $ARCHIVED_COUNT"

if [ $ARCHIVED_COUNT -gt 0 ]; then
    echo -e "${GREEN}✅ Sistema de archivado funcionando${NC}"
    echo ""
    echo "   Mostrando últimas 3 conversaciones archivadas:"
    docker exec atrevete-postgres psql -U atrevete -d atrevete_db -c "SELECT conversation_id, customer_phone, created_at FROM conversation_history ORDER BY created_at DESC LIMIT 3;"
else
    echo -e "${YELLOW}⚠️  No hay conversaciones archivadas (normal si todas son <24h)${NC}"
fi
echo ""

read -p "Presiona ENTER para continuar..."
echo ""

echo "📋 PARTE 5: VERIFICACIÓN DE SERVICIOS"
echo "====================================="
echo ""

echo "9️⃣ Verificando estado de todos los servicios..."
echo ""

docker compose ps

echo ""
echo "🔟 Verificando health check de API..."
echo ""

HEALTH=$(curl -s "$API_URL/health")
echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"

if echo "$HEALTH" | grep -q '"status": "healthy"'; then
    echo -e "${GREEN}✅ API healthy${NC}"
else
    echo -e "${YELLOW}⚠️  API degraded${NC}"
fi
echo ""

echo "========================================="
echo "✅ TESTING COMPLETADO"
echo "========================================="
echo ""
echo "📊 RESUMEN:"
echo "  - Endpoints de API: Verifica los resultados arriba"
echo "  - Checkpoints Redis: $CHECKPOINT_COUNT encontrados"
echo "  - Conversaciones archivadas: $ARCHIVED_COUNT en PostgreSQL"
echo "  - Worker archivado: $ARCHIVER_STATUS"
echo ""
echo "📝 PARA TESTING COMPLETO DE MEMORIA:"
echo "  1. Envía 15+ mensajes a través de WhatsApp/Chatwoot"
echo "  2. Verifica que solo 10 mensajes se mantienen en Redis"
echo "  3. Espera 24h y verifica que se archivan a PostgreSQL"
echo "  4. Usa la API para recuperar el historial archivado"
echo ""
echo "Para más detalles, consulta: docs/TESTING-GUIDE.md"
echo ""
