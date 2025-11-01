# Conversation Test Scenarios - Hybrid Architecture

**Project**: Atrévete Bot
**Environment**: Local Development
**API Endpoint**: http://localhost:8000
**Status**: ✅ System Running

---

## 🚀 Quick Start - How to Test

### Method 1: Using the Test Script (Recommended)

```bash
# Run interactive test script
./scripts/test_conversation.sh
```

### Method 2: Using curl Directly

```bash
# Send a message to the bot
curl -X POST http://localhost:8000/chatwoot/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event": "message_created",
    "message_type": "incoming",
    "conversation": {
      "id": 123,
      "inbox_id": 1
    },
    "sender": {
      "phone_number": "+34612345678",
      "name": "María García"
    },
    "content": "Hola"
  }'
```

### Method 3: Using Python Script

```bash
# Run automated test scenarios
python scripts/test_conversation_flows.py
```

---

## 📋 Test Scenarios

### Scenario 1: First-Time Customer - Greeting & Identification

**Objective**: Test Tier 1 conversational agent handling new customer greeting

**Customer**: María García (+34612345678)
**Flow**: Greeting → Identification → Name confirmation

**Messages to Send:**

```bash
# Message 1: Initial greeting
curl -X POST http://localhost:8000/chatwoot/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event": "message_created",
    "message_type": "incoming",
    "conversation": {"id": 1001, "inbox_id": 1},
    "sender": {"phone_number": "+34612345678", "name": "María García"},
    "content": "Hola"
  }'

# Expected Response: Maite greets and asks for name confirmation
# Should see: "¡Hola! Soy Maite..." and name confirmation request

# Message 2: Confirm name
curl -X POST http://localhost:8000/chatwoot/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event": "message_created",
    "message_type": "incoming",
    "conversation": {"id": 1001, "inbox_id": 1},
    "sender": {"phone_number": "+34612345678", "name": "María García"},
    "content": "Sí, correcto"
  }'

# Expected Response: Confirmation and ask how to help
```

**Expected Behavior:**
- ✅ conversational_agent uses `get_customer_by_phone` tool
- ✅ Customer not found → greets as new customer
- ✅ Asks for name confirmation
- ✅ Creates customer with `create_customer` tool
- ✅ booking_intent_confirmed = False (still in conversation)

---

### Scenario 2: FAQ Query - Hours

**Objective**: Test FAQ handling via `get_faqs` tool

**Customer**: Pedro López (+34612000002)
**Flow**: FAQ question → Direct answer

**Messages to Send:**

```bash
# Message: Ask about hours
curl -X POST http://localhost:8000/chatwoot/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event": "message_created",
    "message_type": "incoming",
    "conversation": {"id": 1002, "inbox_id": 1},
    "sender": {"phone_number": "+34612000002", "name": "Pedro López"},
    "content": "¿A qué hora abrís?"
  }'

# Expected Response: Hours information from database
```

**Expected Behavior:**
- ✅ conversational_agent uses `get_faqs` tool with keywords=["hours"]
- ✅ Returns FAQ answer from database
- ✅ Friendly, natural response in Maite's tone
- ✅ booking_intent_confirmed = False

---

### Scenario 3: Service Inquiry - Pricing

**Objective**: Test service inquiry via `get_services` tool

**Customer**: Ana Martínez (+34612000003)
**Flow**: Price question → Service info

**Messages to Send:**

```bash
# Message: Ask about service price
curl -X POST http://localhost:8000/chatwoot/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event": "message_created",
    "message_type": "incoming",
    "conversation": {"id": 1003, "inbox_id": 1},
    "sender": {"phone_number": "+34612000003", "name": "Ana Martínez"},
    "content": "¿Cuánto cuesta un corte?"
  }'

# Expected Response: Price and duration for "Corte" service
```

**Expected Behavior:**
- ✅ conversational_agent uses `get_services` tool
- ✅ Returns price (25€) and duration (30min) for "Corte"
- ✅ May suggest other services or ask if wants to book
- ✅ booking_intent_confirmed = False

---

### Scenario 4: Booking Intent Detection (Tier 1 → Tier 2)

**Objective**: Test transition from conversational to booking flow

**Customer**: Laura Sánchez (+34612000004)
**Flow**: Booking request → Intent detection → Transition to Tier 2

**Messages to Send:**

```bash
# Message: Express booking intent
curl -X POST http://localhost:8000/chatwoot/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event": "message_created",
    "message_type": "incoming",
    "conversation": {"id": 1004, "inbox_id": 1},
    "sender": {"phone_number": "+34612000004", "name": "Laura Sánchez"},
    "content": "Quiero reservar mechas para el viernes"
  }'

# Expected Response: Acknowledgment and start booking process
```

**Expected Behavior:**
- ✅ conversational_agent detects booking intent
- ✅ Sets booking_intent_confirmed = True
- ✅ Transitions to Tier 2 (booking_handler)
- ✅ May ask for preferred time or other details

