"""Unit tests for shared/permissions.py — ROLE_PERMISSIONS dict and has_permission helper.

Covers: FR-PERM-1, FR-PERM-2.
Verifies exact permission strings, frozenset immutability, and unknown-role fallback.
"""

from __future__ import annotations

import pytest

from shared.permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS, has_permission

# Canonical permission matrix from FR-PERM-2 (proposal permission table).
# Exact strings — any deviation from these is a spec violation.
_ADMIN_EXPECTED = frozenset(
    {
        "users:manage",
        "system:settings",
        "escalations:resolve",
        "customers:delete",
        "conversations:read",
        "conversations:write",
        "appointments:read",
        "appointments:write",
        "customers:read",
        "customers:write",
        "calendar:read",
        "templates:send",
        "bot:pause",
        "bot:resume",
    }
)

_STYLIST_EXPECTED = frozenset(
    {
        "conversations:read",
        "conversations:write",
        "appointments:read",
        "appointments:write",
        "customers:read",
        "customers:write",
        "calendar:read",
        "bot:pause",
        "bot:resume",
        "templates:send",
    }
)


class TestRolePermissionsDict:
    """Tests for ROLE_PERMISSIONS structure."""

    def test_role_permissions_has_admin_key(self):
        """ROLE_PERMISSIONS has an 'admin' key."""
        assert "admin" in ROLE_PERMISSIONS

    def test_role_permissions_has_stylist_key(self):
        """ROLE_PERMISSIONS has a 'stylist' key."""
        assert "stylist" in ROLE_PERMISSIONS

    def test_role_permissions_has_exactly_two_roles(self):
        """ROLE_PERMISSIONS has exactly two roles: admin and stylist."""
        assert set(ROLE_PERMISSIONS.keys()) == {"admin", "stylist"}

    def test_admin_permissions_are_frozenset(self):
        """admin permissions value is a frozenset (immutable — FR-PERM-1)."""
        assert isinstance(ROLE_PERMISSIONS["admin"], frozenset)

    def test_stylist_permissions_are_frozenset(self):
        """stylist permissions value is a frozenset (immutable — FR-PERM-1)."""
        assert isinstance(ROLE_PERMISSIONS["stylist"], frozenset)

    def test_frozenset_immutable_cannot_be_mutated(self):
        """frozenset raises AttributeError on mutation attempts."""
        with pytest.raises(AttributeError):
            ROLE_PERMISSIONS["admin"].add("should_fail")  # type: ignore[attr-defined]


class TestAdminPermissions:
    """Verify exact admin permission strings (FR-PERM-2)."""

    def test_admin_has_users_manage(self):
        assert "users:manage" in ROLE_PERMISSIONS["admin"]

    def test_admin_has_system_settings(self):
        assert "system:settings" in ROLE_PERMISSIONS["admin"]

    def test_admin_has_escalations_resolve(self):
        assert "escalations:resolve" in ROLE_PERMISSIONS["admin"]

    def test_admin_has_customers_delete(self):
        assert "customers:delete" in ROLE_PERMISSIONS["admin"]

    def test_admin_has_conversations_read(self):
        assert "conversations:read" in ROLE_PERMISSIONS["admin"]

    def test_admin_has_conversations_write(self):
        assert "conversations:write" in ROLE_PERMISSIONS["admin"]

    def test_admin_has_appointments_read(self):
        assert "appointments:read" in ROLE_PERMISSIONS["admin"]

    def test_admin_has_appointments_write(self):
        assert "appointments:write" in ROLE_PERMISSIONS["admin"]

    def test_admin_has_customers_read(self):
        assert "customers:read" in ROLE_PERMISSIONS["admin"]

    def test_admin_has_customers_write(self):
        assert "customers:write" in ROLE_PERMISSIONS["admin"]

    def test_admin_has_calendar_read(self):
        assert "calendar:read" in ROLE_PERMISSIONS["admin"]

    def test_admin_has_bot_pause(self):
        assert "bot:pause" in ROLE_PERMISSIONS["admin"]

    def test_admin_has_bot_resume(self):
        assert "bot:resume" in ROLE_PERMISSIONS["admin"]

    def test_admin_has_templates_send(self):
        assert "templates:send" in ROLE_PERMISSIONS["admin"]


