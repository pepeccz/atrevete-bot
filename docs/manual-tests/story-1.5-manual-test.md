# Story 1.5: Basic LangGraph Echo Bot - Manual Testing Guide

## Overview

This document provides step-by-step manual testing procedures for Story 1.5, which implements a basic LangGraph StateGraph that greets customers with "¡Hola! Soy Maite, la asistenta virtual de Atrévete Peluquería 🌸".

## Prerequisites

1. **Chatwoot Instance**: Running with WhatsApp channel configured
2. **Environment Variables**: All required variables configured in `.env`
3. **Docker Compose**: Services running (api, agent, postgres, redis)
4. **Ngrok or Production URL**: For webhook endpoint (if testing with real WhatsApp)

### Required Environment Variables

Ensure these are set in `.env`:

```bash
# Chatwoot
CHATWOOT_API_URL=https://app.chatwoot.com
CHATWOOT_API_TOKEN=your_api_token_here
CHATWOOT_ACCOUNT_ID=12345
CHATWOOT_INBOX_ID=67890

# Redis
REDIS_URL=redis://redis:6379/0

# Application
LOG_LEVEL=INFO
```

---

## Test 1: End-to-End WhatsApp Greeting (Full Integration)

**Purpose**: Verify complete flow from WhatsApp message to AI greeting response

### Setup

1. **Start All Services**:
   ```bash
   docker-compose up
   ```

2. **Verify Services Running**:
   ```bash
   docker-compose ps
   ```
   All services should show "Up" status

3. **Check Agent Logs**:
   ```bash
   docker-compose logs agent | tail -20
   ```
   Should see:
   - "Subscribed to 'incoming_messages' channel"
   - "Subscribed to 'outgoing_messages' channel"
   - "Redis checkpointer created successfully"

### Test Steps

1. **Send WhatsApp Message**:
   - Open WhatsApp on your phone
   - Send any message (e.g., "Hola") to the Chatwoot WhatsApp number

2. **Verify Webhook Received**:
   ```bash
   docker-compose logs api | grep "Chatwoot webhook received"
   ```
   Should see log entry with conversation_id and customer phone

3. **Verify Message Published to Redis**:
   ```bash
   docker-compose logs agent | grep "Message received"
   ```
   Should see log entry with conversation_id and phone number

4. **Verify Graph Execution**:
   ```bash
   docker-compose logs agent | grep "Graph invoked"
   docker-compose logs agent | grep "Graph completed"
   ```
   Should see both invocation and completion logs

5. **Verify Message Sent via Chatwoot**:
   ```bash
   docker-compose logs agent | grep "Message sent"
   ```
   Should see: "Message sent to [phone]: success=True"

6. **Verify WhatsApp Response**:
   - Check WhatsApp on your phone
   - Should receive: "¡Hola! Soy Maite, la asistenta virtual de Atrévete Peluquería 🌸"

### Expected Results

- ✅ WhatsApp message received by Chatwoot
- ✅ Webhook delivered to FastAPI
- ✅ Message published to `incoming_messages` Redis channel
- ✅ Agent processed message through LangGraph
- ✅ Greeting published to `outgoing_messages` Redis channel
- ✅ Chatwoot sent WhatsApp reply
- ✅ WhatsApp user received greeting message

### Troubleshooting

**No webhook received**:
- Verify Chatwoot webhook URL configured correctly
- Check ngrok/production URL is accessible
- Verify API service is running

**No agent processing**:
- Check agent logs for errors: `docker-compose logs agent | grep ERROR`
- Verify Redis connection: `docker-compose exec redis redis-cli PING`
- Verify agent subscribed to channels

**No WhatsApp response**:
- Check Chatwoot API credentials in `.env`
- Verify outgoing message worker logs
- Check Chatwoot inbox ID is correct

---

## Test 2: Crash Recovery Validation

**Purpose**: Verify conversation state persists across agent restarts

### Test Steps

1. **Send First Message**:
   - Send "Test 1" via WhatsApp
   - Verify greeting received

2. **Verify Checkpoint Saved**:
   ```bash
   docker-compose exec redis redis-cli KEYS "checkpoint:*"
   ```
   Should see checkpoint keys (format: `checkpoint:{thread_id}:*`)

3. **Stop Agent Container**:
   ```bash
   docker-compose stop agent
   ```

4. **Verify Agent Stopped**:
   ```bash
   docker-compose ps agent
   ```
   Should show "Exited"

5. **Restart Agent Container**:
   ```bash
   docker-compose start agent
   ```

6. **Wait for Agent Ready** (5-10 seconds):
   ```bash
   docker-compose logs agent | tail -10
   ```
   Should see subscription messages again

7. **Send Second Message**:
   - Send "Test 2" from same WhatsApp number
   - Verify greeting received

8. **Verify State Recovery**:
   ```bash
   docker-compose logs agent | grep "Invoking graph"
   ```
   Should see graph invoked with same thread_id

### Expected Results

- ✅ Agent responds to both messages
- ✅ Checkpoint keys persist in Redis
- ✅ Agent recovers state after restart
- ✅ No errors in agent logs during recovery

---

## Test 3: Redis Pub/Sub Messaging (Direct)

