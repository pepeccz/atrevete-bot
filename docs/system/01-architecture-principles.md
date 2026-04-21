# Principios de Arquitectura

> Reglas innegociables. Si una decisión de diseño viola uno de estos principios, se rechaza o se justifica explícitamente.

Estos principios derivan del análisis empírico de 20+ iteraciones del booking flow. Cada uno cierra una clase de bugs que nos ha mordido.

---

## P1 — Workflow > agente para flujos acotados

**Booking, cancelación y reagendamiento son workflows, no agentes abiertos.** Tienen ≤15 transiciones predecibles. Tratarlos como un loop agéntico abierto (LLM elige libremente la siguiente herramienta sobre 8 tools y un prompt grande) es sobre-ingeniería: paga complejidad y latencia que no necesitamos.

**Aplicación**: Python posee las transiciones de estado. El LLM posee la narración (Spanish/Rioplatense, calidez, fraseo) y la extracción de argumentos para tools. Workflow shell + bolsillos agénticos.

**Cuándo se rompe**: si añadís un flow nuevo (ej. "loyalty inquiry") y necesitás un planner-executor genérico, este principio NO aplica para ese flow. Documentalo.

---

## P2 — Una mutación, una vía

**Cada campo de estado tiene EXACTAMENTE UN write path.**

Caso real que motivó este principio: `service_audience_hint` se escribía desde tres sitios (`_extract_audience_from_reply`, `update_booking._build_response._patch`, manualmente en `_post_tool_result`). Resultado: signal stale en turno N+1 → LLM re-pregunta audiencia que el usuario ya respondió.

**Aplicación**:
- En BookingContext: todo cambio pasa por `_booking_context_patch` devuelto por el tool.
- Resolvers pre-loop también escriben vía patch, no mutan el dict directo.
- NO existe `booking_context["X"] = ...` directo en handlers.

**Cómo se hace cumplir**: AST-lint test (ya parcialmente implementado).

---

## P3 — Intents binarios → resolver determinista pre-loop

**Si la decisión es categórica y el vocabulario es acotado, NO uses LLM.** Usá un resolver Python pre-loop con normalización NFKD + difflib (cutoff 0.86). Latencia <1ms, gratis, 100% reproducible.

**Casos**:
- Sí/no/afirmación.
- Selección de dígito ("la 1", "el segundo").
- Audiencia ("señora", "caballero", "nene", "bebé").
- Negación de "¿algo más?" ("nada más", "ya está", "listo", "nope").
- Cancelación / abort mid-flow ("dejalo", "cancela").

**Patrón canónico**: `infra/resolvers/negation.py:is_negation()` (movido de `shared/negation_phrases.py` en E1 per P8). Replicar para cada intent binario.

**Cuándo escalar**: medir post-deploy. Si `match_rate < 97%` o `(no_match_rate + user_retry_rate) > 3%` durante 14 días → escalar a clasificador Haiku como fallback. Decisión basada en evidencia, no en miedo.

---

## P4 — Intents narrativos → LLM in-loop

**Si la decisión es "¿qué digo ahora?" o requiere comprensión semántica, dejaselo al LLM.**

**Casos**:
- Fechas en lenguaje natural ("el martes que viene", "pasado mañana").
- Resolución de nombres de servicio (con fuzzy DB lookup como validador).
- Extracción de nombre del cliente desde frase libre ("soy Pablo García").
- Fraseo cálido de toda respuesta al usuario.
- Recuperación narrativa cuando un tool rechaza argumentos.

**Regla del pulgar**: el costo de un falso negativo en Python es UN llamado al LLM (el LLM sigue razonando). El costo de un intent classification incorrecto del LLM es un loop infinito que confunde al cliente. El sesgo es hacia Python.

---

## P5 — Tools devuelven transiciones de estado, no prosa

**Toda tool retorna un objeto tipado**:

```
ToolResponse:
  status: Literal["ok", "partial", "rejected", "complete"]
  collected: list[str]      # items capturados (legible humano)
  missing: list[str]        # qué falta
  next_step: str            # estado descriptivo: "Audiencia ambigua: familia Corte; falta confirmar variante"
  errors: list[str]         # SOLO errores de input (nunca instrucciones de flujo)
  payload: dict             # data específica de la tool
```

**Reglas duras**:
- `errors[]` y `ToolCallRejection.error_message` NUNCA empiezan con verbos imperativos (Pregunta, Muestra, Llama, Debes). Describen qué estuvo mal con el INPUT.
- `next_step` es ESTADO descriptivo. El prompt enseña al LLM a narrar desde él.
- El LLM NO inventa estado. Solo dispara mutaciones llamando tools.

