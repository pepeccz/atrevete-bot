# LLM Turn Response Schema

## Overview

This document defines the JSON schema that the LLM MUST return on every turn of a QA conversation. The schema maps directly to the `LLMTurnResponse` dataclass in `tests/e2e/harness/run_models.py`.

## Schema

```json
{
  "reply": "string (required)",
  "flow_status": "string enum (required)",
  "milestone_reached": "string | null (required)",
  "bugs": "array of BugReport (required, may be empty)",
  "should_stop": "boolean (required)",
  "stop_reason": "string (required, empty string if should_stop=false)"
}
```

## Field Definitions

### `reply`

- **Type**: `string`
- **Required**: Yes
- **Description**: The next WhatsApp message to send to the bot, written in Spanish and matching the persona's personality and reply style.
- **Constraints**:
  - Must be non-empty
  - Must be in Spanish
  - Should be 1-2 sentences max (like a real WhatsApp message)
  - Must stay in character for the persona
  - Must NOT reveal the message is from a test agent

### `flow_status`

- **Type**: `string` (enum)
- **Required**: Yes
- **Valid values**:

| Value | Meaning | When to Use |
|-------|---------|-------------|
| `in_progress` | Conversation is advancing normally | Default for most turns |
| `completed` | The flow's completion condition has been met | Bot confirmed booking, escalation resolved, etc. |
| `escalated` | Human handoff occurred or was committed to | Bot offered human contact AND persona accepted |
| `stuck` | Bot is looping, confused, or not progressing | Same question repeated 3+ times, nonsensical replies |

### `milestone_reached`

- **Type**: `string | null`
- **Required**: Yes
- **Description**: The `id` of the milestone that was reached or advanced during THIS turn. Set to `null` if no new milestone was reached.
- **Valid values**: Must be one of the milestone IDs defined in the flow, or `null`.
- **Examples**:
  - `"greeting_done"` — bot greeted and user expressed intent
  - `"service_resolved"` — service type was confirmed
  - `"stylist_resolved"` — stylist was selected
  - `"booking_completed"` — booking was confirmed and persisted
  - `null` — turn was a continuation within the same milestone

### `bugs`

- **Type**: `array` of `BugReport` objects
- **Required**: Yes (use empty array `[]` if no bugs detected)
- **Description**: Semantic issues detected in the bot's reply that keyword matching would miss.

#### BugReport Object

```json
{
  "category": "string enum (required)",
  "evidence": "string (required)",
  "turns": "array of integers (required)"
}
```

**`category`** — one of:

| Category | Description |
|----------|-------------|
| `redundant_question` | Bot re-asks information the user already provided |
| `ignored_preference` | Bot ignores a preference the user explicitly stated |
| `context_loss` | Bot forgets information from earlier in the conversation |
| `hallucination` | Bot mentions services, stylists, or prices that don't exist |
| `wrong_language` | Bot responds in a language other than Spanish |

**`evidence`** — a brief human-readable explanation of what went wrong. Should reference the specific content that triggered the bug detection.

**`turns`** — array of turn numbers involved in the bug. For `redundant_question`, include both the turn where info was first given and the turn where it was re-asked.

### `should_stop`

- **Type**: `boolean`
- **Required**: Yes
- **Description**: Whether the LLM believes the conversation should terminate after this turn.
- **Set to `true` when**:
  - The flow's completion condition is met (e.g., booking confirmed)
  - Escalation was accepted by the persona
  - The bot is completely stuck and further turns won't help
- **Set to `false` when**:
  - The conversation is still progressing normally
  - More information exchange is needed

**Important**: This is a SUGGESTION to the script layer. Scripts enforce hard limits (max turns, timeout, dead loop) independently. The LLM's `should_stop` only signals semantic completion.

### `stop_reason`

