# Documentation Update Checklist

Use this checklist when making code changes to ensure documentation stays synchronized.

---

## 📋 Quick Decision Tree

### Did you change architecture/concepts?
→ Update: `QUICK-CONTEXT.md`, `CLAUDE.md`, `CHANGELOG.md`

### Did you add/modify/remove code?
→ Update: `CHANGELOG.md`, `04-implementation/current-state.md`

### Did you add/move files?
→ Update: `04-implementation/components-map.md`

### Did you change state schema?
→ Update: `QUICK-CONTEXT.md`, `CLAUDE.md`, `04-implementation/current-state.md`

### Did you change tools?
→ Update: `QUICK-CONTEXT.md`, `CLAUDE.md`, `04-implementation/components-map.md`

### Did you change configuration?
→ Update: `CLAUDE.md`, `04-implementation/current-state.md`

---

## 🎯 By Change Type

### Feature Addition

**ALWAYS update:**
- [ ] `docs/CHANGELOG.md` - Add entry with context
- [ ] `04-implementation/current-state.md` - Update "Fully Implemented" section
- [ ] `04-implementation/components-map.md` - Add new component locations

**Update if relevant:**
- [ ] `docs/QUICK-CONTEXT.md` - If changes key concepts
- [ ] `../CLAUDE.md` - If changes development workflow
- [ ] `docs/README.md` - If adds new documentation
- [ ] `03-features/[feature]/` - Create feature docs

**Example:**
```
Added new tool `search_services`
→ CHANGELOG: Entry with tool purpose
→ current-state: Add to "8 Consolidated Tools" list
→ components-map: Add row in Tools table
→ QUICK-CONTEXT: Update tool count (7 → 8)
→ CLAUDE.md: Update "Tools (agent/tools/)" section
```

---

### Bug Fix

**ALWAYS update:**
- [ ] `docs/CHANGELOG.md` - Brief entry with severity

**Update if significant:**
- [ ] `04-implementation/current-state.md` - Remove from "Known Issues" if listed

**Example:**
```
Fixed service_resolver.py price_euros reference
→ CHANGELOG: Entry with bug severity and impact
→ current-state: (no update needed, not in Known Issues)
```

---

### Refactoring / Optimization

**ALWAYS update:**
- [ ] `docs/CHANGELOG.md` - Entry with metrics (before/after)
- [ ] `04-implementation/current-state.md` - Update "Performance Metrics"

**Update if relevant:**
- [ ] `docs/QUICK-CONTEXT.md` - If changes architecture
- [ ] `04-implementation/components-map.md` - If files moved
- [ ] `../CLAUDE.md` - If changes patterns

**Example:**
```
v3.2 Prompt Optimization
→ CHANGELOG: Detailed entry with cost savings
→ current-state: Update "Performance Metrics" table
→ QUICK-CONTEXT: Update metrics section
```

---

### Architecture Change

**ALWAYS update:**
- [ ] `docs/CHANGELOG.md` - Detailed entry
- [ ] `docs/QUICK-CONTEXT.md` - Update architecture section
- [ ] `../CLAUDE.md` - Update "Architecture Overview"
- [ ] `04-implementation/current-state.md` - Update entire document

**Update if relevant:**
- [ ] `04-implementation/components-map.md` - Reorganize structure
- [ ] `docs/README.md` - Update navigation
- [ ] `01-core/architecture.md` - Major section rewrite

**Example:**
```
Eliminated payment system
→ CHANGELOG: Epic-level entry (11 phases)
→ QUICK-CONTEXT: Remove payment references
→ CLAUDE.md: Add "no payment" notes
→ current-state: Update all sections
→ components-map: Remove payment tool rows
```

---

### Configuration Change

**ALWAYS update:**
- [ ] `docs/CHANGELOG.md` - Entry
- [ ] `../CLAUDE.md` - Update config section
- [ ] `04-implementation/current-state.md` - Update "Configuration Requirements"

**Update if relevant:**
- [ ] `docs/QUICK-CONTEXT.md` - If changes external dependencies

**Example:**
```
Migrated from Anthropic to OpenRouter
→ CHANGELOG: Entry with API change
→ CLAUDE.md: Update config.py example (ANTHROPIC_API_KEY → OPENROUTER_API_KEY)
→ current-state: Update env vars section
→ QUICK-CONTEXT: Update "External Dependencies"
```

---

### State Schema Change

**ALWAYS update:**
- [ ] `docs/CHANGELOG.md` - Entry
- [ ] `../CLAUDE.md` - Update "State Schema" section
- [ ] `04-implementation/current-state.md` - Update state schema details
- [ ] `docs/QUICK-CONTEXT.md` - Update ConversationState fields count

**Example:**
```
Added v3.2 tracking fields (service_selected, slot_selected, etc.)
→ CHANGELOG: Entry with new fields
→ CLAUDE.md: Update field count (15 → 19)
→ current-state: Update state schema list
→ QUICK-CONTEXT: Update "ConversationState (19 fields)"
```

---

### Test Addition/Removal

**Update if significant:**
- [ ] `04-implementation/current-state.md` - Update test count/coverage
- [ ] `docs/CHANGELOG.md` - Entry if major test suite change

**Example:**
```
Removed payment tests (200+ lines)
→ CHANGELOG: Entry as part of payment elimination
→ current-state: Note in "Testing" section
```

---

### File Move/Rename

**ALWAYS update:**
- [ ] `04-implementation/components-map.md` - Update all file paths
- [ ] `docs/CHANGELOG.md` - Entry

**Update if relevant:**
- [ ] `docs/README.md` - Update navigation links
- [ ] All docs with links to moved file

**Example:**
```
Moved Funcionalidades/agendar-cita.md → 03-features/booking/flow.md
→ components-map: Update path in relevant tables
→ CHANGELOG: Brief entry
→ README: Update link
```

---

## 🔍 Verification Checklist

After updating docs:

- [ ] All links work (no broken internal links)
- [ ] Markdown renders correctly
- [ ] Code examples are correct
- [ ] Timestamps updated (Last Updated: YYYY-MM-DD)
- [ ] CHANGELOG entry is chronologically correct (newest first)
- [ ] Line numbers in components-map are accurate
- [ ] No outdated information remains

---

## 🤖 Automated Checks (Future)

**Script:** `scripts/update-docs.py` will automate:
- Generating CHANGELOG entries
- Updating timestamps
- Suggesting which docs to update based on changed files
- Validating links

**Usage:**
```bash
python scripts/update-docs.py
# Interactive prompts guide you through updates
```

---

## 📝 Documentation Principles

1. **CHANGELOG is mandatory** - Every significant change gets an entry
2. **Be specific** - Use file paths and line numbers
3. **Explain WHY, not just WHAT** - Context matters
4. **Quantify impact** - Metrics > vague statements
5. **Update immediately** - Don't defer documentation
6. **Link related docs** - Cross-reference for navigation

---

Last updated: 2025-11-13
