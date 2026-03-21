# Design: Greeting duplication and action narration fix

## Architecture Decision

### Problem
Greeting duplication occurs because:
1. Code-level introduction (`FIRST_TURN_INTRO` in `agent/modes/base.py:63`) is prepended to responses
2. LLM is prompted to generate a greeting (in `agent/prompts/modes/greeting.md:11`)
3. Both sources produce greeting text, causing duplication like: "¡Hola! 🌸 Soy Maite... ¡Hola! ¿En qué puedo ayudarte?"

Additionally, action narration appears when the LLM generates phrases like "Voy a buscar horarios..." or "Déjame consultar..." before executing tools, violating the principle that tools should be called silently and only results presented.

### Solution
Establish single source of truth for greetings:
- Keep legal disclosure in code (`FIRST_TURN_INTRO`)
- Remove greeting generation request from GREETING mode prompt
- Have LLM focus only on help question ("¿En qué puedo ayudarte?")
- Implement runtime guard to strip future-action narration from all LLM responses

### Why This Approach
- **Simplicity**: Single source eliminates coordination between code and prompts
- **Maintainability**: Changes only needed in one place (prompt or code)
- **Correctness**: Legal disclosure guaranteed by code, not dependent on prompt adherence
- **Prevention**: Runtime guard catches edge cases where narration slips through

### Alternative Considered and Rejected
**Keep both sources but filter duplicates in prompt**: Rejected because:
- Increases prompt complexity
- Requires sophisticated string matching in LLM instructions
- Still relies on LLM to follow complex filtering instructions
- Doesn't address action narration problem
- Less reliable than code-level guarantee

## Greeting Assembly Changes

### Current Flow
1. `base.py:257` - `_maybe_prepend_intro()` adds `FIRST_TURN_INTRO` if not already sent
2. `greeting_mode.py` - Uses prompt that instructs LLM to "empiece directamente con el saludo cálido"
3. Result: Code prefix + LLM greeting = duplication

### New Flow
1. `base.py:257` - `_maybe_prepend_intro()` adds `FIRST_TURN_INTRO` if not already sent
2. `greeting_mode.py` - Prompt asks for direct help question (no greeting instruction)
3. Result: Code prefix + help question = single proper greeting

### Code Change Required
In `agent/prompts/modes/greeting.md`:
- Line 11: Change "empiece directamente con el saludo cálido y la oferta de ayuda" 
- To: "empiece directamente con una pregunta de ayuda, no con saludo"

## Prompt Changes Required

### Files to Modify

#### 1. `agent/prompts/modes/greeting.md`
- Line 11: Remove "empiece directamente con el saludo cálido"
- Change to: "empiece directamente con una pregunta de ayuda, no con saludo"

#### 2. `agent/prompts/shared/identity.md`
- Remove example showing "¡Hola! 🌸 Soy Maite..." (lines 132-134)
- Keep example showing direct help question (current line 133: "¿En qué puedo ayudarte hoy?")

#### 3. `agent/prompts/general.md`
- Lines 95-106: Remove greeting examples that include "Soy Maite, la asistenta virtual"
- Replace with examples starting directly with help/questions

#### 4. `agent/prompts/shared/recovery.md`
- Line 396: Remove "Déjame buscar horarios..." (part of example in lines 390-397)
- Replace with: "Los horarios disponibles son..."

#### 5. `agent/prompts/shared/critical_rules.md`
- Line 9: Strengthen rule with clearer example
- Add example showing correct vs incorrect narration

## Runtime Guard Implementation

### Location Options
1. **Preferred**: `agent/modes/base.py:260` (after `_run_agentic_loop()` but before returning)
2. **Alternative**: `agent/prompts/loader.py` (after final response text finalized)

### Function Signature
```python
def _strip_future_action_narration(text: str) -> str:
    """Remove phrases like 'Voy a', 'Déjame', 'Ahora voy a' that narrate upcoming tool calls."""
    patterns = [
        r"Ahora,?\s+(déjame|voy a|vamos a).*?\.",  # "Ahora, déjame buscar..."
        r"^Voy a.*?\.\s+",  # "Voy a... [results]"
        r"^Déjame.*?\.\s+",  # "Déjame... [results]"
    ]
    result = text
    for pattern in patterns:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE | re.MULTILINE)
    return result.strip()
```

### Call Location
In `agent/modes/base.py`, after line 350 in `_run_agentic_loop()`:
```python
# After sanitizing response but before returning
response_text = self._strip_future_action_narration(response_text)
return AgenticLoopResult(
    response_text=response_text,
    tool_results=tool_results,
)
```

## Edge Cases Handled

### Legitimate Escalation
Phrases like "Voy a contactar al equipo" should NOT be filtered when:
- They represent the actual next step in conversation
- No tool execution is implied or expected
- Solution: Only filter when followed by tool results or clearly narrating imminent tool use

### User-Facing Reassurance
Some "voy a" phrases are legitimate user reassurance:
- "Voy a dejarte algunas opciones" (when presenting options)
- "Voy a explicarte cómo funciona" (when providing information)
- Solution: Context-aware filtering - only remove when clearly narrating tool execution that follows

### False Positives
Phrases like "Voy a dejarte opciones" when presenting the main response:
- Solution: Make patterns specific to narration patterns that precede tool results
- Require clear separation between narration and factual response

## Code Locations

### Primary Changes
1. `agent/modes/base.py:260` - Runtime guard implementation and call
2. `agent/prompts/modes/greeting.md:11` - Remove greeting instruction
3. `agent/prompts/shared/identity.md` - Update examples
4. `agent/prompts/general.md` - Update greeting examples
5. `agent/prompts/shared/recovery.md:396` - Remove narration example
6. `agent/prompts/shared/critical_rules.md:9` - Strengthen rule

### Secondary (if using loader.py approach)
- `agent/prompts/loader.py` - Alternative guard location

## Test Strategy

### Unit Tests
1. Test greeting single instance in GREETING mode (Turn 1)
2. Test absence of narration patterns in booking/general responses
3. Test idempotency: guard doesn't break legitimate copy
4. Test edge cases: escalation copy preservation, user-facing reassurance

### Integration Tests
1. Verify Luis Turn 1 has exactly one "¡Hola!" (no duplication)
2. Verify Carlos Turn 3 has no "Ahora, déjame..." or similar narration
3. Test that tool results still appear correctly after narration stripping
4. Verify legal disclosure still appears on first turn

### Specific Test Cases
- Input: "Hola" → Output: "¡Hola! 🌸 Soy Maite... ¿En qué puedo ayudarte?" (single greeting)
- Input: "Quiero pedir cita" → Output: No narration like "Voy a buscar..." before showing services
- Input: "¿Qué servicios tienen?" → Output: Direct service list without "Déjame consultar..."

## Backward Compatibility

### No Breaking Changes
- ✅ No DB schema changes required
- ✅ No state modifications needed
- ✅ No changes to tool interfaces or signatures
- ✅ No changes to mode transitions or graph structure

### Potential Test Updates
- Existing tests may need minor updates if they assert on exact response text
- Tests checking for specific greeting phrases should be updated
- No changes needed to business logic or data flow

### API Compatibility
- No changes to FastAPI endpoints
- No changes to webhook handling
- No changes to Redis message formats