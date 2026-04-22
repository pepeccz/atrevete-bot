"""T3.1 RED — build_catalog_prompt_section includes ## Estilistas disponibles.

Asserts that build_catalog_prompt_section() returns a string containing
'## Estilistas disponibles' with at least one stylist line that has an 'id=' UUID suffix.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fake_stylist(name: str, category=None) -> SimpleNamespace:
    """Build a duck-typed stand-in for a Stylist ORM row."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        category=category,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_prompt_section_includes_stylist_roster(monkeypatch):
    """build_catalog_prompt_section() must include ## Estilistas disponibles with name + id=UUID per row."""
    from agent.prompts import catalog_builder

    # Patch get_active_services to avoid real DB
    fake_services = []
    monkeypatch.setattr(catalog_builder, "get_active_services", AsyncMock(return_value=fake_services))

    # Three active stylists
    stylists = [
        _fake_stylist("Ana García"),
        _fake_stylist("Sofía Martínez"),
        _fake_stylist("Marcos López"),
    ]

    # Patch the DB session used inside build_catalog_prompt_section
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []  # services (empty for this test)

    mock_stylist_result = MagicMock()
    mock_stylist_result.scalars.return_value.all.return_value = stylists

    async def fake_execute(query):
        # Distinguish between Service query and Stylist query by inspecting query string
        query_str = str(query)
        if "stylist" in query_str.lower():
            return mock_stylist_result
        return mock_result

    mock_session = AsyncMock()
    mock_session.execute = fake_execute
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_ctx_manager = MagicMock()
    mock_ctx_manager.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx_manager.__aexit__ = AsyncMock(return_value=False)

    with patch("database.connection.get_async_session", return_value=mock_ctx_manager):
        result = await catalog_builder.build_catalog_prompt_section()

    assert "## Estilistas disponibles" in result, (
        "build_catalog_prompt_section() must include '## Estilistas disponibles' section"
    )

    for stylist in stylists:
        assert f"id={stylist.id}" in result, (
            f"Stylist roster must include 'id={stylist.id}' for stylist '{stylist.name}'"
        )
        assert stylist.name in result, (
            f"Stylist roster must include name '{stylist.name}'"
        )


@pytest.mark.asyncio
async def test_prompt_section_no_stylist_section_when_empty(monkeypatch):
    """When no active stylists, ## Estilistas disponibles section is absent."""
    from agent.prompts import catalog_builder

    fake_services = []
    monkeypatch.setattr(catalog_builder, "get_active_services", AsyncMock(return_value=fake_services))

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_ctx_manager = MagicMock()
    mock_ctx_manager.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx_manager.__aexit__ = AsyncMock(return_value=False)

    with patch("database.connection.get_async_session", return_value=mock_ctx_manager):
        result = await catalog_builder.build_catalog_prompt_section()

    assert "## Estilistas disponibles" not in result, (
        "## Estilistas disponibles section must be absent when no active stylists"
    )
