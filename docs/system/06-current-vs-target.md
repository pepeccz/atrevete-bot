# Mapeo: Estado Actual → Target

> Archivo-por-archivo. Qué hay hoy, dónde debería ir, qué transformación se necesita. Este es el puente al plan de migración.

## Cómo leer

| Columna | Significado |
|---------|-------------|
| **Hoy** | Path actual del archivo en el repo |
| **Target** | Path destino en la estructura cores/modulos/infra/ui |
| **Acción** | `MOVE` (mover sin cambios), `SPLIT` (dividir en N archivos), `RENAME` (mismo contenido, nuevo path), `EXTRACT` (extraer parte y dejar el resto), `DELETE` (dead code), `WRAP` (envolver en service layer), `KEEP` (no cambiar) |
| **Phase** | Fase del plan de migración donde se hace |

---

## agent/modes/

| Hoy | Target | Acción | Phase |
|-----|--------|--------|-------|
| `agent/modes/base.py` (805 líneas) | `infra/llm/base_node.py` (~400) + `infra/llm/legacy_loop.py` (~200) + `infra/llm/capability_base.py` (~200) | SPLIT | E1 + E2 |
| `agent/modes/booking_mode.py` (800 líneas) | `modulos/booking/capability.py` (~300) + extracciones a cores | SPLIT + EXTRACT | E2 |
| `agent/modes/appointment_management_mode.py` (800) | `modulos/appointment_management/capability.py` (~300) + extracciones | SPLIT + EXTRACT | E3 |
| `agent/modes/greeting_mode.py` (417) | `modulos/greeting/capability.py` (~200) | EXTRACT (a customers core) | E4 |
| `agent/modes/general_mode.py` (196) | `modulos/general/capability.py` (~150) | RENAME + cleanup | E4 |
| `agent/modes/escalation_mode.py` (400) | `modulos/escalation/capability.py` | RENAME | E4 |

## agent/tools/

| Hoy | Target | Acción | Phase |
|-----|--------|--------|-------|
| `agent/tools/booking_data_tools.py` (`update_booking`) | `modulos/booking/tools/update_booking.py` | MOVE + cleanup | E2 |
| `agent/tools/availability_tools.py` (`check_availability`) | `modulos/booking/tools/check_availability.py` (LLM tool) + `cores/availability/service.py` (lógica) | SPLIT | E2 |
| `agent/tools/booking_tools.py` (`book`) | `modulos/booking/tools/book.py` (LLM tool) + `cores/appointments/operations.py:book` (transacción) | SPLIT | E2 |
| `agent/tools/appointment_management_tools.py` | `modulos/appointment_management/tools/` (split) + `cores/appointments/operations.py` | SPLIT | E3 |
| `agent/tools/customer_tools.py` (`manage_customer`) | `modulos/booking/tools/customer.py` (wrapper) + `cores/customers/operations.py` | SPLIT | E2 |
| `agent/tools/calendar_tools.py` | `infra/google-calendar/client.py` | MOVE + RENAME | E4 |
| `agent/tools/notification_tools.py` | `infra/chatwoot/notifications.py` | MOVE | E4 |
| `agent/tools/escalation_tools.py` (`escalate`) | `modulos/escalation/tools/escalate.py` | MOVE | E4 |

## agent/services/

| Hoy | Target | Acción | Phase |
|-----|--------|--------|-------|
| `agent/services/availability_service.py` | `cores/availability/service.py` | MOVE | E2 |
| `agent/services/customer_memory_service.py` | `cores/customers/memory.py` | MOVE | E4 |
| `agent/services/escalation_service.py` | `cores/escalation/service.py` o `infra/notifications/escalation.py` | EXTRACT | E4 |
| `agent/services/confirmation_service.py` | `cores/appointments/confirmation.py` | MOVE | E4 |
| `agent/services/reschedule_service.py` | `cores/appointments/reschedule.py` | MOVE | E3 |
| `agent/services/cancellation_service.py` | `cores/appointments/cancellation.py` | MOVE | E3 |
| `agent/services/gcal_push_service.py` | `infra/google-calendar/push.py` | MOVE + RENAME | E4 |
| `agent/services/gcal_credential_service.py` | `infra/google-calendar/credentials.py` | MOVE | E4 |
| `agent/services/gcal_oauth_service.py` | `infra/google-calendar/oauth.py` | MOVE | E4 |
| `agent/services/appointment_query_service.py` | `cores/appointments/queries.py` | MOVE | E3 |

