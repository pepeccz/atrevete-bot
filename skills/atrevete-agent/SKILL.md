---
name: atrevete-agent
description: >
  Atrévete Bot agent patterns using create_agent + middleware stack (post-rework, April 2026).
  Trigger: When working on agent/, middleware, tools, prompts, AgentState, or create_agent wiring.
license: MIT
metadata:
  author: atrevete-bot
  version: "3.0"
  scope: [root, agent]
  auto_invoke:
    - "Working on agent/"
    - "Working on create_agent wiring"
    - "Creating/modifying middleware"
    - "Creating agent tools"
    - "Working with AgentState"
    - "Working on prompts"
---

## 1. Architecture Overview

Single LangChain `create_agent` tool-calling loop wrapped by a composed middleware chain. No StateGraph, no mode nodes, no intent router. The LLM picks tools directly each turn; middlewares hydrate context into XML-fenced slots that `PromptAssemblyMiddleware` folds into the system prompt.

### Directory Layout

```
agent/
├── main.py                     # Redis Streams consumer entry
├── graph.py                    # Thin wrapper → build_conversation_agent()
├── agent_factory.py            # build_conversation_agent(): create_agent + tools + middleware
├── llm.py                      # get_llm() — OpenRouter gpt-5.4-mini
├── checkpointer.py             # AsyncRedisSaver wiring
├── resume_handler.py           # Resume helpers for interrupted runs
├── state.py                    # AgentState TypedDict (slim, 7 fields)
├── middleware/                 # 6 composed middlewares (order matters)
│   ├── disclosure.py
│   ├── customer_resolve.py
│   ├── appointment_context.py
│   ├── dynamic_prompt.py
│   ├── prompt_assembly.py
│   └── summarize.py
├── tools/                      # 6 LangChain tools
│   ├── check_availability.py
│   ├── next_available.py       # get_next_available_options
│   ├── book.py                 # atomic create + GCal push
│   ├── update_booking.py       # mutate active draft
│   ├── manage_appointments_tool.py
│   └── escalation_tools.py
├── prompts/
│   ├── loader.py               # load_system_prompt()
│   ├── catalog_builder.py      # build_catalog_prompt_section()
│   ├── business_hours.py       # load_business_hours_snapshot()
│   ├── shared/                 # identity, rules, glossary, booking_flow
│   └── modes/                  # legacy overlays still used as prompt fragments
├── routing/
│   └── intent_types.py         # IntentType enum (legacy, no live router)
├── booking/resolvers/          # service / stylist / time resolvers
├── batching/                   # WhatsApp message batcher
├── services/                   # availability, GCal push, escalation
└── workers/                    # archiver, confirmation_worker
```

### Per-turn Pipeline

```
Redis Stream message
    │
    ▼
build_conversation_agent  (create_agent + state_schema=AgentState)
    │
    ▼  awrap_model_call chain (composed):
    1. DisclosureMiddleware           (first-turn EU AI Act prepend)
    2. CustomerResolveMiddleware      (phone → DB → _slot_customer + customer_id)
    3. AppointmentContextMiddleware   (after CustomerResolve; upcoming appts)
    4. DynamicPromptMiddleware        (catalog + business hours)
    5. PromptAssemblyMiddleware       (fold _slot_* into system_message)
    6. SummarizeMiddleware            (window=20, keep_tail=10)
    │
    ▼
LLM tool-calling loop
    │
    ▼
AsyncRedisSaver checkpoint  (thread_id="v2:{conversation_id}")
```

---

## 2. State Schema

`agent/state.py` — slim `TypedDict`. Single reducer (`add_messages`).

```python
from typing import Annotated, TypedDict
from uuid import UUID
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    conversation_id: str
    customer_phone: str
    user_message: str | None
    pending_whatsapp_name: str | None
    messages: Annotated[list[AnyMessage], add_messages]
    customer_id: UUID | None
    customer_name: str | None
```

### Slot Keys (runtime-only, NOT in static schema)

Slot-writer middlewares attach these to `request.state` via `request.override(state=...)`. `PromptAssemblyMiddleware` reads them in fixed order:

| Slot Key | Writer | Wraps As |
|----------|--------|----------|
| `_slot_customer` | `CustomerResolveMiddleware` | `<customer>...</customer>` |
| `_slot_upcoming_appointments` | `AppointmentContextMiddleware` | `<upcoming_appointments>...</upcoming_appointments>` |
| `_slot_business_hours` | `DynamicPromptMiddleware` | `<business_hours>...</business_hours>` |
| `_slot_catalog` | `DynamicPromptMiddleware` | `<catalog>...</catalog>` |

Missing slots silently skipped. Order is hardcoded in `_SLOT_ORDER` inside `prompt_assembly.py`.

### REMOVED in rework (do NOT use)

`mode_context`, `current_mode`, `mode_history`, `transition_mode()`, `merge_dicts`, `append_unique_list`, `add_message()` helper, `last_node`, `BaseModeNode`, `NodeBridgeMiddleware`. Cite `agent/state.py` and `agent/agent_factory.py` as the only sources of truth.

---

