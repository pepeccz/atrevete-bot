"use client";

import { useEffect, useState, useCallback } from "react";
import { ColumnDef } from "@tanstack/react-table";
import {
  MoreHorizontal,
  Plus,
  Edit,
  Check,
  X,
  Calendar,
} from "lucide-react";

import { Header } from "@/components/layout/header";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { DataTable, SortableHeader } from "@/components/ui/data-table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { toast } from "sonner";
import api from "@/lib/api";
import type { Stylist, ServiceCategory, GoogleCalendar, CalendarOption, CalendarOptionStatus } from "@/lib/types";
import { CALENDAR_OPTION_STATUS } from "@/lib/types";
import { ApiRequestError } from "@/lib/api";

// Category badge
function CategoryBadge({ category }: { category: ServiceCategory }) {
  const variants: Record<ServiceCategory, "default" | "secondary" | "info"> = {
    HAIRDRESSING: "default",
    AESTHETICS: "secondary",
    BOTH: "info",
  };

  const labels: Record<ServiceCategory, string> = {
    HAIRDRESSING: "Peluqueria",
    AESTHETICS: "Estetica",
    BOTH: "Ambos",
  };

  return <Badge variant={variants[category]}>{labels[category]}</Badge>;
}

// Stylist form modal
interface StylistFormData {
  name: string;
  category: ServiceCategory;
  google_calendar_id: string;
  is_active: boolean;
  color: string | null;
}

// Color palette for stylists (matches calendar-view.tsx)
const STYLIST_COLORS = [
  { bg: "#7C3AED", name: "Violeta" },
  { bg: "#2563EB", name: "Azul" },
  { bg: "#059669", name: "Esmeralda" },
  { bg: "#DC2626", name: "Rojo" },
  { bg: "#D97706", name: "Ámbar" },
  { bg: "#7C2D12", name: "Marrón" },
  { bg: "#DB2777", name: "Rosa" },
  { bg: "#0891B2", name: "Cian" },
];

