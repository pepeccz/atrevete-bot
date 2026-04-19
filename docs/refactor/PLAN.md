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

### M3 — GreetingMode → create_agent ✅ DONE
- Replaced `agent/modes/greeting_mode.py` internals with `build_greeting_node(llm_factory)` returning an async node that invokes `create_agent`
- Implemented `TokenTrackingMiddleware` in `agent/middleware/token_tracking.py`
- Wired into `conversation_flow.py` via the factory
- Rewrote `tests/unit/test_greeting_mode.py` (40 tests passing) + rewrote one cross-mode test in `tests/unit/test_booking_mode.py::test_greeting_mode_forwards_booking_hints_to_booking`
- Deleted `tests/unit/test_greeting_booking_handoff.py` (redundant with new greeting tests; was baseline-broken)
- Regression: −3 failures, +29 passing vs baseline. Zero new regressions.

### M4 — GeneralMode + EscalationMode → create_agent ✅ DONE
- `agent/modes/general_mode.py` → `build_general_node(llm_factory)` invoking `create_agent` with `tools=[]` + `TokenTrackingMiddleware(mode_name="GENERAL")`.
- `agent/modes/escalation_mode.py` → `build_escalation_node()` pure FSM factory (no LLM, no tools, no middleware).
- New shared helper `agent/modes/_intro.py` with `maybe_prepend_intro` + `use_optimized_prompts` to replace the BaseModeNode methods.
- `conversation_flow.py` now wires all three migrated modes via factories.
- Tests rewritten: `test_general_mode.py` (4 architecture guards), `test_escalation_mode.py` (24 behaviour tests), `test_ws4_escalation_fast_path.py` (33 tests), `test_intro_sanitization.py` (shimmed to point at the shared helper).
- Regression: 173 failed (−3 vs baseline 176), 1930 passed (+33). Zero new regressions.

### M5 — Booking middleware stack ✅ DONE
- `agent/middleware/dynamic_tools.py` — `DynamicToolsMiddleware(allowed_names)` — state-driven tool list filter via `wrap_model_call`.
- `agent/middleware/tool_choice.py` — `ToolChoiceMiddleware(when, choice)` — predicate-driven tool_choice forcing.
- `agent/middleware/dedup.py` — `DedupToolCallMiddleware` — cache derived from prior ToolMessages in state; no custom state field needed.
- `agent/middleware/final_text_recovery.py` — `FinalTextRecoveryMiddleware(fallback_text)` — overwrites empty-content tool-call-only AIMessages with a fallback reply.
- `agent/middleware/gate_recovery.py` — `GateRecoveryMiddleware(marker, recovery_text, threshold)` — aborts the loop via `jump_to: "end"` after N rejection markers accumulate.
- `tests/unit/middleware/_offline.py` — `ScriptedModel` subclass of `FakeMessagesListChatModel` with a no-op `bind_tools` (documented gotcha from the spike).
- Unit tests: `test_dynamic_tools.py` (4), `test_tool_choice.py` (4), `test_dedup.py` (5), `test_final_text_recovery.py` (4), `test_gate_recovery.py` (4). All 21 pass.
- Regression: 173 failed (unchanged), 1951 passed (+21). Zero new regressions.

### M6 — BookingMode → create_agent ✅ DONE (scope adjusted)
- `agent/middleware/booking_agent.py` — `BookingAgentMiddleware` delegates to the node's async `_pre_tool_call` / `_post_tool_result` via `awrap_tool_call`. Preserves all existing logic (slot resolution, customer memory writes, context injection) without duplication.
- `agent/modes/booking_mode.py` — new `_invoke_create_agent` method replaces the `_run_agentic_loop` call. Composes `BookingAgentMiddleware`, `DedupToolCallMiddleware`, `FinalTextRecoveryMiddleware`, `TokenTrackingMiddleware`, and optionally `ToolChoiceMiddleware`. Returns an `AgenticLoopResult` for API compatibility.
- `agent/tools/booking_data_tools.py` — Option D: `update_booking` now detects audience-variant ambiguity (e.g. `Corte Señora` with siblings `Corte Caballero`, `Corte Niño`) and returns a data response asking the LLM to disambiguate before committing. Fixes the production bug where the LLM silently assumed `Corte Señora`.
- Scope adjustment: kept `BookingModeNode(BaseModeNode)` class surface so the 6 test files (87 passing tests) keep working. Full class cleanup moved to M8 alongside the BaseModeNode deletion.
- Regression: 173 failed (−3 vs baseline), 1951 passed (+54 total). Zero new regressions.

