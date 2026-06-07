"""Unit tests for policy config fields (T05).

Tests cover:
- settings.POLICY_VERSION defaults to "1.0"
- settings.POLICY_URL defaults to "https://atrevetepeluqueria.com/politica-privacidad/"
- Both fields are overridable via environment variables

Refs: Spec §2, Task T05/T06
"""

from __future__ import annotations

import pytest


class TestPolicyVersionDefault:
    """POLICY_VERSION default and override behavior."""

    def test_policy_version_default_is_1_0(self):
        """POLICY_VERSION must default to '1.0' when env var is not set."""
        # Re-import fresh settings without cached instance
        import importlib

        import shared.config as config_module

        importlib.reload(config_module)
        from shared.config import Settings

        s = Settings()
        assert s.POLICY_VERSION == "1.0", (
            f"Expected POLICY_VERSION='1.0', got '{s.POLICY_VERSION}'"
        )

    def test_policy_version_is_string(self):
        """POLICY_VERSION must be a str (not int or other type)."""
        from shared.config import Settings

        s = Settings()
        assert isinstance(s.POLICY_VERSION, str)

    def test_policy_version_env_override(self, monkeypatch):
        """POLICY_VERSION must be overridable via POLICY_VERSION env var."""
        monkeypatch.setenv("POLICY_VERSION", "2.0")

        import importlib

        import shared.config as config_module

        importlib.reload(config_module)
        from shared.config import Settings

        s = Settings()
        assert s.POLICY_VERSION == "2.0", (
            f"Expected POLICY_VERSION='2.0' from env, got '{s.POLICY_VERSION}'"
        )

    def test_policy_version_env_override_semver_ish(self, monkeypatch):
        """POLICY_VERSION must accept semver-ish strings like '1.1-beta'."""
        monkeypatch.setenv("POLICY_VERSION", "1.1-beta")

        import importlib

        import shared.config as config_module

        importlib.reload(config_module)
        from shared.config import Settings

        s = Settings()
        assert s.POLICY_VERSION == "1.1-beta"


class TestPolicyURLDefault:
    """POLICY_URL default and override behavior."""

    def test_policy_url_default_is_atrevete_url(self):
        """POLICY_URL must default to the Atrévete privacy policy URL."""
        import importlib

        import shared.config as config_module

        importlib.reload(config_module)
        from shared.config import Settings

        s = Settings()
        assert s.POLICY_URL == "https://atrevetepeluqueria.com/politica-privacidad/", (
            f"Expected canonical default URL, got '{s.POLICY_URL}'"
        )

    def test_policy_url_is_string(self):
        """POLICY_URL must be a str."""
        from shared.config import Settings

        s = Settings()
        assert isinstance(s.POLICY_URL, str)

    def test_policy_url_env_override(self, monkeypatch):
        """POLICY_URL must be overridable via POLICY_URL env var."""
        monkeypatch.setenv("POLICY_URL", "https://example.com/policy/")

        import importlib

        import shared.config as config_module

        importlib.reload(config_module)
        from shared.config import Settings

        s = Settings()
        assert s.POLICY_URL == "https://example.com/policy/"

    def test_policy_url_accessible_via_get_settings(self):
        """POLICY_URL must be accessible via get_settings() (not just Settings())."""
        # NOTE: get_settings() uses lru_cache so it may return cached instance.
        # We test the field EXISTS on the returned instance.
        import importlib

        import shared.config as config_module

        importlib.reload(config_module)
        from shared.config import get_settings

        settings = get_settings()
        assert hasattr(settings, "POLICY_URL"), "get_settings() instance must have POLICY_URL"
        assert isinstance(settings.POLICY_URL, str)

    def test_policy_version_accessible_via_get_settings(self):
        """POLICY_VERSION must be accessible via get_settings() (not just Settings())."""
        import importlib

        import shared.config as config_module

        importlib.reload(config_module)
        from shared.config import get_settings

        settings = get_settings()
        assert hasattr(settings, "POLICY_VERSION"), (
            "get_settings() instance must have POLICY_VERSION"
        )
        assert isinstance(settings.POLICY_VERSION, str)