---

### Scenario 5: Multi-Turn Conversation - Service Inquiry to Booking

**Objective**: Test natural conversation flow with multiple turns

**Customer**: Carlos Ruiz (+34612000005)
**Flow**: Inquiry → More questions → Decision to book

**Messages to Send:**

```bash
# Turn 1: Ask about service
curl -X POST http://localhost:8000/chatwoot/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event": "message_created",
    "message_type": "incoming",
    "conversation": {"id": 1005, "inbox_id": 1},
    "sender": {"phone_number": "+34612000005", "name": "Carlos Ruiz"},
    "content": "Hola, ¿qué diferencia hay entre mechas y balayage?"
  }'

# Expected: Explanation of differences

# Turn 2: Ask about price
curl -X POST http://localhost:8000/chatwoot/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event": "message_created",
    "message_type": "incoming",
    "conversation": {"id": 1005, "inbox_id": 1},
    "sender": {"phone_number": "+34612000005", "name": "Carlos Ruiz"},
    "content": "¿Y cuánto cuestan las mechas?"
  }'

# Expected: Price information

# Turn 3: Decide to book
curl -X POST http://localhost:8000/chatwoot/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event": "message_created",
    "message_type": "incoming",
    "conversation": {"id": 1005, "inbox_id": 1},
    "sender": {"phone_number": "+34612000005", "name": "Carlos Ruiz"},
    "content": "Vale, quiero reservar"
  }'

# Expected: Transition to booking flow
```

**Expected Behavior:**
- ✅ Maintains conversation context across turns
- ✅ Uses appropriate tools for each question
- ✅ Detects booking intent in final message
- ✅ Smooth transition to Tier 2

---

### Scenario 6: Pack Suggestion

**Objective**: Test pack suggestion when customer requests multiple services

**Customer**: Elena Torres (+34612000006)
**Flow**: Request multiple services → Pack suggestion

**Messages to Send:**

```bash
# Message: Request services that have a pack
curl -X POST http://localhost:8000/chatwoot/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event": "message_created",
    "message_type": "incoming",
    "conversation": {"id": 1006, "inbox_id": 1},
    "sender": {"phone_number": "+34612000006", "name": "Elena Torres"},
    "content": "Quiero mechas y corte"
  }'

# Expected Response: Pack suggestion with savings
```

**Expected Behavior:**
- ✅ conversational_agent uses `suggest_pack_tool`
- ✅ Finds "Mechas + Corte" pack (60€ vs 85€ individual)
- ✅ Presents savings (25€ discount)
- ✅ May set booking_intent_confirmed = True

---

### Scenario 7: Indecision & Consultation Offer

**Objective**: Test indecision detection and consultation offering

**Customer**: Roberto Díaz (+34612000007)
**Flow**: Indecisive message → Consultation offer

**Messages to Send:**

```bash
# Message: Express indecision
curl -X POST http://localhost:8000/chatwoot/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event": "message_created",
    "message_type": "incoming",
    "conversation": {"id": 1007, "inbox_id": 1},
    "sender": {"phone_number": "+34612000007", "name": "Roberto Díaz"},
    "content": "No sé si hacerme mechas o balayage, ¿cuál me recomiendas?"
  }'

# Expected Response: Consultation offer
```

**Expected Behavior:**
- ✅ conversational_agent detects indecision
- ✅ Uses `offer_consultation_tool`
- ✅ Offers free 15-minute consultation
- ✅ Provides consultation service details

---

### Scenario 8: Returning Customer

**Objective**: Test returning customer recognition

**Customer**: Create customer first, then test recognition

**Messages to Send:**

```bash
# Step 1: Create customer (use Scenario 1 first)
# Then test recognition:

curl -X POST http://localhost:8000/chatwoot/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event": "message_created",
    "message_type": "incoming",
    "conversation": {"id": 1008, "inbox_id": 1},
    "sender": {"phone_number": "+34612345678", "name": "María García"},
    "content": "Hola de nuevo"
  }'

# Expected Response: Personalized greeting for returning customer
```

**Expected Behavior:**
- ✅ `get_customer_by_phone` finds existing customer
- ✅ Personalized greeting with customer name
- ✅ May reference previous services/history
- ✅ is_returning_customer = True

---

### Scenario 9: Location/Address FAQ

**Objective**: Test FAQ for location information

**Customer**: Isabel Moreno (+34612000009)

**Messages to Send:**

```bash
curl -X POST http://localhost:8000/chatwoot/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event": "message_created",
    "message_type": "incoming",
    "conversation": {"id": 1009, "inbox_id": 1},
    "sender": {"phone_number": "+34612000009", "name": "Isabel Moreno"},
    "content": "¿Dónde estáis ubicados?"
  }'

# Expected Response: Address and location information
```