## agent/middleware/

Toda la carpeta es infra LLM. **Acción global: MOVE** a `infra/llm/middleware/` en E4.

| Hoy | Target | Phase |
|-----|--------|-------|
| `dynamic_tools.py` | `infra/llm/middleware/dynamic_tools.py` | E4 |
| `node_bridge.py` | `infra/llm/middleware/node_bridge.py` | E4 |
| `dedup.py` | `infra/llm/middleware/dedup.py` | E4 |
| `tool_choice.py` | `infra/llm/middleware/tool_choice.py` | E4 |
| `final_text_recovery.py` | `infra/llm/middleware/final_text_recovery.py` | E4 |
| `gate_recovery.py` | `infra/llm/middleware/gate_recovery.py` | E4 |
| `token_tracking.py` | `infra/llm/middleware/token_tracking.py` | E4 |

## agent/prompts/

| Hoy | Target | Acción | Phase |
|-----|--------|--------|-------|
| `agent/prompts/loader.py` | `infra/prompts/loader.py` | MOVE | E4 |
| `agent/prompts/catalog_builder.py` | `infra/prompts/catalog_builder.py` (con dependencia a `cores/services` y `cores/stylists`) | MOVE | E4 |
| `agent/prompts/dynamic_context.py` | **DELETE en E2** (reemplazado por `next_step` en tool responses) | DELETE | E2 |
| `agent/prompts/shared/identity.md` | `infra/prompts/shared/identity.md` | MOVE | E4 |
| `agent/prompts/shared/critical_rules.md` | `infra/prompts/shared/critical_rules.md` | MOVE | E4 |
| `agent/prompts/modes/booking.md` | `modulos/booking/prompt.md` | MOVE | E2 |
| `agent/prompts/modes/appointment_management.md` | `modulos/appointment_management/prompt.md` | MOVE | E3 |
| `agent/prompts/modes/greeting.md` | `modulos/greeting/prompt.md` | MOVE | E4 |
| `agent/prompts/modes/general.md` | `modulos/general/prompt.md` | MOVE | E4 |
| `agent/prompts/modes/escalation.md` | `modulos/escalation/prompt.md` | MOVE | E4 |
| `agent/prompts/legacy/` | DELETE — but only after E2 makes BookingCapability the active path and the legacy loader is superseded. E1 investigation confirmed `load_maite_system_prompt()` reads it at graph build time; "DELETE\|E1" was wrong. | DELETE | E4 |

## agent/state/

| Hoy | Target | Acción | Phase |
|-----|--------|--------|-------|
| `agent/state/schemas.py` (402) | `infra/state/schemas.py` (slim) + sub-slices en cada `modulos/*/state.py` | SPLIT | E1 + E2 |
| `agent/state/helpers.py` | `infra/state/helpers.py` | MOVE | E4 |
| `agent/state/checkpointer.py` | `infra/redis/checkpointer.py` | MOVE | E4 |

## agent/routing/

| Hoy | Target | Acción | Phase |
|-----|--------|--------|-------|
| `agent/routing/intent_router.py` (400+) | `infra/intent-router/router.py` + `infra/intent-router/keyword_map.py` + `infra/intent-router/llm_fallback.py` | SPLIT | E4 |

## agent/graphs/

| Hoy | Target | Acción | Phase |
|-----|--------|--------|-------|
| `agent/graphs/conversation_flow.py` | `infra/llm/conversation_flow.py` o `agent/graphs/conversation_flow.py` (mantener si centra el orchestrator) | KEEP o MOVE | E4 |

## agent/workers/

| Hoy | Target | Acción | Phase |
|-----|--------|--------|-------|
| `agent/workers/confirmation_worker.py` | `infra/workers/confirmation.py` (compone `cores/appointments/confirmation`) | MOVE | E4 |
| `agent/workers/gcal_sync_worker.py` | `infra/workers/gcal_sync.py` | MOVE | E4 |
| `agent/workers/conversation_archiver.py` | `infra/workers/archiver.py` | MOVE | E4 |
| `agent/workers/billing_worker.py` | `infra/workers/billing.py` | MOVE | E4 |