**Purpose**: Test agent message flow using Redis CLI directly (bypasses Chatwoot)

### Test Steps

1. **Publish Message to incoming_messages**:
   ```bash
   docker-compose exec redis redis-cli
   ```
   Then in Redis CLI:
   ```
   PUBLISH incoming_messages '{"conversation_id":"test-manual-123","customer_phone":"+34612345678","message_text":"Hello from Redis"}'
   ```

2. **Subscribe to outgoing_messages** (in separate terminal):
   ```bash
   docker-compose exec redis redis-cli
   ```
   Then:
   ```
   SUBSCRIBE outgoing_messages
   ```

3. **Verify Agent Logs**:
   ```bash
   docker-compose logs agent | grep "test-manual-123"
   ```
   Should see:
   - "Message received: conversation_id=test-manual-123"
   - "Invoking graph for thread_id=test-manual-123"
   - "Graph completed for conversation_id=test-manual-123"
   - "Message published to outgoing_messages: conversation_id=test-manual-123"

4. **Verify outgoing_messages Subscriber**:
   In the Redis CLI terminal from step 2, should see published message:
   ```json
   {
     "conversation_id": "test-manual-123",
     "customer_phone": "+34612345678",
     "message": "¡Hola! Soy Maite, la asistenta virtual de Atrévete Peluquería 🌸"
   }
   ```

### Expected Results

- ✅ Message published to `incoming_messages`
- ✅ Agent processes message
- ✅ Response published to `outgoing_messages`
- ✅ Greeting message matches expected text

---

## Test 4: Logging Verification

**Purpose**: Verify structured JSON logging with conversation_id traceability

### Test Steps

1. **Send Test Message** (via Redis or WhatsApp)

2. **Check JSON Log Format**:
   ```bash
   docker-compose logs agent | grep "conversation_id" | tail -5
   ```

3. **Verify Log Fields**:
   Each log entry should be valid JSON with fields:
   - `timestamp` (ISO 8601)
   - `level` (INFO, ERROR, etc.)
   - `logger` (module name)
   - `message` (log message)
   - `conversation_id` (for traceability)
   - `customer_phone` (if available)
   - `node_name` (if node execution)

### Expected Results

- ✅ Logs are valid JSON format
- ✅ All required fields present
- ✅ conversation_id included for traceability
- ✅ Logs can be filtered by conversation_id

---

## Test 5: Error Handling

**Purpose**: Verify agent handles errors gracefully without crashing

### Test Steps

1. **Send Invalid JSON** to incoming_messages:
   ```bash
   docker-compose exec redis redis-cli
   PUBLISH incoming_messages 'invalid json here'
   ```

2. **Verify Agent Continues**:
   ```bash
   docker-compose logs agent | tail -10
   ```
   Should see error logged but agent still running

3. **Send Valid Message After Error**:
   ```bash
   PUBLISH incoming_messages '{"conversation_id":"test-after-error","customer_phone":"+34612345678","message_text":"Test"}'
   ```

4. **Verify Agent Processes Valid Message**:
   ```bash
   docker-compose logs agent | grep "test-after-error"
   ```
   Should see successful processing

### Expected Results

- ✅ Invalid JSON logged as error
- ✅ Agent worker continues running
- ✅ Subsequent valid messages processed normally
- ✅ No agent crashes

---

## Common Issues and Solutions

### Issue: Agent not subscribing to channels

**Symptoms**:
- Logs show "Agent service started" but no subscription messages

**Solution**:
1. Check Redis connection: `docker-compose exec redis redis-cli PING`
2. Verify REDIS_URL in `.env`
3. Restart agent: `docker-compose restart agent`

### Issue: Chatwoot messages not sending

**Symptoms**:
- Outgoing messages logged but not received on WhatsApp

**Solution**:
1. Verify Chatwoot credentials in `.env`
2. Check Chatwoot inbox ID is correct
3. Test Chatwoot API directly:
   ```bash
   curl -H "api_access_token: YOUR_TOKEN" \
        https://app.chatwoot.com/api/v1/accounts/YOUR_ACCOUNT_ID/contacts
   ```

### Issue: Checkpoints not persisting

**Symptoms**:
- No checkpoint keys in Redis

**Solution**:
1. Verify Redis volume mounted: `docker-compose config | grep redis_data`
2. Check Redis persistence: `docker-compose exec redis redis-cli CONFIG GET save`
3. Verify checkpointer logs: `docker-compose logs agent | grep checkpointer`

---

## Test Sign-Off

**Tester Name**: _________________
**Date**: _________________
**Environment**: [ ] Local Docker [ ] Staging [ ] Production

### Test Results

- [ ] Test 1: End-to-End WhatsApp Greeting - **PASS** / **FAIL**
- [ ] Test 2: Crash Recovery Validation - **PASS** / **FAIL**
- [ ] Test 3: Redis Pub/Sub Messaging - **PASS** / **FAIL**
- [ ] Test 4: Logging Verification - **PASS** / **FAIL**
- [ ] Test 5: Error Handling - **PASS** / **FAIL**

### Notes

_____________________________________________________________________________
_____________________________________________________________________________
_____________________________________________________________________________

**Story Status**: [ ] Ready for Review [ ] Needs Fixes
