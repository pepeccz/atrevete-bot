"""
Tests for agent/prompts/catalog_builder.py.

Verifies:
- Module and key functions are importable
- _AUDIENCE_LABELS has expected keys
- _CATEGORY_LABELS has expected keys
"""

import pytest


def test_module_importable():
    """catalog_builder module is importable and exports the expected public API."""
    from agent.prompts.catalog_builder import build_catalog_markdown, invalidate_catalog_cache

    assert callable(build_catalog_markdown), "build_catalog_markdown must be callable"
    assert callable(invalidate_catalog_cache), "invalidate_catalog_cache must be callable"


def test_audience_labels_defined():
    """_AUDIENCE_LABELS has all expected audience keys."""
    from agent.prompts.catalog_builder import _AUDIENCE_LABELS

    expected_keys = {"adult_female", "adult_male", "child_female", "child_male", "unisex", None}
    for key in expected_keys:
        assert key in _AUDIENCE_LABELS, f"_AUDIENCE_LABELS missing key: {key!r}"


def test_audience_labels_are_strings():
    """All _AUDIENCE_LABELS values are non-empty strings."""
    from agent.prompts.catalog_builder import _AUDIENCE_LABELS

    for key, value in _AUDIENCE_LABELS.items():
        assert isinstance(value, str) and value, (
            f"_AUDIENCE_LABELS[{key!r}] must be a non-empty string, got {value!r}"
        )


def test_category_labels_defined():
    """_CATEGORY_LABELS has entries for all ServiceCategory values."""
    from database.models import ServiceCategory
    from agent.prompts.catalog_builder import _CATEGORY_LABELS

    for category in (ServiceCategory.HAIRDRESSING, ServiceCategory.AESTHETICS, ServiceCategory.BOTH):
        assert category in _CATEGORY_LABELS, (
            f"_CATEGORY_LABELS missing ServiceCategory.{category.name}"
        )


def test_category_labels_are_strings():
    """All _CATEGORY_LABELS values are non-empty strings."""
    from agent.prompts.catalog_builder import _CATEGORY_LABELS

    for key, value in _CATEGORY_LABELS.items():
        assert isinstance(value, str) and value, (
            f"_CATEGORY_LABELS[{key!r}] must be a non-empty string, got {value!r}"
        )