**Expected Behavior:**
- ✅ Uses `get_faqs` with keywords=["address", "location"]
- ✅ Returns address from database
- ✅ Natural, helpful response

---

### Scenario 10: Escalation to Human

**Objective**: Test escalation when needed

**Customer**: Miguel Fernández (+34612000010)
**Flow**: Complex medical question → Escalation

**Messages to Send:**

```bash
curl -X POST http://localhost:8000/chatwoot/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event": "message_created",
    "message_type": "incoming",
    "conversation": {"id": 1010, "inbox_id": 1},
    "sender": {"phone_number": "+34612000010", "name": "Miguel Fernández"},
    "content": "Tengo una condición médica en el cuero cabelludo, ¿puedo hacerme un tratamiento?"
  }'

# Expected Response: Escalation message
```

**Expected Behavior:**
- ✅ conversational_agent detects medical topic
- ✅ Uses `escalate_to_human` tool with reason="medical_consultation"
- ✅ Provides escalation message
- ✅ Human mode flag set in Redis (future implementation)

---

## 🔍 What to Look For

### Tier 1 (Conversational Agent) Indicators:
- ✅ **Natural, conversational responses** in Spanish
- ✅ **Maite's personality** (friendly, warm, uses emojis 🌸 💕)
- ✅ **Tool usage logged** in console (check Docker logs)
- ✅ **Context maintained** across multiple turns
- ✅ **Appropriate tool selection** for each query type

### Tier 2 (Transactional) Indicators:
- ✅ **booking_intent_confirmed = True** triggers transition
- ✅ **Structured flow** after booking intent
- ✅ **State fields populated** (requested_services, etc.)

### General System Health:
- ✅ **Fast response times** (<5 seconds for simple queries)
- ✅ **No crashes** or error messages
- ✅ **Database queries working** (services, FAQs, customers)
- ✅ **Redis state persistence** working

---

## 🐛 Debugging

### View Docker Logs:

```bash
# API logs
docker logs -f atrevete-api

# Agent logs (if separate)
docker logs -f atrevete-agent

# All logs
docker compose logs -f
```

### Check Conversation State in Redis:

```bash
# Connect to Redis
docker exec -it atrevete-redis redis-cli

# List conversation keys
KEYS conversation:*

# Get conversation state
GET conversation:1001
```

### Query Database Directly:

```bash
# Check customers created
docker exec atrevete-postgres psql -U atrevete -d atrevete_db \
  -c "SELECT * FROM customers ORDER BY created_at DESC LIMIT 5;"

# Check services
docker exec atrevete-postgres psql -U atrevete -d atrevete_db \
  -c "SELECT name, price_euros, duration_minutes FROM services;"

# Check FAQs
docker exec atrevete-postgres psql -U atrevete -d atrevete_db \
  -c "SELECT category, value FROM policies;"
```

---

## 📊 Expected Results Summary

| Scenario | Tier | Tool(s) Used | Expected Outcome |
|----------|------|--------------|------------------|
| 1. First-Time Customer | Tier 1 | get_customer_by_phone, create_customer | Customer created, greeted |
| 2. FAQ - Hours | Tier 1 | get_faqs | FAQ answered |
| 3. Service Inquiry | Tier 1 | get_services | Price/duration provided |
| 4. Booking Intent | Tier 1→2 | - | booking_intent_confirmed=True |
| 5. Multi-Turn | Tier 1 | Multiple | Context maintained |
| 6. Pack Suggestion | Tier 1 | suggest_pack_tool | Pack offered with savings |
| 7. Indecision | Tier 1 | offer_consultation_tool | Consultation offered |
| 8. Returning Customer | Tier 1 | get_customer_by_phone | Personalized greeting |
| 9. Location FAQ | Tier 1 | get_faqs | Address provided |
| 10. Escalation | Tier 1 | escalate_to_human | Escalation message |

---

## 🎯 Success Criteria

### Minimum (MVP):
- ✅ Scenarios 1, 2, 3 working (greeting, FAQ, inquiry)
- ✅ Natural Spanish responses with Maite personality
- ✅ No crashes or errors

### Good:
- ✅ All 10 scenarios working
- ✅ Appropriate tool usage
- ✅ Context maintained across turns
- ✅ Tier 1 → Tier 2 transition working

### Excellent:
- ✅ Fast response times (<3 seconds)
- ✅ Intelligent tool selection
- ✅ Smooth conversation flow
- ✅ Proper error handling

---

## 📝 Notes

- **Phone Numbers**: Use different phone numbers for each test to avoid conversation mixing
- **Conversation IDs**: Use different conversation IDs for each test scenario
- **Timing**: Wait 2-3 seconds between messages in multi-turn scenarios
- **Logs**: Keep Docker logs open to see tool calls and state updates

---

**Created**: 2025-01-30
**Project**: Atrévete Bot - Hybrid Architecture
**Status**: Ready for Testing
