---
name: atrevete-agent
description: >
  Atrévete Bot agent patterns using LangGraph v6.0 mode-based architecture.
  Trigger: When working on agent/, mode nodes, routing, prompts, state, or tools.
license: MIT
metadata:
  author: atrevete-bot
  version: "2.0"
  scope: [root, agent]
  auto_invoke:
    - "Working on agent/"
    - "Creating/modifying mode nodes"
    - "Working on LangGraph"
    - "Working on routing"
    - "Working on prompts"
    - "Working on state management"
    - "Creating agent tools"
---

## 1. Architecture Overview

### Directory Layout

```
agent/
├── main.py                              # Redis Streams consumer entry point
├── graphs/
│   └── conversation_flow.py            # StateGraph factory (v6.0)
├── modes/
│   ├── base.py                          # BaseModeNode abstract class + agentic loop
│   ├── greeting_mode.py                 # GREETING: welcome + menu, no name collection
│   ├── booking_mode.py                  # BOOKING: LLM-driven multi-step booking
│   ├── general_mode.py                  # GENERAL: FAQ/info queries
│   ├── escalation_mode.py               # ESCALATION: deterministic FSM handoff
│   ├── appointment_management_mode.py   # APPOINTMENT_MANAGEMENT: list/cancel/reschedule
│   ├── confirmation_reply_node.py       # CONFIRMATION_REPLY: WhatsApp template responses
│   └── appointment_context.py          # AppointmentContext TypedDict
├── routing/
│   └── intent_router.py                 # Keyword + LLM hybrid classifier (10 intents)
├── prompts/
│   ├── loader.py                        # Layered prompt assembly + TTL cache
│   ├── catalog_builder.py               # DB-driven service catalog (5-min cache)
│   ├── shared/
│   │   ├── identity.md                  # Bot persona + first-turn disclosure
│   │   └── critical_rules.md            # Hard constraints
│   └── modes/
│       ├── greeting.md                  # GREETING overlay
│       ├── booking.md                   # BOOKING overlay
│       ├── general.md                   # GENERAL overlay
│       ├── escalation.md                # ESCALATION overlay (reference only — mode is deterministic)
│       └── appointment_management.md    # APPOINTMENT_MANAGEMENT overlay
├── state/
│   ├── schemas.py                       # ConversationState + BookingContext + reducers
│   ├── checkpointer.py                  # Redis checkpointer
│   └── helpers.py                       # add_message(), get_last_user_message()
├── tools/
│   ├── availability_tools.py            # check_availability
│   ├── booking_tools.py                 # book (atomic transaction)
│   ├── manage_appointments_tool.py      # manage_appointments
│   ├── escalation_tools.py              # escalate_to_human
│   └── customer_tools.py                # manage_customer
├── utils/
│   └── fuzzy_resolver.py                # FuzzyResolver for DB name matching
├── services/
│   ├── availability_service.py          # DB-first availability
│   ├── gcal_push_service.py             # Fire-and-forget Google Calendar push
│   └── escalation_service.py            # Escalation business logic
└── workers/
    ├── conversation_archiver.py         # Archive to PostgreSQL
    └── confirmation_worker.py           # WhatsApp confirmation template worker
```

---

## 2. Graph Topology

### Pipeline

```
START → preprocess → router → mode_dispatcher → [mode node] → summarize → END
```

### Nodes

| Node | Type | Purpose |
|------|------|---------|
| `preprocess` | async fn | Adds user message to history, clears `user_message`, detects first interaction, checks customer in DB |
| `router` | async fn | Classifies intent, applies routing rules, sets `current_mode` |
| `greeting` | async fn | Delegates to `GreetingMode.handle()` |
| `booking` | async fn | Delegates to `BookingModeNode.handle()` |
| `general` | async fn | Delegates to `GeneralMode.handle()` |
| `escalation` | async fn | Delegates to `EscalationMode.handle()` |
| `appointment_management` | async fn | Delegates to `AppointmentManagementMode.handle()` |
| `confirmation_reply` | async fn | Handles WhatsApp confirmation template replies |
| `summarize` | async fn | Compresses old messages; clears `user_message` |

### Edges