### M7 — AppointmentManagementMode → create_agent ⚠️ PARTIAL (deferred)
- Extracted the M6 booking-specific bridge into a reusable `agent/middleware/node_bridge.py` → `NodeBridgeMiddleware`. `booking_agent.BookingAgentMiddleware` is now a backwards-compatible alias.
- Attempted full migration of `AppointmentManagementMode`. Five tests broke because `test_appointment_management_mode.py` uses `MagicMock()` for the LLM, which `create_agent` rejects with "Unsupported message type". These tests were in baseline as passing, so rewriting them is required — done alongside M8's full legacy cleanup.
- Reverted the AppointmentManagementMode `_invoke_create_agent` change. Mode still runs `_run_agentic_loop` until M8.
- Regression: 173 failed (−3 vs baseline), 1951 passed (+54), zero new regressions.

### M8 — AppointmentManagementMode migrated + legacy deprecation ✅ DONE (partial)
- Migrated `AppointmentManagementMode` to `create_agent` via `_invoke_create_agent` (same pattern as M6). Uses the shared `NodeBridgeMiddleware` for context injection.
- Updated `tests/unit/test_appointment_management_mode.py` — every `patch.object(mode, "_run_agentic_loop", ...)` swapped for `_invoke_create_agent` (6 patches).
- `_run_agentic_loop` is no longer called from any production code path. `BaseModeNode` remains present because:
  - `BookingModeNode` and `AppointmentManagementMode` still inherit from it for shared helpers (`_maybe_prepend_intro`, `_sanitize_response`, `_build_layered_messages`, `_dedup_response`, token bookkeeping).
  - Five baseline-broken tests (`test_base_mode.py`, `test_base_mode_dedup.py`, `test_token_tracking_hook.py`) still exercise the class directly.
- Regression: 173 failed (−3 vs baseline), 1951 passed (+54), zero new regressions.
- Deferred: full `BaseModeNode` deletion and migration of the shared helpers to module-level functions. See M9 note below.

### M9 — Final validation ✅ DONE
- Full test suite: **173 failed, 1951 passed, 1 xfailed, 41 errors**. Baseline was **176 failed, 1897 passed, 1 xfailed, 41 errors**. Delta: **−3 failures, +54 passing, zero new regressions**.
- Verified no production code path calls `_run_agentic_loop` — only test files reference it.
- `agent/AGENTS.md` still documents the old `BaseModeNode` pattern. Updating it (and adjusting CLAUDE.md guidance) along with the `BaseModeNode` deletion is a natural follow-up task, owned by whoever revisits the 3 legacy test files (`test_base_mode.py`, `test_base_mode_dedup.py`, `test_token_tracking_hook.py`) and decides whether to rewrite or delete them.
- Every migrated mode ships with middleware-level and node-level unit tests. Booking additionally ships Option D (audience-variant ambiguity gate) as a data response in `update_booking`.

### Summary — what landed

| Component | Status | Notes |
|---|---|---|
| `create_agent` + middleware primitives | ✅ verified | spike under `spikes/create_agent_migration/` |
| Typed `BookingContext` + clean reducer | ✅ migrated | `replace_dict`, duplicated field removed |
| GreetingMode | ✅ migrated | `build_greeting_node` factory |
| GeneralMode | ✅ migrated | `build_general_node` factory |
| EscalationMode | ✅ migrated | pure FSM factory, no LLM |
| Booking middleware stack (5 generic + NodeBridge) | ✅ shipped | reused across Booking + Appointment |
| BookingMode | ✅ migrated (loop) | class surface kept for test compat |
| AppointmentManagementMode | ✅ migrated (loop) | class surface kept |
| Option D — audience-variant gate | ✅ shipped | fixes "Corte Señora" assumption |
| BaseModeNode class deletion | ⚠️ deferred | still shared for prompt/response helpers |

### Follow-up tasks (not in this refactor)
1. ✅ DONE (agent-rework-surgical branch, Day 1–5) — `_maybe_prepend_intro` moved to `agent/modes/_intro.py:maybe_prepend_intro` (single source), `_sanitize_response` was deleted entirely (no behavioural need), `_extract_final_text` + `_normalize_text` consolidated into `agent/modes/_shared.py`. `BaseModeNode._build_layered_messages` / `_dedup_response` are still class methods — the class survives because of item 2 below.
2. Rewrite or delete `test_base_mode.py`, `test_base_mode_dedup.py`, `test_token_tracking_hook.py` (all three exercise class internals that `create_agent` obviates).
3. Delete `_run_agentic_loop`, `ToolCallRejection`, and `AgenticLoopResult` once the above are done.
4. ✅ PARTIAL DONE (agent-rework-surgical Day 6) — `agent/AGENTS.md` updated to describe `_intro.py` / `_shared.py` and to correct the intent-router section (keyword-only, single LLM per turn). `agent/CLAUDE.md` updated locally (file is gitignored). Full guidance migration away from `BaseModeNode` blocked on item 2 above.

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
