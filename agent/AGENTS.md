# Agent Component Guidelines

This directory contains the Atrévete Bot conversational agent built with LangGraph v6.0 mode-based architecture.

> **Architecture**: Mode-based conversation flow with 4 independent modes (GREETING, BOOKING, GENERAL, ESCALATION) and keyword + LLM hybrid intent routing.

---

## Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|
| Creating/modifying mode nodes | `atrevete-agent` |
| Creating agent tools | `atrevete-agent` |
| Working on LangGraph graphs/nodes | `atrevete-agent` |
| Working on conversation flow | `atrevete-agent` |
| Working on prompts | `atrevete-agent` |
| Working with ConversationState | `atrevete-agent` |
| Writing Python tests | `pytest` |

---

## Directory Structure

```
agent/
├── main.py                      # Redis Streams consumer entry point
├── graphs/
│   └── conversation_flow.py     # v6.0 StateGraph factory (preprocess → router → modes → summarize)
├── modes/
│   ├── base.py                  # BaseModeNode (shared patterns for all modes)
│   ├── greeting_mode.py         # GREETING mode (first contact + name collection)
│   ├── booking_mode.py          # BOOKING mode (multi-step appointment flow)
│   ├── general_mode.py          # GENERAL mode (FAQs, info queries)
│   └── escalation_mode.py       # ESCALATION mode (human handoff)
├── routing/
│   └── intent_router.py         # Keyword + LLM hybrid intent classifier
├── state/
│   ├── schemas.py               # ConversationState TypedDict + reducers
│   └── helpers.py               # add_message(), should_summarize(), etc.
├── tools/                       # 4 LangChain tools
│   ├── availability_tools.py    # check_availability
│   ├── booking_tools.py         # book (atomic transaction)
│   ├── manage_appointments_tool.py  # manage_appointments (view/cancel/reschedule)
│   └── escalation_tools.py     # escalate
├── prompts/
│   ├── loader.py                # Dynamic prompt assembly
│   ├── catalog_builder.py       # Builds service catalog string injected into prompt
│   ├── shared/                  # Core prompts (identity, rules, glossary)
│   └── modes/                   # Mode-specific prompt overlays
├── services/                    # Business logic
│   ├── availability_service.py
│   ├── gcal_push_service.py
│   └── escalation_service.py
└── workers/                     # Background workers
    ├── conversation_archiver.py
    └── confirmation_worker.py
```

---

## Architecture Overview

### State Diagram

```
┌──────────────┐
│    START     │ (user message arrives via Redis Streams)
└──────┬───────┘
       │
┌──────▼───────┐
│  preprocess  │ (add message, check customer, detect first interaction)
└──────┬───────┘
       │
┌──────▼───────┐
│    router    │ (intent classification + mode selection)
└──────┬───────┘
       │ (conditional edge based on current_mode)
       │
   ┌───┴───────────┬───────────────┬───────────────┐
   │               │               │               │
   ▼               ▼               ▼               ▼
┌────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│GREETING│   │ BOOKING  │   │ GENERAL  │   │ESCALATION│
└────┬───┘   └────┬─────┘   └────┬─────┘   └────┬─────┘
     │            │              │              │
     └────────────┴──────────────┴──────────────┘
                  │
         ┌────────▼────────┐
         │    summarize    │ (conversation summarization)
         └────────┬────────┘
                  │
         ┌────────▼────────┐
         │       END       │
         └─────────────────┘
```

### Mode-Based Architecture

**Modes** are self-contained conversation contexts with:
- **Dedicated prompt** (core + mode-specific instructions)
- **Filtered tools** (only relevant tools per mode)
- **LLM-driven flow** (system prompt guides the LLM, not hardcoded Python logic)
- **Automatic transitions** (via `transition_mode()` helper)

| Mode | Purpose | Tools | Entry Condition |
|------|---------|-------|-----------------|
| **GREETING** | First contact + name collection | `manage_customer` (customer_tools) | `is_first_interaction=True` or `customer_name=None` |
| **BOOKING** | Multi-step appointment booking | `check_availability`, `book`, `manage_appointments` | `intent=book` or already in BOOKING |
| **GENERAL** | FAQs, business hours, services (catalog in prompt) | `manage_appointments` (read), `escalate` | Default mode |
| **ESCALATION** | Human handoff | `escalate` | `intent=escalate` or `error_count>=3` |

---

## Mode Node Pattern

All modes extend `BaseModeNode` and implement `handle(state, intent)`:

```python
class MyModeNode(BaseModeNode):
    @property
    def mode_name(self) -> str:
        return "MY_MODE"

    async def handle(self, state: ConversationState, intent: object) -> dict:
        # 1. Build system prompt
        messages = self._build_messages(state, system_prompt)

        # 2. Get LLM with mode-specific tools
        tools = self.get_tools()
        llm = self._get_llm(tools)

        # 3. Tool calling loop (or direct response)
        result = await self._run_agentic_loop(messages, tools)

        # 4. Return state updates (MUST include user_message=None)
        return {
            **add_message(state, "assistant", result.response_text),
            "mode_context": updated_context,
            "last_node": "my_mode",
            "user_message": None,  # CRITICAL: clear after processing
        }

    def get_tools(self):
        return [tool1, tool2]
```

---

## Tool-Driven State Management

**Pattern**: Tools explicitly declare state changes via return values:

```python
# In a tool
return {
    "success": True,
    "appointment_id": str(appointment.id),
    "_internal_flags": {
        "appointment_created": True,
    }
}

# In mode node
if tool_result.get("_internal_flags", {}).get("appointment_created"):
    updates["appointment_created"] = True
```

**Why**: Eliminates fragile pattern matching on LLM responses. State changes are explicit and testable.

