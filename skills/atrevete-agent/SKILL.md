---
name: atrevete-agent
description: >
  Atrévete Bot agent patterns using LangGraph v6.0 mode-based architecture.
  Trigger: When working on agent/, mode nodes, routing, prompts, state, or tools.
license: MIT
metadata:
  author: atrevete-bot
  version: "1.0"
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

## Agent Architecture (v6.0 Mode-Based)

```
agent/
├── main.py                    # Entry point: Redis Streams consumer
├── graphs/
│   └── conversation_flow.py   # StateGraph: 7 nodes, mode-based routing
├── modes/
│   ├── base.py                # BaseModeNode abstract class
│   ├── greeting_mode.py       # GREETING: name collection, customer creation
│   ├── booking_mode.py        # BOOKING: multi-step booking flow
│   ├── general_mode.py        # GENERAL: FAQ/info queries
│   └── escalation_mode.py     # ESCALATION: human handoff
├── routing/
│   └── intent_router.py       # Intent classifier (8 intents)
├── prompts/
│   ├── loader.py              # Cached system prompt + dynamic context
│   ├── catalog_builder.py     # Builds service catalog string injected into prompt
│   ├── shared/                # Core prompts (identity, rules, glossary)
│   └── modes/                 # Mode-specific overlays
├── state/
│   ├── schemas.py             # ConversationState TypedDict
│   ├── checkpointer.py        # Redis checkpointer
│   └── helpers.py             # add_message() helper
├── tools/                     # 4 LangChain tools
│   ├── availability_tools.py  # check_availability
│   ├── booking_tools.py       # book (atomic transaction)
│   ├── manage_appointments_tool.py  # manage_appointments (view/cancel/reschedule)
│   └── escalation_tools.py    # escalate
├── services/                  # Business logic
│   ├── availability_service.py    # DB-first availability
│   ├── gcal_push_service.py       # Fire-and-forget GCal push
│   └── stylist_cache.py           # In-memory stylist caching
└── workers/
    └── conversation_archiver.py   # Archive to PostgreSQL
```

## Mode-Based Flow

```
START → preprocess_node → router_node → mode_dispatcher
    → [greeting_node | general_node | booking_node | escalation_node]
    → summarize_node → END
```

**4 Modes:**
- **GREETING**: First contact, name extraction (fires ONCE per new customer)
- **BOOKING**: Multi-step appointment booking — `check_availability`, `book`, `manage_appointments`
- **GENERAL**: FAQs, service info (catalog in prompt; read-only `manage_appointments` + `escalate`)
- **ESCALATION**: Human handoff via `escalate`

## Routing Logic

```python
# Router priority (intent_router.py)
1. escalation_triggered=True → ESCALATION
2. error_count >= 3 → ESCALATION (auto)
3. is_first_interaction=True OR customer_name is None → GREETING
4. intent == escalate → ESCALATION
5. Currently in BOOKING and not cancel/reject → stay BOOKING
6. intent == book → BOOKING
7. intent == greet and not in BOOKING → GREETING
8. Everything else → GENERAL
```

## State Schema (CRITICAL RULES)

```python
from typing import Annotated
import operator

# CORRECT: Annotated wiring — reducer IS called
mode_history: Annotated[list[str], operator.add]
mode_context: Annotated[dict, merge_dicts]

# WRONG: Bare type — reducer NEVER called
mode_history: list[str]  # DON'T DO THIS
mode_context: dict        # DON'T DO THIS
```

### State Update Patterns

**CORRECT: Partial dict return — only what changes**
```python
async def summarize_node(state: ConversationState) -> dict:
    return {"conversation_summary": new_summary, "user_message": None}
```

**WRONG: Full state spread — causes message doubling**
```python
async def summarize_node(state: ConversationState) -> dict:
    return {**state, "conversation_summary": new_summary}  # DON'T
```

### Mode Context with Reset

```python
from agent.state.schemas import transition_mode

# Transition to new mode with reset
updates = transition_mode(state, "BOOKING", context_update={"intent": "book"})
# mode_context will have {"__reset__": True, "intent": "book"}
```

## Mode Node Pattern

