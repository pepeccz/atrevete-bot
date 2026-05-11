"""Role-based permission matrix — backend single source of truth.

PARITY CONTRACT: This dict MUST stay structurally identical to
``admin-panel/src/lib/permissions.ts``. Adding, removing, or moving a
permission requires editing BOTH files in the SAME PR.

CI test ``tests/integration/test_permission_parity.py`` enforces this.

Role names must remain in sync with the CHECK constraint on
``admin_users.role`` (``database/models.py::AdminUser``): only
``'admin'`` and ``'stylist'`` are valid role strings.
"""

from __future__ import annotations

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset(
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
    ),
    "stylist": frozenset(
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
    ),
}

ALL_PERMISSIONS: frozenset[str] = frozenset().union(*ROLE_PERMISSIONS.values())


def has_permission(role: str, action: str) -> bool:
    """Return True if ``role`` grants ``action``. Unknown role returns False.

    Args:
        role: The user's role string (e.g. ``'admin'``, ``'stylist'``).
        action: The permission action to check (e.g. ``'users:manage'``).

    Returns:
        ``True`` if the role's permission set contains the action,
        ``False`` for any unknown role or unknown action.
    """
    return action in ROLE_PERMISSIONS.get(role, frozenset())