class TestStylistPermissions:
    """Verify exact stylist permission strings (FR-PERM-2)."""

    def test_stylist_has_conversations_read(self):
        assert "conversations:read" in ROLE_PERMISSIONS["stylist"]

    def test_stylist_has_conversations_write(self):
        assert "conversations:write" in ROLE_PERMISSIONS["stylist"]

    def test_stylist_has_appointments_read(self):
        assert "appointments:read" in ROLE_PERMISSIONS["stylist"]

    def test_stylist_has_appointments_write(self):
        assert "appointments:write" in ROLE_PERMISSIONS["stylist"]

    def test_stylist_has_customers_read(self):
        assert "customers:read" in ROLE_PERMISSIONS["stylist"]

    def test_stylist_has_customers_write(self):
        assert "customers:write" in ROLE_PERMISSIONS["stylist"]

    def test_stylist_has_calendar_read(self):
        assert "calendar:read" in ROLE_PERMISSIONS["stylist"]

    def test_stylist_has_bot_pause(self):
        assert "bot:pause" in ROLE_PERMISSIONS["stylist"]

    def test_stylist_has_bot_resume(self):
        assert "bot:resume" in ROLE_PERMISSIONS["stylist"]

    def test_stylist_has_templates_send(self):
        assert "templates:send" in ROLE_PERMISSIONS["stylist"]

    def test_stylist_does_not_have_users_manage(self):
        assert "users:manage" not in ROLE_PERMISSIONS["stylist"]

    def test_stylist_does_not_have_system_settings(self):
        assert "system:settings" not in ROLE_PERMISSIONS["stylist"]

    def test_stylist_does_not_have_escalations_resolve(self):
        assert "escalations:resolve" not in ROLE_PERMISSIONS["stylist"]

    def test_stylist_does_not_have_customers_delete(self):
        assert "customers:delete" not in ROLE_PERMISSIONS["stylist"]


class TestAllPermissions:
    """Tests for ALL_PERMISSIONS aggregated set."""

    def test_all_permissions_is_frozenset(self):
        """ALL_PERMISSIONS is a frozenset."""
        assert isinstance(ALL_PERMISSIONS, frozenset)

    def test_all_permissions_is_union_of_all_roles(self):
        """ALL_PERMISSIONS is the union of all role permission sets."""
        expected_union = frozenset().union(*ROLE_PERMISSIONS.values())
        assert ALL_PERMISSIONS == expected_union


class TestHasPermission:
    """Tests for has_permission() helper function."""

    def test_admin_has_users_manage(self):
        assert has_permission("admin", "users:manage") is True

    def test_admin_has_conversations_read(self):
        assert has_permission("admin", "conversations:read") is True

    def test_stylist_does_not_have_users_manage(self):
        assert has_permission("stylist", "users:manage") is False

    def test_stylist_has_appointments_read(self):
        assert has_permission("stylist", "appointments:read") is True

    def test_unknown_role_returns_false(self):
        """Unknown role name returns False without raising (FR-PERM-1)."""
        assert has_permission("unknown_role", "conversations:read") is False

    def test_empty_role_returns_false(self):
        """Empty role returns False."""
        assert has_permission("", "conversations:read") is False

    def test_unknown_action_returns_false(self):
        """Known role with unknown action returns False."""
        assert has_permission("admin", "nonexistent:action") is False

    def test_has_permission_returns_bool(self):
        """has_permission always returns a bool."""
        result = has_permission("admin", "users:manage")
        assert isinstance(result, bool)