## agent/core/

| Hoy | Target | Acción | Phase |
|-----|--------|--------|-------|
| `agent/core/state_delivery.py` (T3 fix) | **CONSOLIDAR**: la primitiva de synthetic state delivery se elimina cuando E2 introduce el target architecture. El bug que arregla desaparece estructuralmente. | DELETE eventualmente | E2 |
| `agent/core/capability.py` (NEW — E1) | `agent/core/capability.py` (stays; is the target contract) | KEEP | — |
| `agent/core/resolvers.py` (NEW — E1) | `agent/core/resolvers.py` (stays) | KEEP | — |
| `agent/core/tool_response.py` (NEW — E1) | `agent/core/tool_response.py` (stays) | KEEP | — |
| `agent/core/status_line.py` (NEW — E1) | `agent/core/status_line.py` (stays; wired into BookingCapability in E2) | KEEP | E2 wiring |

## agent/fsm/

| Hoy | Target | Acción | Phase |
|-----|--------|--------|-------|
| `agent/fsm/models.py` | DELETE — but only after E4 cleanup replaces FSM types in routing/confirmation/cancellation. E1 investigation confirmed 8+ active importers; "DELETE\|E1" label was wrong. | DELETE | E4 |

## agent/hooks/, agent/batching/, agent/resilience/, agent/validators/

E1 dead-code investigation (2026-04-18) resolved all "INVESTIGAR" labels. See `docs/system/e1-dead-code-investigation.md` for full evidence.

| Hoy | Acción | Phase |
|-----|--------|-------|
| `agent/hooks/qa_tool_trace.py` | KEEP (debug tool, mover a `infra/observability/qa_tracing.py`) | E4 |
| `agent/batching/message_batcher.py` | KEEP or MOVE → `infra/workers/batching.py` — imported by `agent/main.py` (live entry point) | E4 |
| `agent/resilience/error_classifier.py` | INVESTIGATE with runtime trace before delete — no production callers found statically; deferred per E4 task | E4 |
| `agent/resilience/fallback_chain.py` | INVESTIGATE with runtime trace before delete | E4 |
| `agent/resilience/retry_strategy.py` | INVESTIGATE with runtime trace before delete | E4 |
| `agent/validators/slot_validator.py` | MOVE → `cores/availability/` — 9+ active importers across booking and availability | E2 |
| `agent/validators/transaction_validators.py` | MOVE → `cores/availability/` — 9+ active importers | E2 |

## shared/

| Hoy | Target | Acción | Phase |
|-----|--------|--------|-------|
| `shared/config.py` | `infra/config.py` (Pydantic Settings) | MOVE | E4 |
| `shared/chatwoot_client.py` | `infra/chatwoot/client.py` | MOVE | E4 |
| `shared/redis_client.py` | `infra/redis/client.py` | MOVE | E4 |
| `shared/negation_phrases.py` | `infra/resolvers/negation.py` | MOVE (DONE — commit f5d6074, E1) | E1 DONE |
| `shared/audience_maps.py` | `cores/services/audience.py` | MOVE | E2 |
| `shared/business_hours_validator.py` | `cores/availability/business_hours.py` | MOVE | E2 |
| `shared/stylist_cache.py` | `cores/stylists/cache.py` o `infra/redis/caches/stylist.py` | MOVE | E4 |
| `shared/circuit_breaker.py` | ~~`infra/circuit_breaker.py`~~ | **DELETED** — module removed intentionally; see `docs/system/07-resilience.md` + deletion guard `tests/unit/test_dead_code_cleanup_assertions.py:52` | ~~E4~~ DONE |
| `shared/encryption.py` | `infra/encryption.py` | MOVE | E4 |
| `shared/audio_transcription.py`, `audio_conversion.py` | `infra/audio/` | MOVE | E4 |
| `shared/resilient_api.py` | `infra/http/resilient_api.py` | MOVE | E4 |
| `shared/settings_service.py` | `infra/settings.py` | MOVE | E4 |
| `shared/cache_signals.py` | `infra/redis/pubsub.py` | MOVE | E4 |
| `shared/email_service.py` | MOVE → `infra/email/` — E1 investigation confirmed active use in `BillingService.send_invoice_email()`; "DELETE?\|E1" was wrong. | MOVE | E4 |
| `shared/logging_config.py` | `infra/observability/logging.py` | MOVE | E4 |
| `shared/startup_validator.py` | `infra/startup_validator.py` | MOVE | E4 |

