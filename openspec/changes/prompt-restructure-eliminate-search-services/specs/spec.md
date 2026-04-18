# Delta Specs: prompt-restructure-eliminate-search-services

## Change ID
`prompt-restructure-eliminate-search-services`

## Status
`spec`

---

## Domain A: booking-mode-guard (P0)

### MODIFIED Capability: `stylist-guard-in-pre-tool-call`

Applies to: `BookingModeNode._pre_tool_call()` in `agent/modes/booking_mode.py` (~line 286-301).

---

## MODIFIED Requirements

### Requirement: Stylist Guard Allows Tool-Arg Stylist Resolution

The system MUST accept a `check_availability` tool call when the LLM provides `stylist_name` directly in `tool_args`, even if `last_stylist` is not yet set in `booking_context`. The guard SHALL check `tool_args.get("stylist_name")` as a valid resolution source alongside `booking_context["last_stylist"]` and `booking_context["no_preference_stylist"]`.

(Previously: guard only checked booking_context fields, blocking check_availability before those fields could be populated — a deadlock)

#### Scenario: LLM provides stylist_name in args — guard passes

- GIVEN the user has said "quiero con Víctor" and the LLM calls `check_availability(stylist_name="Victor")`
- AND `booking_context["last_stylist"]` is NOT set
- WHEN `_pre_tool_call("check_availability", {"stylist_name": "Victor"})` is called
- THEN the guard MUST NOT return ToolCallRejection
- AND the function MUST return the original `tool_args` dict unchanged

#### Scenario: No stylist context at all — guard rejects

- GIVEN `booking_context["last_stylist"]` is not set
- AND `booking_context["no_preference_stylist"]` is not set
- AND `tool_args` does NOT contain `stylist_name`
- WHEN `_pre_tool_call("check_availability", {})` is called
- THEN the guard MUST return a `ToolCallRejection` with `error_code="STYLIST_NOT_RESOLVED"`

#### Scenario: last_stylist already set — guard passes (regression)

- GIVEN `booking_context["last_stylist"]` is set to "Pilar"
- WHEN `_pre_tool_call("check_availability", {})` is called
- THEN the guard MUST NOT return ToolCallRejection

#### Scenario: no_preference_stylist set — guard passes (regression)

- GIVEN `booking_context["no_preference_stylist"]` is True
- WHEN `_pre_tool_call("check_availability", {})` is called
- THEN the guard MUST NOT return ToolCallRejection

#### Scenario: Empty string stylist_name — guard rejects

- GIVEN `tool_args` contains `stylist_name=""` (empty string)
- AND no other stylist context is set
- WHEN `_pre_tool_call("check_availability", {"stylist_name": ""})` is called
- THEN the guard MUST return a `ToolCallRejection` with `error_code="STYLIST_NOT_RESOLVED"`

---

## Domain B: base-tool-loop (P1)

### MODIFIED Capability: `tool-args-preservation-in-agentic-loop`

Applies to: `BaseModeNode._run_agentic_loop()` in `agent/modes/base.py` (~line 564-620).

---

## MODIFIED Requirements

### Requirement: Original tool_args Preserved for _post_tool_result

The system MUST preserve the original `tool_args` dict (as extracted from the LLM tool call) and pass it unchanged to `_post_tool_result`, regardless of what `_pre_tool_call` returns. The variable assigned from `_pre_tool_call` result SHALL be a separate binding (e.g., `effective_args`) and MUST NOT overwrite the original `tool_args` binding.

(Previously: `tool_args = await self._pre_tool_call(...)` at base.py:569 overwrote the original dict; when _pre_tool_call returned ToolCallRejection, `_post_tool_result(tool_name, tool_args, result)` at line 620 received a ToolCallRejection object instead of a dict, causing AttributeError on `.get()` silently swallowed by try/except)

#### Scenario: _pre_tool_call returns ToolCallRejection — post_tool_result receives original dict

- GIVEN the LLM calls `book(slot_index=2)`
- AND `_pre_tool_call` returns a `ToolCallRejection`
- WHEN `_post_tool_result("book", original_tool_args, result)` is invoked
- THEN `original_tool_args` passed to `_post_tool_result` MUST be `{"slot_index": 2}`
- AND MUST NOT be the `ToolCallRejection` object

#### Scenario: _pre_tool_call returns transformed dict — post_tool_result receives enriched dict

- GIVEN the LLM calls `book(slot_index=1)`
- AND `_pre_tool_call` returns an enriched dict `{"slot_index": 1, "slot_id": "<uuid>", ...}`
- WHEN `_post_tool_result("book", effective_args, result)` is invoked
- THEN `effective_args` MUST be the enriched dict
- AND the original `tool_args` binding MUST remain `{"slot_index": 1}`

#### Scenario: _pre_tool_call raises exception — post_tool_result receives original dict

- GIVEN `_pre_tool_call` raises an unexpected exception
- WHEN the exception is caught and execution continues
- THEN `_post_tool_result` MUST receive the original `tool_args` dict
- AND a warning log MUST be emitted with the exception message

---

## Domain C: stylist-data-integrity (P1)

### ADDED Requirement: Seed Script Deactivates Unlisted Stylists

The seed script at `database/seeds/stylists.py` MUST set `is_active=False` for any stylist in the database whose `name` is NOT in the canonical active roster: `[Marta, Pilar, Victor, Harolyn, Rosa]`.

#### Scenario: Stale stylists deactivated on seed run

