import { useAuth } from "@/contexts/auth-context";
import { ROLE_PERMISSIONS } from "@/lib/permissions";

/**
 * Returns true if the current user's role grants `action`.
 *
 * Returns false when:
 * - The user is not authenticated (`user` is null).
 * - The role is unknown (not in ROLE_PERMISSIONS).
 * - The role does not include the requested action.
 *
 * Usage:
 *   const canManageUsers = usePermission("users:manage");
 */
export function usePermission(action: string): boolean {
  const { user } = useAuth();
  if (!user) return false;
  const permissions = ROLE_PERMISSIONS[user.role];
  if (!permissions) return false;
  return permissions.has(action);
}
