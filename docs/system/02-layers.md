# Capas: Cores / Módulos / Infra / UI

> El mapa estructural. Define qué importa de qué. Si esto está mal, todo lo demás colapsa.

## Cuatro capas

```
┌─────────────────────────────────────────────────────────────┐
│  UI                                                         │
│  admin-panel (Next.js)                                      │
└────────────────────────────┬────────────────────────────────┘
                             │ HTTP (REST)
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  INFRA                                                      │
│  llm | chatwoot | gcal | redis | database | intent-router   │
│  resolvers | prompts | state | observability | audit        │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
               ▼                              ▼
┌─────────────────────────────────────────────────────────────┐
│  MODULOS (capabilities)                                     │
│  booking | appointment-mgmt | greeting | general | escalat. │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│  CORES (dominio puro del salón)                             │
│  customers | services | stylists | availability | appoints. │
└─────────────────────────────────────────────────────────────┘
```

## Reglas de dependencia (innegociables)

| Capa | PUEDE importar de | NO PUEDE importar de |
|------|-------------------|-----------------------|
| **CORES** | otros cores (con justificación), stdlib | módulos, infra, UI |
| **MODULOS** | cores, infra | otros módulos, UI |
| **INFRA** | cores (entidades, no servicios), stdlib, librerías externas | módulos, UI |
| **UI** | infra (vía HTTP / API REST únicamente) | cores y módulos directos |

**Reglas adicionales**:

- Un módulo NUNCA importa otro módulo. Si dos módulos necesitan algo en común, sube a `cores/` o a `infra/`.
- La infra NUNCA conoce a un módulo. La infra ofrece servicios genéricos; el módulo los compone.
- Los cores son librerías puras: SQLAlchemy models + funciones de dominio + invariantes. Sin LLM, sin Chatwoot, sin Redis.
- Tests de cores corren sin Postgres real (con SQLite in-memory o repository mock).
- Tests de módulos pueden usar fakes de infra.

## Por qué esta separación

### Cores existen para encapsular el dominio del salón

Un futuro desarrollador debe poder leer `cores/appointments/` y entender CÓMO funciona una cita en este salón sin tocar nada de LLM, Chatwoot, ni Redis. Los cores son la **lingua franca** del proyecto: definen qué es un Customer, qué es un Service, qué es una Appointment, y qué operaciones son legales sobre cada uno.

### Módulos existen para encapsular las capabilities conversacionales

Un módulo es **una conversación posible** con el bot. Booking es una. Cancelación es otra. Loyalty (futura) es otra. Cada módulo orquesta cores + infra para resolver SU caso de uso. Un módulo es self-contained: si lo borrás, los demás siguen funcionando.

### Infra existe para encapsular adaptadores técnicos

El día que cambiamos OpenRouter por Anthropic directo, solo se toca `infra/llm/`. El día que cambiamos Chatwoot por Twilio nativo, solo se toca `infra/chatwoot/` (renombrado a `infra/whatsapp/`). Los módulos NO se enteran.

### UI existe para que humanos operen el sistema

El admin-panel es el ÚNICO consumidor humano directo de la API. Los clientes finales interactúan vía WhatsApp (Chatwoot → infra → módulos), no tocan UI.

## Cómo encaja el sistema actual

Hoy la separación está PARCIALMENTE materializada. E1 introdujo `agent/core/` (capability ABC, resolver registry, ToolResponse, status_line) e `infra/resolvers/` (con `negation.py` movido desde `shared/`). El resto sigue plano:

```
agent/         # mezcla módulos + parte de infra (a separar en E4)
agent/core/    # NUEVO E1: abstracciones del capability contract (capability, resolvers, tool_response, status_line)
api/           # parte de UI (REST) + parte de infra (webhook)
database/      # mezcla parte de cores + infra DB
infra/         # NUEVO E1: solo contiene resolvers/ por ahora; resto se llena en E2-E4
shared/        # aún mezcla dominio + infra; va vaciándose progresivamente
admin-panel/   # UI
```

El plan de migración (`07-migration-plan.md`) usa una estrategia additive-first: en E1 se crean abstracciones nuevas en paralelo + un solo rename atómico (`negation_phrases`). En E2-E3 se portan las capabilities (booking, appointment-mgmt) detrás de feature flag. En E4 se hace el movimiento físico masivo de carpetas. Recién en E5 se valida la extensibilidad con una capability nueva.

## Inventario por capa (target final)

### CORES

