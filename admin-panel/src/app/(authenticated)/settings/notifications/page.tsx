"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Bell,
  Download,
  Mail,
  MailOpen,
  Star,
  Trash2,
  RefreshCw,
} from "lucide-react";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { Header } from "@/components/layout/header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
import { toast } from "sonner";
import api from "@/lib/api";
import type {
  Notification,
  NotificationQueryParams,
  NotificationStatsResponse,
  NotificationsPaginatedResponse,
} from "@/lib/types";
import { NotificationsByCategoryChart } from "@/components/charts/notifications-by-category-chart";
import { NotificationsTrendChart } from "@/components/charts/notifications-trend-chart";
import { NotificationsFilters } from "@/components/notifications/notifications-filters";
import { getNotificationColumns } from "@/components/notifications/notifications-columns";

export default function NotificationsPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<NotificationStatsResponse | null>(null);
  const [data, setData] = useState<NotificationsPaginatedResponse | null>(null);
  const [filters, setFilters] = useState<NotificationQueryParams>({
    page: 1,
    page_size: 20,
  });
  const [rowSelection, setRowSelection] = useState({});
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  // Fetch stats
  const fetchStats = useCallback(async () => {
    try {
      const statsData = await api.getNotificationStats();
      setStats(statsData);
    } catch (error) {
      console.error("Error fetching stats:", error);
    }
  }, []);

  // Fetch notifications
  const fetchNotifications = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.getNotificationsPaginated(filters);
      setData(response);
    } catch (error) {
      console.error("Error fetching notifications:", error);
      toast.error("Error al cargar las notificaciones");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  // Initial fetch
  useEffect(() => {
    fetchStats();
    fetchNotifications();
  }, [fetchStats, fetchNotifications]);

  // Handlers
  const handleToggleStar = async (id: string) => {
    try {
      const result = await api.toggleNotificationStar(id);
      setData((prev) =>
        prev
          ? {
              ...prev,
              items: prev.items.map((n) =>
                n.id === id
                  ? { ...n, is_starred: result.is_starred, starred_at: result.starred_at }
                  : n
              ),
            }
          : null
      );
      toast.success(result.is_starred ? "Marcada como favorita" : "Favorita eliminada");
      fetchStats();
    } catch (error) {
      toast.error("Error al actualizar favorita");
    }
  };

  const handleMarkRead = async (id: string) => {
    try {
      await api.markNotificationRead(id);
      setData((prev) =>
        prev
          ? {
              ...prev,
              items: prev.items.map((n) =>
                n.id === id ? { ...n, is_read: true } : n
              ),
              unread_count: Math.max(0, prev.unread_count - 1),
            }
          : null
      );
      toast.success("Marcada como leida");
      fetchStats();
    } catch (error) {
      toast.error("Error al marcar como leida");
    }
  };

  const handleMarkUnread = async (id: string) => {
    try {
      await api.markNotificationUnread(id);
      setData((prev) =>
        prev
          ? {
              ...prev,
              items: prev.items.map((n) =>
                n.id === id ? { ...n, is_read: false } : n
              ),
              unread_count: prev.unread_count + 1,
            }
          : null
      );
      toast.success("Marcada como no leida");
      fetchStats();
    } catch (error) {
      toast.error("Error al marcar como no leida");
    }
  };

  const handleDelete = (id: string) => {
    setDeleteTarget(id);
    setDeleteDialogOpen(true);
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      await api.deleteNotification(deleteTarget);
      setData((prev) =>
        prev
          ? {
              ...prev,
              items: prev.items.filter((n) => n.id !== deleteTarget),
              total: prev.total - 1,
            }
          : null
      );
      toast.success("Notificacion eliminada");
      fetchStats();
    } catch (error) {
      toast.error("Error al eliminar");
    } finally {
      setDeleteDialogOpen(false);
      setDeleteTarget(null);
    }
  };

  const handleNavigateToEntity = (notification: Notification) => {
    if (notification.entity_type === "appointment" && notification.entity_id) {
      router.push(`/appointments?highlight=${notification.entity_id}`);
    }
  };

  const handleBulkDelete = async () => {
    const selectedIds = Object.keys(rowSelection)
      .filter((key) => rowSelection[key as keyof typeof rowSelection])
      .map((index) => data?.items[parseInt(index)]?.id)
      .filter(Boolean) as string[];

    if (selectedIds.length === 0) return;

    try {
      const result = await api.bulkDeleteNotifications(selectedIds);
      toast.success(`${result.deleted} notificaciones eliminadas`);
      setRowSelection({});
      fetchNotifications();
      fetchStats();
    } catch (error) {
      toast.error("Error al eliminar notificaciones");
    }
  };

  const handleBulkMarkRead = async () => {
    const selectedIds = Object.keys(rowSelection)
      .filter((key) => rowSelection[key as keyof typeof rowSelection])
      .map((index) => data?.items[parseInt(index)]?.id)
      .filter(Boolean) as string[];

    for (const id of selectedIds) {
      await api.markNotificationRead(id);
    }
    toast.success("Notificaciones marcadas como leidas");
    setRowSelection({});
    fetchNotifications();
    fetchStats();
  };

  const handleExport = () => {
    const url = api.getNotificationsExportUrl(filters);
    window.open(url, "_blank");
  };

  const handleRefresh = () => {
    fetchStats();
    fetchNotifications();
  };

  // Table columns
  const columns = getNotificationColumns({
    onToggleStar: handleToggleStar,
    onMarkRead: handleMarkRead,
    onMarkUnread: handleMarkUnread,
    onDelete: handleDelete,
    onNavigateToEntity: handleNavigateToEntity,
  });

  const table = useReactTable({
    data: data?.items || [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    onRowSelectionChange: setRowSelection,
    state: {
      rowSelection,
    },
  });

  const selectedCount = Object.keys(rowSelection).filter(
    (key) => rowSelection[key as keyof typeof rowSelection]
  ).length;

  return (
    <div className="flex flex-col">
      <Header
        title="Centro de Notificaciones"
        description="Historial completo, estadisticas y gestion de notificaciones"
      />

      <div className="flex-1 p-6 space-y-6">
        {/* Stats Cards */}
        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total</CardTitle>
              <Bell className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats?.total || 0}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">No Leidas</CardTitle>
              <Mail className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-primary">
                {stats?.unread || 0}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Favoritas</CardTitle>
              <Star className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-yellow-500">
                {stats?.starred || 0}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Charts */}
        <div className="grid gap-4 md:grid-cols-2">
          {stats && (
            <>
              <NotificationsByCategoryChart data={stats.by_category} />
              <NotificationsTrendChart data={stats.trend} />
            </>
          )}
        </div>

        {/* Filters */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-lg">Filtros</CardTitle>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={handleRefresh}>
                <RefreshCw className="h-4 w-4 mr-2" />
                Actualizar
              </Button>
              <Button variant="outline" size="sm" onClick={handleExport}>
                <Download className="h-4 w-4 mr-2" />
                Exportar CSV
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <NotificationsFilters
              filters={filters}
              onFiltersChange={setFilters}
            />
          </CardContent>
        </Card>

        {/* Bulk Actions */}
        {selectedCount > 0 && (
          <Card className="bg-muted/50">
            <CardContent className="py-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">
                  {selectedCount} notificacion(es) seleccionada(s)
                </span>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleBulkMarkRead}
                  >
                    <MailOpen className="h-4 w-4 mr-2" />
                    Marcar leidas
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={handleBulkDelete}
                  >
                    <Trash2 className="h-4 w-4 mr-2" />
                    Eliminar
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Table */}
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <TableHead key={header.id}>
                        {header.isPlaceholder
                          ? null
                          : flexRender(
                              header.column.columnDef.header,
                              header.getContext()
                            )}
                      </TableHead>
                    ))}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {loading ? (
                  <TableRow>
                    <TableCell colSpan={columns.length} className="text-center py-10">
                      Cargando...
                    </TableCell>
                  </TableRow>
                ) : table.getRowModel().rows?.length ? (
                  table.getRowModel().rows.map((row) => (
                    <TableRow
                      key={row.id}
                      data-state={row.getIsSelected() && "selected"}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id}>
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext()
                          )}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={columns.length} className="text-center py-10">
                      No hay notificaciones
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        {/* Pagination */}
        {data && data.total > 0 && (
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">
              Mostrando {(filters.page! - 1) * filters.page_size! + 1} -{" "}
              {Math.min(filters.page! * filters.page_size!, data.total)} de {data.total}
            </span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setFilters({ ...filters, page: filters.page! - 1 })}
                disabled={filters.page === 1}
              >
                Anterior
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setFilters({ ...filters, page: filters.page! + 1 })}
                disabled={!data.has_more}
              >
                Siguiente
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar notificacion</AlertDialogTitle>
            <AlertDialogDescription>
              Esta accion no se puede deshacer. La notificacion sera eliminada permanentemente.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete}>Eliminar</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
