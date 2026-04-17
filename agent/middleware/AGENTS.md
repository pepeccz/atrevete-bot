# agent/middleware — Parity Contract

Every `AgentMiddleware` subclass in this directory that overrides a hook from a sync/async pair
**MUST** override both variants of that pair. This document explains why and how to comply.

---

## Composition rule

LangChain 1.2.x (`langchain/agents/factory.py:878-918` for tool-call hooks,
`:978-1017` for model-call hooks) builds two separate dispatch chains — one for `invoke` and
one for `ainvoke` — at `create_agent` time. The wiring is **symmetric**: if a class overrides
**either** `wrap_tool_call` **or** `awrap_tool_call`, the factory pulls it into **both** chains.
The same applies to the model-call pair.

The consequence: if your class overrides only the sync variant, the async chain still includes
your class — but calls the **base-class** `awrap_tool_call`, which raises:

```
NotImplementedError: Asynchronous implementation of awrap_tool_call is not available.
```

This is exactly the production failure observed on WhatsApp when `DedupToolCallMiddleware`
overrode only `wrap_tool_call` (commit `366cf79`). The error only appears under `ainvoke`
(e.g., async WhatsApp message handling), making it invisible to sync unit tests.

---

## Parity requirements

- **REQ-1 — Tool-call hook parity**: any subclass that overrides `wrap_tool_call` MUST also
  override `awrap_tool_call`, and vice versa.

- **REQ-2 — Model-call hook parity**: any subclass that overrides `wrap_model_call` MUST also
  override `awrap_model_call`, and vice versa.

---

## State-lifecycle hook exemption

- **REQ-3**: The hooks `before_model`, `after_model`, `aafter_model`, `after_agent`, and their
  variants are **exempt**. LangChain provides graceful fallback for state-lifecycle hooks; they
  do not participate in the symmetric chain composition. Do NOT implement async parity variants
  for lifecycle hooks.

  Examples of exempt classes (correct as-is):
  - `FinalTextRecoveryMiddleware` — uses `after_agent` only
  - `TokenTrackingMiddleware` — uses `aafter_model` only
  - `GateRecoveryMiddleware` — uses `after_model` only

---

## Opt-out mechanism

A subclass may opt out of the parity requirement by setting:

```python
from typing import ClassVar

class MySpecialMiddleware(AgentMiddleware):
    """Only used in the sync chain by design because <reason>.

    Single variant is acceptable here: this middleware is only composed
    into sync agents invoked via invoke(), never ainvoke().
    """

    _allow_single_variant: ClassVar[bool] = True

    def wrap_tool_call(self, request, handler):
        ...
```

Opt-out rules:
1. `_allow_single_variant = True` **and** a non-empty class docstring are both required.
2. The docstring must explain **why** single-variant is acceptable.
3. An opted-out class with an empty or missing docstring causes the guardrail to **FAIL**.

---

## Regression guard

Two tests enforce this contract automatically:

- **Collection-time guardrail** (`tests/unit/middleware/test_middleware_parity.py`):
  Parametrizes over all `AgentMiddleware` subclasses at pytest collection time via
  `AgentMiddleware.__subclasses__()` (with eager `pkgutil.iter_modules` import to catch lazy
  modules). Fails instantly when a new subclass violates parity. Zero overhead: no asyncio,
  no network, runs in < 1 s.

- **Integration regression canary** (`tests/integration/test_middleware_stack_ainvoke.py`):
  Composes the full BOOKING middleware stack verbatim (mirroring `booking_mode.py:650-663`)
  and drives it via `create_agent.ainvoke()` with a scripted tool call. This test **FAILED**
  on master before the fix (commit `366cf79`) and is the definitive end-to-end proof that
  async dispatch works correctly under the production stack.

---

## Dynamic tool filtering pattern

### When to use it

Use `DynamicToolsMiddleware` when the set of tools the LLM should see must change
**mid-flow within a single `ainvoke` call** — for example, exposing `check_availability`
only after the user selects a reschedule action, or hiding `book` until a service and
stylist are resolved.  Static pre-filtering at `create_agent(tools=...)` construction
time is NOT enough because the LLM may loop across multiple tool calls before returning.

### How to wire it

Pass a **zero-arg closure** that captures `self` (the owning node instance):

```python
DynamicToolsMiddleware(get_tools_fn=lambda: self.get_tools(self._mode_context))
```

Place the middleware BEFORE `NodeBridgeMiddleware` in the list (position 0, or position 1
when `ToolChoiceMiddleware` is present):

```python
middleware = [
    DynamicToolsMiddleware(get_tools_fn=lambda: self.get_tools(self._mode_context)),
    NodeBridgeMiddleware(self),
    ...
]
```

`self._mode_context` (or `self._booking_context`) MUST be set by `handle()` before
`_invoke_create_agent` is called.  The closure reads the live attribute on each model
call, so mid-loop mutations are reflected immediately.

### Critical rule: NEVER read `request.state` for project context

`request.state` inside a middleware hook is LangChain's `AgentState` — it contains
**only** `messages`, `jump_to`, and `structured_response`.  It does NOT contain booking
context, mode context, or any application-level state.  Reading it for project data
produces `KeyError` / `None` silently.  Always use a closure over the node instance
instead (decision D1 in the design artifact).

### How to test

See `tests/unit/middleware/test_dynamic_tools.py`, especially:

- `test_closure_reads_live_node_attribute_between_calls` — proves the closure reads a
  freshly mutated node attribute on the second `wrap_model_call` without re-constructing
  the middleware.
- `test_sync_async_parity` — proves `wrap_model_call` and `awrap_model_call` produce
  identical filtering results.

### Parity reminder

`DynamicToolsMiddleware` overrides the **model-call** pair.  Per REQ-2 above, both
`wrap_model_call` and `awrap_model_call` MUST be defined.  They share a `_apply_filter`
helper to prevent drift.  Do NOT add `wrap_tool_call` or `awrap_tool_call` unless the
filtering logic also needs to apply at the tool-call layer.
