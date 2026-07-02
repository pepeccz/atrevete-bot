"""Unit tests for Slice 3 config settings (T1 — RED before T2 adds the fields).

Verifies that Settings exposes the five new auto-cancel / final-warning fields with
their correct types and safe default values (spec S3-R1, S3-R15).

RED contract: these assertions fail BEFORE T2 adds the fields to shared/config.py.
GREEN contract: all assertions pass AFTER T2 is applied.
"""

from __future__ import annotations

import pytest

from shared.config import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def default_settings() -> Settings:
    """Return a Settings instance built from defaults (no .env file required)."""
    return Settings()


# ---------------------------------------------------------------------------
# T1-A: AUTO_CANCEL_ENABLED — kill switch, must default to False
# ---------------------------------------------------------------------------


def test_auto_cancel_enabled_exists_and_defaults_false(default_settings: Settings) -> None:
    """AUTO_CANCEL_ENABLED must exist, be bool, and default to False (S3-R1)."""
    assert hasattr(default_settings, "AUTO_CANCEL_ENABLED"), (
        "Settings must expose AUTO_CANCEL_ENABLED (missing — add it in T2)"
    )
    assert isinstance(default_settings.AUTO_CANCEL_ENABLED, bool), (
        f"AUTO_CANCEL_ENABLED must be bool, got {type(default_settings.AUTO_CANCEL_ENABLED)}"
    )
    assert default_settings.AUTO_CANCEL_ENABLED is False, (
        "AUTO_CANCEL_ENABLED must default to False (safe — no destructive action without opt-in)"
    )


# ---------------------------------------------------------------------------
# T1-B: WHATSAPP_TEMPLATE_FINAL_WARNING — empty default; Meta approval pending
# ---------------------------------------------------------------------------


def test_whatsapp_template_final_warning_exists_and_defaults_empty(
    default_settings: Settings,
) -> None:
    """WHATSAPP_TEMPLATE_FINAL_WARNING must exist, be str, and default to '' (S3-R2)."""
    assert hasattr(default_settings, "WHATSAPP_TEMPLATE_FINAL_WARNING"), (
        "Settings must expose WHATSAPP_TEMPLATE_FINAL_WARNING (missing — add it in T2)"
    )
    assert isinstance(default_settings.WHATSAPP_TEMPLATE_FINAL_WARNING, str), (
        "WHATSAPP_TEMPLATE_FINAL_WARNING must be str, "
        f"got {type(default_settings.WHATSAPP_TEMPLATE_FINAL_WARNING)}"
    )
    assert default_settings.WHATSAPP_TEMPLATE_FINAL_WARNING == "", (
        "WHATSAPP_TEMPLATE_FINAL_WARNING must default to '' "
        "(populated only after Meta approves the template)"
    )


# ---------------------------------------------------------------------------
# T1-C: AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS — default 12, range [1, 36]
# ---------------------------------------------------------------------------


def test_auto_cancel_grace_before_warning_hours_exists_and_defaults_12(
    default_settings: Settings,
) -> None:
    """AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS must exist, be int, default 12 (S3-R15)."""
    assert hasattr(default_settings, "AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS"), (
        "Settings must expose AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS (missing — add it in T2)"
    )
    val = default_settings.AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS
    assert isinstance(val, int), (
        f"AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS must be int, got {type(val)}"
    )
    assert val == 12, (
        f"AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS must default to 12, got {val}"
    )


def test_auto_cancel_grace_before_warning_hours_validation() -> None:
    """AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS must accept boundary values [1, 36] (S3-R15)."""
    low = Settings(AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS=1)
    assert low.AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS == 1

    high = Settings(AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS=36)
    assert high.AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS == 36


