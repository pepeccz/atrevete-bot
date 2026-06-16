"use client";

import React, { useEffect, useState, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { ColumnDef } from "@tanstack/react-table";
import {
  Shield,
  Plus,
  Edit,
  KeyRound,
  UserX,
  UserCheck,
  Lock,
} from "lucide-react";

import { Header } from "@/components/layout/header";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { formatDate } from "@/components/shared/format-utils";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { AdminUser, AdminUserCreateRequest, AdminUserRole } from "@/lib/types";
import { usePermission } from "@/hooks/use-permission";
import { useAuth } from "@/contexts/auth-context";

// ── User Form Modal ────────────────────────────────────────────────────────────

function UserFormModal({
  open,
  onOpenChange,
  onSuccess,
  user,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
  user?: AdminUser | null;
}) {
  const isEdit = !!user;
  const [loading, setLoading] = useState(false);

  // Local form state (no global form library per project conventions)
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<AdminUserRole>("stylist");
  const [displayName, setDisplayName] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (open) {
      if (user) {
        setUsername(user.username);
        setPassword("");
        setRole(user.role);
        setDisplayName(user.display_name ?? "");
      } else {
        setUsername("");
        setPassword("");
        setRole("stylist");
        setDisplayName("");
      }
      setErrors({});
    }
  }, [open, user]);

  function validate(): boolean {
    const newErrors: Record<string, string> = {};
    if (!username || username.length < 3 || username.length > 64) {
      newErrors.username = "El nombre de usuario debe tener entre 3 y 64 caracteres.";
    }
    if (!isEdit && (!password || password.length < 8)) {
      newErrors.password = "La contraseña debe tener al menos 8 caracteres.";
    }
    if (isEdit && password && password.length < 8) {
      newErrors.password = "La contraseña debe tener al menos 8 caracteres.";
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;

    setLoading(true);
    try {
      if (isEdit && user) {
        const updateData: { role?: AdminUserRole; display_name?: string | null } = {
          role,
          display_name: displayName || null,
        };
        await api.updateUser(user.id, updateData);
        toast.success("Usuario actualizado correctamente");
      } else {
        const createData: AdminUserCreateRequest = {
          username,
          password,
          role,
          display_name: displayName || null,
        };
        await api.createUser(createData);
        toast.success("Usuario creado correctamente");
      }
      onOpenChange(false);
      onSuccess();
    } catch (error) {
      toast.error(`Error: ${error instanceof Error ? error.message : "Error desconocido"}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Editar Usuario" : "Nuevo Usuario"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Modifica el rol o nombre visible del usuario."
              : "Crea un nuevo usuario administrador o estilista."}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Username — readonly on edit */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Nombre de usuario *</label>
            <Input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={isEdit}
              placeholder="ej. maria_garcia"
              autoComplete="off"
            />
            {errors.username && (
              <p className="text-xs text-destructive">{errors.username}</p>
            )}
          </div>

          {/* Password — required on create, optional on edit */}
          <div className="space-y-1">
            <label className="text-sm font-medium">
              Contraseña {isEdit ? "(dejar en blanco para no cambiar)" : "*"}
            </label>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={isEdit ? "••••••••" : "Mínimo 8 caracteres"}
              autoComplete="new-password"
            />
            {errors.password && (
              <p className="text-xs text-destructive">{errors.password}</p>
            )}
          </div>

          {/* Role */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Rol *</label>
            <Select value={role} onValueChange={(v) => setRole(v as AdminUserRole)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="admin">Admin</SelectItem>
                <SelectItem value="stylist">Estilista</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Display name */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Nombre visible (opcional)</label>
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="ej. María García"
              maxLength={120}
            />
          </div>

          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? "Guardando..." : isEdit ? "Actualizar" : "Crear Usuario"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ── Reset Password Modal ───────────────────────────────────────────────────────

function ResetPasswordModal({
  open,
  onOpenChange,
  onSuccess,
  userId,
  username,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
  userId: string;
  username: string;
}) {
  const [newPassword, setNewPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (open) {
      setNewPassword("");
      setError("");
    }
  }, [open]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword.length < 8) {
      setError("La contraseña debe tener al menos 8 caracteres.");
      return;
    }
    setLoading(true);
    try {
      await api.resetUserPassword(userId, newPassword);
      toast.success(`Contraseña de "${username}" actualizada`);
      onOpenChange(false);
      onSuccess();
    } catch (err) {
      toast.error(`Error: ${err instanceof Error ? err.message : "Error desconocido"}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Restablecer contraseña</DialogTitle>
          <DialogDescription>
            Establecé una nueva contraseña para <strong>{username}</strong>.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1">
            <label className="text-sm font-medium">Nueva contraseña *</label>
            <Input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="Mínimo 8 caracteres"
              autoComplete="new-password"
            />
            {error && <p className="text-xs text-destructive">{error}</p>}
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? "Guardando..." : "Restablecer"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────────

export default function UsersPage() {
  const router = useRouter();
  const { user: currentUser } = useAuth();
  const canManageUsers = usePermission("users:manage");

  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);

  // Modals
  const [formOpen, setFormOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<AdminUser | null>(null);
  const [resetPasswordOpen, setResetPasswordOpen] = useState(false);
  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null);
  const [deactivateOpen, setDeactivateOpen] = useState(false);
  const [deactivateTarget, setDeactivateTarget] = useState<AdminUser | null>(null);

  // Route protection (FR-UI-6): redirect non-admin users
  useEffect(() => {
    if (!canManageUsers) {
      router.replace("/dashboard");
    }
  }, [canManageUsers, router]);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.listUsers({ limit: 100, offset: 0 });
      setUsers(res.items);
    } catch {
      toast.error("Error al cargar los usuarios");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (canManageUsers) {
      loadUsers();
    }
  }, [canManageUsers, loadUsers]);

  const handleCreate = () => {
    setEditingUser(null);
    setFormOpen(true);
  };

  const handleEdit = useCallback((user: AdminUser) => {
    setEditingUser(user);
    setFormOpen(true);
  }, []);

  const handleResetPassword = useCallback((user: AdminUser) => {
    setResetTarget(user);
    setResetPasswordOpen(true);
  }, []);

  const handleDeactivate = useCallback((user: AdminUser) => {
    setDeactivateTarget(user);
    setDeactivateOpen(true);
  }, []);

  const handleReactivate = useCallback(async (user: AdminUser) => {
    try {
      await api.updateUser(user.id, { is_active: true });
      toast.success(`Usuario "${user.username}" reactivado`);
      loadUsers();
    } catch (err) {
      toast.error(`Error: ${err instanceof Error ? err.message : "Error desconocido"}`);
    }
  }, [loadUsers]);

  const confirmDeactivate = async () => {
    if (!deactivateTarget) return;
    try {
      await api.updateUser(deactivateTarget.id, { is_active: false });
      toast.success(`Usuario "${deactivateTarget.username}" desactivado`);
      loadUsers();
    } catch (err) {
      toast.error(`Error: ${err instanceof Error ? err.message : "Error desconocido"}`);
    } finally {
      setDeactivateOpen(false);
      setDeactivateTarget(null);
    }
  };

  const columns = useMemo<ColumnDef<AdminUser>[]>(
    () => [
      {
        accessorKey: "username",
        header: "Usuario",
        cell: ({ row }) => (
          <span className="font-medium text-ink">{row.original.username}</span>
        ),
      },
      {
        accessorKey: "display_name",
        header: "Nombre visible",
        cell: ({ row }) => row.original.display_name ?? (
          <span className="text-ink-mute italic">—</span>
        ),
      },
      {
        accessorKey: "role",
        header: "Rol",
        cell: ({ row }) => (
          <Badge variant={row.original.role === "admin" ? "default" : "secondary"}>
            {row.original.role === "admin" ? "Admin" : "Estilista"}
          </Badge>
        ),
      },
      {
        accessorKey: "is_active",
        header: "Estado",
        cell: ({ row }) => (
          <Badge variant={row.original.is_active ? "default" : "secondary"}
            className={row.original.is_active
              ? "bg-green-100 text-green-800 border-green-200"
              : "bg-red-100 text-red-800 border-red-200"
            }
          >
            {row.original.is_active ? "Activo" : "Inactivo"}
          </Badge>
        ),
      },
      {
        accessorKey: "last_login_at",
        header: "Último acceso",
        cell: ({ row }) =>
          row.original.last_login_at
            ? formatDate(row.original.last_login_at, false)
            : <span className="text-ink-mute italic">Nunca</span>,
      },
      {
        id: "actions",
        header: "Acciones",
        cell: ({ row }) => {
          const u = row.original;
          const isSelf = currentUser?.id === u.id;
          return (
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                title="Editar"
                onClick={() => handleEdit(u)}
              >
                <Edit className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                title="Restablecer contraseña"
                onClick={() => handleResetPassword(u)}
              >
                <KeyRound className="h-4 w-4" />
              </Button>
              {u.is_active ? (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-orange-600 hover:text-orange-700"
                  title={isSelf ? "No puedes desactivar tu propia cuenta" : "Desactivar"}
                  disabled={isSelf}
                  onClick={() => !isSelf && handleDeactivate(u)}
                >
                  <UserX className="h-4 w-4" />
                </Button>
              ) : (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-green-600 hover:text-green-700"
                  title="Reactivar"
                  onClick={() => handleReactivate(u)}
                >
                  <UserCheck className="h-4 w-4" />
                </Button>
              )}
            </div>
          );
        },
      },
    ],
    [currentUser, handleEdit, handleResetPassword, handleDeactivate, handleReactivate]
  );

  // Don't render content for non-admin users (redirect in progress)
  if (!canManageUsers) {
    return null;
  }

  return (
    <div className="flex flex-col">
      <Header
        title="Usuarios"
        description="Gestión de usuarios del panel de administración"
        action={
          <Button onClick={handleCreate}>
            <Plus className="mr-2 h-4 w-4" />
            Nuevo usuario
          </Button>
        }
      />

      <div className="flex-1 p-4 md:p-6">
        <Card>
          <CardContent className="pt-6">
            {!loading && users.length === 0 ? (
              <EmptyState
                icon={Lock}
                title="No hay usuarios registrados"
                description="Crea el primer usuario administrador o estilista."
                action={{ label: "Nuevo usuario", onClick: handleCreate }}
              />
            ) : (
              <DataTable
                columns={columns}
                data={users}
                isLoading={loading}
                searchKey="username"
                searchPlaceholder="Buscar por usuario..."
              />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Create / Edit Modal */}
      <UserFormModal
        open={formOpen}
        onOpenChange={setFormOpen}
        onSuccess={loadUsers}
        user={editingUser}
      />

      {/* Reset Password Modal */}
      {resetTarget && (
        <ResetPasswordModal
          open={resetPasswordOpen}
          onOpenChange={setResetPasswordOpen}
          onSuccess={loadUsers}
          userId={resetTarget.id}
          username={resetTarget.username}
        />
      )}

      {/* Deactivate Confirmation */}
      <AlertDialog open={deactivateOpen} onOpenChange={setDeactivateOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Desactivar usuario</AlertDialogTitle>
            <AlertDialogDescription>
              El usuario <strong>{deactivateTarget?.username}</strong> no podrá iniciar sesión.
              Puedes reactivarlo en cualquier momento.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDeactivate}
              className="bg-orange-600 text-white hover:bg-orange-700"
            >
              Desactivar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
