# create_agent Migration Spike — Results

## Environment

| Package | Version |
|---|---|
| langchain | 1.2.15 |
| langchain-core | 1.2.26 |
| langgraph | 1.1.6 |
| langchain-openai | 1.1.12 |
| Python | 3.14 (pydantic v1 warning — benign) |

## Imports used

```python
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    AgentState, ModelRequest, ModelResponse, ToolCallRequest,
)
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
```

`create_agent` is in `langchain.agents` (not `langgraph.prebuilt`). Middleware types live under `langchain.agents.middleware.types`.

Offline model: `FakeMessagesListChatModel` does NOT implement `bind_tools`, so a subclass (`ScriptedModel`) with a no-op `bind_tools` was needed. The agent factory calls `model.bind_tools(...)` every iteration — this is a real gotcha if you ever want to unit-test agents offline.

## Pattern results

All five ran in one invocation of `spike.py`:

```
[Pattern 1 | dynamic tool filtering] PASS
[Pattern 2 | conditional tool_choice] PASS
[Pattern 3 | dedup via wrap_tool_call] PASS  (1 real execution, 1 cached)
[Pattern 4 | final-text recovery]     PASS
[Pattern 5 | forced recovery after N] PASS
```

| # | Pattern | Status | Hook used | Minimal LOC |
|---|---|---|---|---|
| 1 | Dynamic tool filtering by state | PASS | `wrap_model_call` + `dataclasses.replace(request, tools=...)` | ~15 |
| 2 | Conditional `tool_choice="required"` | PASS | Same `wrap_model_call`, branch on `isinstance(last, HumanMessage)` | ~3 |
| 3 | Dedup guard via `wrap_tool_call` | PASS-WITH-CAVEAT | `wrap_tool_call` — cache REBUILT from prior `ToolMessage`s in `request.state['messages']` | ~20 |
| 4 | Final-text recovery | PASS | `after_model` returns `{"messages": [fixed_AIMessage]}` with same `id` (overwrite via `add_messages` reducer) | ~10 |
| 5 | Forced recovery after N rejections | PASS (5a approach) | `after_model` counts rejections, returns `{"messages": [...], "jump_to": "end"}` | ~15 |

### Notable mechanics

- **ModelRequest is a frozen-ish dataclass.** Direct attribute set is deprecated; use `dataclasses.replace(request, tools=..., tool_choice=...)` instead. The skill docs don't call this out.
- **`add_messages` reducer overwrites when IDs match.** For Pattern 4/5, returning a new `AIMessage` with the SAME `id` as the existing one replaces it in place. No custom reducer needed.
- **`jump_to: "end"` terminates the agent loop cleanly** from inside `after_model`. `JumpTo = Literal['tools', 'model', 'end']`. This is the official exit-hatch; no outer `StateGraph` wrapper required for Pattern 5 — option 5a worked, options 5b/5c unnecessary.
- **`request.state` inside `wrap_tool_call` reflects message history up to that point,** including ToolMessages from previous super-steps. Pattern 3's cache is thus derivable from state without any new state field.

## Go / No-Go Verdict

**GO.** All 5 patterns map cleanly to the existing middleware API in LangChain 1.2. No pattern required fighting the framework, no pattern required an outer `StateGraph` wrapper, no pattern required an escape hatch into raw LangGraph. The hooks exposed (`wrap_model_call`, `wrap_tool_call`, `after_model`, `before_agent`) plus `jump_to` cover everything in `agent/modes/base.py:519-804`.

## Biggest Surprise

`FakeMessagesListChatModel` can't be used directly with `create_agent`. The factory calls `bind_tools` unconditionally and the base `BaseChatModel.bind_tools` raises `NotImplementedError`. Any offline test harness needs a thin subclass. The skills don't mention this. For the migration, this means our test fixtures need updating — not just the production code.

Runner-up: `ModelRequest` deprecates direct attribute setting. We MUST use `dataclasses.replace(request, ...)` or `request.override(...)`. Any code that does `request.tools = filtered` will emit deprecation warnings today and break later.

## Effort Revision

**Down.** Prior estimate: 2.5-3 weeks. New estimate: **1.5-2 weeks**. Reasons:

1. All 5 patterns are roughly 10-20 LOC each in middleware form, versus the ~285 LOC hand-rolled loop in `base.py`. Direct line-count reduction of ~70%.
2. `jump_to: "end"` removes the need to design a custom "forced recovery" mechanism — it's built in.
3. The `add_messages` reducer's ID-match-overwrite behavior means Pattern 4/5 don't need a custom message-replacement reducer.
4. The one real gotcha (ModelRequest immutability via `replace`) is a one-line fix per call site.

Add back ~3 days for:
- Fixing the offline test harness (`ScriptedModel` shim + fixtures that embed `bind_tools`).
- Reviewing every `{**state}` spread in the agent for reducer correctness post-migration (CLAUDE.md rule #3 still applies).
- The `AgentState` schema has new reserved keys (`jump_to`, `structured_response`) that could clash with the project's existing state fields — needs audit.

## File tree

```
spikes/create_agent_migration/
├── spike.py       (380 LOC — 5 pattern tests in one script)
└── RESULTS.md     (this file)
```