- **Type**: `string`
- **Required**: Yes
- **Description**: Explanation of why the conversation should stop. Must be an empty string `""` when `should_stop` is `false`.
- **Examples**:
  - `"Booking confirmed by bot, appointment details provided"`
  - `"Human handoff accepted, escalation complete"`
  - `"Bot stuck in loop asking same question for 3 turns"`
  - `""` (when `should_stop` is `false`)

## Examples

### Normal booking turn (in progress)

```json
{
  "reply": "Para dama, por favor.",
  "flow_status": "in_progress",
  "milestone_reached": "service_resolved",
  "bugs": [],
  "should_stop": false,
  "stop_reason": ""
}
```

### Turn with bug detected

```json
{
  "reply": "Ya te dije, para dama.",
  "flow_status": "in_progress",
  "milestone_reached": null,
  "bugs": [
    {
      "category": "redundant_question",
      "evidence": "User said 'corte para dama' on turn 2, bot asked 'es para dama o caballero?' on turn 4",
      "turns": [2, 4]
    }
  ],
  "should_stop": false,
  "stop_reason": ""
}
```

### Booking completed

```json
{
  "reply": "Perfecto, muchas gracias!",
  "flow_status": "completed",
  "milestone_reached": "booking_completed",
  "bugs": [],
  "should_stop": true,
  "stop_reason": "Booking confirmed by bot with appointment details"
}
```

### Escalation accepted

```json
{
  "reply": "Si, prefiero hablar con alguien del equipo.",
  "flow_status": "escalated",
  "milestone_reached": "escalation_completed",
  "bugs": [],
  "should_stop": true,
  "stop_reason": "Human handoff accepted, bot confirmed follow-up"
}
```

### Indecisive client asking questions

```json
{
  "reply": "Mmm, no estoy seguro. Que me recomendas para un cambio de look?",
  "flow_status": "in_progress",
  "milestone_reached": "discovery_started",
  "bugs": [],
  "should_stop": false,
  "stop_reason": ""
}
```

### Multiple bugs in one turn

```json
{
  "reply": "Quiero con Luciana, ya te lo dije.",
  "flow_status": "in_progress",
  "milestone_reached": null,
  "bugs": [
    {
      "category": "ignored_preference",
      "evidence": "User requested Luciana on turn 3, bot assigned Sofia on turn 5",
      "turns": [3, 5]
    },
    {
      "category": "context_loss",
      "evidence": "Bot asked for service type again despite confirming 'corte dama' on turn 2",
      "turns": [2, 5]
    }
  ],
  "should_stop": false,
  "stop_reason": ""
}
```

### Bot stuck in a loop

```json
{
  "reply": "Es para dama, ya te lo dije tres veces.",
  "flow_status": "stuck",
  "milestone_reached": null,
  "bugs": [
    {
      "category": "redundant_question",
      "evidence": "Bot asked 'dama o caballero' on turns 3, 5, and 7 despite user answering each time",
      "turns": [3, 5, 7]
    }
  ],
  "should_stop": true,
  "stop_reason": "Bot stuck in loop, asking same question for 3 consecutive turns"
}
```

## Mapping to Python Dataclass

The JSON response maps directly to `LLMTurnResponse` in `tests/e2e/harness/run_models.py`:

| JSON Field | Dataclass Field | Python Type |
|------------|----------------|-------------|
| `reply` | `reply` | `str` |
| `flow_status` | `flow_status` | `str` |
| `milestone_reached` | `milestone_reached` | `str \| None` |
| `bugs` | `bugs` | `list[dict[str, Any]]` |
| `should_stop` | `should_stop` | `bool` |
| `stop_reason` | `stop_reason` | `str` |

## Parsing Notes

- The LLM MUST be called with `response_format: { type: "json_object" }` to enforce valid JSON output.
- If JSON parsing fails, retry once. If it fails again, record the error and use a generic fallback reply (e.g., `"Si, dale."`) with `flow_status: "in_progress"`, no bugs, and `should_stop: false`.
- The `bugs` array uses `list[dict[str, Any]]` rather than a typed dataclass to allow flexibility for additional bug categories without code changes.
