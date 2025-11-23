#!/bin/bash
# Monitor FSM state changes during manual testing
# Usage: ./scripts/monitor-fsm.sh

echo "=== Monitoreando estados FSM ==="
echo "Presiona Ctrl+C para salir"
echo ""

docker-compose logs -f agent 2>&1 | grep --line-buffered -E \
  "FSM (loaded|transition)|state=|intent.*type=|coherence|regenerat" | \
  sed -E 's/.*FSM/\n🔄 FSM/g; s/.*transition SUCCESS/✅ TRANSICIÓN/g; s/.*transition REJECTED/❌ RECHAZADO/g; s/.*intent/🎯 Intent/g; s/.*coherence/🔍 Coherence/g'