```python
graph.set_entry_point("preprocess")
graph.add_edge("preprocess", "router")
graph.add_conditional_edges("router", mode_dispatcher, {
    "greeting": "greeting",
    "general": "general",
    "booking": "booking",
    "escalation": "escalation",
    "confirmation_reply": "confirmation_reply",
    "appointment_management": "appointment_management",
})
# All modes → summarize → END
for node in ["greeting","general","booking","escalation","appointment_management","confirmation_reply"]:
    graph.add_edge(node, "summarize")
graph.add_edge("summarize", END)
```

### `mode_dispatcher` (conditional edge function)

```python
def mode_dispatcher(state: ConversationState) -> str:
    mode_to_node = {
        "GREETING": "greeting",
        "GENERAL": "general",
        "BOOKING": "booking",
        "ESCALATION": "escalation",
        "CONFIRMATION_REPLY": "confirmation_reply",
        "APPOINTMENT_MANAGEMENT": "appointment_management",
    }
    return mode_to_node.get(state.get("current_mode") or "GENERAL", "general")
```

### `preprocess` behaviour (critical)

- Reads `state["user_message"]` (the transient incoming message field)
- Calls `add_message(state, "user", user_message)` to persist it to `messages`
- Sets `user_message = None` immediately — all downstream nodes MUST use `get_last_user_message()`
- Detects `is_first_interaction` (True when `messages` was empty before this turn)
- Checks customer in DB and sets `customer_id` / `customer_name` if found
- Checks for pending appointment confirmation templates

---

## 3. Router Priorities

Rules applied in priority order inside `router_node`:

| # | Condition | Result |
|---|-----------|--------|
| 1 | `escalation_triggered=True` | → ESCALATION |
| 2 | `error_count >= 3` | → ESCALATION (auto) |
| 2.5 | `pending_confirmation_appointment_id` AND intent in `{confirm,reject,cancel}` | → CONFIRMATION_REPLY |
| 3 | `intent == escalate` | → ESCALATION (+ save BOOKING draft if in BOOKING) |
| 4 | `current_mode == BOOKING AND intent == ask_info` | Stay BOOKING if booking-related query or active booking with no exit phrase; else → GENERAL (save draft) |
| 5 | `current_mode == BOOKING AND intent not in {cancel,reject,ask_info}` | Stay BOOKING (inertia) |
| 5.5 | `current_mode == ESCALATION AND intent not in {book}` | Stay ESCALATION (inertia) |
| 5.8 | `current_mode == APPOINTMENT_MANAGEMENT AND intent not in {book,greet}` | Stay APPOINTMENT_MANAGEMENT |
| 6 | `intent in {reschedule, check_appointments}` | → APPOINTMENT_MANAGEMENT |
| 7 | `current_mode == GENERAL AND has_general_booking_handoff AND intent in {confirm,ambiguous}` | → BOOKING (Rule 7.9 service handoff) |
| 8 | `intent == book` | → BOOKING (restores BOOKING draft from `draft_contexts` if available) |
| 8.5 | `intent == cancel AND current_mode not in {BOOKING,CONFIRMATION_REPLY}` | → APPOINTMENT_MANAGEMENT |
| 9 | `intent == greet AND is_first_interaction` | → GREETING |
| 9.5 | `intent in {ask_info,ambiguous} AND _is_explicit_handoff(message)` | → ESCALATION (explicit override) |
| 10 | Default | → GENERAL |

---

## 4. State Management

### `ConversationState` Key Fields

```python
class ConversationState(TypedDict, total=False):
    # Core
    conversation_id: str
    customer_phone: str
    messages: Annotated[list[dict[str, Any]], operator_add]   # FIFO, max 10 in window
    user_message: str | None                                   # cleared by preprocess

    # Mode routing
    current_mode: str                                          # GREETING/BOOKING/GENERAL/ESCALATION/...
    previous_mode: str | None
    mode_context: Annotated[dict[str, Any], merge_dicts]      # routing metadata ONLY
    mode_history: Annotated[list[str], append_unique_list]
    draft_contexts: Annotated[dict[str, Any], merge_dicts]    # saved contexts for resumption

    # Durable booking state (replace-reducer — no zombie keys)
    booking_context: Annotated[BookingContext | None, replace_booking_context]

    # Tracking
    is_first_interaction: bool
    ai_disclosure_sent: bool
    escalation_triggered: bool
    error_count: int
    pending_confirmation_appointment_id: str | None
```

