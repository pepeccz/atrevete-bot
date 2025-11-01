# 5. API Specification

The API layer consists of REST webhook endpoints for receiving events from external systems. No customer-facing API exists—all customer interactions occur via WhatsApp through Chatwoot.

## 5.1 REST API Specification

```yaml
openapi: 3.0.0
info:
  title: Atrévete Bot Webhook API
  version: 1.0.0
  description: |
    Internal webhook API for receiving events from Chatwoot (WhatsApp messages)
    and Stripe (payment confirmations). All endpoints require signature validation.

    **Security:**
    - Chatwoot: HMAC-SHA256 signature in X-Chatwoot-Signature header
    - Stripe: Stripe-Signature header validated via stripe.Webhook.construct_event()

    **Rate Limiting:** 10 requests/minute per source IP (429 if exceeded)

servers:
  - url: https://bot.atrevete.com/api
    description: Production VPS
  - url: http://localhost:8000/api
    description: Local development

paths:
  /webhook/chatwoot:
    post:
      summary: Receive WhatsApp messages from Chatwoot
      description: |
        Webhook endpoint for incoming customer messages. Validates signature,
        extracts message content, and enqueues to Redis 'incoming_messages' channel
        for LangGraph agent processing. Returns 200 OK immediately (async processing).

      tags:
        - Webhooks

      security:
        - chatwootSignature: []

      responses:
        '200':
          description: Message received and enqueued successfully
        '401':
          description: Invalid or missing signature
        '429':
          description: Rate limit exceeded (>10 req/min)

  /webhook/stripe:
    post:
      summary: Receive payment events from Stripe
      description: |
        Webhook endpoint for Stripe payment confirmations. Validates signature,
        extracts payment metadata (appointment_id), and enqueues to Redis
        'payment_events' channel for booking confirmation workflow.

      tags:
        - Webhooks

      security:
        - stripeSignature: []

      responses:
        '200':
          description: Event received and processed
        '401':
          description: Invalid Stripe signature
        '400':
          description: Missing appointment_id in metadata

  /health:
    get:
      summary: Health check endpoint
      description: |
        Returns system health status including Redis and PostgreSQL connectivity.
        Used by monitoring systems (UptimeRobot, Docker healthcheck).

      tags:
        - System

      responses:
        '200':
          description: All systems operational
        '503':
          description: Service degraded or unavailable

components:
  securitySchemes:
    chatwootSignature:
      type: apiKey
      in: header
      name: X-Chatwoot-Signature
      description: HMAC-SHA256 signature of request body

    stripeSignature:
      type: apiKey
      in: header
      name: Stripe-Signature
      description: Stripe webhook signature (t=timestamp,v1=signature)
```

---
