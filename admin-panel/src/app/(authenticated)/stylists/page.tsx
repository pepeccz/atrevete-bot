"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
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
  DialogFooter,
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
import { Checkbox } from "@/components/ui/checkbox";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { toast } from "sonner";
import api from "@/lib/api";
import type { Stylist, ServiceCategory, GoogleCalendar, CalendarOption, CalendarOptionStatus } from "@/lib/types";
import { CALENDAR_OPTION_STATUS } from "@/lib/types";
import { ApiRequestError } from "@/lib/api";
import { CategoryBadge } from "@/components/shared/category-badge";
import { StylistFormSchema, type StylistFormValues } from "./stylist-form.schema";

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

  const form = useForm<StylistFormValues>({
    resolver: zodResolver(StylistFormSchema),
    defaultValues: {
      name: "",
      category: "HAIRDRESSING",
      google_calendar_id: "",
      is_active: true,
      color: null,
    },
  });

  useEffect(() => {
    setConflictError(null);
    if (open) {
      if (stylist) {
        form.reset({
          name: stylist.name,
          category: stylist.category,
          google_calendar_id: stylist.google_calendar_id ?? "",
          is_active: stylist.is_active,
          color: stylist.color || null,
        });
      } else {
        form.reset({
          name: "",
          category: "HAIRDRESSING",
          google_calendar_id: "",
          is_active: true,
          color: null,
        });
      }
    }
  }, [stylist, open, form]);

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
    const currentCalendarId = stylist?.google_calendar_id;
    const calendarOwners = new Map<string, string>();
    allStylists.forEach((s) => {
      if (s.google_calendar_id) {
        calendarOwners.set(s.google_calendar_id, s.name);
      }
    });

    return availableCalendars.map((cal) => {
      const ownerName = calendarOwners.get(cal.id);
      let status: CalendarOptionStatus = CALENDAR_OPTION_STATUS.AVAILABLE;

      if (cal.id === currentCalendarId) {
        status = CALENDAR_OPTION_STATUS.CURRENT;
      } else if (ownerName && ownerName !== stylist?.name) {
        status = CALENDAR_OPTION_STATUS.OCCUPIED;
      }

      return { calendar: cal, status, ownerStylistName: ownerName };
    });
  };

  const calendarOptions = buildCalendarOptions();

  const handleSubmit = async (values: StylistFormValues) => {
    setLoading(true);
    setConflictError(null);

    // Normalize: empty string → null
    const calendarId = values.google_calendar_id?.trim() || null;

    try {
      if (stylist) {
        await api.update("stylists", stylist.id, {
          name: values.name,
          category: values.category,
          google_calendar_id: calendarId,
          is_active: values.is_active,
          color: values.color,
        });
        toast.success("Estilista actualizado correctamente");
      } else {
        await api.create("stylists", {
          name: values.name,
          category: values.category,
          google_calendar_id: calendarId,
          is_active: values.is_active,
          color: values.color,
        });
        toast.success("Estilista creado correctamente");
      }
      onOpenChange(false);
      onSuccess();
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 409) {
        const stylistNames = error.stylistNames || [];
        setConflictError({ message: error.message, stylistNames });
        toast.error("El calendario seleccionado ya está en uso");
      } else {
        toast.error(
          `Error: ${error instanceof Error ? error.message : "Error desconocido"}`
        );
      }
    } finally {
      setLoading(false);
    }
  };

  const watchedColor = form.watch("color");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md flex flex-col max-h-[90vh]">
        <DialogHeader>
          <DialogTitle>
            {stylist ? "Editar Estilista" : "Nuevo Estilista"}
          </DialogTitle>
          <DialogDescription>
            {stylist
              ? "Actualiza la información del estilista"
              : "Crea un nuevo estilista"}
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className="flex flex-col flex-1 min-h-0">
            {/* Scrollable body */}
            <div className="flex-1 min-h-0 overflow-y-auto px-1">
              <div className="space-y-4 py-2">
                <FormField
                  control={form.control}
                  name="name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Nombre *</FormLabel>
                      <FormControl>
                        <Input placeholder="Maria Garcia" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="category"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Categoría</FormLabel>
                      <Select value={field.value} onValueChange={field.onChange}>
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="HAIRDRESSING">Peluquería</SelectItem>
                          <SelectItem value="AESTHETICS">Estética</SelectItem>
                          <SelectItem value="BOTH">Ambos</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="google_calendar_id"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Google Calendar</FormLabel>
                      {availableCalendars.length > 0 ? (
                        <>
                          <Select
                            value={field.value ?? ""}
                            onValueChange={(value) => {
                              field.onChange(value);
                              setConflictError(null);
                            }}
                            disabled={loadingCalendars}
                          >
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue placeholder="Selecciona un calendario..." />
                              </SelectTrigger>
                            </FormControl>
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
                                        <Badge variant="outline" className="text-xs">Actual</Badge>
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
                          <FormControl>
                            <Input
                              placeholder="calendario@group.calendar.google.com"
                              disabled={loadingCalendars}
                              {...field}
                              value={field.value ?? ""}
                              onChange={(e) => {
                                field.onChange(e.target.value);
                                setConflictError(null);
                              }}
                            />
                          </FormControl>
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
                            <a href="/settings/google-calendar" className="underline hover:text-foreground">
                              Conectá Google Calendar en Ajustes
                            </a>{" "}
                            para ver los calendarios disponibles.
                          </p>
                        </>
                      )}
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="is_active"
                  render={({ field }) => (
                    <FormItem className="flex items-center space-x-2 space-y-0">
                      <FormControl>
                        <Checkbox
                          checked={field.value}
                          onCheckedChange={field.onChange}
                        />
                      </FormControl>
                      <FormLabel className="cursor-pointer font-normal">
                        Estilista activo
                      </FormLabel>
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="color"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Color del calendario</FormLabel>
                      <FormControl>
                        <div className="flex flex-wrap gap-2">
                          {STYLIST_COLORS.map((color) => (
                            <button
                              key={color.bg}
                              type="button"
                              onClick={() => field.onChange(color.bg)}
                              className={`w-8 h-8 rounded-full border-2 transition-all ${
                                watchedColor === color.bg
                                  ? "border-gray-900 scale-110"
                                  : "border-transparent hover:scale-105"
                              }`}
                              style={{ backgroundColor: color.bg }}
                              title={color.name}
                            />
                          ))}
                          <button
                            type="button"
                            onClick={() => field.onChange(null)}
                            className={`w-8 h-8 rounded-full border-2 transition-all flex items-center justify-center text-xs ${
                              watchedColor === null
                                ? "border-gray-900 scale-110 bg-gray-100"
                                : "border-gray-300 hover:scale-105 bg-gray-50"
                            }`}
                            title="Automático (por orden)"
                          >
                            Auto
                          </button>
                        </div>
                      </FormControl>
                      <p className="text-xs text-muted-foreground">
                        Selecciona un color o deja en automático
                      </p>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
            </div>

            {/* Fixed footer */}
            <DialogFooter>
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
            </DialogFooter>
          </form>
        </Form>
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

  const handleEdit = useCallback((stylist: Stylist) => {
    setEditingStylist(stylist);
    setModalOpen(true);
  }, []);

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

  const columns = useMemo<ColumnDef<Stylist>[]>(
    () => [
      {
        accessorKey: "name",
        header: ({ column }) => (
          <SortableHeader column={column}>Nombre</SortableHeader>
        ),
      },
      {
        accessorKey: "category",
        header: "Categoría",
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
          const calId = row.getValue("google_calendar_id") as string | null;
          if (!calId) {
            return <span className="text-muted-foreground text-sm">Sin conectar</span>;
          }
          return (
            <span title={calId} className="text-sm">
              Conectado
            </span>
          );
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
    ],
    [handleEdit]
  );

  return (
    <div className="flex flex-col">
      <Header
        title="Estilistas"
        description="Gestión de estilistas del salón"
        action={
          <Button onClick={handleCreate}>
            <Plus className="mr-2 h-4 w-4" />
            Nuevo Estilista
          </Button>
        }
      />

      <div className="flex-1 p-4 md:p-6">
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
              Esta acción no se puede deshacer. El estilista será eliminado
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
