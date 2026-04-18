# Infra — Adaptadores Técnicos

> Lo que conecta el dominio con el mundo. Sin dominio del salón. Reemplazables sin tocar cores ni módulos.

## Inventario

| Infra | Responsabilidad | Estado |
|-------|------------------|--------|
| llm | OpenRouter, create_agent, base middleware | Sólido, en uso |
| chatwoot | Cliente Chatwoot, rate limiting, webhook handler | Sólido |
| google-calendar | Push events, OAuth, credenciales | Sólido pero acoplado a `agent/services/` |
| redis | Streams (incoming, workers), checkpointer LangGraph | Sólido |
| database | AsyncEngine, SessionLocal, migrations | Sólido |
| intent-router | Keyword + LLM hybrid classifier | Sólido |
| resolvers | Registry de resolvers pre-loop | Parcial (registry formalizado en `agent/core/resolvers.py` desde E1; `negation` movido a `infra/resolvers/`; audience/digit/no-pref aún inline en modes hasta E2) |
| prompts | Layered assembly + TTL cache | Sólido |
| state | ConversationState schema + reducers | Sólido pero con state fragmentation |
| observability | Structured logging, telemetry, measured-gate | Parcial |
| audit | Audit log de operaciones admin | A definir |
| auth | Auth admin panel | Mínimo |

---

## llm

**Responsabilidad**: gestionar el cliente OpenRouter, construir agentes vía `create_agent` (LangChain 1.0+), proveer middleware base reutilizable por cualquier módulo.

### Componentes

- **Cliente OpenRouter**: configurado vía `shared/config.py`. Default model: `openai/gpt-5.4-mini`.
- **`create_agent` factory**: `agent/modes/base.py` (805 líneas, `BaseModeNode` clase abstracta) abstrae la construcción.
- **Middleware stack genérico** (`agent/middleware/`):
  - `DynamicToolsMiddleware` — filtra tools según closure `get_tools_fn(state)`.
  - `NodeBridgeMiddleware` — bridges legacy `_pre_tool_call` / `_post_tool_result` a create_agent. Soporta sync + async.
  - `DedupToolCallMiddleware` — caché `(tool_name, sorted_args) → result` dentro del loop.
  - `FinalTextRecoveryMiddleware` — si loop termina sin texto y hubo tool_results, re-invoca al LLM sin tools.
  - `GateRecoveryMiddleware` — cuenta rechazos de tools; dispara fallbacks.
  - `ToolChoiceMiddleware` — config-driven (ALWAYS_FORCE / FORCE_AFTER_SERVICE / NEVER_FORCE).
  - `TokenTrackingMiddleware` — telemetría tokens (input/output) por modo y turno.

### Contratos

- Cualquier capability puede componer middleware en cualquier orden. **Orden importa**: `ToolChoice → DynamicTools → NodeBridge → Dedup → FinalTextRecovery → TokenTracking`.
- Un middleware NO puede contener lógica de dominio del salón. Si la necesita, debe recibirla como parámetro/closure.

### Anti-patrones a corregir

- `BaseModeNode` mezcla concerns: legacy `_run_agentic_loop`, helpers de prompts, helpers de state, etc. En target: separar en `infra/llm/base_node.py` (solo create_agent + middleware) y `infra/llm/legacy_loop.py` (solo para AppointmentManagementMode hasta migrar).

---

## chatwoot

**Responsabilidad**: gateway de WhatsApp. Recibir webhooks entrantes, enviar mensajes salientes, manejar rate limits.

### Componentes

- `shared/chatwoot_client.py` — singleton client con rate limiting.
- `api/routes/chatwoot.py` — webhook endpoint que recibe mensajes y los empuja a Redis Stream `incoming_messages`.

### Contratos

- Mensajes entrantes se persisten en `messages` table + push a Redis Stream.
- Mensajes salientes se enviar via cliente; en caso de fallo, retry con circuit breaker.
- El operador puede intervenir en cualquier conversación desde Chatwoot UI; el bot detecta `assignee_changed` event y se calla.

### Anti-patrones

- Cliente Chatwoot vive en `shared/`. Es claramente INFRA: debe vivir en `infra/chatwoot/`.

---

## google-calendar

**Responsabilidad**: mirror push-only de las citas a los Google Calendars de las 5 estilistas.

### Componentes

- `agent/services/gcal_credential_service.py` — gestión de credenciales OAuth.
- `agent/services/gcal_oauth_service.py` — flow OAuth.
- `agent/services/gcal_push_service.py` — push de citas a GCal.
- `agent/tools/calendar_tools.py` — tools de read/write GCal.
- `agent/workers/gcal_sync_worker.py` — worker async que consume Redis Stream y empuja a GCal.

### Contratos

- DB es fuente de verdad. GCal es READ-ONLY desde el punto de vista del usuario final del bot.
- Si la sync GCal falla, NO se rolea back la DB. Se reintenta async.
- Cada estilista tiene su propio `gcal_calendar_id` y credenciales independientes.