### `BookingContext` — Typed Booking State

```python
class BookingContext(TypedDict, total=False):
    booking_step: str                         # service_selection|stylist_selection|datetime_selection|name_collection|notes_collection|confirmation
    last_services: list[str]                  # e.g. ["CORTE LARGO"]
    last_total_duration_minutes: int | None
    last_stylist: str | None                  # e.g. "Pilar" or "Sin preferencia"
    no_preference_stylist: bool
    offered_slots: list[dict[str, Any]]       # from check_availability
    selected_slot: dict[str, Any] | None
    customer_name: str | None
    customer_id: str | None
    confirmation_summary_sent: bool
    confirmation_shown: bool
    _booking_completed: bool
    preferred_stylist_name: str | None        # upfront hint from router
    preferred_date_hint: str | None
    pending_service_options: list[str] | None
    pending_stylist_options: list[str] | None
    notes: str | None
    notes_state: Literal["not_asked", "skipped", "provided"]
```

### Reducers

| Field | Reducer | Behaviour |
|-------|---------|-----------|
| `messages` | `operator_add` | Appends new messages list, FIFO windowing in summarize |
| `mode_context` | `merge_dicts` | Shallow merge; `{"__reset__": True, ...}` clears all stale keys |
| `draft_contexts` | `merge_dicts` | Shallow merge of draft dict |
| `mode_history` | `append_unique_list` | Appends, skips consecutive duplicates |
| `booking_context` | `replace_booking_context` | **Full replace** — update replaces entire dict; falsy update → keep current |

### `transition_mode()` — The ONLY correct way to change modes

```python
from agent.state.schemas import transition_mode

# Returns partial state dict with:
# - current_mode = new_mode
# - mode_context = {"__reset__": True, ...context_update}  ← clears stale data
# - mode_history = [..., old_mode]
# - draft_contexts = {old_mode: old_mode_context, ...}
updates = transition_mode(state, "BOOKING", context_update={"intent": "book"})
```

**NEVER** write `{"current_mode": "BOOKING"}` directly — stale `mode_context` leaks across modes.

### `add_message()` — The ONLY correct way to add messages

```python
from agent.state.helpers import add_message

# Returns partial state update — pass directly into return dict
return {
    **add_message(state, "assistant", response_text),
    "booking_context": new_booking_context,
    "last_node": "booking",
    "user_message": None,
}
```

### `get_last_user_message()` — Canonical current-turn reader

```python
from agent.state.helpers import get_last_user_message

user_message = get_last_user_message(state)  # reads reversed(messages) for last role=user
```

**`state["user_message"]` is cleared by `preprocess`. NEVER read it in mode nodes.**

---

## 5. Mode Patterns

### Mode Summary Table

| Mode | Type | Tools | Prompt overlay | Entry condition |
|------|------|-------|----------------|-----------------|
| GREETING | LLM-driven | none | `greeting.md` | `intent=greet` AND `is_first_interaction=True` |
| BOOKING | LLM-driven | `check_availability`, `book`, `escalate_to_human` | `booking.md` | `intent=book` or BOOKING inertia |
| GENERAL | LLM-driven | `manage_appointments` (read), `escalate_to_human` | `general.md` | Default fallback |
| ESCALATION | Deterministic FSM | `escalate_to_human` | `escalation.md` (reference only) | `intent=escalate` or `error_count>=3` |
| APPOINTMENT_MANAGEMENT | LLM-driven | `manage_appointments` | `appointment_management.md` | `intent=reschedule` or `intent=check_appointments` |
| CONFIRMATION_REPLY | Deterministic | none | none | `pending_confirmation_appointment_id` + confirm/reject intent |

---

### GREETING Mode

**Purpose**: First-contact welcome + menu. Pure response, no side effects.

**Key behaviours**:
- Renders a static welcome message (new vs returning customer variant)
- Prepends the mandatory EU AI Act disclosure via `agent.modes._intro.maybe_prepend_intro()` on first turn
- Detects booking-content tokens in the greeting message to set `service_audience_hint`
- Transitions to BOOKING if `last_intent == "book"`, else GENERAL
- **NO name collection** — does not ask for the customer's name
- **NO DB writes** — no customer creation

