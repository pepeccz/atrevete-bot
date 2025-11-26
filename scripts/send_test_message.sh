#!/bin/bash
# Quick test script to send messages to the bot
# Usage: ./send_test_message.sh "phone" "message" [conversation_id] [name]

PHONE="${1:-+34612345678}"
MESSAGE="${2:-Hola}"
CONV_ID="${3:-1001}"
NAME="${4:-Test Customer}"

# Get webhook token from .env
WEBHOOK_TOKEN=$(grep CHATWOOT_WEBHOOK_TOKEN .env | cut -d '=' -f2)

if [ -z "$WEBHOOK_TOKEN" ]; then
    echo "❌ Error: CHATWOOT_WEBHOOK_TOKEN not found in .env"
    exit 1
fi

echo "📤 Sending message to bot..."
echo "  Phone: $PHONE"
echo "  Message: $MESSAGE"
echo "  Conversation ID: $CONV_ID"
echo "  Name: $NAME"
echo ""

curl -X POST "http://localhost:8000/webhook/chatwoot/$WEBHOOK_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"event\": \"message_created\",
    \"message_type\": \"incoming\",
    \"conversation\": {\"id\": $CONV_ID, \"inbox_id\": 1},
    \"sender\": {\"phone_number\": \"$PHONE\", \"name\": \"$NAME\"},
    \"content\": \"$MESSAGE\"
  }" \
  2>/dev/null

echo ""
echo ""
echo "✅ Message sent!"
echo ""
echo "💡 Check Docker logs: docker logs -f atrevete-api"
echo "💡 Check agent logs: docker logs -f atrevete-agent"
