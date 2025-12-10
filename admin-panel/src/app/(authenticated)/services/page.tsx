"use client";

import { useEffect, useState, useCallback } from "react";
import { ColumnDef } from "@tanstack/react-table";
import {
  MoreHorizontal,
  Plus,
  Clock,
  Edit,
  Check,
  X,
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
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { toast } from "sonner";
import api from "@/lib/api";
import type { Service, ServiceCategory } from "@/lib/types";

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

// Service form modal
interface ServiceFormData {
  name: string;
  category: ServiceCategory;
  duration_minutes: number;
  description: string;
  is_active: boolean;
}

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
  const [formData, setFormData] = useState<ServiceFormData>({
    name: "",
    category: "HAIRDRESSING",
    duration_minutes: 30,
    description: "",
    is_active: true,
  });

  useEffect(() => {
    if (service) {
      setFormData({
        name: service.name,
        category: service.category,
        duration_minutes: service.duration_minutes,
        description: service.description || "",
        is_active: service.is_active,
      });
    } else {
      setFormData({
        name: "",
        category: "HAIRDRESSING",
        duration_minutes: 30,
        description: "",
        is_active: true,
      });
    }
  }, [service, open]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name) {
      toast.error("El nombre es requerido");
      return;
    }

    setLoading(true);
    try {
      if (service) {
        await api.update("services", service.id, {
          name: formData.name,
          category: formData.category,
          duration_minutes: formData.duration_minutes,
          description: formData.description || null,
          is_active: formData.is_active,
        });
        toast.success("Servicio actualizado correctamente");
      } else {
        await api.create("services", {
          name: formData.name,
          category: formData.category,
          duration_minutes: formData.duration_minutes,
          description: formData.description || null,
          is_active: formData.is_active,
        });
        toast.success("Servicio creado correctamente");
      }
      onOpenChange(false);
      onSuccess();
    } catch (error) {
      toast.error(
        `Error: ${error instanceof Error ? error.message : "Unknown error"}`
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {service ? "Editar Servicio" : "Nuevo Servicio"}
          </DialogTitle>
          <DialogDescription>
            {service
              ? "Actualiza la informacion del servicio"
              : "Crea un nuevo servicio"}
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
              placeholder="Corte de pelo"
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
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
              <Label htmlFor="duration">Duracion (min)</Label>
              <Input
                id="duration"
                type="number"
                min={5}
                max={480}
                step={5}
                value={formData.duration_minutes}
                onChange={(e) =>
                  setFormData((prev) => ({
                    ...prev,
                    duration_minutes: parseInt(e.target.value) || 30,
                  }))
                }
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="description">Descripcion</Label>
            <Textarea
              id="description"
              value={formData.description}
              onChange={(e) =>
                setFormData((prev) => ({
                  ...prev,
                  description: e.target.value,
                }))
              }
              placeholder="Descripcion del servicio..."
            />
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
              Servicio activo
            </Label>
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
                : service
                  ? "Actualizar"
                  : "Crear Servicio"}
            </Button>
          </div>
        </form>
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

  const handleEdit = (service: Service) => {
    setEditingService(service);
    setModalOpen(true);
  };

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

  const columns: ColumnDef<Service>[] = [
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
      accessorKey: "duration_minutes",
      header: () => (
        <div className="flex items-center">
          <Clock className="mr-2 h-4 w-4" />
          Duracion
        </div>
      ),
      cell: ({ row }) => `${row.getValue("duration_minutes")} min`,
    },
    {
      accessorKey: "description",
      header: "Descripcion",
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
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="h-8 w-8 p-0">
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => handleEdit(service)}>
                <Edit className="mr-2 h-4 w-4" />
                Editar
              </DropdownMenuItem>
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
        );
      },
    },
  ];

  return (
    <div className="flex flex-col">
      <Header
        title="Servicios"
        description="Gestion de servicios del salon"
        action={
          <Button onClick={handleCreate}>
            <Plus className="mr-2 h-4 w-4" />
            Nuevo Servicio
          </Button>
        }
      />

      <div className="flex-1 p-6">
        <Card>
          <CardContent className="pt-6">
            {/* Filters */}
            <div className="flex gap-4 mb-6">
              <div className="w-[200px]">
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
                    <SelectValue placeholder="Filtrar por categoria" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Todas las categorias</SelectItem>
                    <SelectItem value="HAIRDRESSING">Peluqueria</SelectItem>
                    <SelectItem value="AESTHETICS">Estetica</SelectItem>
                    <SelectItem value="BOTH">Ambos</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="w-[200px]">
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

            <DataTable
              columns={columns}
              data={services}
              isLoading={loading}
              searchKey="name"
              searchPlaceholder="Buscar por nombre..."
            />
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
              Esta accion no se puede deshacer. El servicio sera eliminado
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
