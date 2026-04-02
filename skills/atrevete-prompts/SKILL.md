---
name: atrevete-prompts
description: >
  Atrévete Bot prompt editing gateway — file map, token budgets, and anti-patterns.
  Trigger: When editing, reviewing, or creating any file under agent/prompts/**/*.md.
metadata:
  author: atrevete-bot
  version: "1.0"
  scope: [root, agent]
  auto_invoke:
    - "Editing agent system prompts"
    - "Modifying files in agent/prompts/"
    - "Working on prompt .md files"
    - "Creating new prompt module"
    - "Reviewing prompt quality"
    - "Working on system prompts"
    - "Modifying core prompt rules"
    - "Modifying mode prompt instructions"
    - "Editing identity.md or critical_rules.md"
---

## When to Use This Skill

Load this skill **before** editing any file under `agent/prompts/**/*.md`.

It answers:
1. **Where does this rule belong?** → Canonical Location Map
2. **Am I over budget?** → Token Budgets table
3. **Am I making a classic mistake?** → Anti-Patterns

Do NOT skip this skill — prompt degradation is cumulative and hard to reverse.

---

## Prompt Assembly Architecture

The assembly pipeline in `agent/prompts/loader.py`:

```
shared/identity.md
  → shared/critical_rules.md
  → shared/glossary.md
  → [MODE OVERLAY if applicable]
  → dynamic_context (injected by loader.py)
```

**Key points**:
- All `.md` files are cached at startup with 10-minute TTL
- `loader.py:get_system_prompt()` concatenates shared/ files
- Mode overlays (optional) append mode-specific instructions
- Changes require cache clear (`loader.clear_prompt_cache()`) or service restart

---

## Canonical Location Map

Each rule/instruction type has exactly ONE canonical home.

| Rule / Instruction Type | Canonical File | Notes |
|-------------------------|----------------|-------|
| Agent identity, name, personality | `shared/identity.md` | Single source of truth |
| Rules that MUST NEVER be broken | `shared/critical_rules.md` | Hard constraints only |
| Business terms, service glossary | `shared/glossary.md` | Definitions and synonyms |
| Mode-specific flow | `modes/{mode}.md` | GREETING, BOOKING, GENERAL, ESCALATION |
| Cancellation handling | `cancellation.md` | Standalone cancellation flow |
| Conversation summary | `summarization_prompt.md` | Summarization logic |
| Legacy monolithic prompt | `maite_system_prompt.md` | **DEPRECATED** — do not edit |

**PROHIBITED duplications**:
- Identity rules outside `shared/identity.md`
- Critical rules in mode files → use `shared/critical_rules.md`

---

## Token Budgets

Token estimate: `len(content) // 4` (proxy — real GPT tokens ≈ words × 1.3)

| File | Token Budget | Chars (actual) | Purpose |
|------|-------------|----------------|---------|
| `shared/identity.md` | ≤350 | ≤1,400 | Who is Maite — currently ~301t |
| `shared/critical_rules.md` | ≤1,100 | ≤4,400 | Hard constraints — currently ~1,056t |
| `shared/glossary.md` | N/A | N/A | **NOT loaded at runtime** — developer reference only |
| `modes/greeting.md` | ≤280 | ≤1,120 | First contact — currently ~232t |
| `modes/booking.md` | ≤1,800 | ≤7,200 | Booking flow (8-step + errors) — currently ~1,734t |
| `modes/general.md` | ≤450 | ≤1,800 | FAQs — currently ~443t |
| `modes/escalation.md` | N/A | N/A | **NOT loaded at runtime** — FSM in Python, doc only |
| **RUNTIME TOTAL** | **≤3,980** | **≤15,920** | shared/ + active mode overlay |

> **Note on `modes/booking.md`**: This file has a higher budget than other modes because it covers an 8-step flow with error handling, date parsing, and upsell logic. The 1,800t ceiling reflects the minimum after a full deduplication pass (April 2026). Do NOT compress below ~1,500t without a dedicated exploration — further cuts risk behavioral regressions on Steps 4–8.

> **Note on `glossary.md` and `escalation.md`**: These files are **never injected into the LLM context**. `glossary.md` is excluded by `loader.py` (tools serve the service catalog). `escalation.md` is never loaded because EscalationMode is a deterministic Python FSM. Edits to these files have zero runtime impact.

**Measure current size**:
```bash
python3 -c "print(len(open('agent/prompts/modes/booking.md').read()) // 4)"
```

---

## Pre-Edit Checklist

**MANDATORY before any change to `agent/prompts/`**:

1. **Load this skill** — Read fully
2. **Locate canonical file** — Use map above
3. **Measure tokens** — `python -c "print(len(open('PATH').read()) // 4)"`
4. **Check for duplicates** — `rg "your rule" agent/prompts/`
5. **Measure after edit** — Confirm within budget
6. **Clear cache** — Test with fresh load

---

## Anti-Patterns

### AP-1: Editing maite_system_prompt.md

❌ **This file is DEPRECATED** (28KB legacy monolith)

**Why harmful**: It's not used by the v6.0 loader. Changes here have no effect.

**Rule**: Edit `shared/*.md` and `modes/*.md` instead.

---

### AP-2: Duplicate Rules

❌ Same rule in `shared/critical_rules.md` AND `modes/booking.md`

**Why harmful**: Creates contradictions when rules diverge.

**Rule**: One canonical location per rule type.

---

### AP-3: Hardcoded Context

❌ `El cliente se llama Juan` in `.md` files

**Why harmful**: Context is dynamic via `dynamic_context.py`.

**Rule**: Never hardcode client data in prompt files.

---

### AP-4: Legacy Step Files

❌ Editing `legacy/step*.md` files

**Why harmful**: These are archived FSM prompts, not used in v6.0.

**Rule**: Do not touch `legacy/` directory.

---

### AP-5: Forgetting Cache Clear

❌ Edit prompt → test immediately → "nothing changed!"

**Why harmful**: 10-minute cache TTL means changes don't reflect immediately.

**Rule**: After prompt edits, run `loader.clear_prompt_cache()` or restart agent.

---

## Critical Rules

1. ✅ ALWAYS load `atrevete-prompts` skill before editing prompts
2. ✅ ALWAYS check Canonical Location Map
3. ✅ ALWAYS measure tokens before/after edit
4. ✅ NEVER edit `maite_system_prompt.md` (deprecated)
5. ✅ NEVER edit `legacy/*.md` files (archived)
6. ✅ NEVER hardcode client/context data in `.md` files
7. ❌ NEVER duplicate rules across files
8. ❌ NEVER commit without clearing cache and testing

---

## Resources

- **Prompt files**: `agent/prompts/` (`shared/` + `modes/`)
- **Assembly logic**: `agent/prompts/loader.py`
- **Dynamic context**: `agent/prompts/dynamic_context.py`
- **Cache control**: `loader.clear_prompt_cache()`
- **Architecture**: `agent/AGENTS.md` → Prompt System section
- **Related skill**: [`atrevete-agent`](./atrevete-agent/SKILL.md) — agent architecture