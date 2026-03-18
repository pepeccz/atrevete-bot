---
name: atrevete-qa-tester
description: >
  Executes conversational QA scenarios against the live Atrévete Bot by injecting
  messages into Redis and capturing agent responses from Pub/Sub.
  Trigger: When executing a conversational QA run, simulating a WhatsApp user, or validating a QA flow end to end.
license: MIT
metadata:
  author: atrevete-bot
  version: "1.0"
  scope: [root]
  auto_invoke:
    - "Executing a conversational QA run"
    - "Simulating a WhatsApp user"
    - "Validating a QA flow end to end"
---

## Purpose

Act as the QA driver that simulates a realistic user persona while exercising the exact Redis-based production path.

## Execution Steps

1. Read `.atl/qa-testing-context.md` or consume structured context from `atrevete-qa-context`.
2. Generate a fresh UUID4 `conversation_id` for the run.
3. Connect to Redis using project settings.
4. Subscribe to the `outgoing_messages` Pub/Sub channel BEFORE sending anything.
5. For each turn in the flow:
   - decide the next user utterance for the persona,
   - inject the message into `INCOMING_STREAM` using `{"data": json.dumps(payload)}`,
   - wait for a matching response on `outgoing_messages`,
   - record timestamps, latency, and both sides of the turn.
6. Capture final checkpoint state with a binary Redis/checkpointer client if available.
7. Return a structured conversation trace.

## Critical Redis Details

- Stream name comes from `shared.redis_client.INCOMING_STREAM` and resolves to `incoming_messages_stream`.
- Response capture uses Pub/Sub channel `outgoing_messages`, not a Redis Stream.
- The injected payload must use the wrapped `XADD` shape: `{"data": json.dumps(message_payload)}`.
- Agent responses use the `message` key, not `message_text`.
- Tests should force `MESSAGE_BATCH_WINDOW_SECONDS=0` to avoid batching delays.

## Rules

- Always subscribe before injecting to avoid race conditions.
- Never reuse a `conversation_id` across runs.
- Time out clearly when a response does not arrive.
- Keep the trace chronological and include latency metrics.
- Preserve the raw final state snapshot for later evaluation.

## Usage Example

```json
{
  "flow_id": "returning_client",
  "persona_id": "carlos_returning_client",
  "response_timeout": 30.0
}
```

Expected result shape:

```json
{
  "scenario_id": "returning_client",
  "conversation_id": "uuid4",
  "turns": [
    {
      "turn_number": 1,
      "user_message": "Hola, soy Carlos de nuevo",
      "agent_response": "...",
      "response_latency_ms": 1200
    }
  ],
  "final_state": {}
}
```