## database/

| Hoy | Target | Acción | Phase |
|-----|--------|--------|-------|
| `database/models.py` (1441 líneas) | SPLIT entre `cores/*/models.py` (Customer → customers, Service → services, Stylist → stylists, Appointment → appointments, etc.) + `infra/database/base.py` (declarative base compartido) | SPLIT | E4 (riesgo alto, cuidado con migrations) |
| `database/connection.py` | `infra/database/connection.py` | MOVE | E4 |
| `database/alembic/` | KEEP (migrations son la fuente de verdad del schema) | KEEP | — |
| `database/seeds/services.py` | `cores/services/seeds.py` | MOVE | E4 |
| `database/seeds/stylists.py` | `cores/stylists/seeds.py` | MOVE | E4 |
| `database/seeds/business_hours.py` | `cores/availability/seeds.py` | MOVE | E4 |

## api/

| Hoy | Target | Acción | Phase |
|-----|--------|--------|-------|
| `api/main.py` | `infra/api/main.py` o `ui/api/main.py` | MOVE | E4 |
| `api/routes/admin.py` | `ui/api/admin.py` (sirve al admin panel) | MOVE | E4 |
| `api/routes/chatwoot.py` | `infra/chatwoot/webhook.py` | MOVE | E4 |
| `api/routes/conversations.py` | `ui/api/conversations.py` | MOVE | E4 |
| `api/routes/google_oauth.py` | `infra/google-calendar/oauth_routes.py` | MOVE | E4 |
| `api/services/billing_service.py` | `cores/billing/service.py` o `infra/billing/` | MOVE | E4 |
| `api/services/stripe_service.py` | MOVE → `cores/billing/` or `infra/billing/` — E1 investigation confirmed active use across 4 billing routes; "DELETE?\|E1" was wrong. | MOVE | E4 |
| `api/services/conversation_delete_service.py` | `cores/conversations/delete.py` | MOVE | E4 |

## admin-panel/

KEEP. UI ya está bien aislada en su propia carpeta. Eventualmente puede mover a `ui/admin-panel/` por consistencia, pero es cosmético.

## tests/

KEEP estructura. Pero conforme se mueven los archivos productivos, los tests deben moverse análogamente. Ejemplo:
- `tests/unit/test_agent/test_booking_mode.py` → `tests/unit/modulos/booking/test_capability.py`
- `tests/unit/test_audience_maps.py` → `tests/unit/cores/services/test_audience.py`

---

## Acoplamientos críticos identificados (los 10 que duelen más)

Resumen del audit del subagente. Cada uno tiene su fix path en alguna phase:

| # | Acoplamiento | Hoy | Phase de fix |
|---|--------------|-----|--------------|
| 1 | `booking_mode._load_stylists_by_category` query directa a DB | `booking_mode.py:467` | E2 (vía `cores/stylists/get_by_category`) |
| 2 | `booking_mode._resolve_service_category` query directa a DB | `booking_mode.py:488` | E2 (vía `cores/services/find_category`) |
| 3 | Negation resolver inline en booking_mode | `booking_mode.py:373-406` | E1 (extraer a `infra/resolvers/`) |
| 4 | Audience extraction duplica `canonicalize_audience` | `booking_mode.py:132-169` | E2 (consolidar en `cores/services/audience`) |
| 5 | "¿algo más?" decidido entre prompt + flag + flow_hint | `booking_mode.py:188-189`, `booking.md`, `_build_flow_hint` | E2 (eliminar flow_hint XML; usar `next_step`) |
| 6 | Customer memory write embebido en `_post_tool_result` | `booking_mode.py:708-725` | E2 (extraer a `cores/customers/update_post_booking`) |
| 7 | AppointmentMgmt duplica negation/affirmative phrase lists | `appointment_management_mode.py:1-50` | E3 (importar de `infra/resolvers/`) |
| 8 | Catálogo hardcoded en booking.md prompt | `booking.md:6-16` | E2 (inyectar dinámico vía `catalog_builder`) |
| 9 | Fuzzy match duplicado entre `_find_similar_services` y `fuzzy_resolver` | `booking_data_tools.py:115-131` | E2 (consolidar en `cores/services/fuzzy`) |
| 10 | Alias `_booking_context == _mode_context` | `booking_mode.py:319-320` | E2 (usar único atributo canónico) |