def test_auto_cancel_grace_before_warning_hours_rejects_out_of_range() -> None:
    """AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS must reject values outside [1, 36] (S3-R15)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS=0)

    with pytest.raises(ValidationError):
        Settings(AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS=37)


# ---------------------------------------------------------------------------
# T1-D: AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS — default 6, range [1, 24]
# ---------------------------------------------------------------------------


def test_auto_cancel_grace_before_cancel_hours_exists_and_defaults_6(
    default_settings: Settings,
) -> None:
    """AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS must exist, be int, default 6 (S3-R15)."""
    assert hasattr(default_settings, "AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS"), (
        "Settings must expose AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS (missing — add it in T2)"
    )
    val = default_settings.AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS
    assert isinstance(val, int), (
        f"AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS must be int, got {type(val)}"
    )
    assert val == 6, (
        f"AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS must default to 6, got {val}"
    )


def test_auto_cancel_grace_before_cancel_hours_validation() -> None:
    """AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS must accept boundary values [1, 24] (S3-R15)."""
    low = Settings(AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS=1)
    assert low.AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS == 1

    high = Settings(AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS=24)
    assert high.AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS == 24


def test_auto_cancel_grace_before_cancel_hours_rejects_out_of_range() -> None:
    """AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS must reject values outside [1, 24] (S3-R15)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS=0)

    with pytest.raises(ValidationError):
        Settings(AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS=25)


# ---------------------------------------------------------------------------
# T1-E: AUTO_CANCEL_MIN_LEAD_HOURS — default 24, range [12, 48]
# ---------------------------------------------------------------------------


def test_auto_cancel_min_lead_hours_exists_and_defaults_24(
    default_settings: Settings,
) -> None:
    """AUTO_CANCEL_MIN_LEAD_HOURS must exist, be int, default 24 (S3-R15)."""
    assert hasattr(default_settings, "AUTO_CANCEL_MIN_LEAD_HOURS"), (
        "Settings must expose AUTO_CANCEL_MIN_LEAD_HOURS (missing — add it in T2)"
    )
    val = default_settings.AUTO_CANCEL_MIN_LEAD_HOURS
    assert isinstance(val, int), (
        f"AUTO_CANCEL_MIN_LEAD_HOURS must be int, got {type(val)}"
    )
    assert val == 24, (
        f"AUTO_CANCEL_MIN_LEAD_HOURS must default to 24, got {val}"
    )


def test_auto_cancel_min_lead_hours_validation() -> None:
    """AUTO_CANCEL_MIN_LEAD_HOURS must accept boundary values [12, 48] (S3-R15)."""
    low = Settings(AUTO_CANCEL_MIN_LEAD_HOURS=12)
    assert low.AUTO_CANCEL_MIN_LEAD_HOURS == 12

    high = Settings(AUTO_CANCEL_MIN_LEAD_HOURS=48)
    assert high.AUTO_CANCEL_MIN_LEAD_HOURS == 48


def test_auto_cancel_min_lead_hours_rejects_out_of_range() -> None:
    """AUTO_CANCEL_MIN_LEAD_HOURS must reject values outside [12, 48] (S3-R15)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(AUTO_CANCEL_MIN_LEAD_HOURS=11)

    with pytest.raises(ValidationError):
        Settings(AUTO_CANCEL_MIN_LEAD_HOURS=49)


# ---------------------------------------------------------------------------
# T1-F: Legacy keys coexist without collision (S3-R15 constraint)
# ---------------------------------------------------------------------------


def test_legacy_keys_coexist_without_collision(default_settings: Settings) -> None:
    """Legacy CONFIRMATION_HOURS_BEFORE and AUTO_CANCEL_HOURS_BEFORE must NOT be removed.

    These are non-atrevete legacy keys kept for backward compatibility.
    The new Slice-3 settings use the AUTO_CANCEL_GRACE_* prefix and must NOT
    collide with or replace the legacy keys (S3-R15 constraint).
    """
    assert hasattr(default_settings, "CONFIRMATION_HOURS_BEFORE"), (
        "Legacy CONFIRMATION_HOURS_BEFORE must NOT be removed (backward compat)"
    )
    assert hasattr(default_settings, "AUTO_CANCEL_HOURS_BEFORE"), (
        "Legacy AUTO_CANCEL_HOURS_BEFORE must NOT be removed (backward compat)"
    )
    # New keys must be distinct from legacy keys
    assert default_settings.CONFIRMATION_HOURS_BEFORE == 48  # legacy default
    assert default_settings.AUTO_CANCEL_HOURS_BEFORE == 24  # legacy default
    # New AUTO_CANCEL_MIN_LEAD_HOURS is a different setting with a different key
    assert hasattr(default_settings, "AUTO_CANCEL_MIN_LEAD_HOURS")
    assert "AUTO_CANCEL_MIN_LEAD_HOURS" != "AUTO_CANCEL_HOURS_BEFORE"