### Anti-patrones

- Servicios GCal viven en `agent/services/`. Son INFRA: deben vivir en `infra/google-calendar/`.
- `calendar_tools.py` mezcla: la operación de read es infra, el wrapping como Tool LLM es de capability. Separar.

---

## redis

**Responsabilidad**: streams (cola de mensajes entrantes, workers async), checkpointer LangGraph (persistencia de state entre turnos), pub/sub legacy.

### Componentes

- `shared/redis_client.py` — cliente singleton, abstracciones streams (add/read/ack), pub/sub.
- `agent/state/checkpointer.py` — checkpointer LangGraph backed by Redis (RedisJSON + RedisSearch).

### Contratos

- `incoming_messages` stream: producer = `api/routes/chatwoot.py`. Consumer = `agent/main.py`.
- `gcal_sync` stream: producer = booking flow al hacer `book()`. Consumer = `gcal_sync_worker`.
- Checkpointer key: `thread_id = conversation_id`.

### Anti-patrones

- Pub/sub legacy convive con Streams. Limpiar en E4.
- Cliente Redis en `shared/` → mover a `infra/redis/`.

---

## database

**Responsabilidad**: persistencia de dominio (PostgreSQL 15+). AsyncEngine, SessionLocal, migrations Alembic.

### Componentes

- `database/models.py` (1441 líneas) — 9 core models + 5 calendar models + 2 system models. **30 tablas total.**
- `database/connection.py` — AsyncEngine + AsyncSessionLocal factory.
- `database/alembic/` — 30+ migrations.
- `database/seeds/` — data seeding inicial.

### Contratos

- Todos los timestamps usan `DateTime(timezone=True)`.
- Todos los primary keys usan UUID (no autoincrement).
- Relaciones lazy por default; eager solo cuando hay performance hot-path.
- Migrations son la única fuente de truth del schema.

### Anti-patrones

- `database/models.py` mezcla TODOS los modelos en un archivo. En target: dividir por core (`cores/customers/models.py`, `cores/appointments/models.py`, etc.) usando declarative base compartido en `infra/database/base.py`.
- Modes acceden `database.models` directamente. Debe pasar por cores (P9).

---

## intent-router

**Responsabilidad**: clasificar el intent de cada mensaje entrante para enrutar al modo correcto.

### Componentes

- `agent/routing/intent_router.py` (400+ líneas) — `IntentResult` + `KEYWORD_MAP` (9 intents × 10-20 keywords) + LLM fallback.

### Contratos

- Keyword fast-path con confidence 0.8 si hay match.
- LLM fallback (clasificador con structured output) si no hay match.
- Retorna SIEMPRE un `IntentResult`. NUNCA falla silente.

### Limitaciones conocidas

- Single-intent: "cancela y rebook" se clasifica como uno o como otro, no como ambos.
- Intent drift mid-turn: si usuario pivota, el modo activo debe poder emitir señal de transición (no solo el router).

### Anti-patrones

- Vive en `agent/routing/`. En target: `infra/intent-router/`.

---

## resolvers

**Responsabilidad**: registry de resolvers deterministas pre-loop. Son funciones puras `(user_text, state) → Optional[StatePatch]`.

### Componentes actuales

- `agent/core/resolvers.py` — registry formalizado con telemetría estructurada (NUEVO E1).
- `infra/resolvers/negation.py:is_negation` — clasifica negaciones. Patrón canónico (movido desde `shared/negation_phrases.py` en E1).
- Inline en `booking_mode.py` (a extraer en E2):
  - `_extract_audience_from_reply` — extrae audience.
  - `_resolve_digit_selection` — extrae selección numérica.
  - `_NO_PREF_PHRASES` — detecta "me da igual".

### Contratos (target)

- Cada resolver: `(user_text, state) → Optional[StatePatch]`.
- StatePatch es un dict que se aplica vía la patch pipeline (no muta directo).
- Resolvers son **registrables**: cada capability declara qué resolvers usa en su contrato.
- Telemetría obligatoria: cada match emite `{resolver, conversation_id, turn, user_text_hash, matched, fuzzy_distance}`.

### Resolvers a añadir (gap actual)

- `is_affirmation` — simétrico a `is_negation`. Para "sí", "vale", "dale", "ok", "perfecto".
- `is_abort` — detecta abandono mid-flow ("dejalo", "cancela", "me lo pienso").

### Anti-patrones

- Resolvers inline en el modo (rompen P3 + reusabilidad). Extraer a `infra/resolvers/` en E2.
- ~~`shared/negation_phrases.py` en realidad es resolver. Mover a `infra/resolvers/negation.py`.~~ **RESUELTO en E1 (commit f5d6074)**.

---

## prompts

**Responsabilidad**: ensamblar el system message en capas (identity, rules, mode overlay, dynamic context). Cachear lo cacheable.

### Componentes