## Tabla resumen por phase

| Phase | Qué se hace | Riesgo | Reversible? |
|-------|-------------|--------|-------------|
| E1 | Crear scaffolding (`infra/resolvers/`, `infra/state/`, `core/capability.py`, `core/tool_response.py`). Migrar `negation_phrases.py`. Limpiar dead code. | Bajo | Sí |
| E2 | Portar booking a capability contract. Cores: services, stylists, customers, availability, appointments. Behind feature flag. | Alto | Sí (flip flag) |
| E3 | Portar appointment-management. Tools cancel/reschedule completas. | Medio | Sí (flip flag) |
| E4 | Cleanup: mover physical de carpetas (modes, tools, prompts, middleware, state, services, shared). Consolidar database. | Alto | Difícil (mucho rename) |
| E5 | Validar extensibilidad: añadir loyalty capability nueva sin tocar otros módulos. | Bajo | Sí |

---

## Phase E1 Status (2026-04-18) — COMPLETE

E1 scaffolding is done. All commits on branch `feat/architecture-migration-e1`.

### New modules introduced (zero behavioral changes)

| Module | Purpose | Spec |
|--------|---------|------|
| `agent/core/capability.py` | `Capability` ABC — 7-property contract every conversational capability must implement. First concrete implementation is `BookingCapability` in E2. | R1, R2 |
| `agent/core/resolvers.py` | Resolver registry with structured P10 telemetry. 7 required log fields per resolver invocation; raw user text never logged. | R3–R6 |
| `agent/core/tool_response.py` | Pydantic `ToolResponse` model + AST-lint companion. Enforces 14 forbidden Spanish imperatives in `errors[]`. | R7–R9 |
| `agent/core/status_line.py` | Pre-turn `HumanMessage` builder (≤600 chars). Replacement for cached `<dynamic_context>` XML block (bug #3949). Wiring deferred to E2. | R10–R13 |
| `infra/resolvers/negation.py` | Hard rename of `shared/negation_phrases.py` per P8. Zero logic changes. 2 importers updated atomically. | R14, R15 |
| `scripts/check_layers.py` | AST layer-import gate (≤150 LOC, stdlib-only). CI-only in E1; exit 0 on current repo (cores/modulos absent). | R16, R17 |

### Dead-code investigation outcome

Investigated 7 flagged candidates; found 0 confirmed-dead. Corrected stale "DELETE|E1" labels throughout this file. See `docs/system/e1-dead-code-investigation.md` for full evidence.

### Test results post-E1

- Baseline (pre-E1): 234 failed / 2321 passed / 83 errors / 5 skipped / 1 xfailed
- Post-E1: 234 failed / 2412 passed / 83 errors / 5 skipped / 1 xfailed / 1 xpassed
- Net new passing tests: +91
- Coverage on new E1 modules (`agent.core`, `infra.resolvers`): verified ≥90% (see FG run)

### Migration plan link

E1 is criteria-complete per `docs/system/07-migration-plan.md §Phase E1`. Next: E2 — port Booking to Capability contract.

---

## Cómo se valida cada movimiento

1. Tests unit del componente movido pasan en la nueva ubicación.
2. Tests integration que tocan el componente pasan.
3. Linter de imports valida reglas de capa (ningún módulo importa otro módulo, etc.).
4. Smoke test conversacional (script de QA que ejecuta una reserva end-to-end via webhook).

## Referencias

- `02-layers.md` — la separación target completa.
- `07-migration-plan.md` — orden y entregables por phase.
