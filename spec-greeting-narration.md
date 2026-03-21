# Spec: Greeting duplication and action narration fix

## Requirements

### REQ-1: Single greeting in first turn
The first turn of any conversation must show exactly ONE greeting phrase. This should be either:
- The legal introduction (prepended in code)
- OR a warm greeting from the agent
But NOT both duplicated.

### REQ-2: No future-action narration
No response in any mode should contain phrases indicating upcoming actions like:
- "voy a"
- "déjame" 
- "ahora voy a"
Followed by narration about what the bot is about to do.

### REQ-3: Silent tool execution
Tools should be called and their results presented directly without narrating the tool call first.

### REQ-4: Clean system prompts
System prompts must not contain contradictory examples that show narration of upcoming actions.

## Scenarios

### Scenario 1: First turn greeting
**Given**: User starts conversation with "Hola"
**When**: Bot processes first message
**Then**: Bot responds with exactly one greeting like:
"¡Hola! 🌸 Soy Maite, tu asistente de belleza. ¿En qué puedo ayudarte hoy?"
**Not**: Duplicated greeting like "¡Hola! 🌸 Soy Maite... ¡Hola! Soy Maite..."

### Scenario 2: Service search
**Given**: User asks "Qué servicios tienen?"
**When**: Bot processes request in GENERAL mode
**Then**: Bot lists services directly:
"Ofrecemos: Cortes de cabello, Manicura, Pedicura, Depilación..."
**Not**: With narration like "Voy a buscar los servicios para ti. Ofrecemos..."

### Scenario 3: Booking slot inquiry
**Given**: User asks "¿Horarios el viernes?"
**When**: Bot processes request in BOOKING mode
**Then**: Bot shows available slots directly:
"Tenemos disponibles: Viernes 10:00, 11:00, 14:00..."
**Not**: With narration like "Déjame buscar disponibilidad para el viernes. Tenemos..."

### Scenario 4: Returning client
**Given**: User says "Quiero un turno con Luciana" (and has been greeted before)
**When**: Bot processes request with existing context
**Then**: Bot acknowledges and proceeds with booking:
"Perfecto, Luciana. ¿Qué fecha te gustaría para tu turno?"
**Not**: Asking for name again like "Hola de nuevo, ¿cómo te llamas?"

## Prompt Changes Required

### agent/modes/greeting_mode.py
- Remove any instruction to produce a greeting since it's prepended in code
- Keep only instructions for identifying if user is new/returning

### agent/prompts/modes/general.md
- Remove line showing example: "Voy a ayudarte a encontrar lo que necesitas"
- Replace with direct assistance examples

### agent/prompts/modes/recovery.md
- Remove line showing example: "Déjame buscar esa información por ti"
- Replace with direct action examples

### agent/prompts/shared/critical_rules.md
Add explicit rule:
**NEVER describe upcoming tool calls. Call the tool silently, present results only.**

## Runtime Guard Implementation

### Location: agent/prompts/loader.py (after LLM response, before returning to user)

### Implementation:
```python
def narration_guard(response: str) -> str:
    """
    Removes future-action narration from bot responses.
    Patterns to remove: "voy a|déjame|vamos a|ahora voy a" + future tense action
    """
    import re
    
    # Pattern to match narration phrases followed by action descriptions
    narration_pattern = r'\b(voy a|déjame|vamos a|ahora voy a)\b[^.!?]*[.!?]'
    
    # Find all matches
    matches = re.findall(narration_pattern, response, re.IGNORECASE)
    
    # If matches found, remove the narration clauses
    if matches:
        # Remove each narration phrase and what follows until punctuation
        cleaned = re.sub(narration_pattern, '', response, flags=re.IGNORECASE)
        # Clean up extra spaces and punctuation
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        # Ensure proper punctuation at end if needed
        if cleaned and cleaned[-1] not in '.!?':
            cleaned += '.'
        return cleaned
    
    return response
```

### Example transformation:
**Input**: "Ahora, déjame buscar horarios para el viernes. Tenemos: 10:00, 11:00..."
**Output**: "Tenemos: 10:00, 11:00..."

## Acceptance Criteria

### AC-1: Greeting count verification
- First turn response contains exactly one greeting phrase
- Automated test verifies greeting_count(response) == 1 for turn 1

### AC-2: Narration absence verification
- Zero matches for regex pattern: `(?i)\b(voy a|déjame|vamos a|ahora voy a)\b`
- Applied to all mode responses in test suite

### AC-3: Luis flow validation
- Turn 1: Single greeting, no duplication (per REQ-1)
- Verified through conversation trace testing

### AC-4: Carlos flow validation  
- Turn 3 (or later): No "Ahora, déjame buscar..." narration
- Verified through specific test case

### AC-5: Test coverage
- Unit tests for narration_guard function
- Integration tests verifying full conversation flows
- Minimum 90% coverage on modified files

## Edge Cases

### Edge Case 1: Legitimate future statements
**Concern**: What if bot needs to say "Voy a contactar al equipo" in ESCALATION mode?
**Resolution**: The narration guard should ONLY filter when the phrase is followed by description of the bot's own imminent actions. 
- "Voy a contactar al equipo" (statement of intent) → ALLOWED
- "Voy a buscar disponibilidad..." (narration of action) → FILTERED
Implementation: Enhance guard to check if followed by action verbs related to bot's capabilities (buscar, mostrar, consultar, etc.)

### Edge Case 2: User preference for explanatory language
**Concern**: Some users might expect to hear "I'll search for you" type language
**Resolution**: This conflicts with the core requirement of reducing verbosity. 
- Alternative: Add configuration flag for verbosity level (minimal/standard/verbose)
- Default: Minimal (no narration) as per REQ-2
- Verbose mode would keep some explanatory phrases but still avoid duplication

### Edge Case 3: False positives
**Concern**: Phrases like "Voy a dejarte opciones" being incorrectly filtered
**Resolution**: Refine regex pattern to be more specific:
- Require action verb after the phrase: \b(voy a|déjame|vamos a|ahora voy a)\s+(buscar|mostrar|consultar|contactar|esperar)\b
- This catches only when followed by bot-action verbs

### Edge Case 4: Multilingual responses
**Concern**: Spanish responses might have different verb constructions
**Resolution**: Pattern specifically targets Spanish future-action phrases as specified. 
- For English responses, similar guard would be needed if bot ever responds in English
- Current scope: Spanish-only as per project requirements