- `agent/prompts/loader.py` — `build_layered_messages(state, booking_context)`.
- `agent/prompts/catalog_builder.py` — construye string de catálogo (servicios, estilistas).
- `agent/prompts/dynamic_context.py` — flow_hint, audience hints, collected_data.
- `agent/prompts/shared/identity.md` (13 líneas).
- `agent/prompts/shared/critical_rules.md` (39 líneas).
- `agent/prompts/modes/*.md` (5 archivos).

### Capas

| Capa | Cache | Ejemplo |
|------|-------|---------|
| 1. Identity + critical_rules | TTL 10 min, ~1500 tokens | identity.md + critical_rules.md |
| 2. Catálogo | NO cacheado actualmente (debería) | catalog_builder.py |
| 3. Mode overlay | TTL 10 min | booking.md (214 líneas) |
| 4. Conversation history | Variable | últimos 6-8 mensajes |
| 5. Dynamic context | Por turno | flow_hint, audience_hints, collected_data |

### Anti-patrones

- Catálogo no cacheado (debería: cambia solo cuando admin edita system_settings).
- `<dynamic_context>` XML en system_message: el system_message es CACHEADO turn-to-turn por `create_agent`. Cualquier cambio dinámico que vaya ahí es invisible al LLM hasta que el cache expire. Bug histórico (#3949). **Target**: cambios dinámicos vía `next_step` en tool responses + tool visibility filtering, no XML en system_message.

---

## state

**Responsabilidad**: schema y reducers de `ConversationState`. Helpers para mutación segura.

### Componentes

- `agent/state/schemas.py` (402 líneas) — `ConversationState` TypedDict + `BookingContext` TypedDict + reducers.
- `agent/state/helpers.py` — `add_message()`, `get_last_user_message()`, `should_summarize()`.
- `agent/state/checkpointer.py` — Redis-backed.

### Reducers

| Field | Reducer | Comportamiento |
|-------|---------|----------------|
| `messages` | `operator_add` | Append |
| `mode_context` | `merge_dicts` | Shallow merge + `__reset__` sentinel (deprecated, M8 cleanup pending) |
| `booking_context` | `replace_dict` | Full replace, sin zombie keys |
| `mode_history` | `append_unique_list` | Append + dedup adjacent |

### Anti-patrón crítico: state fragmentation

- `booking_context` (replace_dict), `mode_context` (merge_dicts + __reset__), `appointment_context` (in-memory bag) — TRES contenedores con DOS reducers distintos.
- No se puede preguntar "¿hay booking activo?" desde appointment_management.
- En target: sub-slices unificadas bajo un único pattern (todas con replace_dict + TypedDict). Ver `07-migration-plan.md` Phase E1.

---

## observability

**Responsabilidad**: structured logging, telemetría de resolvers, tools, mode transitions. Measured-gate contracts.

### Componentes actuales

- `shared/logging_config.py` — config base de logging.
- Telemetría dispersa entre modes y middleware (TokenTrackingMiddleware emite, otros no).
- Measured-gate memos persistidos en engram (`measured-gate/booking-negation-resolver-2026-04-17`).

### Componentes target

- Resolver telemetry estandarizada (cada resolver emite el mismo schema).
- Tool call telemetry (cada tool call emite status + latencia + next_step).
- Mode transition logger.
- Métricas agregadas offline desde logs (script en `scripts/aggregate_metrics.py`).

### Anti-patrones

- Sin estandarización de schema entre componentes que loggean.
- Sin dashboard ni script de agregación: se tienen que `grep` los logs a mano.

---

## audit

**Responsabilidad**: registro inmutable de operaciones administrativas (cambios de catálogo, edición de citas desde panel, escalations).

### Estado actual

- No formalmente implementado. Algunos cambios se loggean pero sin schema unificado.

### Target

- Tabla `audit_log` (UUID, timestamp, actor, action, target_id, payload_json, ip).
- API endpoint `GET /admin/audit` paginado.
- Triggers SQLAlchemy o middleware FastAPI para captura automática.

---

## auth

**Responsabilidad**: autenticación del admin panel.

### Estado actual

- Mínimo. Detalles en `api/routes/admin.py`.

### Target

- JWT con refresh tokens.
- Roles (admin / operator / read-only).
- 2FA opcional.

---

## Reglas que aplican a TODA la infra

1. **Zero dominio del salón**. Si te encontrás escribiendo `if service.audience == "señora"` en infra, parate. Eso va a un core.
2. **Configurable vía `shared/config.py`** (Pydantic Settings). Nada de `os.getenv()` directo.
3. **Circuit breaker** para todo adaptador externo (`shared/circuit_breaker.py` ya provee templates).
4. **Async-first**: todo I/O usa `async/await`.
5. **Tests con fakes**: cada infra debe tener un fake mockable para que módulos puedan testearse sin la dependencia real.

## Referencias

- `02-layers.md` — reglas de dependencia.
- `06-current-vs-target.md` — mapping archivo-por-archivo.
- `07-migration-plan.md` — orden de migración.
