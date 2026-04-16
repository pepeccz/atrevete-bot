# Refactor: Migrate BaseModeNode → create_agent + middleware

## Target

Replace hand-rolled `BaseModeNode._run_agentic_loop` (~285 LOC per mode) with `langchain.agents.create_agent` + composable middleware. Eliminate overlapping recovery machinery, gain native streaming, structured output, and HITL.

## Scope

In scope:
- `agent/modes/base.py` — replaced by thin wrapper or deleted
- `agent/modes/greeting_mode.py`, `general_mode.py`, `escalation_mode.py`, `booking_mode.py`, `appointment_management_mode.py` — migrate each
- `agent/state/schemas.py` — typed state with clean reducers
- `agent/graphs/conversation_flow.py` — wire new modes
- Middleware modules in new `agent/middleware/`
- Tests: reescribir los que tocan el loop interno; preservar los que asertan end-state
- Old loop code, `ToolCallRejection` machinery, dedup guard, final-text recovery helpers — DELETE

Out of scope:
- Preexisting test failures (176 tests, 41 errors at baseline) unrelated to the loop
- `agent/tools/*` semantic changes (only update signatures if middleware requires)
- `agent/routing/intent_router.py` refactor (future: #3 structured output)
- Prompts (`agent/prompts/**`) — leave as-is
- Deploy to server — user does it

## Baseline (before refactor)

- 1897 pass, 176 fail, 1 xfailed, 41 errors
- Saved: `docs/refactor/baseline-failures.txt`
- Rule: refactor must not cause any test in `baseline-failures.txt` NEGATIVE list to transition from pass→fail. Tests that were failing may remain failing. Tests I reescribo obviously change.

## Milestones

### M1 — Spike ✅ DONE
- `spikes/create_agent_migration/spike.py` — 5 patterns verified PASS
- `spikes/create_agent_migration/RESULTS.md` — results report
- Key findings: use `dataclasses.replace(request, ...)`, `jump_to: "end"` in `after_model` for forced recovery, `add_messages` ID-overwrite for final-text recovery.

### M2 — Typed state schema + middleware scaffolding
- Rewrite `agent/state/schemas.py`:
  - Typed `BookingContext` dataclass/TypedDict (replaces `dict` booking_context)
  - Clean `replace_dict` reducer (drop `merge_dicts + __reset__` sentinel pattern)
  - Single reducer strategy across all dict-shaped state
  - Fix duplicate `customer_data_collected` field
- Create `agent/middleware/` package:
  - `__init__.py`
  - `types.py` — shared data classes
- Write unit tests for reducers in `tests/unit/test_state_reducers_v2.py`
- Done when: schema tests pass; existing code using old schema types still compiles (may break at runtime — caught by integration later)

### M3 — GreetingMode → create_agent
- Replace `agent/modes/greeting_mode.py` internals with `create_agent` instance
- Implement `TokenTrackingMiddleware` (generic, used by all modes) in `agent/middleware/token_tracking.py`
- Wire into `conversation_flow.py` as graph node (factory pattern)
- Rewrite tests: `tests/unit/test_greeting_mode.py`
- Done when: greeting mode tests pass; conversation_flow still imports; graph builds without error

### M4 — GeneralMode + EscalationMode → create_agent
- Same pattern as M3
- Rewrite tests for both
- Done when: both modes pass tests; graph builds

### M5 — Booking middleware stack
- `agent/middleware/dynamic_tools.py` — filters tools by `BookingContext` state via `wrap_model_call` + `dataclasses.replace`
- `agent/middleware/tool_choice.py` — forces `tool_choice="required"` on HumanMessage turn
- `agent/middleware/dedup.py` — `wrap_tool_call` with cache derived from prior ToolMessages
- `agent/middleware/final_text_recovery.py` — `after_model` injects fallback AIMessage if loop ends with empty content + tool_calls
- `agent/middleware/gate_recovery.py` — `after_model` counts rejections, `jump_to: "end"` with fixed text on threshold
- Unit tests for each middleware with `FakeMessagesListChatModel` (subclass with `bind_tools` stub) in `tests/unit/middleware/`
- Done when: all 5 middleware have passing unit tests

### M6 — BookingMode → create_agent
- Replace `agent/modes/booking_mode.py` with `create_agent` + middleware stack
- Preserve existing `_pre_tool_call`/`_post_tool_result` LOGIC as pre/post hooks inside middleware (customer_memories write, slot clearing, etc.)
- Port audience-variant validation (bug "Corte Señora") into `update_booking` tool as data response with `ambiguity` payload (not rejection)
- Rewrite tests in `tests/unit/test_booking_mode.py` and related
- Done when: booking mode passes; "Corte Señora" scenario handles ambiguity without assuming

### M7 — AppointmentManagementMode → create_agent
- Same pattern as M6
- Keep `interrupt()` for destructive actions OUT OF SCOPE this refactor — port the existing confirmation-gate keyword matcher as-is
- Done when: mode tests pass

### M8 — Delete legacy code
- Delete `agent/modes/base.py` (the entire BaseModeNode class, `_run_agentic_loop`, `ToolCallRejection`, dedup helpers)
- Delete orphaned helpers in `agent/state/helpers.py` if unused
- Delete baseline-broken tests that tested loop internals: `test_base_mode.py`, `test_base_mode_dedup.py`, `test_token_tracking_hook.py` (token tracking is now a middleware with its own tests)
- Update `conversation_flow.py` to remove any BaseModeNode references
- Done when: `rg 'BaseModeNode|_run_agentic_loop|ToolCallRejection' agent/` returns empty

### M9 — Final validation
- Run full test suite, compare to `baseline-failures.txt`
- Zero net regressions (pre-existing failures may stay, new failures must be zero)
- Manually trace through conversation_flow.py to verify graph shape preserved
- Update `CLAUDE.md` and `AGENTS.md` references to BaseModeNode → create_agent
- Done when: delta of failing tests ≤ 0, all new middleware + modes have tests, legacy code gone

## Conventions

- Each milestone commits separately with message `refactor(modes): M{N} — {summary}`
- Python imports: `from langchain.agents import create_agent`, middleware types from `langchain.agents.middleware.types`
- `ModelRequest` updates: ALWAYS use `dataclasses.replace(request, ...)`, never `request.x = ...`
- Middleware naming: `{Purpose}Middleware` class; one per file under `agent/middleware/`
- Offline tests use `FakeMessagesListChatModel` with subclass adding no-op `bind_tools`

## References

- Current loop: `agent/modes/base.py:519-804`
- Tool filter to port: `agent/modes/booking_mode.py:62-89` (`get_tools`) and `:836-841` (`_refresh_tools`)
- Audit report: (in conversation history, engram memory `project_create_agent_migration`)
- Spike: `spikes/create_agent_migration/`