| Core | Responsabilidad | Estado actual (archivos clave) |
|------|------------------|--------------------------------|
| `customers` | Identidad, lookup por phone, historial, preferencias | `database/models.py:Customer`, `agent/services/customer_memory_service.py` |
| `services` | Catálogo, audience disambiguation, duración, precio | `database/models.py:Service`, `shared/audience_maps.py`, `agent/prompts/catalog_builder.py` (parcial) |
| `stylists` | Las 5 estilistas, especialidades, business hours | `database/models.py:Stylist`, `agent/services/availability_service.py` (parcial) |
| `availability` | Slots, holds, conflictos, holidays, business hours | `agent/services/availability_service.py`, `shared/business_hours_validator.py` |
| `appointments` | Book, cancel, reschedule (transacciones atómicas) | `agent/tools/booking_tools.py:book`, `agent/services/cancellation_service.py`, `agent/services/reschedule_service.py` |

### MODULOS (capabilities)

| Módulo | State slice | Tools | Resolvers usados |
|--------|-------------|-------|------------------|
| `greeting` | `greeting_context` | (sin tools) | `_extract_audience_from_reply` |
| `booking` | `booking_context` | `update_booking`, `check_availability`, `book` | `is_negation`, `_extract_audience_from_reply`, `_resolve_digit_selection` |
| `appointment-management` | `appointment_context` | `manage_appointments`, `confirm_cancellation`, `execute_cancellation` (futuras) | `is_affirmation`, `_resolve_digit_selection`, `is_negation` |
| `general` | (stateless) | (sin tools) | — |
| `escalation` | `escalation_context` | `escalate` | (FSM Python pura, sin LLM) |

### INFRA

| Infra | Responsabilidad | Estado actual (archivos clave) |
|-------|------------------|--------------------------------|
| `llm` | OpenRouter, create_agent, base middleware | `agent/modes/base.py`, `agent/middleware/*` |
| `chatwoot` | Cliente Chatwoot, rate limiting, webhook handler | `shared/chatwoot_client.py`, `api/routes/chatwoot.py` |
| `google-calendar` | Push events, OAuth, credenciales | `agent/services/gcal_*_service.py`, `agent/tools/calendar_tools.py` |
| `redis` | Streams (incoming, workers), checkpointer LangGraph | `shared/redis_client.py`, `agent/state/checkpointer.py` |
| `database` | AsyncEngine, SessionLocal, migrations | `database/connection.py`, `database/alembic/` |
| `intent-router` | Keyword + LLM hybrid classifier | `agent/routing/intent_router.py` |
| `resolvers` | Registry de resolvers pre-loop deterministas | `agent/core/resolvers.py` (registry + telemetry, NUEVO E1), `infra/resolvers/negation.py` (movido desde `shared/` en E1), partes inline en `booking_mode.py` (a extraer en E2) |
| `prompts` | Layered assembly + TTL cache | `agent/prompts/loader.py`, `agent/prompts/dynamic_context.py` |
| `state` | ConversationState schema + reducers + helpers | `agent/state/schemas.py`, `agent/state/helpers.py` |
| `observability` | Structured logging, telemetry, measured-gate | `shared/logging_config.py`, partes dispersas |
| `audit` | Audit log de operaciones admin | (a definir) |
| `auth` | Auth admin panel | `api/routes/admin.py` (parcial) |

### UI

| UI | Responsabilidad | Estado actual |
|----|------------------|---------------|
| `admin-panel` | Next.js 15: agenda, conversaciones, catálogo, settings | `admin-panel/` |

## Cross-cutting concerns

Algunos concerns NO encajan en una sola capa:

- **Configuración** (`shared/config.py` con Pydantic Settings): infra, accesible desde todas las capas que la necesiten. Es la única excepción legal a "infra no toca módulos".
- **Logging estructurado**: infra (`observability`), accesible desde todas las capas.
- **Encryption** (`shared/encryption.py`): infra utility. Cualquier capa que persista secretos lo usa.
- **Degradación por adaptador**: `shared/circuit_breaker.py` fue removido intencionalmente. Estrategia de degradación documentada en `docs/system/07-resilience.md`. Deletion guard: `tests/unit/test_dead_code_cleanup_assertions.py:52`.

## Cómo validar que la separación se respeta

1. **Test de imports**: script que valida con AST que ningún archivo en `cores/X/` importa de `modulos/` o `infra/`. Análogo para `modulos/` no importando otros `modulos/`.
2. **Linter**: regla que bloquea `from agent.modes.X import Y` desde `agent.modes.Z`.
3. **CI gate**: PR que viola las reglas falla automáticamente.

Esto se construye en **Phase E1** del plan de migración.

## Referencias

- `03-cores.md` — detalle de cada core.
- `04-modulos.md` — detalle de cada módulo.
- `05-infra.md` — detalle de cada infra.
- `06-current-vs-target.md` — mapeo archivo-por-archivo.
- `07-migration-plan.md` — Phase E1-E5.
