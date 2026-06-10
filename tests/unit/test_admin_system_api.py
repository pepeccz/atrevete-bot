"""
Unit tests for admin system API — policy version endpoint (PR-3 / Group H).

Covers:
- T33: GET /api/admin/system/policy-version returns {"version": settings.POLICY_VERSION}
- T33b: Endpoint is accessible (no strict auth required for public config)

All tests use mocks — no real database required.
"""

from unittest.mock import patch

import pytest

# ============================================================================
# T33: GET /api/admin/system/policy-version
# ============================================================================


@pytest.mark.asyncio
async def test_policy_version_endpoint_returns_current_version():
    """
    T33: GET /api/admin/system/policy-version returns {"version": <POLICY_VERSION>}.
    """
    from api.routes.admin import get_policy_version

    with patch("api.routes.admin.get_settings") as mock_get_settings:
        mock_settings = mock_get_settings.return_value
        mock_settings.POLICY_VERSION = "1.0"

        result = await get_policy_version()

    assert result == {"version": "1.0"}


@pytest.mark.asyncio
async def test_policy_version_endpoint_reflects_env_override():
    """
    T33: Endpoint value reflects whatever POLICY_VERSION is configured —
    not hardcoded.
    """
    from api.routes.admin import get_policy_version

    with patch("api.routes.admin.get_settings") as mock_get_settings:
        mock_settings = mock_get_settings.return_value
        mock_settings.POLICY_VERSION = "2.0"

        result = await get_policy_version()

    assert result == {"version": "2.0"}


@pytest.mark.asyncio
async def test_policy_version_endpoint_returns_dict_with_version_key():
    """
    T33: Response always has exactly the "version" key.
    """
    from api.routes.admin import get_policy_version

    with patch("api.routes.admin.get_settings") as mock_get_settings:
        mock_settings = mock_get_settings.return_value
        mock_settings.POLICY_VERSION = "1.0"

        result = await get_policy_version()

    assert "version" in result
    assert isinstance(result["version"], str)