- GIVEN the database contains "Ana" and "Ana María" (stale, not in canonical list)
- WHEN the seed script runs
- THEN "Ana" and "Ana María" MUST have `is_active=False`
- AND canonical stylists MUST remain `is_active=True`

#### Scenario: Seed is idempotent

- GIVEN the seed script has already run once
- WHEN the seed script runs again
- THEN no additional records are created
- AND no correctly-active stylists are deactivated

#### Scenario: Fresh DB — all 5 canonical stylists created active

- GIVEN the database has no stylist rows
- WHEN the seed script runs
- THEN 5 rows are created with `is_active=True` for `[Marta, Pilar, Victor, Harolyn, Rosa]`

### ADDED Requirement: Booking Prompt Examples Reference Active Stylists Only

The file `agent/prompts/modes/booking.md` MUST NOT contain any stylist name in example blocks that refers to a name not in the active roster `[Marta, Pilar, Victor, Harolyn, Rosa]`.

#### Scenario: booking.md has no stale stylist name examples

- GIVEN `booking.md` is loaded as a string
- WHEN scanned for standalone stylist name examples
- THEN the name "Ana" MUST NOT appear as a stylist example
- AND every example stylist name MUST match one of `[Marta, Pilar, Victor, Harolyn, Rosa]`

---

## Domain D: prompt-token-budgets (P2)

### ADDED Requirement: Static Prompt Files Conform to Individual Token Budgets

Each static prompt file MUST measure at or below its defined token budget using tiktoken `gpt-4o-mini` encoding:

| File | Budget |
|------|--------|
| `agent/prompts/shared/identity.md` | ≤350 tokens |
| `agent/prompts/modes/booking.md` | ≤1,800 tokens |
| `agent/prompts/modes/greeting.md` | ≤280 tokens |

Files already within budget (`critical_rules.md` ≤1,100t, `general.md` ≤450t) MUST NOT regress.

#### Scenario: identity.md trimmed to budget

- GIVEN identity.md currently measures 477 tokens
- WHEN redundant formatting instructions and duplicate phrasing are removed
- THEN tiktoken count for identity.md MUST be ≤350
- AND bot identity, salon name, and core persona content MUST be preserved

#### Scenario: booking.md trimmed to budget

- GIVEN booking.md currently measures 1,876 tokens
- WHEN redundant disambiguation tables and stale examples are removed
- THEN tiktoken count for booking.md MUST be ≤1,800
- AND booking flow steps, slot selection, and confirmation gate MUST be preserved

#### Scenario: greeting.md trimmed to budget

- GIVEN greeting.md currently measures 350 tokens
- WHEN rules are condensed
- THEN tiktoken count for greeting.md MUST be ≤280
- AND name collection and first-interaction logic MUST be preserved

#### Scenario: Trimmed prompts do not regress booking flow

- GIVEN all three prompt files are trimmed to budget
- WHEN a complete booking flow QA run executes (service → stylist → slot → confirm)
- THEN the bot MUST complete the booking successfully
- AND MUST NOT produce STYLIST_NOT_RESOLVED or unexpected ToolCallRejection errors

---

## Domain E: dead-code-cleanup (P2/P3)

### ADDED Requirement: No stale search_services References in Active Files

All references to `search_services` in active source and test files MUST be removed. Dead code under `agent/fsm/` is addressed by FSM deletion below.

#### Scenario: test_mode_prompts.py passes without search_services assertion

- GIVEN `tests/integration/test_mode_prompts.py` currently asserts `search_services` appears in prompts
- WHEN the assertion is replaced to reflect catalog_builder.py architecture
- THEN the test MUST pass
- AND MUST NOT reference `search_services` in any assertion

#### Scenario: Zero search_services references remain in active files

- GIVEN 57 references exist across test and source files
- WHEN all active (non-FSM) files are updated
- THEN a scan (`rg "search_services"`) on active files MUST return 0 matches

### ADDED Requirement: Dead agent/fsm/ Module Is Deleted

The directory `agent/fsm/` (`models.py`, `fsm_action.py`) MUST be deleted. No active import path SHALL reference `agent.fsm`.

#### Scenario: No imports of agent.fsm after deletion

- GIVEN `agent/fsm/` is deleted
- WHEN `rg "from agent\.fsm|import agent\.fsm"` runs on the repo
- THEN 0 matches MUST be found outside of archived/git-history files

#### Scenario: Full test suite passes after FSM deletion

- GIVEN `agent/fsm/` is deleted and imports cleaned
- WHEN `pytest` runs
- THEN no test MUST fail due to missing `agent.fsm` imports

---

## Edge Cases

| Area | Edge Case | Expected Behavior |
|------|-----------|-------------------|
| Stylist guard | `tool_args["stylist_name"] = ""` (empty string) | Treated as absent — guard rejects with STYLIST_NOT_RESOLVED |
| Stylist guard | `tool_args["stylist_name"]` present but wrong casing | Guard passes (case resolution is downstream, not guard's responsibility) |
| tool_args preservation | `_pre_tool_call` returns original dict unchanged | `_post_tool_result` receives same dict — no regression |
| Seed script | DB is empty (first deploy) | Creates all 5 canonical stylists as active; deactivation loop is a no-op |
| Seed script | All canonical stylists exist and active, no stale rows | Script is a complete no-op |
| Prompt trim | Removing content takes a file under 100 tokens (over-trim) | Regression test must catch missing critical sections |
| FSM deletion | A migration file references `agent.fsm` models | Migration files must be audited and updated if they import FSM types |
| search_services cleanup | A test imports search_services for a negative assertion | Test must be rewritten to assert catalog_builder output instead |
