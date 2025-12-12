"use client";

import { useEffect, useState, useCallback } from "react";
import { ColumnDef } from "@tanstack/react-table";
import { format } from "date-fns";
import { es } from "date-fns/locale";
import {
  MoreHorizontal,
  Plus,
  Phone,
  User,
  Calendar,
  Edit,
} from "lucide-react";

import { Header } from "@/components/layout/header";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import api from "@/lib/api";
import type { Customer } from "@/lib/types";

// Format date for display
function formatDate(dateString: string | null): string {
  if (!dateString) return "-";
  try {
    return format(new Date(dateString), "dd/MM/yyyy", { locale: es });
  } catch {
    return dateString;
  }
}

// Customer form modal
interface CustomerFormData {
  phone: string;
  first_name: string;
  last_name: string;
  notes: string;
}

function CustomerModal({
  open,
  onOpenChange,
  onSuccess,
  customer,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
  customer?: Customer | null;
}) {
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState<CustomerFormData>({
    phone: "",
    first_name: "",
    last_name: "",
    notes: "",
  });

  useEffect(() => {
    if (customer) {
      setFormData({
        phone: customer.phone,
        first_name: customer.first_name,
        last_name: customer.last_name || "",
        notes: customer.notes || "",
      });
    } else {
      setFormData({
        phone: "",
        first_name: "",
        last_name: "",
        notes: "",
      });
    }
  }, [customer, open]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.phone || !formData.first_name) {
      toast.error("Por favor completa los campos requeridos");
      return;
    }

    setLoading(true);
    try {
      if (customer) {
        await api.update("customers", customer.id, {
          phone: formData.phone,
          first_name: formData.first_name,
          last_name: formData.last_name || null,
          notes: formData.notes || null,
        });
        toast.success("Cliente actualizado correctamente");
      } else {
        await api.create("customers", {
          phone: formData.phone,
          first_name: formData.first_name,
          last_name: formData.last_name || null,
          notes: formData.notes || null,
        });
        toast.success("Cliente creado correctamente");
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
            {customer ? "Editar Cliente" : "Nuevo Cliente"}
          </DialogTitle>
          <DialogDescription>
            {customer
              ? "Actualiza la informacion del cliente"
              : "Crea un nuevo cliente"}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="phone">Telefono *</Label>
            <Input
              id="phone"
              value={formData.phone}
              onChange={(e) =>
                setFormData((prev) => ({ ...prev, phone: e.target.value }))
              }
              placeholder="+34612345678"
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="first_name">Nombre *</Label>
              <Input
                id="first_name"
                value={formData.first_name}
                onChange={(e) =>
                  setFormData((prev) => ({
                    ...prev,
                    first_name: e.target.value,
                  }))
                }
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="last_name">Apellido</Label>
              <Input
                id="last_name"
                value={formData.last_name}
                onChange={(e) =>
                  setFormData((prev) => ({
                    ...prev,
                    last_name: e.target.value,
                  }))
                }
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="notes">Notas</Label>
            <Textarea
              id="notes"
              value={formData.notes}
              onChange={(e) =>
                setFormData((prev) => ({ ...prev, notes: e.target.value }))
              }
              placeholder="Notas adicionales sobre el cliente..."
            />
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
                : customer
                  ? "Actualizar"
                  : "Crear Cliente"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function CustomersPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingCustomer, setEditingCustomer] = useState<Customer | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [customerToDelete, setCustomerToDelete] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.list<Customer>("customers", { page_size: 200 });
      setCustomers(res.items);
    } catch (error) {
      toast.error("Error al cargar los clientes");
      console.error(error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleEdit = (customer: Customer) => {
    setEditingCustomer(customer);
    setModalOpen(true);
  };

  const handleCreate = () => {
    setEditingCustomer(null);
    setModalOpen(true);
  };

  const handleDelete = async () => {
    if (!customerToDelete) return;

    try {
      await api.delete("customers", customerToDelete);
      toast.success("Cliente eliminado");
      loadData();
    } catch (error) {
      toast.error("Error al eliminar el cliente");
      console.error(error);
    } finally {
      setDeleteDialogOpen(false);
      setCustomerToDelete(null);
    }
  };

  const columns: ColumnDef<Customer>[] = [
    {
      accessorKey: "phone",
      header: () => (
        <div className="flex items-center">
          <Phone className="mr-2 h-4 w-4" />
          Telefono
        </div>
      ),
    },
    {
      accessorKey: "first_name",
      header: ({ column }) => (
        <SortableHeader column={column}>
          <User className="mr-2 h-4 w-4" />
          Nombre
        </SortableHeader>
      ),
      cell: ({ row }) => {
        const customer = row.original;
        return `${customer.first_name} ${customer.last_name || ""}`.trim();
      },
    },
    {
      accessorKey: "last_service_date",
      header: ({ column }) => (
        <SortableHeader column={column}>
          <Calendar className="mr-2 h-4 w-4" />
          Ultima Visita
        </SortableHeader>
      ),
      cell: ({ row }) => formatDate(row.getValue("last_service_date")),
    },
    {
      accessorKey: "created_at",
      header: ({ column }) => (
        <SortableHeader column={column}>Registro</SortableHeader>
      ),
      cell: ({ row }) => formatDate(row.getValue("created_at")),
    },
    {
      accessorKey: "notes",
      header: "Notas",
      cell: ({ row }) => {
        const notes = row.getValue("notes") as string | null;
        if (!notes) return "-";
        return notes.length > 30 ? notes.substring(0, 30) + "..." : notes;
      },
    },
    {
      id: "actions",
      cell: ({ row }) => {
        const customer = row.original;
        return (
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={() => handleEdit(customer)}
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
                    setCustomerToDelete(customer.id);
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
        title="Clientes"
        description="Gestion de clientes del salon"
        action={
          <Button onClick={handleCreate}>
            <Plus className="mr-2 h-4 w-4" />
            Nuevo Cliente
          </Button>
        }
      />

      <div className="flex-1 p-6">
        <Card>
          <CardContent className="pt-6">
            <DataTable
              columns={columns}
              data={customers}
              isLoading={loading}
              searchKey="first_name"
              searchPlaceholder="Buscar por nombre..."
            />
          </CardContent>
        </Card>
      </div>

      {/* Create/Edit Modal */}
      <CustomerModal
        open={modalOpen}
        onOpenChange={setModalOpen}
        onSuccess={loadData}
        customer={editingCustomer}
      />

      {/* Delete Confirmation */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar cliente</AlertDialogTitle>
            <AlertDialogDescription>
              Esta accion no se puede deshacer. El cliente sera eliminado
              permanentemente junto con su historial.
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