## 3. Middleware Pattern

All middlewares subclass `langchain.agents.middleware.AgentMiddleware`, override `awrap_model_call` only, and set `_allow_single_variant = True` (async-only opt-out).

### Skeleton — slot-writer

```python
from collections.abc import Awaitable, Callable
from typing import ClassVar
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

class MySlotMiddleware(AgentMiddleware):
    _allow_single_variant: ClassVar[bool] = True

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        state = request.state or {}

        # 1. Compute or fetch context (async I/O OK)
        block = await self._build_block(state)
        if not block:
            return await handler(request)

        # 2. Write slot key — never edit system_message directly
        new_state = {**state, "_slot_my_block": f"<my_block>\n{block}\n</my_block>"}

        # 3. Call handler with overridden request
        return await handler(request.override(state=new_state))
```

### Skeleton — response mutator

Used when you need to edit the LLM's reply (Disclosure prepends first-turn text):

```python
class MyResponseMiddleware(AgentMiddleware):
    _allow_single_variant: ClassVar[bool] = True

    async def awrap_model_call(self, request, handler):
        response = await handler(request)
        # mutate response.result (list[AIMessage|...])
        return ModelResponse(result=transformed_messages)
```

### Registration (load-bearing order)

`agent/agent_factory.py`:

```python
return create_agent(
    model=model,
    tools=AGENT_TOOLS,
    system_prompt=load_system_prompt(),
    middleware=[
        DisclosureMiddleware(),
        CustomerResolveMiddleware(),
        AppointmentContextMiddleware(),  # MUST be after CustomerResolve (reads customer_id)
        DynamicPromptMiddleware(),
        PromptAssemblyMiddleware(),      # MUST be after all slot-writers
        SummarizeMiddleware(window=20, keep_tail=10),
    ],
    checkpointer=checkpointer,
    state_schema=AgentState,
)
```

### Adding a new slot

1. Write middleware that produces an XML-fenced block and assigns it to a `_slot_<name>` key.
2. Append `"_slot_<name>"` to `_SLOT_ORDER` in `agent/middleware/prompt_assembly.py` at the desired position.
3. Register the middleware in `agent_factory.py` BEFORE `PromptAssemblyMiddleware`.
4. Add a unit test under `tests/unit/test_agent/test_middleware_<name>.py`.

---

## 4. Tools (6)

Tools are async `@tool`-decorated functions returning JSON-serializable dicts. State propagates via tool returns + middleware on the next turn — there is no `mode_context` to mutate.

| Tool | File | Purpose |
|------|------|---------|
| `check_availability` | `tools/check_availability.py` | Probe slots for service + stylist + day |
| `get_next_available_options` | `tools/next_available.py` | Return next N free slots |
| `book` | `tools/book.py` | Atomic create appointment + push to GCal |
| `update_booking` | `tools/update_booking.py` | Mutate active booking draft (slot collector) |
| `manage_appointments` | `tools/manage_appointments_tool.py` | List / cancel / reschedule |
| `escalate` | `tools/escalation_tools.py` | Hand off to human agent |

Resolvers (service / stylist / time) live in `agent/booking/resolvers/` and are called from inside tools. Helpers shared across tools live in `agent/tools/_booking_helpers.py`.

### Tool skeleton

```python
from langchain_core.tools import tool

@tool
async def check_availability(service_id: str, day: str) -> dict:
    """Return available slots for service on day. Day in YYYY-MM-DD."""
    options = await availability_service.probe(service_id, day)
    return {
        "success": True,
        "options": [{"start": o.start.isoformat(), "stylist": o.stylist} for o in options],
    }
```

### Adding a new tool

1. Implement async `@tool` function in `agent/tools/<name>.py`.
2. Append to `AGENT_TOOLS` list in `agent/agent_factory.py`.
3. Update prompt fragments under `agent/prompts/shared/` (or `prompts/modes/`) to teach the LLM when to call it.
4. Add unit test under `tests/unit/test_agent/test_tools_<name>.py`.

---

## 5. Prompts

Base prompt loaded once via `load_system_prompt()` at agent build. Dynamic context (customer, appointments, catalog, business hours) is injected per-turn by middleware as XML slots appended to the base prompt.

### Files

- `agent/prompts/shared/identity.md` — bot persona (Maite, salón Atrévete)
- `agent/prompts/shared/critical_rules.md` — hard constraints
- `agent/prompts/shared/booking_flow.md` — booking step-by-step instructions
- `agent/prompts/shared/glossary.md` — service vocabulary
- `agent/prompts/modes/*.md` — legacy mode overlays still used as prompt fragments (concatenated into base prompt; not gated by mode anymore)
- `agent/prompts/catalog_builder.py` — async DB-driven catalog (with TTL cache)
- `agent/prompts/business_hours.py` — async business hours snapshot

### Editing rules

- **User-facing strings**: Spanish (Rioplatense if applicable to product copy, but Maite uses ES-ES casual).
- **Comments / instructions to LLM**: Spanish.
- **File comments / Python docstrings**: English.
- Never hardcode service names, prices, or hours into prompts — they come from the DB through `catalog_builder` / `business_hours`.