```python
# After greeting, always transitions out
target_mode = "BOOKING" if last_intent == "book" else "GENERAL"
return {
    **add_message(state, "assistant", welcome_text),
    **transition_mode(state, target_mode, context_update={...}),
    "ai_disclosure_sent": True,
    "last_node": "greeting",
    "user_message": None,
}
```

---

### BOOKING Mode (`BookingModeNode`)

**Purpose**: Multi-step appointment booking — fully LLM-driven except for data-integrity gates.

**Python's responsibilities** (everything else is LLM):
- `_compute_step(ctx)` — idempotent, re-evaluates booking step from `booking_context` fields
- `_resolve_pending_selection()` — maps digit/ordinal/time/affirmative to slot/service/stylist
- `_pre_tool_call()` — confirmation gate + slot_index→UUID injection + stylist guard
- `_post_tool_result()` — extracts tool output into `booking_context` mid-loop
- `_refresh_dynamic_context()` — rebuilds dynamic SystemMessage after each tool round
- `_build_response()` — code-renders F-8 booking confirmation block

**Booking steps** (computed by `_compute_step`):

```
service_selection → stylist_selection → datetime_selection → name_collection → notes_collection → confirmation
```

**State contract**:
- `booking_context` — all booking-specific data (full replace via `replace_booking_context`)
- `mode_context` — routing metadata ONLY (`last_intent`, `last_intent_confidence`, `awaiting_human`)

**Slot acceptance** (deterministic, before LLM sees the turn):
- Bare digit `"2"` → `offered_slots[1]`
- Time expression `"a las 11"`, `"11:00"`, `"a las 9 y media"` → matched slot
- Ordinal `"la primera"`, `"el último"` → matched slot
- Spanish affirmative `"sí"`, `"dale"` → first slot (only when exactly 1 offered)

**`_pre_tool_call` gates**:

| Tool | Gate | Rejection code |
|------|------|---------------|
| `check_availability` | stylist must be resolved | `STYLIST_NOT_RESOLVED` |
| `book` | slot_index→UUID resolution | `INVALID_SLOT_INDEX` |
| `book` | confirmation gate (all data + confirmation_shown) | `CONFIRMATION_NOT_SHOWN` |

**`_post_tool_result` extractions**:

| Tool | Extracted into `booking_context` |
|------|----------------------------------|
| `check_availability` | `offered_slots`, `last_services`, `last_total_duration_minutes`, `last_stylist` |
| `book` | `_booking_completed = True` |

**After completed booking**: transitions to GENERAL via `transition_mode(state, "GENERAL")` — `booking_context` persists independently via its own field.

---

### GENERAL Mode

**Purpose**: FAQ, service info, business hours. Catalog injected in prompt. Can hand off to BOOKING.

**Key behaviours**:
- Reads catalog from prompt (not from tools)
- Can detect booking intent and set `general_booking_handoff` in `mode_context`
- If `general_booking_handoff` is set, router Rule 7.9 transitions to BOOKING on next confirmation
- Calls `_maybe_escalate()` after `handle()` in the graph node wrapper

---

### ESCALATION Mode

**Purpose**: Human handoff. **Deterministic FSM — does NOT use the LLM**.

**FSM steps** (stored in `mode_context["escalation_step"]`):

```
→ ACKNOWLEDGE → DESCRIBE → CONTACT → DONE
```

| Step | Bot action | Collects |
|------|-----------|----------|
| ACKNOWLEDGE | Empathy message + asks for issue description | — |
| DESCRIBE | Stores `issue_summary`, asks for contact preference | `issue_summary` |
| CONTACT | Normalises preference, calls `escalate_to_human`, confirms | `contact_preference` |
| DONE | Returns waiting message for all subsequent turns | — |

**Fast-paths** (skip intake FSM):
- **Explicit human request** (`"pasame con una persona"`, `"quiero hablar con un humano"`) → escalate immediately
- **Technical auto-escalation** (`error_count >= 3`) → escalate immediately with `reason="technical_error"`
- **Already escalated** (`escalation_step == DONE`) → return `_ALREADY_ESCALATED` response

