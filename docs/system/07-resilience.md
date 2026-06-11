# Resilience and Degradation Strategy

> How the system behaves when external dependencies fail. No circuit breaker module — degradation is per-adapter, documented here.

---

## circuit_breaker.py — Intentional Removal

`shared/circuit_breaker.py` was removed intentionally. The module added complexity (OPEN/HALF_OPEN state machine, PyBreaker dependency) without providing meaningful protection for this workload:

- The bot is a single-worker async process. A failing upstream (OpenRouter, GCal, Chatwoot) surfaces quickly via exceptions — no queue build-up to protect against.
- The openai SDK's native retry (exponential backoff + jitter, see U2 below) covers transient LLM failures.
- GCal failures are already handled fire-and-forget via `gcal_sync_status` + admin retry endpoint.

**Deletion guard**: `tests/unit/test_dead_code_cleanup_assertions.py:52` asserts that `shared/circuit_breaker.py` does NOT exist. Do not recreate this file.

---

## Per-Adapter Degradation Matrix

### PostgreSQL (primary store)

| Failure point | Behavior |
|---|---|
| Startup | `validate_startup_config()` in `shared/startup_validator.py` probes PG; raises `StartupValidationError` → `agent/main.py` logs CRITICAL and exits non-zero. |
| `customer_resolve` middleware | DB lookup wrapped in try/except; on failure, the customer slot is omitted → agent treats the user as a new customer (fail-open). Booking proceeds; the appointment is not created until the next DB-successful turn. |
| `book` tool | `AsyncSession.commit()` failure raises; the tool returns a `retry_later` result, the agent tells the user to try again. No partial write (SQLAlchemy rolls back automatically). |

### Google Calendar (push-only mirror)

| Failure point | Behavior |
|---|---|
| GCal push on `book()` | Fire-and-forget: `gcal_push_service` logs the error and sets `appointment.gcal_sync_status = 'failed'`. The appointment IS created in DB regardless. |
| Sync worker retry | `gcal_sync_worker` polls `gcal_sync_status = 'failed'` appointments and retries. |
| Admin manual retry | `POST /api/admin/appointments/{id}/gcal-retry` endpoint triggers a single re-push. |

### Redis (hard dependency — startup SPOF)

| Failure point | Behavior |
|---|---|
| Absent at startup | `startup_validator.py:157-197` probes Redis (MODULE LIST). Failure → `StartupValidationError` with a clear human-readable message. `agent/main.py:307-309` catches it, logs CRITICAL, and re-raises → process exits non-zero. No raw traceback to stdout. |
| Lost at runtime | Redis is a hard dependency for the LangGraph checkpointer and the Redis Streams message queue. Runtime Redis loss causes the agent to fail processing new messages. No graceful degradation — this is a documented SPOF. HA (Redis Sentinel / cluster) is deferred to a future infrastructure change. |

**Operational note**: Monitor Redis health via `docker compose logs redis` and set up alerts on the `incoming_messages` stream lag.

### LLM / OpenRouter (bounded retry + timeout)

Implemented via U2 (Change U — Operational Readiness):

| Setting | Default | Description |
|---|---|---|
| `LLM_MAX_RETRIES` | `3` | Retried status codes: 408, 409, 429, ≥500, and connection errors. Auth failures (401, 403) and bad requests (400, 422) are NOT retried (openai SDK semantics). |
| `LLM_REQUEST_TIMEOUT` | `60.0 s` | Per-request timeout. The previous implicit default was 600 s; this tightens latency on hangs. |

Retry backoff is exponential with jitter, implemented natively by the openai SDK client (no `RunnableRetry` wrapper).

When retries are exhausted, the exception propagates to `agent/main.py`, which logs the error and publishes an error response to the Chatwoot conversation (the user sees a fallback message).

Multi-provider fallback (`LLM_FALLBACK_MODEL`, `LLM_EMERGENCY_MODEL`) is available when `RESILIENCE_ENABLED=True` (see `shared/config.py`).

### Chatwoot (outbound messages)

| Failure point | Behavior |
|---|---|
| `send_message` failure | Logged at ERROR level. The agent continues — the message is lost for this turn. The user may not see the reply; this is acceptable for rare API failures. No retry queue currently. |

---

## Redis Startup Path — Verified Friendly Fatal

The startup Redis failure path was verified during Change U (2026-06-11):

1. `agent/main.py:304-309` calls `validate_startup_config()` inside a try/except.
2. `shared/startup_validator.py` probes Redis and raises `StartupValidationError("Redis connection failed: ...")` on failure.
3. `agent/main.py:308` logs `logger.critical(f"Startup blocked due to configuration errors: {e}")`.
4. Line 309 re-raises → the asyncio event loop terminates with a non-zero exit code.

Result: a clean, human-readable CRITICAL log line. No raw exception traceback.

---

## Observability Checklist

- GCal sync failures: query `SELECT COUNT(*) FROM appointments WHERE gcal_sync_status = 'failed'`.
- LLM retry storms: watch `docker compose logs agent | grep "Retrying request"`.
- Redis stream lag: `XLEN incoming_messages` (should drain continuously).
