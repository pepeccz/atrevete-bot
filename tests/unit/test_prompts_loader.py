"""T3.4 / T7.2 — prompt loader: identity + rules + glossary concatenated + cached.

TDD RED phase — written before agent/prompts/loader.py exists.
"""



def test_load_system_prompt_importable():
    """load_system_prompt is importable from agent.prompts.loader."""
    from agent.prompts.loader import load_system_prompt

    assert callable(load_system_prompt)


def test_load_system_prompt_returns_string():
    """load_system_prompt() returns a non-empty string."""
    from agent.prompts.loader import load_system_prompt

    result = load_system_prompt()
    assert isinstance(result, str)
    assert len(result) > 50, "System prompt must have meaningful content"


def test_load_system_prompt_contains_identity():
    """System prompt contains the Maite persona (identity.md content)."""
    from agent.prompts.loader import load_system_prompt

    prompt = load_system_prompt()
    assert "Maite" in prompt, "Identity section must mention 'Maite'"


def test_load_system_prompt_contains_critical_rules():
    """System prompt contains critical rules (UUID, Spanish-only)."""
    from agent.prompts.loader import load_system_prompt

    prompt = load_system_prompt()
    # Critical rules must mention UUID or service_ids constraint
    assert any(kw in prompt.lower() for kw in ["uuid", "service_id", "uuid"]), (
        "Critical rules section must contain UUID constraints"
    )


def test_load_system_prompt_contains_glossary():
    """System prompt contains audience glossary (adult_female etc.)."""
    from agent.prompts.loader import load_system_prompt

    prompt = load_system_prompt()
    assert "adult_female" in prompt, "Glossary section must contain audience taxonomy"


def test_load_system_prompt_caches_result():
    """Second call to load_system_prompt returns the same object (cached)."""
    from agent.prompts.loader import load_system_prompt

    result1 = load_system_prompt()
    result2 = load_system_prompt()
    assert result1 is result2, "load_system_prompt must cache and return same object"
