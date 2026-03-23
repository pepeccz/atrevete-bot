# QA Trace Output Format

## Overview

This document defines the trace report format that the tester sub-agent produces at the end of a conversational QA session. The sub-agent no longer returns JSON per turn -- it runs the full conversation loop and returns a COMPLETE markdown trace as its final output.

The trace serves as both the test result and the audit trail. The orchestrator can parse it for pass/fail decisions, bug counts, and performance metrics.

## Trace Structure

```markdown
# QA Trace: {flow_id}

## Metadata
- **Persona**: {persona_name} ({persona_role})
- **Flow**: {flow_id}
- **Conversation ID**: {conversation_id}
- **Total Turns**: {N}
- **Result**: {result_status}
- **Bugs Found**: {bug_count}
- **Avg Latency**: {avg_latency_ms}ms

## Conversation

| Turn | Speaker | Message | Milestone | Bugs | Latency |
|------|---------|---------|-----------|------|---------|
| ... | ... | ... | ... | ... | ... |

## Bugs

{bug_details_or_none}

## Agent State (Final)

```json
{final_state_json}
```

## Summary

{summary_text}
```

## Field Definitions

### Metadata Fields

| Field | Type | Description |
|-------|------|-------------|
| `Persona` | string | Display name and role, e.g. `Maria Garcia (new_client)` |
| `Flow` | string | The `flow_id` being tested, e.g. `new-booking` |
| `Conversation ID` | UUID | The unique conversation ID used for all CLI calls |
| `Total Turns` | integer | Number of user-bot turn pairs completed |
| `Result` | enum | Final outcome (see Result Status below) |
| `Bugs Found` | integer | Total count of bugs detected across all turns |
| `Avg Latency` | integer | Average bot response time in milliseconds |

### Result Status

| Value | Meaning |
|-------|---------|
| `completed` | Flow reached its final milestone successfully |
| `escalated` | Human handoff occurred (may or may not be expected) |
| `stuck` | Bot entered a loop or stopped progressing |
| `error` | Agent error (timeouts, crashes, tool failures) |
| `max_turns` | Hit the 20-turn safety limit without completion |
| `infra_error` | Infrastructure failure (Redis down, agent not running) |

### Conversation Table

Each turn pair produces TWO rows: one for the user message, one for the bot response.

| Column | Description |
|--------|-------------|
| Turn | Turn number (1-based). Both user and bot rows share the same turn number |
| Speaker | `User` or `Bot` |
| Message | The actual message text (truncate to ~100 chars in table, full text in bugs section if needed) |
| Milestone | Milestone ID reached on this turn, or `--` if none |
| Bugs | Comma-separated bug category shortcodes, or `--` if none |
| Latency | Bot response time (only on Bot rows), or `--` for User rows |

### Bug Detail Section

Each bug gets its own subsection:

```markdown
### Bug {N}: {category}
- **Turns**: {turn_numbers}
- **Evidence**: {description of what went wrong with quotes from the conversation}
- **Severity**: {low | medium | high | critical}
```

**Severity guidelines**:

| Severity | Criteria |
|----------|----------|
| `critical` | Booking made with wrong data, hallucinated service/stylist booked |
| `high` | Context loss that blocks the flow, ignored preference that changes the outcome |
| `medium` | Redundant questions, minor context loss that doesn't block flow |
| `low` | Tone issues, slightly awkward phrasing, cosmetic language mixing |

### Agent State (Final)

The JSON output from `qa_turn_helper.py state` at the end of the conversation. Always captured before producing the trace. Structure:

```json
{
  "has_checkpoint": true,
  "current_mode": "BOOKING",
  "mode_context": {},
  "customer_name": "Maria Garcia",
  "is_first_interaction": false,
  "error_count": 0,
  "mode_history": ["GREETING", "BOOKING"]
}
```

### Summary

A 1-2 sentence human-readable summary covering:
- Whether the flow completed as expected
- Key bugs found (if any)
- Any notable observations (unusual latency, unexpected mode transitions, etc.)

## Example: Successful Booking Flow