```python
from agent.modes.base import BaseModeNode, AgenticLoopResult
from agent.state.schemas import ConversationState

class BookingMode(BaseModeNode):
    @property
    def mode_name(self) -> str:
        return "BOOKING"
    
    async def handle(self, state: ConversationState, intent: Any) -> dict:
        # 1. Build messages
        messages = await self._build_layered_messages(
            state, mode_context, step_name="booking"
        )
        
        # 2. Run agentic loop with tools
        result = await self._run_agentic_loop(messages, tools=self.tools)
        
        # 3. Return partial state update
        return {
            "messages": [{"role": "assistant", "content": result.response_text, "timestamp": now()}],
            "mode_context": {"booking_step": next_step},
            "last_node": "booking_node",
        }
```

## Tool Definition

```python
from langchain.tools import StructuredTool
from pydantic import BaseModel, Field

class CheckAvailabilityInput(BaseModel):
    date: str = Field(description="Date to check (YYYY-MM-DD)")
    stylist_id: str | None = Field(None, description="Specific stylist or any")
    service_duration: int = Field(60, description="Service duration in minutes")

async def check_availability(date: str, stylist_id: str | None, service_duration: int):
    """Check availability for a specific date."""
    # Implementation
    return {"available_slots": [...]}

check_availability_tool = StructuredTool.from_function(
    name="check_availability",
    description="Check stylist availability for a date",
    args_schema=CheckAvailabilityInput,
    coroutine=check_availability,
)
```

## Message Format

**CRITICAL: Always use add_message() helper**

```python
from agent.state.helpers import add_message

# CORRECT: Returns properly formatted message
return add_message(state, "assistant", "Response text")
# Returns: {"messages": [{"role": "assistant", "content": "...", "timestamp": "..."}]}

# Message format (role is "user" or "assistant", NEVER "human" or "ai")
{
    "role": "user" | "assistant",
    "content": str,
    "timestamp": str  # ISO 8601 Europe/Madrid
}
```

## Prompt System (v6.1)

```python
from agent.prompts.loader import get_system_prompt, build_layered_messages

# 1. Load cached system prompt (~2,200 tokens)
system_prompt = await get_system_prompt()
# Loads: shared/identity.md + shared/critical_rules.md + shared/glossary.md

# 2. Build dynamic context (~300 tokens)
context = build_step_context(state, mode_context, step_info)

# 3. Layered messages (optimized for caching)
messages = await build_layered_messages(state, mode_context, step_info)
# Returns: [SystemMessage, HumanMessage(context), ...history]
```

## Redis Checkpointer

```python
from agent.state.checkpointer import get_redis_checkpointer, initialize_redis_indexes

checkpointer = get_redis_checkpointer()
await initialize_redis_indexes(checkpointer)

# Requires Redis Stack (RedisSearch + RedisJSON modules)
```

## Critical Anti-Patterns

### ❌ NEVER Mutate State Directly
```python
# WRONG
state["messages"].append({"role": "assistant", "content": "Hi"})
return state
```

### ✅ Return New Dict
```python
# CORRECT
return {
    "messages": state["messages"] + [{"role": "assistant", "content": "Hi"}],
}
```

### ❌ NEVER Use {**state} Spread
```python
# WRONG — causes operator.add fields to double
return {**state, "last_node": "booking_node"}
```

### ✅ Return Partial Dict Only
```python
# CORRECT
return {"last_node": "booking_node"}
```

### ❌ NEVER Clear user_message Early
```python
# WRONG — downstream nodes need it
async def preprocess_node(state):
    return {"user_message": None}  # Too early!
```

### ✅ Clear Only in summarize_node (END)
```python
# CORRECT
async def summarize_node(state):
    return {"user_message": None}  # End of pipeline
```

## Testing

```python
import pytest
from agent.modes.greeting_mode import GreetingMode

@pytest.mark.asyncio
async def test_greeting_mode():
    mode = GreetingMode(tools=[])
    state = {
        "conversation_id": "test-001",
        "current_mode": "GREETING",
        "user_message": "Hola, soy Juan",
        "messages": [],
        "customer_name": None,
    }
    
    result = await mode.handle(state, intent=None)
    
    assert "messages" in result
    assert result["last_node"] == "greeting_node"
```

## Environment Variables

```python
from shared.config import get_settings

settings = get_settings()
llm_model = settings.LLM_MODEL  # openai/gpt-4o-mini
resilience_enabled = settings.RESILIENCE_ENABLED  # True
use_optimized = settings.USE_OPTIMIZED_PROMPTS  # True
```

---

**Version**: 1.0 (Mode-based v6.0 architecture)
**Last Updated**: March 2026
