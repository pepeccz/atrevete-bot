/**
 * Role-based permission matrix — frontend mirror of backend SSOT.
 *
 * PARITY CONTRACT: This dict MUST stay structurally identical to
 * `shared/permissions.py` (ROLE_PERMISSIONS). Adding, removing, or moving a
 * permission requires editing BOTH files in the SAME PR.
 *
 * CI test `tests/integration/test_permission_parity.py` enforces equality.
 *
 * DO NOT CHANGE THE SHAPE of ROLE_PERMISSIONS below without also updating
 * the regex parser in `tests/integration/test_permission_parity.py`.
 * The parser expects: `"<role>": new Set([...])` with one permission per line.
 */

export const ROLE_PERMISSIONS: Record<string, ReadonlySet<string>> = {
  admin: new Set([
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
  ]),
  stylist: new Set([
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
  ]),
};

/**
 * Return true if `role` grants `action`. Unknown role returns false.
 *
 * @param role - The user's role string (e.g. "admin", "stylist").
 * @param action - The permission action to check (e.g. "users:manage").
 */
export function hasPermission(role: string, action: string): boolean {
  const perms = ROLE_PERMISSIONS[role];
  if (!perms) return false;
  return perms.has(action);
}
