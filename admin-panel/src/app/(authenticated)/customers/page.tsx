"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { ColumnDef } from "@tanstack/react-table";

import Link from "next/link";
import {
  MoreHorizontal,
  Plus,
  Phone,
  User,
  Calendar,
  Edit,
  Users,
} from "lucide-react";

import { Header } from "@/components/layout/header";
import { formatDate } from "@/components/shared/format-utils";
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
import { Textarea } from "@/components/ui/textarea";
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
import type { Customer } from "@/lib/types";
import { EmptyState } from "@/components/shared/empty-state";
import { RequirePermission } from "@/components/auth/require-permission";
import { CustomerFormSchema, type CustomerFormValues } from "./customer-form.schema";

// Customer form modal
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

  const form = useForm<CustomerFormValues>({
    resolver: zodResolver(CustomerFormSchema),
    defaultValues: {
      phone: "+34",
      first_name: "",
      last_name: "",
      notes: "",
    },
  });

  useEffect(() => {
    if (open) {
      if (customer) {
        form.reset({
          phone: customer.phone,
          first_name: customer.first_name,
          last_name: customer.last_name || "",
          notes: customer.notes || "",
        });
      } else {
        form.reset({
          phone: "+34",
          first_name: "",
          last_name: "",
          notes: "",
        });
      }
    }
  }, [customer, open, form]);

  const handleSubmit = async (values: CustomerFormValues) => {
    setLoading(true);
    try {
      if (customer) {
        await api.update("customers", customer.id, {
          phone: values.phone,
          first_name: values.first_name,
          last_name: values.last_name || null,
          notes: values.notes || null,
        });
        toast.success("Cliente actualizado correctamente");
      } else {
        await api.create("customers", {
          phone: values.phone,
          first_name: values.first_name,
          last_name: values.last_name || null,
          notes: values.notes || null,
        });
        toast.success("Cliente creado correctamente");
      }
      onOpenChange(false);
      onSuccess();
    } catch (error) {
      toast.error(
        `Error: ${error instanceof Error ? error.message : "Error desconocido"}`
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
              ? "Actualizá la información del cliente"
              : "Creá un nuevo cliente"}
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="phone"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Teléfono *</FormLabel>
                  <FormControl>
                    <Input placeholder="+34612345678" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="grid grid-cols-2 gap-4">
              <FormField
                control={form.control}
                name="first_name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Nombre *</FormLabel>
                    <FormControl>
                      <Input {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="last_name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Apellido</FormLabel>
                    <FormControl>
                      <Input {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="notes"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Notas</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="Notas adicionales sobre el cliente..."
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

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
        </Form>
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

  const handleEdit = useCallback((customer: Customer) => {
    setEditingCustomer(customer);
    setModalOpen(true);
  }, []);

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

  const columns = useMemo<ColumnDef<Customer>[]>(
    () => [
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
          const name = `${customer.first_name} ${customer.last_name || ""}`.trim();
          return (
            <Link
              href={`/customers/${customer.id}`}
              className="font-medium text-primary hover:underline"
            >
              {name}
            </Link>
          );
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
        cell: ({ row }) => formatDate(row.getValue("last_service_date"), false),
      },
      {
        accessorKey: "created_at",
        header: ({ column }) => (
          <SortableHeader column={column}>Registro</SortableHeader>
        ),
        cell: ({ row }) => formatDate(row.getValue("created_at"), false),
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
                  <RequirePermission action="customers:delete">
                    <DropdownMenuItem
                      onClick={() => {
                        setCustomerToDelete(customer.id);
                        setDeleteDialogOpen(true);
                      }}
                      className="text-destructive"
                    >
                      Eliminar
                    </DropdownMenuItem>
                  </RequirePermission>
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
        title="Clientes"
        description="Gestión de clientes del salón"
        action={
          <Button onClick={handleCreate}>
            <Plus className="mr-2 h-4 w-4" />
            Nuevo Cliente
          </Button>
        }
      />

      <div className="flex-1 p-4 md:p-6">
        <Card>
          <CardContent className="pt-6">
            {!loading && customers.length === 0 ? (
              <EmptyState
                icon={Users}
                title="No hay clientes registrados"
                description="Cuando el bot genere nuevos clientes, aparecerán aquí."
                action={{ label: "Nuevo cliente", onClick: handleCreate }}
              />
            ) : (
              <DataTable
                columns={columns}
                data={customers}
                isLoading={loading}
                searchKey="first_name"
                searchPlaceholder="Buscar por nombre..."
              />
            )}
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
              Esta acción no se puede deshacer. El cliente será eliminado
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
