# Conversational QA E2E

This folder contains the Redis-based harness and scenario-driven tests for Atrévete Bot conversational QA.

## What It Covers

- Injects user messages into `incoming_messages_stream`
- Captures responses from Pub/Sub channel `outgoing_messages`
- Loads personas, flows, and criteria from `.atl/qa-testing-context.md`
- Provides deterministic evaluation scaffolding plus hooks for evaluator-skill review

## Required Environment

- Redis running and reachable through `REDIS_URL`
- Agent worker consuming `incoming_messages_stream`
- `MESSAGE_BATCH_WINDOW_SECONDS=0`

## How To Run Later

```bash
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/e2e/test_conversation_e2e.py -v
```

## Main Files

- `tests/e2e/harness/context_manager.py` - parses QA personas, flows, and criteria
- `tests/e2e/harness/redis_harness.py` - injects and captures Redis traffic
- `tests/e2e/harness/state_reset.py` - clears Redis artifacts between runs
- `tests/e2e/conftest.py` - pytest fixtures and test environment overrides
- `tests/e2e/test_conversation_e2e.py` - scenario orchestration
