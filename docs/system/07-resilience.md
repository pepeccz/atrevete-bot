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
| Startup | `validate_startup_config()` in `shared/startup_validator.py` probes PG; raises `StartupValidationError` → `agent/main.py __main__` catches it explicitly, logs CRITICAL (no traceback), and calls `sys.exit(1)`. |
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
| Absent at startup | `startup_validator.py:157-197` probes Redis (MODULE LIST). Failure → `StartupValidationError` with a clear human-readable message. `agent/main.py __main__` catches `StartupValidationError` explicitly, logs CRITICAL (no `exc_info` → no raw traceback), and calls `sys.exit(1)` → exits non-zero. |
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

The startup Redis failure path was verified and remediated during Change U (2026-06-11):

1. `agent/main.py` calls `validate_startup_config()` inside `async def main()`.
2. `shared/startup_validator.py` probes Redis and raises `StartupValidationError("Redis connection failed: ...")` on failure.
3. `main()` re-raises the `StartupValidationError`; `asyncio.run(main())` propagates it.
4. The `__main__` guard catches `StartupValidationError` **before** the broad `except Exception`, logs
   `logger.critical(f"Startup validation failed: {e}")` (no `exc_info=True` → no raw traceback), then
   calls `sys.exit(1)`.

Result: a clean, human-readable CRITICAL log line, exit code 1. No raw exception traceback to stdout.

---

---

## Security — Dependabot Alert Triage (Change U, 2026-06-11)

### Critical CVEs — RESOLVED in Change U (U5)

| Package | CVE | Vulnerable range | Fix version | Runtime? | Action |
|---|---|---|---|---|---|
| `django` | CVE-2025-64459 | ≥5.2a1, <5.2.8 | 5.2.8 | **No** — dead dependency (zero `import django` in the codebase; admin-panel is Next.js, not Django). Installs into api/agent images via `Dockerfile.api:24` / `Dockerfile.agent:23` as an unused transitive chain. The ≥5.2.8 bump mitigates CVE-2025-64459. Proper fix (removing the dead Django block) deferred to a named follow-up change (dead-dep-cleanup). | Bumped: `requirements.txt` → `django>=5.2.8`; `requirements-frozen.txt` → `Django==5.2.8` |
| `langchain-core` | CVE-2025-68664 | ≥1.0.0, <1.2.5 | 1.2.5 | Yes (agent core) | Bumped: added explicit `langchain-core>=1.2.5` to `requirements.txt`; `requirements-frozen.txt` → `langchain-core==1.2.5` |

### High CVEs — DEFERRED (out of scope for Change U)

The following high-severity alerts appear in `requirements-frozen.txt` (which is significantly out of sync with the actual installed state) and/or `uv.lock` (not the active package manager for this project — `uv.lock` is not read by pip). None require urgent breaking changes:

| Package | Max severity | Patched version | Reason deferred |
|---|---|---|---|
| `urllib3` | high | 2.7.0 | Already ≥2.7 installed on server (7.0.0 in redis-stack env); frozen file is stale. No exploitable attack surface in this workload (private server, no untrusted redirects). |
| `langsmith` | high | 0.8.0 | Dev/observability dep only. Not in the critical booking path. Monitor for next minor release cycle. |
| `Mako` | high | 1.3.12 | Alembic transitive dep. No user-controlled Mako template input. Low exploitability. |
| `python-multipart` | high | 0.0.27 | FastAPI dep. Patched in next FastAPI upgrade cycle. No unrestricted file upload endpoints exposed publicly. |
| `orjson` | high | 3.11.6 | Serialization dep. Patch bump; include in next routine requirements refresh. |
| `pyasn1` | high | 0.6.3 | Google auth transitive dep. No direct exposure. |
| `starlette` | high | 0.49.1 | FastAPI transitive dep; pin will be pulled when FastAPI is upgraded. |
| `langchain-core` additional | high (multiple) | 1.2.22, 1.2.28 | Superseded by the critical 1.2.5 bump above — installing ≥1.2.5 addresses the critical; the high alerts at higher versions are additive improvements, not critical. Schedule next routine bump to ≥1.2.28. |
| `next` (admin-panel) | high | 16.2.6 | Frontend only. `admin-panel/package-lock.json` entries; resolved by `npm audit fix` in next admin-panel release. No server-side exploit path. |

**Action required (next maintenance cycle)**: Run `pip-compile requirements.txt --upgrade` (or equivalent) to regenerate `requirements-frozen.txt` from scratch. The current frozen file is severely out of sync with the actual installed state on the server.

---

## Observability Checklist

- GCal sync failures: query `SELECT COUNT(*) FROM appointments WHERE gcal_sync_status = 'failed'`.
- LLM retry storms: watch `docker compose logs agent | grep "Retrying request"`.
- Redis stream lag: `XLEN incoming_messages` (should drain continuously).
- Disclosure per-thread firing (sdd/context-coherence, D9): `disclosure.turn_evaluated`
  (INFO, `agent/middleware/disclosure.py`) logs `conversation_id`, `is_first_turn`,
  `prior_message_count` — use it to confirm a reply to a notification lands with
  `is_first_turn=false` on a known thread. See `agent/AGENTS.md § Disclosure Policy`
  for why per-thread firing is correct and unchanged.
- New Chatwoot conversation created by a notification worker send: `new_conversation_created`
  (WARNING, `shared/chatwoot_client.py`) — should be RARE after Stream 1 (threading fix);
  frequent occurrences indicate the canonical-conversation resolver is missing rows.
- Assembled prompt slots per turn: `prompt_assembly.slots` (INFO, `agent/middleware/prompt_assembly.py`)
  logs the slot NAMES present (never content) — useful to confirm `_slot_upcoming_appointments`
  was injected on a given turn.
