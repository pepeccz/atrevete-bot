# Atrévete Bot — Visión del Sistema

> Documento de referencia. Lee esto primero. Resto de `docs/system/` profundiza cada bloque.

## Qué es

Asistente conversacional vía WhatsApp para una peluquería con **5 estilistas**. Recibe mensajes a través de Chatwoot, mantiene una conversación natural en español (rioplatense/peninsular), y gestiona el ciclo completo de reservas: consultar disponibilidad, reservar, cancelar y reagendar citas. Se llama **Maite**.

El calendario es **DB-first**: PostgreSQL es la fuente de verdad; Google Calendar es un mirror push-only para que las estilistas vean su agenda desde su móvil.

## Para quién

- **Cliente final**: persona que escribe a la peluquería por WhatsApp. NO sabe que habla con un bot, o lo intuye pero le da igual mientras le resuelvan.
- **Operador del salón**: usa el panel `admin-panel/` (Next.js 15) para ver agenda, intervenir conversaciones, gestionar catálogo y precios.
- **Estilistas**: solo consumen Google Calendar (no entran al panel).

## Scope

### Dentro del scope
- Reserva multi-paso (servicio → estilista → fecha → slot → nombre → confirmación).
- Desambiguación de servicios con audiencia (ej: "Corte" → ¿señora, caballero, niño, bebé?).
- Cancelación y reprogramación de citas existentes.
- Información general (horarios, precios, ubicación, servicios disponibles).
- Escalado a humano cuando el bot no puede resolver.
- Confirmación automática 48h antes de cita.
- Memoria de preferencias del cliente entre conversaciones (servicio favorito, estilista habitual).

### Fuera del scope
- Pagos in-chat (Stripe fue removido).
- Multi-salón (la arquitectura es single-tenant).
- Multi-idioma (solo español).
- Reservas con más de un servicio simultáneo de salones distintos.
- Análisis de sentimiento, upselling automatizado, marketing.

## Stack

| Capa | Tecnología |
|------|-----------|
| Agente | Python 3.11+, LangGraph 0.6.7+, LangChain 0.3.0+ |
| LLM | GPT-5.4-mini vía OpenRouter |
| API | FastAPI 0.116, Pydantic 2.x, Uvicorn |
| DB | PostgreSQL 15+, SQLAlchemy 2 (asyncpg), Alembic |
| Cache / Streams | Redis Stack (Streams + RedisJSON + RedisSearch para checkpointer) |
| Admin | Next.js 15.0.3 (App Router), React 18, Tailwind |
| Externos | Chatwoot (gateway WhatsApp), Google Calendar API |

## Componentes top-level

| Carpeta | Rol |
|---------|-----|
| `agent/` | LangGraph orchestrator, modes, tools, prompts, middleware, routing, state |
| `api/` | FastAPI: webhooks Chatwoot + admin endpoints |
| `database/` | SQLAlchemy models + Alembic migrations + seeds |
| `admin-panel/` | Next.js 15 admin |
| `shared/` | Config (Pydantic Settings), clientes externos, utilidades, audience maps, negation phrases |
| `tests/` | 254 archivos: unit + integration + qa scenarios |

## Estado actual de la arquitectura

**v6.x mode-based**. Cinco modes (GREETING, BOOKING, GENERAL, ESCALATION, APPOINTMENT_MANAGEMENT) que heredan de `BaseModeNode`. El BookingMode usa `create_agent` + middleware composable; AppointmentManagement aún arrastra el loop legacy `_run_agentic_loop`.

**Estado real**: arquitectura sólida en principios pero con dominio del salón aún parcialmente mezclado en `shared/` (E1 ya extrajo `negation_phrases` a `infra/resolvers/`; el resto se mueve en E2-E4), modes accediendo a `database/` directamente, y lógica de flow distribuida entre prompt + flags + flow_hint. Esto produce bugs estructurales recurrentes (ver `04-modulos.md` → booking → "Bug histórico: ¿algo más? loop").

**Por qué este documento existe**: bajar a tierra qué hay HOY, identificar qué es **dominio**, **capability** o **adaptador**, y trazar el camino para una separación limpia `cores/modulos/infra/ui`. Ver `02-layers.md`.

## Cómo leer el resto

1. `01-architecture-principles.md` — los principios que ordenan todo (workflow > agent, capability contract, una sola write path, tools como state machine).
2. `02-layers.md` — la separación cores/modulos/infra/ui y las **reglas de dependencia** entre capas.
3. `03-cores.md` — entidades de dominio del salón.
4. `04-modulos.md` — capabilities conversacionales.
5. `05-infra.md` — adaptadores técnicos.
6. `06-current-vs-target.md` — mapa archivo-por-archivo de hoy vs target.
7. `07-migration-plan.md` — plan de migración (Phase E1-E5, sin big-bang, behind feature flag).

## Documentos vinculados

- `CLAUDE.md` (raíz) — guía operativa: comandos, env vars, deploy.
- `AGENTS.md` (raíz) — gobernanza del repo.
- `docs/AGENT_SPEC.md` — spec antigua del agente (anterior a esta documentación).
- `docs/refactor/` — exploraciones previas, conservadas como histórico.

---

**Última actualización**: 2026-04-18
