"use client";

import { useState, useMemo, useRef } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Search, UserPlus, ChevronLeft, Loader2, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
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
import { NewCustomerSchema, type NewCustomerValues } from "./schemas";

interface CustomerStepProps {
  customers: Customer[];
  selectedCustomer: Customer | null;
  onSelect: (customer: Customer) => void;
  onCreateNew: (customer: Customer) => void;
}

/** Estimated row height for the virtualizer (px). */
const ESTIMATED_ROW_HEIGHT = 56;

export function CustomerStep({
  customers,
  selectedCustomer,
  onSelect,
  onCreateNew,
}: CustomerStepProps) {
  const [search, setSearch] = useState("");
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [creating, setCreating] = useState(false);

  // Scroll container ref used by virtualizer
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const form = useForm<NewCustomerValues>({
    resolver: zodResolver(NewCustomerSchema),
    defaultValues: {
      phone: "+34",
      first_name: "",
      last_name: "",
    },
  });

  const filteredCustomers = useMemo(() => {
    if (!search) return customers;
    const term = search.toLowerCase();
    return customers.filter(
      (c) =>
        c.first_name.toLowerCase().includes(term) ||
        (c.last_name?.toLowerCase() || "").includes(term) ||
        c.phone.includes(term)
    );
  }, [customers, search]);

  // Virtualizer: renders only visible rows (~20 at a time for 300px container)
  const rowVirtualizer = useVirtualizer({
    count: filteredCustomers.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: () => ESTIMATED_ROW_HEIGHT,
    overscan: 5,
  });

  const handleCreateCustomer = async (values: NewCustomerValues) => {
    setCreating(true);
    try {
      const created = await api.create<Customer>("customers", {
        phone: values.phone,
        first_name: values.first_name,
        last_name: values.last_name || null,
      });
      toast.success("Cliente creado");
      onCreateNew(created);
      setShowCreateForm(false);
      form.reset();
    } catch (error) {
      toast.error(
        `Error: ${error instanceof Error ? error.message : "Error desconocido"}`
      );
    } finally {
      setCreating(false);
    }
  };

  if (showCreateForm) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2 mb-4">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setShowCreateForm(false);
              form.reset();
            }}
          >
            <ChevronLeft className="h-4 w-4 mr-1" />
            Volver
          </Button>
          <span className="text-sm font-medium">Crear nuevo cliente</span>
        </div>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleCreateCustomer)} className="space-y-4">
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

            <FormField
              control={form.control}
              name="first_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Nombre *</FormLabel>
                  <FormControl>
                    <Input placeholder="María" {...field} />
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
                    <Input placeholder="García" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <Button type="submit" disabled={creating} className="w-full">
              {creating ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Creando...
                </>
              ) : (
                <>
                  <UserPlus className="mr-2 h-4 w-4" />
                  Crear Cliente
                </>
              )}
            </Button>
          </form>
        </Form>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Buscar por nombre o teléfono..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Button variant="outline" onClick={() => setShowCreateForm(true)}>
          <UserPlus className="h-4 w-4 mr-2" />
          Nuevo
        </Button>
      </div>

      {/* Virtualized list — ScrollArea provides styled scrollbar, inner div drives virtualizer */}
      <ScrollArea className="h-[300px]">
        <div
          ref={scrollContainerRef}
          className="h-[300px] overflow-auto"
        >
          {filteredCustomers.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <p>No se encontraron clientes</p>
              <Button
                variant="link"
                onClick={() => setShowCreateForm(true)}
                className="mt-2"
              >
                Crear nuevo cliente
              </Button>
            </div>
          ) : (
            <div
              style={{
                height: `${rowVirtualizer.getTotalSize()}px`,
                width: "100%",
                position: "relative",
              }}
            >
              {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                const customer = filteredCustomers[virtualRow.index];
                return (
                  <div
                    key={customer.id}
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                      height: `${virtualRow.size}px`,
                      transform: `translateY(${virtualRow.start}px)`,
                      paddingBottom: "8px",
                    }}
                  >
                    <div
                      onClick={() => onSelect(customer)}
                      className={`p-3 rounded-lg border cursor-pointer transition-colors h-full box-border ${
                        selectedCustomer?.id === customer.id
                          ? "border-primary bg-primary/5"
                          : "hover:border-primary/50"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <p className="font-medium truncate">
                          {customer.first_name} {customer.last_name || ""}
                        </p>
                        <div className="flex items-center gap-2 shrink-0">
                          <p className="text-sm text-muted-foreground">
                            {customer.phone}
                          </p>
                          {selectedCustomer?.id === customer.id && (
                            <Check className="h-5 w-5 text-primary" />
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
