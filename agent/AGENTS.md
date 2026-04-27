# Agent Component Guidelines

Conversational agent built on **LangChain `create_agent` + middleware stack**. No custom StateGraph, no mode nodes, no intent router. Single LLM tool-calling loop wrapped by 6 middlewares that hydrate state and assemble the system prompt.

> **Architecture**: `create_agent` (langchain.agents) loop with 6 tools and 6 composed middlewares. Each turn: middleware chain hydrates customer + appointments + catalog + business hours into XML-fenced slots, assembles into the system prompt, then the LLM picks tools.

---

## Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|
| Creating/modifying middleware | `atrevete-agent` |
| Creating agent tools | `atrevete-agent` |
| Working on `create_agent` wiring | `atrevete-agent` |
| Working on conversation flow | `atrevete-agent` |
| Working on prompts | `atrevete-prompts` |
| Working with `AgentState` | `atrevete-agent` |
| Writing Python tests | `pytest` |

---

## Directory Structure

```
agent/
├── main.py                  # Redis Streams consumer entry point
├── graph.py                 # Thin wrapper → build_conversation_agent()
├── agent_factory.py         # build_conversation_agent: create_agent + tools + middleware
├── llm.py                   # get_llm() factory (OpenRouter gpt-5.4-mini)
├── checkpointer.py          # AsyncRedisSaver wiring
├── resume_handler.py        # Resume helpers for interrupted runs
├── state.py                 # AgentState TypedDict (slim, 7 fields)
├── middleware/              # 6 composed middlewares (order matters)
│   ├── disclosure.py        # First-turn EU AI Act disclosure prepend
│   ├── customer_resolve.py  # phone → Customer DB lookup, writes _slot_customer
│   ├── appointment_context.py # upcoming PENDING/CONFIRMED appts → _slot_upcoming_appointments
│   ├── dynamic_prompt.py    # catalog + business hours → _slot_catalog, _slot_business_hours
│   ├── prompt_assembly.py   # collapse _slot_* keys into system_message in fixed order
│   └── summarize.py         # collapse history > window into [Resumen previo] SystemMessage
├── tools/                   # 6 LangChain tools
│   ├── check_availability.py
│   ├── next_available.py    # get_next_available_options
│   ├── book.py              # atomic booking (create + GCal push)
│   ├── update_booking.py    # mutate active booking draft
│   ├── manage_appointments_tool.py # view/cancel/reschedule
│   └── escalation_tools.py  # escalate
├── prompts/
│   ├── loader.py            # load_system_prompt() — base prompt loader
│   ├── catalog_builder.py   # build_catalog_prompt_section()
│   ├── business_hours.py    # load_business_hours_snapshot()
│   ├── shared/              # identity, rules, glossary, booking_flow
│   └── modes/               # legacy mode overlays still used as prompt fragments
├── routing/
│   └── intent_types.py      # IntentType enum (legacy, no live router)
├── booking/
│   └── resolvers/           # service / stylist / time resolvers used by tools
├── batching/
│   └── message_batcher.py   # WhatsApp message batcher (consumer side)
├── services/                # Business logic (availability, GCal push, escalation)
└── workers/                 # Background workers (archiver, confirmation)
```

---

## Architecture Overview

### Pipeline (per turn)

```
Redis Streams message
        │
        ▼
┌───────────────────┐
│ build_conversation│  create_agent(model, tools, system_prompt, middleware, state_schema)
│      _agent       │
└────────┬──────────┘
         │
         ▼  awrap_model_call chain (composed)
┌─────────────────────────────────────────────────────────┐
│ 1. DisclosureMiddleware                                 │  prepend EU-AI-Act on first turn
│ 2. CustomerResolveMiddleware                            │  phone → DB → _slot_customer + customer_id
│ 3. AppointmentContextMiddleware  (after CustomerResolve)│  upcoming appts → _slot_upcoming_appointments
│ 4. DynamicPromptMiddleware                              │  catalog + hours → _slot_catalog, _slot_business_hours
│ 5. PromptAssemblyMiddleware                             │  fold _slot_* into system_message (fixed order)
│ 6. SummarizeMiddleware (window=20, keep_tail=10)        │  compress old messages
└─────────────────────────────────────────────────────────┘
         │
         ▼
   model.invoke (LLM tool-calling loop)
         │
         ▼
       checkpoint → AsyncRedisSaver (thread_id v2:{conversation_id})
```

### Tools (6)

| Tool | Purpose |
|------|---------|
| `check_availability` | Probe slots for service + stylist + day |
| `get_next_available_options` | Return next N free slots |
| `book` | Atomic create appointment + push to GCal |
| `update_booking` | Mutate active booking draft (slot collector) |
| `manage_appointments` | List / cancel / reschedule existing appointments |
| `escalate` | Hand off to human agent |

LLM picks tools directly. No keyword router gates the model — the system prompt and middleware-injected slots provide the steering.

### Slot Order (PromptAssemblyMiddleware)

Fixed order appended to base `system_message.content`:

1. `_slot_customer` → `<customer>...</customer>`
2. `_slot_upcoming_appointments` → `<upcoming_appointments>...</upcoming_appointments>`
3. `_slot_business_hours` → `<business_hours>...</business_hours>`
4. `_slot_catalog` → `<catalog>...</catalog>`

Missing slots silently skipped.

---

## Middleware Pattern

All middlewares subclass `langchain.agents.middleware.AgentMiddleware` and override `awrap_model_call` only. Sync variant intentionally absent (`_allow_single_variant = True`) — runtime is async-only.

```python
class MyMiddleware(AgentMiddleware):
    _allow_single_variant: ClassVar[bool] = True

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        # 1. Read state
        state = request.state or {}

        # 2. Compute slot / mutate state
        new_state = {**state, "_slot_my_block": "<my_block>...</my_block>"}

        # 3. Call handler with override
        modified = request.override(state=new_state)
        return await handler(modified)
```

**Slot-writer middlewares** (CustomerResolve, AppointmentContext, DynamicPrompt) write `_slot_*` keys ONLY. They do NOT mutate `system_message` directly — assembly is centralized in `PromptAssemblyMiddleware`.

**Response-mutating middlewares** (Disclosure) wrap `await handler(request)` and edit the returned `ModelResponse.result`.

---

## State Schema

`agent/state.py` — slim `TypedDict`:

```python
class AgentState(TypedDict):
    conversation_id: str
    customer_phone: str
    user_message: str | None
    pending_whatsapp_name: str | None
    messages: Annotated[list[AnyMessage], add_messages]   # std reducer
    customer_id: UUID | None
    customer_name: str | None
```

`add_messages` from `langgraph.graph.message` is the only reducer. Slot keys (`_slot_*`) are added at runtime by middlewares and not part of the static schema.

No `mode_context`, no `current_mode`, no `transition_mode`, no `merge_dicts`. All gone with the rework.

---

## Critical Rules

### 1. Use `request.override(state=...)` — never mutate `request.state` in place
```python
# ❌ WRONG
request.state["_slot_x"] = "..."  # silent failure

# ✅ CORRECT
new_state = {**(request.state or {}), "_slot_x": "..."}
return await handler(request.override(state=new_state))
```

### 2. Write `_slot_*` keys, never edit `system_message` directly in slot-writer middlewares
PromptAssemblyMiddleware owns assembly. Bypassing it breaks slot order and double-assembly bugs.

### 3. Async-only middlewares set `_allow_single_variant = True`
Required to opt out of the sync-parity guardrail. Otherwise the test suite flags missing sync variant.

### 4. New middlewares: register in `agent_factory.py` middleware list with explicit order
```python
middleware=[
    DisclosureMiddleware(),
    CustomerResolveMiddleware(),
    AppointmentContextMiddleware(),  # MUST run after CustomerResolve (reads customer_id)
    DynamicPromptMiddleware(),
    PromptAssemblyMiddleware(),      # MUST run AFTER all slot-writers, BEFORE Summarize
    SummarizeMiddleware(window=20, keep_tail=10),
]
```

### 5. Always `async/await` for I/O — no sync DB calls
DB lookups in `customer_resolve` / `appointment_context` use async SQLAlchemy.

---

## Tools Pattern

Tools are plain `@tool`-decorated async functions returning JSON-serializable dicts. State plumbing happens through middleware and tool returns — there is no `mode_context` to mutate.

```python
@tool
async def check_availability(...) -> dict:
    return {
        "success": True,
        "options": [...],
    }
```

Booking helpers (resolvers for service / stylist / time) live in `agent/booking/resolvers/`.

---

## Testing

```bash
# All agent tests
DATABASE_URL="postgresql+asyncpg://..." pytest tests/unit/test_agent/

# Specific middleware
pytest tests/unit/test_agent/test_middleware_customer_resolve.py -v
```

---

## Resources

- [Root AGENTS.md](../AGENTS.md) — Repository governance
- [atrevete-agent skill](../skills/atrevete-agent/SKILL.md) — Detailed patterns
- `agent/agent_factory.py` — Single source of truth for graph wiring
- `agent/state.py` — State schema

**Last Updated**: 2026-04-27 (post create_agent rework, v2 thread_id)

### Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|
| Creating agent tools | `atrevete-agent` |
| Creating new prompt module | `atrevete-prompts` |
| Creating/modifying middleware | `atrevete-agent` |
| Editing agent system prompts | `atrevete-prompts` |
| Editing identity.md or critical_rules.md | `atrevete-prompts` |
| Modifying core prompt rules | `atrevete-prompts` |
| Modifying files in agent/prompts/ | `atrevete-prompts` |
| Modifying mode prompt instructions | `atrevete-prompts` |
| Reviewing prompt quality | `atrevete-prompts` |
| Working on agent/ | `atrevete-agent` |
| Working on create_agent wiring | `atrevete-agent` |
| Working on prompt .md files | `atrevete-prompts` |
| Working on prompts | `atrevete-agent` |
| Working on system prompts | `atrevete-prompts` |
| Working with AgentState | `atrevete-agent` |
