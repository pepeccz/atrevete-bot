"""
Unit tests for dynamic prompt injection (stylist context).

Tests verify that the load_stylist_context() function correctly queries
the database and formats stylist information for system prompt injection.
"""

import pytest

from agent.prompts import load_stylist_context


@pytest.mark.asyncio
async def test_load_stylist_context_returns_formatted_markdown():
    """Verify that load_stylist_context returns properly formatted markdown."""
    context = await load_stylist_context()

    # Should be non-empty string
    assert isinstance(context, str)
    assert len(context) > 0

    # Should contain markdown headers
    assert "### Equipo de Estilistas" in context
    assert "**Peluquería:**" in context
    assert "**Estética:**" in context


@pytest.mark.asyncio
async def test_load_stylist_context_includes_database_stylists():
    """Verify that all active stylists from database are included."""
    context = await load_stylist_context()

    # Expected stylists based on seed data (database reality)
    # NOTE: These are the actual 6 active stylists in the database
    expected_stylists = ["Ana", "Ana Maria", "Marta", "Pilar", "Rosa", "Victor"]

    for stylist_name in expected_stylists:
        assert stylist_name in context, f"Stylist '{stylist_name}' should be in context"


@pytest.mark.asyncio
async def test_load_stylist_context_excludes_ghost_stylists():
    """Verify that non-existent stylists (ghosts) are NOT included."""
    context = await load_stylist_context()

    # "Harol" was in the old hardcoded prompt but does NOT exist in database
    ghost_stylists = ["Harol"]

    for ghost_name in ghost_stylists:
        assert ghost_name not in context, f"Ghost stylist '{ghost_name}' should NOT be in context"


@pytest.mark.asyncio
async def test_load_stylist_context_categorizes_correctly():
    """Verify stylists are categorized by their database category."""
    context = await load_stylist_context()

    # Rosa should appear under Estética (AESTHETICS in DB)
    rosa_index = context.find("Rosa")
    estetica_index = context.find("**Estética:**")
    assert rosa_index > estetica_index, "Rosa should appear after Estética header"

    # Marta should appear under Peluquería (HAIRDRESSING in DB)
    # NOTE: Old prompt incorrectly said "Peluquería y Estética"
    marta_index = context.find("Marta")
    peluqueria_index = context.find("**Peluquería:**")
    assert marta_index > peluqueria_index, "Marta should appear after Peluquería header"

    # Verify Marta does NOT appear in Estética section
    estetica_section_start = context.find("**Estética:**")
    estetica_section_end = len(context)  # Estética is the last section
    estetica_section = context[estetica_section_start:estetica_section_end]
    assert "Marta" not in estetica_section, "Marta should NOT be in Estética section"


@pytest.mark.asyncio
async def test_load_stylist_context_counts_correctly():
    """Verify the stylist count in the header matches database reality."""
    context = await load_stylist_context()

    # Database has 6 active stylists (Ana, Ana Maria, Marta, Pilar, Rosa, Victor)
    # Old prompt incorrectly said "5 profesionales"
    assert "6 profesionales" in context, "Should show 6 active professionals"


@pytest.mark.asyncio
async def test_load_stylist_context_fallback_on_error():
    """Verify graceful fallback if database query fails."""
    # This test would require mocking database failure
    # For now, we verify the function doesn't raise exceptions
    try:
        context = await load_stylist_context()
        assert isinstance(context, str)
        assert len(context) > 0
    except Exception as e:
        pytest.fail(f"load_stylist_context() should not raise exceptions: {e}")


@pytest.mark.asyncio
async def test_load_stylist_context_alphabetically_sorted():
    """Verify stylists are sorted alphabetically within each category."""
    context = await load_stylist_context()

    # Extract Peluquería section
    peluqueria_start = context.find("**Peluquería:**")
    estetica_start = context.find("**Estética:**")
    peluqueria_section = context[peluqueria_start:estetica_start]

    # Verify order: Ana < Ana Maria < Marta < Pilar < Victor
    ana_index = peluqueria_section.find("Ana\n")  # Exact match to avoid "Ana Maria"
    ana_maria_index = peluqueria_section.find("Ana Maria")
    marta_index = peluqueria_section.find("Marta")
    pilar_index = peluqueria_section.find("Pilar")
    victor_index = peluqueria_section.find("Victor")

    assert ana_index < ana_maria_index, "Ana should come before Ana Maria"
    assert ana_maria_index < marta_index, "Ana Maria should come before Marta"
    assert marta_index < pilar_index, "Marta should come before Pilar"
    assert pilar_index < victor_index, "Pilar should come before Victor"
