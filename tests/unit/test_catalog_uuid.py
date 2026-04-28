"""T3.5 / T7.3 — catalog_builder: every line contains id=<uuid>.

TDD RED phase for UUID emission — verifies the design §7 requirement.
"""

import re
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest


UUID_PATTERN = re.compile(
    r"id=[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


def _fake_svc(name: str, service_id: UUID | None = None, **kwargs) -> SimpleNamespace:
    """Build a duck-typed Service-like object for testing."""
    return SimpleNamespace(
        id=service_id or uuid4(),
        name=name,
        duration_minutes=45,
        description="Descripción de prueba",
        audience="adult_female",
        category="hairdressing",
        metadata_={"service_type": "principal", "dimension": "hair"},
        **kwargs,
    )


def test_catalog_line_contains_uuid_when_id_present():
    """A service with an id produces a line containing 'id=<uuid>'."""
    from agent.prompts.catalog_builder import build_catalog_for_prompt

    svc_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    svc = _fake_svc("Corte de Mujer", service_id=svc_id)
    result = build_catalog_for_prompt([svc])

    assert f"id={svc_id}" in result, (
        f"Expected 'id={svc_id}' in catalog line, got: {result!r}"
    )


def test_catalog_line_uuid_matches_pattern():
    """The UUID appended to each line matches the standard UUID format."""
    from agent.prompts.catalog_builder import build_catalog_for_prompt

    svc = _fake_svc("Tinte Completo")
    result = build_catalog_for_prompt([svc])

    assert UUID_PATTERN.search(result) is not None, (
        f"No 'id=<uuid>' pattern found in: {result!r}"
    )


def test_catalog_no_id_field_omits_uuid():
    """A service object without an id attribute produces a line without 'id='."""
    from agent.prompts.catalog_builder import build_catalog_for_prompt

    svc = SimpleNamespace(
        name="Sin ID",
        duration_minutes=30,
        description=None,
        audience=None,
        category="hairdressing",
        metadata_={"service_type": "addon", "dimension": "hair"},
        # Intentionally no `id` attribute
    )
    result = build_catalog_for_prompt([svc])
    # No id attribute → no id= suffix
    assert "id=" not in result


def test_multiple_services_all_have_uuids():
    """All services in a multi-service catalog have their UUIDs appended."""
    from agent.prompts.catalog_builder import build_catalog_for_prompt

    svcs = [
        _fake_svc("Corte de Mujer", service_id=uuid4()),
        _fake_svc("Tinte Completo", service_id=uuid4()),
        _fake_svc("Manicura", service_id=uuid4()),
    ]
    result = build_catalog_for_prompt(svcs)

    lines = [line for line in result.splitlines() if line.strip()]
    assert len(lines) == 3
    for line in lines:
        assert UUID_PATTERN.search(line) is not None, (
            f"Line missing UUID: {line!r}"
        )
