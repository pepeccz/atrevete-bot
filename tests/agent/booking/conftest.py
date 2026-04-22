"""Shared fixtures for tests/agent/booking/ — booking-prompts-audit-fix.

Provides an autouse patch for the prompt builder's DB-dependent functions so
that existing leaf tests (and new ones) don't need a running database.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import SystemMessage


@pytest.fixture(autouse=True)
def patch_prompt_builder_db_calls():
    """Patch DB-calling functions inside prompt_builder so leaves tests stay offline."""
    with (
        patch(
            "agent.booking.prompt_builder.build_catalog_prompt_section",
            new=AsyncMock(return_value="Corte de cabello — 30min"),
        ),
        patch(
            "agent.booking.prompt_builder.load_business_hours_snapshot",
            new=AsyncMock(return_value={"lunes": "09:00-18:00"}),
        ),
    ):
        yield
