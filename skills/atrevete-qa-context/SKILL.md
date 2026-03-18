---
name: atrevete-qa-context
description: >
  Loads conversational QA personas, flows, and evaluation criteria from
  .atl/qa-testing-context.md.
  Trigger: When loading QA context, choosing a QA persona, or preparing a conversational QA scenario.
license: MIT
metadata:
  author: atrevete-bot
  version: "1.0"
  scope: [root]
  auto_invoke:
    - "Loading QA context"
    - "Choosing a QA persona"
    - "Preparing a conversational QA scenario"
---

## Purpose

Load the shared QA context file and turn it into structured inputs for the tester and evaluator skills.

## Execution Steps

1. Read `.atl/qa-testing-context.md`.
2. Parse the YAML frontmatter to obtain `personas`, `criteria`, and `flows`.
3. Validate the requested flow exists.
4. Resolve the persona attached to that flow unless the caller explicitly overrides it.
5. Return a structured object with `flow`, `persona`, `criteria`, and the list of available flows.

## Rules

- Fail clearly when the context file is missing or malformed.
- Fail clearly when the requested flow or persona does not exist.
- Always include all five evaluation levels in the returned payload.
- Keep file paths and identifiers exact so the tester skill can reuse them directly.

## Usage Example

Input:

```json
{
  "flow_id": "booking_complete"
}
```

Output shape:

```json
{
  "flow_id": "booking_complete",
  "persona_id": "maria_new_client",
  "available_flows": ["booking_complete", "returning_client", "escalation", "indecision"],
  "criteria": {
    "level_1_structure": {},
    "level_2_text": {},
    "level_3_execution": {},
    "level_4_context": {},
    "level_5_ux_tone": {}
  }
}
```
