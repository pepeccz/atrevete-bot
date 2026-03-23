---
name: atrevete-qa-context
description: >
  Prepares QA persona and flow context for Claude Code sub-agent delegation.
  The orchestrator reads .atl/qa-testing-context.md, extracts the persona + flow
  for the requested scenario, and produces a single prompt block to pass to the
  tester sub-agent.
  Trigger: When preparing a QA testing scenario, selecting a persona, or building the tester sub-agent prompt.
license: MIT
metadata:
  author: atrevete-bot
  version: "3.0"
  scope: [root]
  auto_invoke:
    - "Preparing a QA testing scenario"
    - "Selecting a QA persona"
    - "Building tester sub-agent prompt"
---

## Purpose

Transform the shared QA context file (`.atl/qa-testing-context.md`) into a structured prompt block that the orchestrator passes to the tester sub-agent. The sub-agent never reads the context file itself -- the orchestrator resolves everything and injects it into the delegation prompt.

## Data Source

The context file lives at `.atl/qa-testing-context.md`. It uses JSON frontmatter between `---` fences and contains:

- **personas**: Keyed by `persona_id`. Each has `name`, `role`, `description`, `behavior` (list of rules), `expected_flow`, `typical_phrases` (list, in Spanish), and `phone`.
- **flows**: Keyed by `flow_id`. Each has `persona_id`, `description`, `expected_outcome`, and `steps` (ordered list with `turn`, `mode`, `user`, `expect`).
- **criteria**: Evaluation levels (optional, not passed to tester sub-agent).

The Python loader is `TestingContextManager` in `tests/e2e/harness/context_manager.py`. Key dataclasses: `Persona`, `Flow`, `FlowStep`, `QATestingContext`.

## Execution Steps (Orchestrator)

1. **Read** `.atl/qa-testing-context.md`.
2. **Identify** the requested flow (by `flow_id`). Fail if missing.
3. **Resolve** the persona attached to that flow (via `flow.persona_id`), or use an explicit override.
4. **Extract** the persona block:
   - Name, role, description
   - Behavior rules (numbered list)
   - Typical phrases (bulleted list, in Spanish)
   - Phone number (for `--phone` flag in CLI calls)
5. **Extract** the flow milestones from the flow's `steps` list:
   - Map each step to a milestone: `{turn}. {mode} -- {expect description}`
   - Mark the final step as `[COMPLETION]`
6. **Assemble** the prompt block (see Output Format below).
7. **Pass** the assembled block as part of the tester sub-agent's delegation prompt.

## Output Format

The orchestrator produces a single markdown block with these sections:

```markdown
## Persona: {persona_name}

**Role**: {role}
**Phone**: {phone}
**Description**: {description}

### Behavior Rules
1. {behavior_rule_1}
2. {behavior_rule_2}
...

### Typical Phrases
- "{phrase_1}"
- "{phrase_2}"
...

## Flow: {flow_id}

**Description**: {flow_description}
**Expected Outcome**: {expected_outcome}

### Milestones
1. {step_1_mode} -- {step_1_expect_summary}
2. {step_2_mode} -- {step_2_expect_summary}
...
N. {final_step_mode} -- {final_step_expect_summary} [COMPLETION]
```

## Rules

- Fail clearly when the context file is missing or malformed.
- Fail clearly when the requested flow or persona does not exist. List available options in the error.
- Always include ALL behavior rules and typical phrases -- do not summarize or truncate.
- Keep phone numbers exact (used as `--phone` argument in `qa_turn_helper.py`).
- The orchestrator MUST resolve persona + flow BEFORE launching the sub-agent. The sub-agent receives the assembled block, never raw file references.

## Available Personas and Flows

To list available scenarios, parse the `personas` and `flows` keys from the frontmatter. Common pairings:

| Persona | Flow | Scenario |
|---------|------|----------|
| `maria_new_client` | `new-booking` | New client books haircut + color |
| `carlos_returning_client` | `returning-booking` | Returning client, usual service |
| `ana_indecisive` | `indecision-flow` | Indecisive client, lots of questions |
| `elena_escalation` | `escalation-flow` | Frustrated client triggers escalation |

(Exact pairings depend on current `.atl/qa-testing-context.md` contents.)

## Usage Example

Orchestrator delegation prompt includes:

```
You are a QA tester sub-agent. Your job is to simulate a WhatsApp customer
interacting with the Atrevete Bot.

## Persona: Maria Garcia

**Role**: new_client
**Phone**: +34999000001
**Description**: New client who has never visited the salon before...

### Behavior Rules
1. Always greet politely before stating what you want
2. State your desired services clearly: haircut and color
...

### Typical Phrases
- "Hola, buenas tardes, quiero pedir una cita"
- "Quiero un corte de cabello y un tinte por favor"
...

## Flow: new-booking

**Description**: Complete booking flow for a new client
**Expected Outcome**: Appointment booked successfully

### Milestones
1. GREETING -- Bot greeted, user expressed booking intent
2. BOOKING -- Service type confirmed
3. BOOKING -- Stylist selected or accepted
4. BOOKING -- Date/time slot selected
5. BOOKING -- User confirmed the booking
6. BOOKING -- book() called, appointment persisted [COMPLETION]
```