**Por qué**: si los errores contienen instrucciones imperativas, el LLM las reproduce textualmente al usuario. Bug histórico (#3906) en AppointmentManagementMode.

---

## P6 — Visibilidad de tools = state machine

**`DynamicToolsMiddleware` es la autoridad de qué puede hacer el LLM en cada momento.**

Una tool visible es invocable. Una tool oculta no existe desde la perspectiva del LLM (ni schema ni descripción se mandan al modelo, validado en design Q G5).

**Aplicación**:
- `check_availability` se oculta cuando `pending_disambiguations` está activo (commit 06a5ba1, renombrado Phase 2).
- `book` solo aparece cuando `_booking_complete` retorna true.
- Cada capability define `get_tools(state) → list[Tool]` que filtra dinámicamente.

**Por qué**: gates en `_pre_tool_call` que rechazan invocaciones malas son SUBÓPTIMOS. Si el LLM ve la tool en el schema, va a intentar llamarla; los rechazos generan bucles. Mejor: que la tool no exista cuando no debe usarse.

---

## P7 — Capability contract estricto

Cada modo (booking, cancelación, etc.) implementa un contrato de **6 campos** (más `name` como séptimo identificador de telemetría):

1. **name** — identificador estable para registry y telemetría (ej. `"booking"`).
2. **state_slice** — un sub-dict del ConversationState que SOLO esta capability muta.
3. **tools** — lista de tools disponibles.
4. **prompt_overlay** — un `.md` con la guía específica del flow.
5. **pre_loop_resolvers** — lista de resolvers deterministas a correr antes del LLM.
6. **completion_predicate** — función pura `(state) → bool` que dice si el flow terminó.
7. **exit_edges** — qué modos pueden activarse al completar este (típicamente GENERAL).

**Implementación formal (introducida en E1)**: `agent/core/capability.py` define `Capability(ABC)` con los 7 campos como `@property @abstractmethod`. Omitir cualquiera de los 7 lanza `TypeError` en tiempo de instanciación — enforcement en runtime, no solo en estática. El primer implementor concreto es `BookingCapability` en E2.

**Test de extensibilidad**: añadir una capability nueva (ej. `loyalty_mode`) requiere SOLO crear la capability + 1 entrada en intent_router. CERO cambios en booking, appointment_management o infra. Si tocás otro modo, fallaste.

---

## P8 — Dominio fuera de `shared/`

**`shared/` es para utilidades técnicas reutilizables (config, clientes HTTP, encryption, logging). NO para dominio del salón.**

Ejemplos actuales que violan esto:
- `shared/audience_maps.py` — define las audiencias del salón. Es DOMINIO.
- `shared/negation_phrases.py` — frases de negación. Frontera difusa, pero más cerca de dominio conversacional que de utility.

**Aplicación**: dominio va a `cores/`. Resolvers van a `infra/resolvers/`. Adaptadores externos van a `infra/<servicio>/`.

---

## P9 — DB por capa de servicio, no acceso directo desde modes

**Los modes NO importan `database.models`.** Pasan por una capa de servicio (`StylistQueryService`, `ServiceQueryService`, `AvailabilityService`, etc.) que vive en el core correspondiente.

**Por qué**: testabilidad (mock del service, no de la DB). Aislamiento de queries. Cambios de schema no rompen modes.

**Estado actual**: violado. `booking_mode.py:467` y `:488` hacen queries directas a `Stylist` y `Service`. Ver `06-current-vs-target.md`.

---

## P10 — Observabilidad de primera clase

**Cada resolver pre-loop, cada tool call, cada transición de modo emite un log estructurado.**

Mínimo:
- Resolver: `{resolver, conversation_id, turn, user_text_hash, matched, matched_phrase, fuzzy_distance}`
- Tool call: `{tool, conversation_id, turn, status, collected_count, missing, next_step, latency_ms, errors}`
- Mode transition: `{from_mode, to_mode, trigger, conversation_id, turn}`

**Métricas agregadas (offline desde logs)**:
- `resolver.match_rate` por resolver.
- `tool.rejection_rate` por tool por modo.
- `mode.completion_rate` (booking, cancel, reschedule).
- `turns_per_booking` p50/p95.
- `loop_detection_rate`.

**Por qué**: el bug "¿algo más? loop" tomó 5 iteraciones porque NO había métricas. El equipo arreglaba a ojo. Sin métricas, cada fix es una hipótesis sin validar.

**Measured-gate contract**: cada resolver tiene fecha de revisión + thresholds. Si los thresholds breachen → escalar a siguiente tier (ej. resolver determinista → resolver Haiku).

---

## Anti-principios (lo que NUNCA hacemos)

- **Multi-agent fan-out**: los flows comparten customer + appointment + stylist. Splitearlos en agentes aislados es coordinación cara sin beneficio.
- **Deep Agents (planner-executor)**: una reserva tiene ≤15 transiciones. Un planner abierto es overkill: 3-5x token cost, +500ms-2s/turn.
- **Pure-LLM con cero state Python**: probado en `trust-llm-reasoning` (#3652), revertido 24h después. Bajo presión adversarial (typos, dialecto), el LLM salta pasos.
- **Schema-forced output para narración**: rompe el tono cálido. Solo usamos structured output para CLASIFICACIÓN (intent router, fallback classifier).
- **Multi-write path por field** (P2 violado): genera signals stale, leaks, y bugs imposibles de trazar.

---

## Cómo se aplican

Estos principios son la **vara** contra la que se mide cada PR y cada change SDD. Si una capability nueva o un fix viola un principio, hay que justificarlo en el proposal o reescribirlo.

El plan de migración (`07-migration-plan.md`) está estructurado para que **cada fase haga cumplir más principios** sobre el código actual.