```markdown
# QA Trace: new-booking

## Metadata
- **Persona**: Maria Garcia (new_client)
- **Flow**: new-booking
- **Conversation ID**: a1b2c3d4-e5f6-7890-abcd-ef1234567890
- **Total Turns**: 7
- **Result**: completed
- **Bugs Found**: 0
- **Avg Latency**: 1150ms

## Conversation

| Turn | Speaker | Message | Milestone | Bugs | Latency |
|------|---------|---------|-----------|------|---------|
| 1 | User | Hola, buenas tardes, quiero pedir una cita | -- | -- | -- |
| 1 | Bot | Hola! Bienvenida a Atrevete. Como te llamas? | greeting_done | -- | 1320ms |
| 2 | User | Me llamo Maria Garcia | -- | -- | -- |
| 2 | Bot | Encantada Maria! Que servicio te gustaria? | name_collected | -- | 980ms |
| 3 | User | Quiero un corte de cabello y un tinte por favor | -- | -- | -- |
| 3 | Bot | Perfecto! Corte y tinte para dama. Queres agregar algo mas? | service_resolved | -- | 1100ms |
| 4 | User | No gracias, solo eso | -- | -- | -- |
| 4 | Bot | Dale! Tenes preferencia de estilista? | addons_handled | -- | 890ms |
| 5 | User | No, cualquiera esta bien | -- | -- | -- |
| 5 | Bot | Te muestro los horarios disponibles para esta semana... Jueves 10:00 con Luciana? | stylist_resolved | -- | 1450ms |
| 6 | User | El jueves me viene bien, si | -- | -- | -- |
| 6 | Bot | Perfecto! Te confirmo: Corte + Tinte, jueves 10:00 con Luciana. Confirmas? | slot_resolved | -- | 1200ms |
| 7 | User | Si, confirmo la cita | -- | -- | -- |
| 7 | Bot | Listo! Tu cita quedo confirmada. Te esperamos el jueves! | booking_completed | -- | 1110ms |

## Bugs

No bugs detected.

## Agent State (Final)

```json
{
  "has_checkpoint": true,
  "current_mode": "BOOKING",
  "mode_context": {"booking_confirmed": true},
  "customer_name": "Maria Garcia",
  "is_first_interaction": false,
  "error_count": 0,
  "mode_history": ["GREETING", "BOOKING"]
}
```

## Summary

Flow completed successfully in 7 turns. New client Maria Garcia booked corte + tinte for Thursday with no issues. Average latency 1150ms within acceptable range.
```

## Example: Trace With Bugs

```markdown
# QA Trace: returning-booking

## Metadata
- **Persona**: Carlos Ruiz (returning_client)
- **Flow**: returning-booking
- **Conversation ID**: f9e8d7c6-b5a4-3210-fedc-ba9876543210
- **Total Turns**: 9
- **Result**: completed
- **Bugs Found**: 2
- **Avg Latency**: 1380ms

## Conversation

| Turn | Speaker | Message | Milestone | Bugs | Latency |
|------|---------|---------|-----------|------|---------|
| 1 | User | Hola, quiero reservar mi corte de siempre | -- | -- | -- |
| 1 | Bot | Hola! Bienvenido a Atrevete. Como te llamas? | greeting_done | -- | 1200ms |
| 2 | User | Soy Carlos Ruiz, ya soy cliente | -- | -- | -- |
| 2 | Bot | Hola Carlos! Que servicio te gustaria? | name_collected | -- | 950ms |
| 3 | User | El de siempre, corte de caballero | -- | -- | -- |
| 3 | Bot | Corte de caballero, perfecto! Es para caballero, verdad? | -- | redundant | 1100ms |
| 4 | User | Si, de caballero, ya te lo dije | -- | -- | -- |
| 4 | Bot | Perfecto! Algun servicio adicional? | service_resolved | -- | 880ms |
| 5 | User | No, solo el corte | -- | -- | -- |
| 5 | Bot | Tenes preferencia de estilista? | addons_handled | -- | 920ms |
| 6 | User | El que tenga antes | -- | -- | -- |
| 6 | Bot | Lunes 11:00 con Sofia. Te queda bien? | stylist_resolved | -- | 1650ms |
| 7 | User | Dale, perfecto | -- | -- | -- |
| 7 | Bot | Como te llamas para la reserva? | -- | context_loss | 1400ms |
| 8 | User | Ya te dije, Carlos Ruiz | -- | -- | -- |
| 8 | Bot | Perdon Carlos! Confirmas corte caballero lunes 11:00 con Sofia? | slot_resolved | -- | 1300ms |
| 9 | User | Si, confirmado | -- | -- | -- |
| 9 | Bot | Listo! Tu cita quedo confirmada. Nos vemos el lunes! | booking_completed | -- | 1020ms |

## Bugs

### Bug 1: redundant_question
- **Turns**: 3
- **Evidence**: User said "corte de caballero" on turn 3. Bot asked "es para caballero, verdad?" on the same turn despite the user being explicit.
- **Severity**: medium

### Bug 2: context_loss
- **Turns**: 2, 7
- **Evidence**: User provided name "Carlos Ruiz" on turn 2. Bot asked "como te llamas para la reserva?" on turn 7, forgetting the name.
- **Severity**: high

## Agent State (Final)

```json
{
  "has_checkpoint": true,
  "current_mode": "BOOKING",
  "mode_context": {"booking_confirmed": true},
  "customer_name": "Carlos Ruiz",
  "is_first_interaction": false,
  "error_count": 0,
  "mode_history": ["GREETING", "BOOKING"]
}
```

## Summary

Flow completed in 9 turns (expected ~6). Two bugs found: a redundant clarification question about service gender (medium) and a name context loss on turn 7 that forced the user to repeat their name (high severity). Both suggest state management issues in the booking mode.
```

## Parsing the Trace Programmatically

The trace is designed for human readability first, but can be parsed:

- **Metadata**: Regex on `- **{Key}**: {value}` lines.
- **Result**: Extract from `- **Result**: {value}` -- one of the enum values above.
- **Bug count**: Extract from `- **Bugs Found**: {N}` or count `### Bug N:` headers.
- **Pass/fail heuristic**: `result == "completed" && bugs_found == 0` is a clean pass. `result == "completed" && bugs_found > 0` is a pass with issues. Anything else is a failure.

The orchestrator can use these heuristics to decide whether to flag the run for human review.