Note: `escalation.md` overlay is loaded by the prompt system but **not used** — the mode is 100% deterministic Python code.

---

### APPOINTMENT_MANAGEMENT Mode

**Purpose**: List, cancel, and reschedule appointments. LLM-driven with pre-resolvers and safety gates.

**Key behaviours**:
- Pre-resolvers: detect action (list/cancel/reschedule), resolve `selected_appointment_id` from user digit input, detect confirmation
- `_pre_tool_call` safety gates: block cancel/reschedule without `pending_confirmation`
- 48-hour policy enforced in tool (cannot cancel within 48h of appointment)
- Natural language selection: user can say "la primera", "la de Pilar", "el martes"

---

### CONFIRMATION_REPLY Node

**Purpose**: Handle WhatsApp appointment confirmation template responses (confirm/reject/cancel).

**Behaviour**: Deterministic — reads `pending_confirmation_appointment_id` from state, calls `handle_confirmation_response()` service, sends appropriate reply.

---

## 6. BaseModeNode Pattern

All modes extend `BaseModeNode` and implement `handle(state, intent) → dict`:

```python
from agent.modes.base import BaseModeNode, AgenticLoopResult
from agent.state.schemas import ConversationState

class MyMode(BaseModeNode):
    @property
    def mode_name(self) -> str:
        return "MY_MODE"

    async def handle(self, state: ConversationState, intent: Any) -> dict:
        mode_context = state.get("mode_context") or {}

        # 1. Build layered messages
        messages = await self._build_layered_messages(
            state, mode_context, include_history=True, history_limit=6
        )

        # 2. Run agentic loop (up to MAX_TOOL_ROUNDS=6 iterations)
        result = await self._run_agentic_loop(messages, tools=self.tools)

        # 3. Handle first-turn disclosure (moved off BaseModeNode into agent/modes/_intro.py)
        from agent.modes._intro import maybe_prepend_intro
        response_text, disclosure_sent = maybe_prepend_intro(result.response_text, state)

        # 4. Return partial state update
        updates = {
            **add_message(state, "assistant", response_text),
            "mode_context": {"last_intent": mode_context.get("last_intent")},
            "last_node": "my_mode",
            "user_message": None,
        }
        if disclosure_sent:
            updates["ai_disclosure_sent"] = True
        return updates
```

### BaseModeNode hooks

| Hook | Called when | Override for |
|------|------------|--------------|
| `_pre_tool_call(tool_name, tool_args)` | Before each tool execution | Argument injection, gates (return `ToolCallRejection` to block) |
| `_post_tool_result(tool_name, tool_args, result)` | After each tool execution | Extract tool output into mode/booking context mid-loop |
| `_refresh_dynamic_context(working_messages)` | After each tool round | Rebuild the dynamic context SystemMessage with fresh state |

### Testing instantiation

```python
# CORRECT: pass tools=[] for unit tests
mode = BookingModeNode(tools=[])
mode = EscalationMode(tools=[], llm_client=None)
```

---

## 7. Tool Patterns

### Available Tools

| Tool | Module | Mode(s) | Purpose |
|------|--------|---------|---------|
| `check_availability` | `availability_tools.py` | BOOKING | Query available slots for date/stylist/service |
| `book` | `booking_tools.py` | BOOKING | Create appointment (atomic DB + GCal push) |
| `manage_appointments` | `manage_appointments_tool.py` | GENERAL, APPOINTMENT_MANAGEMENT | List/cancel/reschedule appointments |
| `escalate_to_human` | `escalation_tools.py` | BOOKING, GENERAL, ESCALATION | Trigger human handoff in Chatwoot |
| `manage_customer` | `customer_tools.py` | (internal) | Create/update customer records |

### FuzzyResolver (tool-level name matching)

```python
from agent.utils.fuzzy_resolver import resolve_from_options, resolve_ordinal

# Resolve ordinal: "la segunda" → index 1
idx = resolve_ordinal(user_message, len(options))
if idx is not None:
    return options[idx]

# Resolve text: exact → normalized/contains → prefix → fuzzy (≥0.75 threshold)
match = resolve_from_options(user_message, options)
return match.value if match else None
```

