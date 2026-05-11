"""Unit tests for api.services.template_catalog.

Covers:
  - env-flag gating: is_approved() returns True when flag is True, False otherwise.
  - Unknown template: is_approved() returns False (no KeyError).
  - get_templates() returns list with correct status values based on env flags.
  - get_template_def() raises KeyError for unknown templates.
  - render_body() renders template strings correctly and raises KeyError on missing params.
  - Empty catalog fallback: get_templates() returns empty list if registry were empty.

No DB or network calls are required (pure module-level logic + env flags).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from api.services.template_catalog import (
    get_template_def,
    get_templates,
    is_approved,
    render_body,
)

# ---------------------------------------------------------------------------
# is_approved — env-flag gating
# ---------------------------------------------------------------------------


class TestIsApproved:
    """Tests for env-flag-based approval gating."""

    def test_returns_true_when_flag_is_true(self):
        """is_approved('reengagement') returns True when INBOX_TEMPLATE_REENGAGEMENT_APPROVED=True."""
        with patch(
            "api.services.template_catalog.get_settings",
        ) as mock_settings:
            mock_settings.return_value.INBOX_TEMPLATE_REENGAGEMENT_APPROVED = True
            result = is_approved("reengagement")
        assert result is True

    def test_returns_false_when_flag_is_false(self):
        """is_approved('reengagement') returns False when INBOX_TEMPLATE_REENGAGEMENT_APPROVED=False."""
        with patch(
            "api.services.template_catalog.get_settings",
        ) as mock_settings:
            mock_settings.return_value.INBOX_TEMPLATE_REENGAGEMENT_APPROVED = False
            result = is_approved("reengagement")
        assert result is False

    def test_returns_false_for_unknown_template(self):
        """is_approved() returns False (not KeyError) for templates not in the registry."""
        result = is_approved("nonexistent_template_xyz")
        assert result is False

    def test_returns_false_by_default_without_flag(self):
        """Default settings have INBOX_TEMPLATE_REENGAGEMENT_APPROVED=False."""
        # This tests that the default is safe (False) — no surprise approvals at startup
        from shared.config import Settings

        s = Settings()
        assert s.INBOX_TEMPLATE_REENGAGEMENT_APPROVED is False


# ---------------------------------------------------------------------------
# get_templates — full list with status
# ---------------------------------------------------------------------------


class TestGetTemplates:
    """Tests for get_templates() returning the annotated template list."""

    def test_returns_list(self):
        """get_templates() always returns a list."""
        result = get_templates()
        assert isinstance(result, list)

    def test_returns_pending_status_when_not_approved(self):
        """Template status is 'pending' when env flag is False."""
        with patch(
            "api.services.template_catalog.get_settings",
        ) as mock_settings:
            mock_settings.return_value.INBOX_TEMPLATE_REENGAGEMENT_APPROVED = False
            templates = get_templates()

        reengagement = next((t for t in templates if t["name"] == "reengagement"), None)
        assert reengagement is not None
        assert reengagement["status"] == "pending"

    def test_returns_approved_status_when_flag_true(self):
        """Template status is 'approved' when env flag is True."""
        with patch(
            "api.services.template_catalog.get_settings",
        ) as mock_settings:
            mock_settings.return_value.INBOX_TEMPLATE_REENGAGEMENT_APPROVED = True
            templates = get_templates()

        reengagement = next((t for t in templates if t["name"] == "reengagement"), None)
        assert reengagement is not None
        assert reengagement["status"] == "approved"

    def test_template_has_required_keys(self):
        """Each template dict has name, display_name, params, and status keys."""
        templates = get_templates()
        for template in templates:
            assert "name" in template
            assert "display_name" in template
            assert "params" in template
            assert "status" in template

    def test_template_status_is_approved_or_pending(self):
        """Template status is always exactly 'approved' or 'pending'."""
        with patch(
            "api.services.template_catalog.get_settings",
        ) as mock_settings:
            mock_settings.return_value.INBOX_TEMPLATE_REENGAGEMENT_APPROVED = True
            templates = get_templates()

        for t in templates:
            assert t["status"] in ("approved", "pending")

    def test_window_open_param_does_not_filter(self):
        """get_templates(window_open=True) still returns all templates (caller decides)."""
        all_templates = get_templates()
        window_open_templates = get_templates(window_open=True)
        assert len(all_templates) == len(window_open_templates)

    def test_empty_registry_returns_empty_list(self):
        """If the registry were empty, get_templates() returns [] without error."""
        with patch("api.services.template_catalog._TEMPLATE_REGISTRY", {}):
            result = get_templates()
        assert result == []


# ---------------------------------------------------------------------------
# get_template_def — KeyError on unknown
# ---------------------------------------------------------------------------


class TestGetTemplateDef:
    """Tests for get_template_def() retrieval and error handling."""

    def test_returns_template_def_for_known_name(self):
        """get_template_def('reengagement') returns a TemplateDef."""
        from api.services.template_catalog import TemplateDef

        result = get_template_def("reengagement")
        assert isinstance(result, TemplateDef)
        assert result.name == "reengagement"

    def test_raises_key_error_for_unknown_template(self):
        """get_template_def() raises KeyError for unknown template names."""
        with pytest.raises(KeyError):
            get_template_def("does_not_exist")


# ---------------------------------------------------------------------------
# render_body — template rendering
# ---------------------------------------------------------------------------


class TestRenderBody:
    """Tests for render_body() template parameter substitution."""

    def test_renders_body_with_correct_params(self):
        """render_body renders the template body string with provided params."""
        result = render_body("reengagement", {"customer_name": "María"})
        assert "María" in result
        assert "{customer_name}" not in result  # placeholder replaced

    def test_raises_key_error_on_missing_param(self):
        """render_body raises KeyError when a required param is not provided."""
        with pytest.raises(KeyError):
            render_body("reengagement", {})  # customer_name is required

    def test_raises_key_error_for_unknown_template(self):
        """render_body raises KeyError for templates not in the catalog."""
        with pytest.raises(KeyError):
            render_body("ghost_template", {"customer_name": "Test"})
