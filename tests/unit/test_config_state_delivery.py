"""
Unit tests for feature flag: state_delivery_synthetic_enabled.

TDD cycle: C6.1 — feature flag in shared/config.py.
Covers R4, S5.
"""

from __future__ import annotations

import importlib
import os


class TestStateDeliverySyntheticFlag:
    """C6.1: state_delivery_synthetic_enabled must exist in Settings with default True."""

    def test_flag_exists_and_defaults_true(self):
        """R4: settings.state_delivery_synthetic_enabled is True by default."""
        # Re-import fresh (lru_cache may hold a prior instance)
        from shared.config import Settings

        s = Settings()
        assert hasattr(s, "state_delivery_synthetic_enabled"), (
            "Settings must have state_delivery_synthetic_enabled field"
        )
        assert s.state_delivery_synthetic_enabled is True, (
            f"Expected default True, got {s.state_delivery_synthetic_enabled!r}"
        )

    def test_flag_reads_env_var_false(self, monkeypatch):
        """S5: setting STATE_DELIVERY_SYNTHETIC_ENABLED=false returns False."""
        monkeypatch.setenv("STATE_DELIVERY_SYNTHETIC_ENABLED", "false")

        from shared.config import Settings

        s = Settings()
        assert s.state_delivery_synthetic_enabled is False, (
            "Expected False when env var is 'false', "
            f"got {s.state_delivery_synthetic_enabled!r}"
        )

    def test_flag_reads_env_var_true_explicit(self, monkeypatch):
        """R4: explicit true env var also yields True."""
        monkeypatch.setenv("STATE_DELIVERY_SYNTHETIC_ENABLED", "true")

        from shared.config import Settings

        s = Settings()
        assert s.state_delivery_synthetic_enabled is True
