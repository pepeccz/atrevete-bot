---
name: skill-sync
description: >
  Syncs skill metadata to AGENTS.md Auto-invoke sections.
  Trigger: When updating skill metadata, regenerating Auto-invoke tables, or after creating/modifying skills.
metadata:
  author: atrevete-bot
  version: "1.0"
  scope: [root]
  auto_invoke:
    - "After creating/modifying a skill"
    - "Regenerate AGENTS.md Auto-invoke tables"
    - "Troubleshoot missing skill in auto-invoke"
---

## Purpose

Keeps AGENTS.md Auto-invoke sections in sync with skill metadata. When you create or modify a skill, run the sync script to automatically update all affected AGENTS.md files.

## Required Skill Metadata

Each skill that should appear in Auto-invoke sections needs these fields in `metadata`:

```yaml
metadata:
  author: atrevete-bot
  version: "1.0"
  scope: [agent]                                 # Which AGENTS.md files to update
  auto_invoke: "Action that triggers this skill" # Single action
  # OR multiple actions:
  # auto_invoke:
  #   - "Working on conversation flow"
  #   - "Creating graph nodes"
```

### Scope Values

| Scope | Updates |
|-------|---------|
| `root` | `AGENTS.md` (repo root) |
| `agent` | `agent/AGENTS.md` |
| `api` | `api/AGENTS.md` |
| `database` | `database/AGENTS.md` |

Skills can have multiple scopes: `scope: [root, agent]`

---

## Usage

### After Creating/Modifying a Skill

```bash
./skills/skill-sync/assets/sync.sh
```

### What It Does

1. Reads all `skills/*/SKILL.md` files
2. Extracts `metadata.scope` and `metadata.auto_invoke`
3. Generates Auto-invoke tables for each AGENTS.md
4. Updates the `### Auto-invoke Skills` section in each file

---

## Commands

```bash
# Sync all AGENTS.md files
./skills/skill-sync/assets/sync.sh

# Dry run (show what would change)
./skills/skill-sync/assets/sync.sh --dry-run

# Sync specific scope only
./skills/skill-sync/assets/sync.sh --scope agent
```

---

## Example

Given this skill metadata:

```yaml
# skills/atrevete-agent/SKILL.md
metadata:
  author: atrevete-bot
  version: "1.0"
  scope: [root, agent]
  auto_invoke:
    - "Working on conversation flow"
    - "Creating graph nodes"
```

The sync script generates in both `AGENTS.md` and `agent/AGENTS.md`:

```markdown
### Auto-invoke Skills

| Action | Skill |
|--------|-------|
| Creating graph nodes | `atrevete-agent` |
| Working on conversation flow | `atrevete-agent` |
```

---

## Checklist After Modifying Skills

- [ ] Added `metadata.scope` to new/modified skill
- [ ] Added `metadata.auto_invoke` with action description
- [ ] Ran `./skills/skill-sync/assets/sync.sh`
- [ ] Verified AGENTS.md files updated correctly

## Anti-Patterns

### NEVER Do This

- **Don't edit Auto-invoke tables manually** - They will be overwritten by sync.sh
- **Don't forget to run sync.sh** - AGENTS.md will be out of date
- **Don't use vague auto_invoke descriptions** - Be specific about the action

### ALWAYS Do This

- Run sync.sh after ANY skill modification
- Use descriptive, action-oriented auto_invoke phrases
- Include all relevant scopes for the skill