---

## Critical Rules

### 1. ALWAYS use `add_message()` helper
```python
# ❌ WRONG - mutates state directly
state["messages"].append({"role": "assistant", "content": text})

# ✅ CORRECT - returns partial update
return add_message(state, "assistant", text)
```

### 2. NEVER use `{**state}` spread in node returns
```python
# ❌ WRONG - causes message duplication
return {**state, "current_mode": "BOOKING"}

# ✅ CORRECT - return only changes
return {"current_mode": "BOOKING"}
```

### 3. ALWAYS use `Annotated[T, reducer_fn]` for custom reducers
```python
# In state/schemas.py
mode_context: Annotated[dict[str, Any], merge_dicts]
mode_history: Annotated[list[str], append_unique_list]
```

### 4. ALWAYS use `transition_mode()` for mode transitions
```python
# Clears mode_context via __reset__ sentinel
return {
    **transition_mode(state, "BOOKING"),
    **add_message(state, "assistant", response),
}
```

### 5. ALWAYS clear `user_message` at end of pipeline
```python
# In every mode node return:
return {
    # ... other updates
    "user_message": None,  # Cleared by summarize_node (FIX-001)
}
```

### 6. ALWAYS use async/await for I/O operations
```python
# ❌ WRONG
result = some_io_operation()  # blocking!

# ✅ CORRECT
result = await some_io_operation()
```

---

## State Mutation Guardrails

### The `merge_dicts` Reducer

```python
def merge_dicts(current: dict | None, update: dict | None) -> dict:
    """
    If update contains {"__reset__": True, ...rest}, returns ONLY rest.
    Otherwise performs standard shallow merge.
    """
    current = current or {}
    update = update or {}
    if update.get("__reset__"):
        return {k: v for k, v in update.items() if k != "__reset__"}
    return {**current, **update}
```

**Usage in `transition_mode()`**:
```python
new_mode_context = {"__reset__": True, "booking_step": "service_selection"}
# Results in: {"booking_step": "service_selection"} (stale data cleared)
```

### The `add_message()` Helper

```python
def add_message(state, role, content):
    """
    Returns partial state update with new message.
    Uses `operator.add` reducer to accumulate messages.
    """
    return {
        "messages": [{"role": role, "content": content, "timestamp": ...}],
        "total_message_count": state.get("total_message_count", 0) + 1,
    }
```

---

## Anti-patterns

### NEVER Mutate State Directly
```python
# ❌ WRONG
state["current_mode"] = "BOOKING"
state["messages"].append(new_message)

# ✅ CORRECT
return {
    "current_mode": "BOOKING",
    **add_message(state, "assistant", text),
}
```

### NEVER Return Full State Copy
```python
# ❌ WRONG - causes message duplication
updated = dict(state)
updated["current_mode"] = "BOOKING"
return updated

# ✅ CORRECT - return only what changed
return {"current_mode": "BOOKING"}
```

### NEVER Forget to Parse Tool Results
```python
# ❌ WRONG - assumes dict, could be JSON string
result = await tool.ainvoke(...)
_apply_tool_flags(mode_context, result, logger)  # BUG if result is string!

# ✅ CORRECT - parse explicitly
result = await tool.ainvoke(...)
result_dict = json.loads(result) if isinstance(result, str) else result
_apply_tool_flags(mode_context, result_dict, logger)
```

### NEVER Block Mode Transition with Stale Data
```python
# ❌ WRONG - old booking data leaks into new mode
return {"current_mode": "GENERAL"}  # mode_context still has old booking_step!

# ✅ CORRECT - use transition_mode to clear context
return transition_mode(state, "GENERAL")
```

---

## Intent Router

### Keyword + LLM Hybrid Classification

```python
# 1. Fast keyword matching (9 intents)
KEYWORD_PATTERNS = {
    "book": ["reservar", "cita", "turno", "quiero ir"],
    "cancel": ["cancelar", "anular", "no puedo"],
    "escalate": ["humano", "persona", "ayuda"],
    # ... more
}

# 2. LLM fallback for ambiguous cases
intent = await intent_router.classify(text=user_message, current_mode=current_mode)
```

**Confidence threshold**: 0.75 (below → clarification)

---

## Testing

```bash
# Run agent tests
DATABASE_URL="postgresql+asyncpg://..." pytest tests/unit/test_agent/

# Run specific mode test
DATABASE_URL="postgresql+asyncpg://..." pytest tests/unit/test_agent/test_greeting_mode.py -v
```

---

## Resources

- [Root AGENTS.md](../AGENTS.md) — Repository governance
- [atrevete-agent skill](../skills/atrevete-agent/SKILL.md) — Detailed patterns
- `agent/graphs/conversation_flow.py` — Graph definition
- `agent/state/schemas.py` — State schema and reducers

**Last Updated**: March 2026

### Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|
| Creating agent tools | `atrevete-agent` |
| Creating new prompt module | `atrevete-prompts` |
| Creating/modifying mode nodes | `atrevete-agent` |
| Editing agent system prompts | `atrevete-prompts` |
| Editing identity.md or critical_rules.md | `atrevete-prompts` |
| Modifying core prompt rules | `atrevete-prompts` |
| Modifying files in agent/prompts/ | `atrevete-prompts` |
| Modifying mode prompt instructions | `atrevete-prompts` |
| Reviewing prompt quality | `atrevete-prompts` |
| Working on LangGraph | `atrevete-agent` |
| Working on agent/ | `atrevete-agent` |
| Working on prompt .md files | `atrevete-prompts` |
| Working on prompts | `atrevete-agent` |
| Working on routing | `atrevete-agent` |
| Working on state management | `atrevete-agent` |
| Working on system prompts | `atrevete-prompts` |