### Tool Definition Pattern

```python
from langchain.tools import StructuredTool
from pydantic import BaseModel, Field

class CheckAvailabilityInput(BaseModel):
    service_names: list[str] = Field(description="List of service names from the catalog")
    stylist_name: str | None = Field(None, description="Stylist name or None for any")
    date_hint: str | None = Field(None, description="Spanish date expression, e.g. 'el viernes'")

check_availability = StructuredTool.from_function(
    name="check_availability",
    description="Check available appointment slots for given services and optional stylist",
    args_schema=CheckAvailabilityInput,
    coroutine=_check_availability_impl,
)
```

---

## 8. Prompt System

### Layered Assembly (per turn)

```
1. SystemMessage: identity.md + critical_rules.md    ← cached 10 min
2. SystemMessage: catalog (service/stylist data)      ← cached 5 min (catalog_builder.py)
3. SystemMessage: mode overlay (booking.md, etc.)     ← cached 10 min per mode
4. HumanMessage + AIMessage pairs: conversation history (last 6-8 messages)
5. SystemMessage: dynamic context (current step, collected/missing data, offered slots)  ← built fresh every turn
```

### Calling `build_layered_messages`

```python
from agent.prompts.loader import build_layered_messages

messages, dynamic_context_index = await build_layered_messages(
    state=state,
    mode_context=mode_context,          # or booking_context for BOOKING
    mode_name="BOOKING",
    dynamic_context_override=my_xml,    # optional — BOOKING builds its own
    include_history=True,
    history_limit=8,
)
```

### Dynamic context (BOOKING example)

```xml
Fecha y hora actual: martes 07 de abril de 2026, 14:30 (Europa/Madrid)
Teléfono del cliente: +34612345678
<booking_context>
  <min_valid_date>jueves 09 de abril (2026-04-09)</min_valid_date>
  <current_step>stylist_selection</current_step>
  <next_action>Preguntar preferencia de estilista</next_action>
  <collected_data>
    ✅ Servicio: CORTE LARGO (45min)
  </collected_data>
  <missing_data>
    ❌ Estilista: pendiente
    ❌ Fecha/hora: pendiente
    ❌ Nombre: pendiente
  </missing_data>
</booking_context>
```

### Prompt files

| File | Cached | Purpose |
|------|--------|---------|
| `shared/identity.md` | Yes (10 min, base cache) | Bot persona, EU AI Act disclosure text, name |
| `shared/critical_rules.md` | Yes (10 min, base cache) | Hard constraints (booking rules, tone, language) |
| `modes/greeting.md` | Yes (10 min, per-mode cache) | GREETING overlay |
| `modes/booking.md` | Yes (10 min, per-mode cache) | BOOKING flow instructions |
| `modes/general.md` | Yes (10 min, per-mode cache) | GENERAL FAQ instructions |
| `modes/escalation.md` | Yes (10 min, per-mode cache) | Reference only (mode is deterministic) |
| `modes/appointment_management.md` | Yes (10 min, per-mode cache) | APPT_MGMT overlay |

---

## 9. Intent Router

### `IntentResult` dataclass

```python
@dataclass
class IntentResult:
    intent: str        # greet|book|ask_info|confirm|reject|cancel|escalate|retry|reschedule|check_appointments|ambiguous
    confidence: float  # 0.0-1.0 (1.0 = keyword hit, <0.8 = LLM inferred)
    raw_input: str
    mode_hint: str | None
```

### Classification flow

1. **Keyword fast-path**: Check message against `KEYWORD_MAP` (10 intents). Threshold: `0.80`. If hit → return immediately, skip LLM.
2. **LLM fallback**: Send message + current_mode to GPT-5.4-mini for classification. Returns structured JSON.
3. **Bare-digit shortcut**: If `booking_step == "slot_selection"` and message is a bare digit → classify as `"confirm"` without LLM.

---

## 10. Anti-Patterns

### ❌ NEVER read `user_message` in mode nodes

```python
# WRONG — cleared by preprocess before modes run
user_msg = state.get("user_message")

# CORRECT
from agent.state.helpers import get_last_user_message
user_msg = get_last_user_message(state)
```

