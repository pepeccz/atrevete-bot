"""
Tests for dynamic context handling in the loader module (simplified architecture).

Verifies:
- _STEP_VISIBLE_FIELDS is gone (was part of the old step-driven context system)
- _build_simple_dynamic_context exists in loader (the new simpler replacement)
"""

import inspect

import pytest


def test_no_old_context_keys():
    """_STEP_VISIBLE_FIELDS is not present in the loader module."""
    import agent.prompts.loader as loader_module

    assert not hasattr(loader_module, "_STEP_VISIBLE_FIELDS"), (
        "_STEP_VISIBLE_FIELDS should be removed — step-driven context was replaced "
        "by _build_simple_dynamic_context"
    )


def test_no_step_visible_fields_in_source():
    """_STEP_VISIBLE_FIELDS string does not appear anywhere in loader source."""
    import agent.prompts.loader as loader_module

    source = inspect.getsource(loader_module)
    assert "_STEP_VISIBLE_FIELDS" not in source, (
        "_STEP_VISIBLE_FIELDS should not appear in loader.py source"
    )


def test_build_simple_dynamic_context_exists():
    """_build_simple_dynamic_context function exists in loader module."""
    from agent.prompts.loader import _build_simple_dynamic_context

    assert callable(_build_simple_dynamic_context), (
        "_build_simple_dynamic_context must be a callable function"
    )


def test_build_simple_dynamic_context_returns_string():
    """_build_simple_dynamic_context returns a non-empty string given minimal state."""
    from agent.prompts.loader import _build_simple_dynamic_context

    state = {"customer_phone": "+34612345678", "conversation_summary": None}
    result = _build_simple_dynamic_context(state)
    assert isinstance(result, str), "_build_simple_dynamic_context must return a str"
    assert len(result) > 0, "_build_simple_dynamic_context must return a non-empty string"