---

## 6. Critical Rules

### 1. Use `request.override(state=...)`. Never mutate `request.state` in place

```python
# ❌ WRONG — silent failure: ModelRequest is frozen-ish; mutations don't propagate
request.state["_slot_x"] = "..."

# ✅ CORRECT
new_state = {**(request.state or {}), "_slot_x": "..."}
return await handler(request.override(state=new_state))
```

### 2. Slot-writer middlewares MUST NOT edit `system_message` directly

`PromptAssemblyMiddleware` owns assembly. Direct edits cause:
- double-assembly when the model reuses the prompt cached
- slot-order bugs (block appears before `_slot_customer` etc.)

```python
# ❌ WRONG
new_system = SystemMessage(content=request.system_message.content + "\n\n<my>...</my>")
return await handler(request.override(system_message=new_system))

# ✅ CORRECT
new_state = {**state, "_slot_my": "<my>...</my>"}
return await handler(request.override(state=new_state))
```

### 3. Async-only middleware → `_allow_single_variant: ClassVar[bool] = True`

Required to bypass the test-suite's sync-parity guardrail. Do NOT implement a sync `wrap_model_call` variant — runtime is async-only and a sync path would be dead code.

### 4. Middleware ORDER in `agent_factory.py` is load-bearing

Required ordering invariants:

- `AppointmentContextMiddleware` MUST run AFTER `CustomerResolveMiddleware` (reads `customer_id` set by it).
- `PromptAssemblyMiddleware` MUST run AFTER every slot-writer.
- `SummarizeMiddleware` MUST run last (operates on the final composed message list).

### 5. Use async/await for ALL I/O

DB lookups (`customer_resolve`, `appointment_context`) and prompt loaders (`catalog_builder`, `business_hours`) are async SQLAlchemy / async functions. There is no sync DB code path. New middleware that touches the DB must use `database.connection.get_async_session()`.

### 6. UUID for all IDs; `DateTime(timezone=True)` for timestamps

Inherits from project-wide rules. UUIDs flow through tool returns and `_slot_*` blocks as plain strings (`str(appointment.id)`).

### 7. Spanish for user-facing copy, English for code/comments

### 8. Don't reintroduce removed concepts

`mode_context`, `current_mode`, `transition_mode`, `BaseModeNode`, `merge_dicts`, intent router, etc. — all removed in the rework. New cross-cutting context belongs in a slot-writer middleware, not in state.

---

## 7. Anti-patterns

### NEVER edit `request.state` in place

Already covered in Rule 1. Most common mistake when porting old node code.

### NEVER call `system_message=...` override from a slot-writer

Already covered in Rule 2.

### NEVER skip `_allow_single_variant` on async-only middleware

Test suite will fail with a parity-guardrail error pointing at the missing sync variant. Do not implement a fake sync method to silence it — set the flag.

### NEVER add per-turn business logic to `agent_factory.py`

The factory is a wiring file. All per-turn logic belongs in middleware or tools. The factory's only job is `create_agent(...)`.

### NEVER bypass `PromptAssemblyMiddleware` order

Adding a slot-writer AFTER `PromptAssemblyMiddleware` means its slot is silently dropped. Always add new slot-writers BEFORE assembly in the registration list.

### NEVER use sync DB clients

```python
# ❌ WRONG
from database.connection import get_sync_session   # does not exist; do not create
session = get_sync_session()

# ✅ CORRECT
from database.connection import get_async_session
async with get_async_session() as session:
    result = await session.execute(...)
```

---

## 8. Testing

```bash
# All agent tests
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/pytest tests/unit/test_agent/

# Specific middleware
./venv/bin/pytest tests/unit/test_agent/test_middleware_customer_resolve.py -v

# Tools
./venv/bin/pytest tests/unit/test_agent/test_tools_book.py -v
```

### Middleware test pattern

Build a fake `ModelRequest` with the input state, capture the `state` passed to `handler`, assert slot is present and well-formed.

```python
async def test_customer_resolve_writes_slot_for_known_customer(...):
    middleware = CustomerResolveMiddleware()
    captured = {}

    async def handler(req):
        captured["state"] = req.state
        return ModelResponse(result=[AIMessage(content="ok")])

    request = ModelRequest(state={"customer_phone": "+34..."}, system_message=SystemMessage(content=""), ...)
    await middleware.awrap_model_call(request, handler)

    assert "_slot_customer" in captured["state"]
    assert "<customer>" in captured["state"]["_slot_customer"]
```

### Tool test pattern

Tools are plain async functions; invoke directly via `.ainvoke({...})` and assert on the returned dict.

---

## 9. Resources

- [Root AGENTS.md](../../AGENTS.md) — Repo governance
- [agent/AGENTS.md](../../agent/AGENTS.md) — Component governance
- [agent/CLAUDE.md](../../agent/CLAUDE.md) — Component quick-ref
- `agent/agent_factory.py` — Single source of truth for graph wiring
- `agent/state.py` — State schema
- `agent/middleware/` — All middleware implementations

**Last Updated**: 2026-04-27 (post create_agent rework)
