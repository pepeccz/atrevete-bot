"""
Unit tests for stylist context generation.

Tests to verify that stylist UUIDs are included correctly in system prompts
without truncation (fix for bug discovered Nov 13, 2025).
"""

import re

import pytest

from agent.prompts import load_stylist_context


@pytest.mark.asyncio
async def test_stylist_context_contains_full_uuids():
    """
    Verify stylist context includes full UUIDs (36 chars), not truncated.

    Context:
    - Bug discovered Nov 13, 2025: Truncated UUIDs ("4a5c3172...") in system prompt
      caused LLM to copy incomplete UUIDs to book() tool, resulting in
      "badly formed hexadecimal UUID string" errors.
    - Fix: Include full UUIDs in system prompt to match tool outputs.

    This test ensures the bug doesn't regress.
    """
    context = await load_stylist_context()

    # UUID format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (36 characters with hyphens)
    uuid_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    full_uuids = re.findall(uuid_pattern, context, re.IGNORECASE)

    # Must have at least 1 UUID (assuming active stylists exist in test DB)
    assert len(full_uuids) > 0, (
        "Expected at least 1 full UUID in stylist context. "
        "Are there active stylists in the test database?"
    )

    # All UUIDs must be full length (36 chars)
    for uuid_str in full_uuids:
        assert len(uuid_str) == 36, (
            f"UUID '{uuid_str}' is not 36 characters long. "
            f"Got {len(uuid_str)} chars. Is it truncated?"
        )

    # Must NOT contain truncated patterns like "4a5c3172..."
    # Pattern matches: (ID: 8_hex_chars...)
    truncated_pattern = r'\(ID:\s*[0-9a-f]{8}\.\.\.\)'
    truncated_matches = re.findall(truncated_pattern, context, re.IGNORECASE)

    assert len(truncated_matches) == 0, (
        f"Found {len(truncated_matches)} truncated UUID pattern(s) in context: "
        f"{truncated_matches}. UUIDs must be complete (36 chars) for LLM tool calls."
    )


@pytest.mark.asyncio
async def test_stylist_context_format():
    """
    Verify stylist context follows expected format.

    Expected format:
    ### Equipo de Estilistas (N profesionales)

    **Peluquería:**
    - Name (ID: full-uuid)

    **Estética:**
    - Name (ID: full-uuid)
    """
    context = await load_stylist_context()

    # Must contain header
    assert "### Equipo de Estilistas" in context

    # Must contain category sections
    assert "**Peluquería:**" in context
    assert "**Estética:**" in context

    # Must contain at least one stylist entry with UUID
    # Pattern: "- Name (ID: uuid)"
    stylist_pattern = r'-\s+\w+\s+\(ID:\s+[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\)'
    stylist_entries = re.findall(stylist_pattern, context, re.IGNORECASE)

    assert len(stylist_entries) > 0, (
        "Expected at least one stylist entry with format '- Name (ID: uuid)'"
    )


@pytest.mark.asyncio
async def test_stylist_context_caching():
    """
    Verify stylist context is cached correctly.

    Context is cached for 10 minutes to reduce database queries.
    """
    # First call - loads from DB
    context1 = await load_stylist_context()

    # Second call - should use cache
    context2 = await load_stylist_context()

    # Both should return identical content
    assert context1 == context2

    # Both should contain full UUIDs (not truncated)
    uuid_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    assert len(re.findall(uuid_pattern, context2)) > 0
