---
name: atrevete-qa-evaluator
description: >
  Evaluates conversational QA traces against Atrévete Bot's five-level quality pyramid.
  Trigger: When evaluating a QA conversation, scoring a conversational flow, or generating a QA report.
license: MIT
metadata:
  author: atrevete-bot
  version: "1.0"
  scope: [root]
  auto_invoke:
    - "Evaluating a QA conversation"
    - "Scoring a conversational flow"
    - "Generating a QA report"
---

## Purpose

Score a captured conversation trace across the five QA levels and produce an actionable report.

## Level Definitions

1. `Structure` - deterministic: response exists, usable text, no internal errors.
2. `Text` - rubric: coherent Spanish, answers the user's intent, avoids hallucinations.
3. `Execution` - deterministic: expected flow markers, state flags, and step progression.
4. `Context` - deterministic: name, service, and booking progress persist across turns.
5. `UX/Tone` - rubric: natural, warm, not robotic, brand-appropriate style.

## Execution Steps

1. Read the conversation trace and expected flow.
2. Evaluate Level 1 first and stop escalation of confidence if it fails.
3. Evaluate Levels 2 and 5 with explicit rubric evidence.
4. Evaluate Levels 3 and 4 using deterministic checks against final state and flow expectations.
5. Determine business completion independently from stylistic quality.
6. Return a structured report with scores, failed checks, evidence, and recommended fixes.

## Report Format

```json
{
  "overall_pass": true,
  "levels": {
    "level_1_structure": {"pass": true, "score": 1.0, "evidence": "..."},
    "level_2_text": {"pass": true, "score": 0.9, "evidence": "..."},
    "level_3_execution": {"pass": true, "score": 1.0, "evidence": "..."},
    "level_4_context": {"pass": true, "score": 1.0, "evidence": "..."},
    "level_5_ux_tone": {"pass": true, "score": 4.0, "evidence": "..."}
  },
  "business_completion": {"goal_achieved": true},
  "failed_checks": [],
  "recommended_fixes": []
}
```

## Rules

- Mention whether each level is deterministic or rubric-based.
- Provide concrete evidence for every failed or partial check.
- Do not claim business completion unless the trace or final state supports it.
- Keep recommendations tied to the failed level so they can feed a later SDD fix.

## Usage Example

Use this skill after `atrevete-qa-tester` returns a trace for flows like `booking_complete`, `returning_client`, `escalation`, or `indecision`.