### ❌ NEVER use `{**state}` spread in node returns

```python
# WRONG — operator.add fields (messages) get doubled
return {**state, "last_node": "booking"}

# CORRECT — return only what changed
return {"last_node": "booking"}
```

### ❌ NEVER store booking data in `mode_context`

```python
# WRONG — mode_context uses merge_dicts (cannot delete keys = zombie data)
return {"mode_context": {"last_services": ["CORTE"], "booking_step": "stylist_selection"}}

# CORRECT — booking data goes into booking_context (replace reducer = clean state)
return {"booking_context": updated_booking_ctx, "mode_context": routing_only_ctx}
```

### ❌ NEVER bypass `transition_mode()` for mode changes

```python
# WRONG — stale mode_context leaks into new mode
return {"current_mode": "GENERAL"}

# CORRECT
return {**transition_mode(state, "GENERAL"), "last_node": "booking"}
```

### ❌ NEVER mutate state directly

```python
# WRONG
state["messages"].append(new_msg)
state["booking_context"]["last_stylist"] = "Pilar"

# CORRECT — return partial update
return add_message(state, "assistant", text)
```

### ❌ NEVER duplicate `get_last_user_message()` logic locally

```python
# WRONG — local re-implementation
for msg in reversed(state.get("messages", [])):
    if msg["role"] == "user":
        return msg["content"]

# CORRECT
from agent.state.helpers import get_last_user_message
return get_last_user_message(state)
```

---

## 11. Testing Patterns

### Mode instantiation

```python
# CORRECT: tools=[] for unit tests (no actual tool calls)
mode = BookingModeNode(tools=[])
mode = EscalationMode(tools=[], llm_client=None)
```

### State factory helper

```python
def _make_state(messages: list[dict], booking_ctx: dict | None = None, mode_ctx: dict | None = None) -> dict:
    return {
        "conversation_id": "test-001",
        "customer_phone": "+34612345678",
        "messages": messages,
        "user_message": None,           # ALWAYS None — preprocess has already run
        "current_mode": "BOOKING",
        "mode_context": mode_ctx or {},
        "booking_context": booking_ctx or {},
        "mode_history": [],
        "draft_contexts": {},
        "is_first_interaction": False,
        "ai_disclosure_sent": True,
        "escalation_triggered": False,
        "error_count": 0,
    }
```

### Test pattern: booking context separate from mode context

```python
state = _make_state(
    messages=[{"role": "user", "content": "Quiero reservar un corte", "timestamp": "..."}],
    booking_ctx={"last_services": ["CORTE LARGO"], "booking_step": "stylist_selection"},
    mode_ctx={"last_intent": "book", "last_intent_confidence": 0.9},
)
```

### Static analysis: zero `user_message` reads in mode files

```python
def test_no_user_message_reads_in_modes():
    """Modes must never read state['user_message'] — it's cleared by preprocess."""
    import ast, glob
    for path in glob.glob("agent/modes/*.py"):
        tree = ast.parse(open(path).read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript):
                if (isinstance(node.value, ast.Name) and node.value.id == "state"
                        and isinstance(node.slice, ast.Constant) and node.slice.value == "user_message"):
                    assert False, f"{path}: direct state['user_message'] read — use get_last_user_message()"
```

---

## 12. Environment Variables

```python
from shared.config import get_settings

settings = get_settings()
settings.LLM_MODEL                # "openai/gpt-5.4-mini"
settings.OPENROUTER_API_KEY       # OpenRouter API key
settings.USE_OPTIMIZED_PROMPTS    # True (layered prompt system)
settings.RESILIENCE_ENABLED       # True
```

---

## 13. LLM Client

```python
from langchain_openai import ChatOpenAI
from shared.config import get_settings

settings = get_settings()
llm = ChatOpenAI(
    model=settings.LLM_MODEL,
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.OPENROUTER_API_KEY,
    temperature=0.3,
    request_timeout=30.0,
    max_retries=2,
)
```

Tests mock via `patch("agent.graphs.conversation_flow._get_llm_client")`.

---

**Version**: 2.0 (Mode-based v6.0 — 6 modes, BookingContext, replace-reducer)
**Last Updated**: April 2026
