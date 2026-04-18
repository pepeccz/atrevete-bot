"""
Unit tests for feature flags in shared/config.py.

Tests cover:
- T0.5: ENABLE_STATUS_LINE_MIDDLEWARE feature flag exists and defaults to False
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestEnableStatusLineMiddlewareFlag:
    """Tests for ENABLE_STATUS_LINE_MIDDLEWARE in Settings."""

    def test_flag_exists_in_settings(self):
        """ENABLE_STATUS_LINE_MIDDLEWARE must exist as an attribute on Settings."""
        from shared.config import Settings

        s = Settings()
        assert hasattr(s, "ENABLE_STATUS_LINE_MIDDLEWARE")

    def test_flag_defaults_to_false(self):
        """Default value must be False (safe rollout — flag off until explicitly enabled)."""
        from unittest.mock import patch

        # Clear the lru_cache so Settings re-reads env without the flag set
        from shared.config import get_settings

        get_settings.cache_clear()
        with patch.dict("os.environ", {}, clear=False):
            # Remove the flag from env if present
            import os
            env = {k: v for k, v in os.environ.items() if k != "ENABLE_STATUS_LINE_MIDDLEWARE"}
            with patch.dict("os.environ", env, clear=True):
                from shared.config import Settings

                s = Settings()
                assert s.ENABLE_STATUS_LINE_MIDDLEWARE is False

    def test_flag_can_be_overridden_via_env(self):
        """ENABLE_STATUS_LINE_MIDDLEWARE=true in env must override the default."""
        from unittest.mock import patch

        with patch.dict("os.environ", {"ENABLE_STATUS_LINE_MIDDLEWARE": "true"}):
            from shared.config import Settings

            s = Settings()
            assert s.ENABLE_STATUS_LINE_MIDDLEWARE is True

    def test_flag_is_bool_type(self):
        """ENABLE_STATUS_LINE_MIDDLEWARE must be typed as bool, not str."""
        from shared.config import Settings

        s = Settings()
        assert isinstance(s.ENABLE_STATUS_LINE_MIDDLEWARE, bool)

    def test_flag_independent_from_other_feature_flags(self):
        """ENABLE_STATUS_LINE_MIDDLEWARE=True must not affect STATE_DELIVERY_SYNTHETIC_ENABLED."""
        import os

        env = {k: v for k, v in os.environ.items() if k != "ENABLE_STATUS_LINE_MIDDLEWARE"}
        env["ENABLE_STATUS_LINE_MIDDLEWARE"] = "true"
        with patch.dict("os.environ", env, clear=True):
            from shared.config import Settings

            s = Settings()
            assert s.ENABLE_STATUS_LINE_MIDDLEWARE is True
            # STATE_DELIVERY_SYNTHETIC_ENABLED defaults to True — must remain unaffected
            assert s.STATE_DELIVERY_SYNTHETIC_ENABLED is True
