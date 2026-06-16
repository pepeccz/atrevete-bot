"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { ColumnDef } from "@tanstack/react-table";
import {
  MoreHorizontal,
  Plus,
  Clock,
  Edit,
  Check,
  X,
  Scissors,
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
import { Textarea } from "@/components/ui/textarea";
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
import api, { ApiRequestError } from "@/lib/api";
import type { Service, ServiceCategory } from "@/lib/types";
import { ServiceMetadataForm } from "@/components/services/ServiceMetadataForm";
import { CategoryBadge } from "@/components/shared/category-badge";
import { EmptyState } from "@/components/shared/empty-state";
import { ServiceFormSchema, type ServiceFormValues } from "./service-form.schema";

function ServiceModal({
  open,
  onOpenChange,
  onSuccess,
  service,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
  service?: Service | null;
}) {
  const [loading, setLoading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const form = useForm<ServiceFormValues>({
    resolver: zodResolver(ServiceFormSchema),
    defaultValues: {
      name: "",
      category: "HAIRDRESSING",
      duration_minutes: 30,
      description: "",
      is_active: true,
      audience: null,
    },
  });

  useEffect(() => {
    setFormError(null);
    if (open) {
      if (service) {
        form.reset({
          name: service.name,
          category: service.category,
          duration_minutes: service.duration_minutes,
          description: service.description || "",
          is_active: service.is_active,
          audience: service.audience ?? null,
        });
      } else {
        form.reset({
          name: "",
          category: "HAIRDRESSING",
          duration_minutes: 30,
          description: "",
          is_active: true,
          audience: null,
        });
      }
    }
  }, [service, open, form]);

  const handleSubmit = async (values: ServiceFormValues) => {
    setLoading(true);
    setFormError(null);
    try {
      if (service) {
        await api.update("services", service.id, {
          name: values.name,
          category: values.category,
          duration_minutes: values.duration_minutes,
          description: values.description || null,
          is_active: values.is_active,
          audience: values.audience,
        });
        toast.success("Servicio actualizado correctamente");
      } else {
        await api.create("services", {
          name: values.name,
          category: values.category,
          duration_minutes: values.duration_minutes,
          description: values.description || null,
          is_active: values.is_active,
          audience: values.audience,
        });
        toast.success("Servicio creado correctamente");
      }
      onOpenChange(false);
      onSuccess();
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 422) {
        if (Array.isArray(error.detail)) {
          const messages = (error.detail as Array<{ loc?: string[]; msg: string }>)
            .map((d) => {
              const field = d.loc?.slice(1).join(" → ") || "campo desconocido";
              return `${field}: ${d.msg}`;
            })
            .join("\n");
          setFormError(messages);
        } else if (typeof error.detail === "string") {
          setFormError(error.detail);
        } else {
          setFormError("Error de validación. Revisá los datos ingresados.");
        }
      } else {
        setFormError(
          `Error al guardar: ${error instanceof Error ? error.message : "Intentá de nuevo."}`
        );
        toast.error(
          `Error: ${error instanceof Error ? error.message : "Error desconocido"}`
        );
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg flex flex-col max-h-[90vh]">
        <DialogHeader>
          <DialogTitle>
            {service ? "Editar Servicio" : "Nuevo Servicio"}
          </DialogTitle>
          <DialogDescription>
            {service
              ? "Actualiza la información del servicio"
              : "Crea un nuevo servicio"}
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
                        <Input placeholder="Corte de pelo" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <div className="grid grid-cols-2 gap-4">
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
                    name="duration_minutes"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Duración (min)</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            min={5}
                            max={480}
                            step={5}
                            {...field}
                            onChange={(e) => field.onChange(parseInt(e.target.value) || 30)}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>

                <FormField
                  control={form.control}
                  name="description"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Descripción</FormLabel>
                      <FormControl>
                        <Textarea
                          placeholder="Descripción del servicio..."
                          {...field}
                        />
                      </FormControl>
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
                        Servicio activo
                      </FormLabel>
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="audience"
                  render={({ field }) => (
                    <FormItem>
                      <FormControl>
                        <ServiceMetadataForm
                          value={field.value ?? null}
                          onChange={field.onChange}
                          disabled={loading}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {formError && (
                  <div className="rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2 text-sm text-destructive whitespace-pre-line">
                    {formError}
                  </div>
                )}
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
                  : service
                    ? "Actualizar"
                    : "Crear Servicio"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}

export default function ServicesPage() {
  const [services, setServices] = useState<Service[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingService, setEditingService] = useState<Service | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [serviceToDelete, setServiceToDelete] = useState<string | null>(null);
  const [filters, setFilters] = useState({
    category: "",
    is_active: "",
  });

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.list<Service>("services", {
        page_size: 200,
        ...(filters.category && { category: filters.category }),
        ...(filters.is_active && { is_active: filters.is_active === "true" }),
      });
      setServices(res.items);
    } catch (error) {
      toast.error("Error al cargar los servicios");
      console.error(error);
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleEdit = useCallback((service: Service) => {
    setEditingService(service);
    setModalOpen(true);
  }, []);

  const handleCreate = () => {
    setEditingService(null);
    setModalOpen(true);
  };

  const handleDelete = async () => {
    if (!serviceToDelete) return;

    try {
      await api.delete("services", serviceToDelete);
      toast.success("Servicio eliminado");
      loadData();
    } catch (error) {
      toast.error("Error al eliminar el servicio");
      console.error(error);
    } finally {
      setDeleteDialogOpen(false);
      setServiceToDelete(null);
    }
  };

  const columns = useMemo<ColumnDef<Service>[]>(
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
        accessorKey: "duration_minutes",
        header: () => (
          <div className="flex items-center">
            <Clock className="mr-2 h-4 w-4" />
            Duración
          </div>
        ),
        cell: ({ row }) => `${row.getValue("duration_minutes")} min`,
      },
      {
        accessorKey: "description",
        header: "Descripción",
        cell: ({ row }) => {
          const desc = row.getValue("description") as string | null;
          if (!desc) return "-";
          return desc.length > 40 ? desc.substring(0, 40) + "..." : desc;
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
          const service = row.original;
          return (
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => handleEdit(service)}
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
                      setServiceToDelete(service.id);
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
        title="Servicios"
        description="Gestión de servicios del salón"
        action={
          <Button onClick={handleCreate}>
            <Plus className="mr-2 h-4 w-4" />
            Nuevo Servicio
          </Button>
        }
      />

      <div className="flex-1 p-4 md:p-6">
        <Card>
          <CardContent className="pt-6">
            {/* Filters */}
            <div className="flex flex-wrap gap-4 mb-6">
              <div className="w-full sm:w-[200px]">
                <Select
                  value={filters.category}
                  onValueChange={(value) =>
                    setFilters((prev) => ({
                      ...prev,
                      category: value === "all" ? "" : value,
                    }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Filtrar por categoría" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Todas las categorías</SelectItem>
                    <SelectItem value="HAIRDRESSING">Peluquería</SelectItem>
                    <SelectItem value="AESTHETICS">Estética</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="w-full sm:w-[200px]">
                <Select
                  value={filters.is_active}
                  onValueChange={(value) =>
                    setFilters((prev) => ({
                      ...prev,
                      is_active: value === "all" ? "" : value,
                    }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Filtrar por estado" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Todos</SelectItem>
                    <SelectItem value="true">Activos</SelectItem>
                    <SelectItem value="false">Inactivos</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {!loading && services.length === 0 ? (
              <EmptyState
                icon={Scissors}
                title="No hay servicios creados"
                description="Crea los servicios del salón para que el bot pueda ofrecerlos."
                action={{ label: "Nuevo servicio", onClick: handleCreate }}
              />
            ) : (
              <DataTable
                columns={columns}
                data={services}
                isLoading={loading}
                searchKey="name"
                searchPlaceholder="Buscar por nombre..."
              />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Create/Edit Modal */}
      <ServiceModal
        open={modalOpen}
        onOpenChange={setModalOpen}
        onSuccess={loadData}
        service={editingService}
      />

      {/* Delete Confirmation */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar servicio</AlertDialogTitle>
            <AlertDialogDescription>
              Esta acción no se puede deshacer. El servicio será eliminado
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
