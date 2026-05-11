"use client";

import { usePermission } from "@/hooks/use-permission";

interface RequirePermissionProps {
  /** The permission action to check (e.g. "system:settings", "users:manage"). */
  action: string;
  /** Content to render when the user has the permission. */
  children: React.ReactNode;
  /** Content to render when the user lacks the permission. Defaults to null (hidden). */
  fallback?: React.ReactNode;
}

/**
 * Declarative gating wrapper: renders `children` only when the current user
 * holds `action`, otherwise renders `fallback` (default: nothing).
 *
 * Usage:
 *   <RequirePermission action="system:settings">
 *     <AdminOnlyComponent />
 *   </RequirePermission>
 *
 *   <RequirePermission action="users:manage" fallback={<p>Access denied</p>}>
 *     <UserManagementPanel />
 *   </RequirePermission>
 */
export function RequirePermission({
  action,
  children,
  fallback = null,
}: RequirePermissionProps) {
  const allowed = usePermission(action);
  return allowed ? <>{children}</> : <>{fallback}</>;
}
