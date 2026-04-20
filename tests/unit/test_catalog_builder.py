"""
Tests for agent/prompts/catalog_builder.py.

Verifies:
- Module and key functions are importable
- _AUDIENCE_LABELS has expected keys
- _CATEGORY_LABELS has expected keys
- _build_service_type_tag emits the correct PRINCIPAL / VARIANTE / ADDON tag
- seeds populate metadata_ consistently on every service
"""

from types import SimpleNamespace

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


# ---------------------------------------------------------------------------
# _build_service_type_tag — data-driven PRINCIPAL / VARIANTE / ADDON tags
# ---------------------------------------------------------------------------


def _fake_service(metadata_=None, audience=None):
    """Build a duck-typed stand-in for a Service ORM row."""
    return SimpleNamespace(metadata_=metadata_, audience=audience)


def test_principal_tag_includes_dimension_and_audience():
    from agent.prompts.catalog_builder import _build_service_type_tag

    svc = _fake_service(
        metadata_={"service_type": "principal", "dimension": "cut", "parent_service_name": None},
        audience="adult_female",
    )
    assert _build_service_type_tag(svc) == " [PRINCIPAL · cut · adult_female]"


def test_principal_tag_uses_any_when_audience_is_none():
    from agent.prompts.catalog_builder import _build_service_type_tag

    svc = _fake_service(
        metadata_={"service_type": "principal", "dimension": "manicure", "parent_service_name": None},
        audience=None,
    )
    assert _build_service_type_tag(svc) == " [PRINCIPAL · manicure · any]"


def test_variant_tag_references_parent():
    from agent.prompts.catalog_builder import _build_service_type_tag

    svc = _fake_service(
        metadata_={"service_type": "variant", "dimension": "cut", "parent_service_name": "Cortar"},
    )
    assert _build_service_type_tag(svc) == " [VARIANTE de Cortar]"


def test_addon_tag_shows_dimension():
    from agent.prompts.catalog_builder import _build_service_type_tag

    svc = _fake_service(
        metadata_={"service_type": "addon", "dimension": "treatment", "parent_service_name": None},
    )
    assert _build_service_type_tag(svc) == " [ADDON · treatment]"


@pytest.mark.parametrize("metadata", [None, {}, {"service_type": None}, {"service_type": ""}])
def test_backward_compatible_when_metadata_missing(metadata):
    """Services with no/empty metadata_ produce no tag — old catalog shape."""
    from agent.prompts.catalog_builder import _build_service_type_tag

    svc = _fake_service(metadata_=metadata)
    assert _build_service_type_tag(svc) == ""


def test_unknown_service_type_yields_no_tag():
    from agent.prompts.catalog_builder import _build_service_type_tag

    svc = _fake_service(metadata_={"service_type": "weird", "dimension": "x"})
    assert _build_service_type_tag(svc) == ""


# ---------------------------------------------------------------------------
# seeds — every seeded service carries consistent metadata_
# ---------------------------------------------------------------------------


def test_seeds_populate_metadata_keys_for_every_service():
    """All seeded services expose service_type / dimension / parent_service_name."""
    from database.seeds.services import ALL_SERVICES

    required_keys = {"service_type", "dimension", "parent_service_name"}
    valid_types = {"principal", "variant", "addon"}

    for svc in ALL_SERVICES:
        meta = svc.get("metadata_", {})
        missing = required_keys - meta.keys()
        assert not missing, (
            f"Service {svc['name']!r} metadata_ is missing keys: {missing}"
        )
        assert meta["service_type"] in valid_types, (
            f"Service {svc['name']!r} has invalid service_type={meta['service_type']!r}"
        )


def test_seeds_variant_parent_references_are_valid():
    """Every variant's parent_service_name matches an existing service name."""
    from database.seeds.services import ALL_SERVICES

    all_names = {svc["name"] for svc in ALL_SERVICES}

    for svc in ALL_SERVICES:
        meta = svc.get("metadata_", {})
        if meta.get("service_type") != "variant":
            continue
        parent = meta.get("parent_service_name")
        assert parent, f"Variant {svc['name']!r} must declare parent_service_name"
        assert parent in all_names, (
            f"Variant {svc['name']!r} points at unknown parent {parent!r}"
        )


def test_seeds_principals_and_addons_have_no_parent():
    """Principals and addons must leave parent_service_name as None."""
    from database.seeds.services import ALL_SERVICES

    for svc in ALL_SERVICES:
        meta = svc.get("metadata_", {})
        stype = meta.get("service_type")
        if stype in {"principal", "addon"}:
            assert meta.get("parent_service_name") is None, (
                f"Service {svc['name']!r} is {stype} but declares parent_service_name="
                f"{meta.get('parent_service_name')!r}"
            )