function StylistModal({
  open,
  onOpenChange,
  onSuccess,
  stylist,
  allStylists,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
  stylist?: Stylist | null;
  allStylists: Stylist[];
}) {
  const [loading, setLoading] = useState(false);
  const [availableCalendars, setAvailableCalendars] = useState<GoogleCalendar[]>([]);
  const [loadingCalendars, setLoadingCalendars] = useState(false);
  const [conflictError, setConflictError] = useState<{ message: string; stylistNames: string[] } | null>(null);
  const [formData, setFormData] = useState<StylistFormData>({
    name: "",
    category: "HAIRDRESSING",
    google_calendar_id: "",
    is_active: true,
    color: null,
  });

  useEffect(() => {
    if (stylist) {
      setFormData({
        name: stylist.name,
        category: stylist.category,
        google_calendar_id: stylist.google_calendar_id ?? "",
        is_active: stylist.is_active,
        color: stylist.color || null,
      });
    } else {
      setFormData({
        name: "",
        category: "HAIRDRESSING",
        google_calendar_id: "",
        is_active: true,
        color: null,
      });
    }
    // Clear conflict error when modal opens/closes or stylist changes
    setConflictError(null);
  }, [stylist, open]);

  // Load available calendars when modal opens
  useEffect(() => {
    if (!open) return;
    setLoadingCalendars(true);
    api.getGoogleCalendars()
      .then((data) => setAvailableCalendars(data.calendars))
      .catch(() => setAvailableCalendars([]))
      .finally(() => setLoadingCalendars(false));
  }, [open]);

  // Build classified calendar options (available | current | occupied)
  const buildCalendarOptions = (): CalendarOption[] => {
    const currentStylistId = stylist?.id;
    const currentCalendarId = stylist?.google_calendar_id;

    // Build a map of calendar_id -> stylist name for quick lookup
    const calendarOwners = new Map<string, string>();
    allStylists.forEach((s) => {
      if (s.google_calendar_id) {
        calendarOwners.set(s.google_calendar_id, s.name);
      }
    });

    return availableCalendars.map((cal) => {
      const ownerName = calendarOwners.get(cal.id);

      // Classify the calendar
      let status: CalendarOptionStatus = CALENDAR_OPTION_STATUS.AVAILABLE;

      if (cal.id === currentCalendarId) {
        // This is the current stylist's own calendar
        status = CALENDAR_OPTION_STATUS.CURRENT;
      } else if (ownerName && ownerName !== stylist?.name) {
        // This calendar is owned by a different stylist
        status = CALENDAR_OPTION_STATUS.OCCUPIED;
      }

      return {
        calendar: cal,
        status,
        ownerStylistName: ownerName,
      };
    });
  };

  const calendarOptions = buildCalendarOptions();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name) {
      toast.error("El nombre del estilista es requerido");
      return;
    }

    setLoading(true);
    setConflictError(null);

    try {
      if (stylist) {
        await api.update("stylists", stylist.id, {
          name: formData.name,
          category: formData.category,
          google_calendar_id: formData.google_calendar_id,
          is_active: formData.is_active,
          color: formData.color,
        });
        toast.success("Estilista actualizado correctamente");
      } else {
        await api.create("stylists", {
          name: formData.name,
          category: formData.category,
          google_calendar_id: formData.google_calendar_id,
          is_active: formData.is_active,
          color: formData.color,
        });
        toast.success("Estilista creado correctamente");
      }
      onOpenChange(false);
      onSuccess();
    } catch (error) {
      // Handle 409 Conflict errors (calendar already assigned)
      if (error instanceof ApiRequestError && error.status === 409) {
        const stylistNames = error.stylistNames || [];
        setConflictError({
          message: error.message,
          stylistNames,
        });
        // Don't close the modal - let user pick a different calendar
        toast.error("El calendario seleccionado ya está en uso");
      } else {
        toast.error(
          `Error: ${error instanceof Error ? error.message : "Unknown error"}`
        );
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {stylist ? "Editar Estilista" : "Nuevo Estilista"}
          </DialogTitle>
          <DialogDescription>
            {stylist
              ? "Actualiza la informacion del estilista"
              : "Crea un nuevo estilista"}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name">Nombre *</Label>
            <Input
              id="name"
              value={formData.name}
              onChange={(e) =>
                setFormData((prev) => ({ ...prev, name: e.target.value }))
              }
              placeholder="Maria Garcia"
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="category">Categoria</Label>
            <Select
              value={formData.category}
              onValueChange={(value) =>
                setFormData((prev) => ({
                  ...prev,
                  category: value as ServiceCategory,
                }))
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="HAIRDRESSING">Peluqueria</SelectItem>
                <SelectItem value="AESTHETICS">Estetica</SelectItem>
                <SelectItem value="BOTH">Ambos</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="google_calendar_id">Google Calendar</Label>
            {availableCalendars.length > 0 ? (
              <>
                <Select
                  value={formData.google_calendar_id}
                  onValueChange={(value) => {
                    setFormData((prev) => ({
                      ...prev,
                      google_calendar_id: value,
                    }));
                    // Clear conflict error when user changes selection
                    setConflictError(null);
                  }}
                  disabled={loadingCalendars}
                >
                  <SelectTrigger id="google_calendar_id">
                    <SelectValue placeholder="Selecciona un calendario..." />
                  </SelectTrigger>
                  <SelectContent>
                    {calendarOptions.map((option) => {
                      const isOccupied = option.status === CALENDAR_OPTION_STATUS.OCCUPIED;
                      const isCurrent = option.status === CALENDAR_OPTION_STATUS.CURRENT;

                      return (
                        <SelectItem
                          key={option.calendar.id}
                          value={option.calendar.id}
                          disabled={isOccupied}
                          className={isOccupied ? "text-muted-foreground" : undefined}
                        >
                          <div className="flex items-center justify-between w-full gap-4">
                            <span>{option.calendar.summary}</span>
                            {isCurrent && (
                              <Badge variant="outline" className="text-xs">
                                Actual
                              </Badge>
                            )}
                            {isOccupied && option.ownerStylistName && (
                              <Badge variant="secondary" className="text-xs bg-red-100 text-red-700 border-red-200">
                                Ocupado: {option.ownerStylistName}
                              </Badge>
                            )}
                          </div>
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
                {conflictError && (
                  <div className="rounded-md bg-red-50 p-3 text-sm text-red-700 border border-red-200">
                    <p className="font-medium">Conflicto de calendario</p>
                    <p>{conflictError.message}</p>
                    {conflictError.stylistNames.length > 0 && (
                      <p className="mt-1 text-red-600">
                        Asignado a: {conflictError.stylistNames.join(", ")}
                      </p>
                    )}
                  </div>
                )}
                <p className="text-xs text-muted-foreground">
                  Selecciona el calendario de Google de este estilista.
                  Los calendarios marcados como &quot;Ocupado&quot; ya están asignados a otro estilista.
                </p>
              </>
            ) : (
              <>
                <Input
                  id="google_calendar_id"
                  value={formData.google_calendar_id}
                  onChange={(e) => {
                    setFormData((prev) => ({
                      ...prev,
                      google_calendar_id: e.target.value,
                    }));
                    setConflictError(null);
                  }}
                  placeholder="calendario@group.calendar.google.com"
                  disabled={loadingCalendars}
                />
                {conflictError && (
                  <div className="rounded-md bg-red-50 p-3 text-sm text-red-700 border border-red-200">
                    <p className="font-medium">Conflicto de calendario</p>
                    <p>{conflictError.message}</p>
                    {conflictError.stylistNames.length > 0 && (
                      <p className="mt-1 text-red-600">
                        Asignado a: {conflictError.stylistNames.join(", ")}
                      </p>
                    )}
                  </div>
                )}
                <p className="text-xs text-muted-foreground">
                  ID del calendario de Google asociado a este estilista.{" "}
                  <a
                    href="/settings/google-calendar"
                    className="underline hover:text-foreground"
                  >
                    Conecta Google Calendar en Ajustes
                  </a>{" "}
                  para ver los calendarios disponibles.
                </p>
              </>
            )}
          </div>

          <div className="flex items-center space-x-2">
            <Checkbox
              id="is_active"
              checked={formData.is_active}
              onCheckedChange={(checked) =>
                setFormData((prev) => ({
                  ...prev,
                  is_active: checked === true,
                }))
              }
            />
            <Label htmlFor="is_active" className="cursor-pointer">
              Estilista activo
            </Label>
          </div>

          <div className="space-y-2">
            <Label>Color del calendario</Label>
            <div className="flex flex-wrap gap-2">
              {STYLIST_COLORS.map((color) => (
                <button
                  key={color.bg}
                  type="button"
                  onClick={() =>
                    setFormData((prev) => ({ ...prev, color: color.bg }))
                  }
                  className={`w-8 h-8 rounded-full border-2 transition-all ${
                    formData.color === color.bg
                      ? "border-gray-900 scale-110"
                      : "border-transparent hover:scale-105"
                  }`}
                  style={{ backgroundColor: color.bg }}
                  title={color.name}
                />
              ))}
              <button
                type="button"
                onClick={() => setFormData((prev) => ({ ...prev, color: null }))}
                className={`w-8 h-8 rounded-full border-2 transition-all flex items-center justify-center text-xs ${
                  formData.color === null
                    ? "border-gray-900 scale-110 bg-gray-100"
                    : "border-gray-300 hover:scale-105 bg-gray-50"
                }`}
                title="Automático (por orden)"
              >
                Auto
              </button>
            </div>
            <p className="text-xs text-muted-foreground">
              Selecciona un color o deja en automático
            </p>
          </div>

          <div className="flex justify-end gap-2 pt-4">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancelar
            </Button>
            <Button type="submit" disabled={loading}>
              {loading
                ? "Guardando..."
                : stylist
                  ? "Actualizar"
                  : "Crear Estilista"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function StylistsPage() {
  const [stylists, setStylists] = useState<Stylist[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingStylist, setEditingStylist] = useState<Stylist | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [stylistToDelete, setStylistToDelete] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.list<Stylist>("stylists", { page_size: 100 });
      setStylists(res.items);
    } catch (error) {
      toast.error("Error al cargar los estilistas");
      console.error(error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleEdit = (stylist: Stylist) => {
    setEditingStylist(stylist);
    setModalOpen(true);
  };

  const handleCreate = () => {
    setEditingStylist(null);
    setModalOpen(true);
  };

  const handleDelete = async () => {
    if (!stylistToDelete) return;

    try {
      await api.delete("stylists", stylistToDelete);
      toast.success("Estilista eliminado");
      loadData();
    } catch (error) {
      toast.error("Error al eliminar el estilista");
      console.error(error);
    } finally {
      setDeleteDialogOpen(false);
      setStylistToDelete(null);
    }
  };

  const columns: ColumnDef<Stylist>[] = [
    {
      accessorKey: "name",
      header: ({ column }) => (
        <SortableHeader column={column}>Nombre</SortableHeader>
      ),
    },
    {
      accessorKey: "category",
      header: "Categoria",
      cell: ({ row }) => (
        <CategoryBadge category={row.getValue("category") as ServiceCategory} />
      ),
    },
    {
      accessorKey: "google_calendar_id",
      header: () => (
        <div className="flex items-center">
          <Calendar className="mr-2 h-4 w-4" />
          Google Calendar
        </div>
      ),
      cell: ({ row }) => {
        const calId = row.getValue("google_calendar_id") as string;
        return calId.length > 30 ? calId.substring(0, 30) + "..." : calId;
      },
    },
    {
      accessorKey: "is_active",
      header: "Activo",
      cell: ({ row }) =>
        row.getValue("is_active") ? (
          <Check className="h-4 w-4 text-green-500" />
        ) : (
          <X className="h-4 w-4 text-red-500" />
        ),
    },
    {
      id: "actions",
      cell: ({ row }) => {
        const stylist = row.original;
        return (
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={() => handleEdit(stylist)}
            >
              <Edit className="h-4 w-4" />
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" className="h-8 w-8 p-0">
                  <MoreHorizontal className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  onClick={() => {
                    setStylistToDelete(stylist.id);
                    setDeleteDialogOpen(true);
                  }}
                  className="text-destructive"
                >
                  Eliminar
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        );
      },
    },
  ];

  return (
    <div className="flex flex-col">
      <Header
        title="Estilistas"
        description="Gestion de estilistas del salon"
        action={
          <Button onClick={handleCreate}>
            <Plus className="mr-2 h-4 w-4" />
            Nuevo Estilista
          </Button>
        }
      />

      <div className="flex-1 p-6">
        <Card>
          <CardContent className="pt-6">
            <DataTable
              columns={columns}
              data={stylists}
              isLoading={loading}
              searchKey="name"
              searchPlaceholder="Buscar por nombre..."
            />
          </CardContent>
        </Card>
      </div>

      {/* Create/Edit Modal */}
      <StylistModal
        key={editingStylist?.id ?? 'new'}
        open={modalOpen}
        onOpenChange={setModalOpen}
        onSuccess={loadData}
        stylist={editingStylist}
        allStylists={stylists}
      />

      {/* Delete Confirmation */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar estilista</AlertDialogTitle>
            <AlertDialogDescription>
              Esta accion no se puede deshacer. El estilista sera eliminado
              permanentemente.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Eliminar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
