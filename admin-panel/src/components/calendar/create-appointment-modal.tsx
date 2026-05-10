"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { ChevronsUpDown, Plus, Search, Check, UserPlus, X } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DatePicker } from "@/components/shared/date-picker";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { OverlapConfirmDialog } from "./overlap-confirm-dialog";
import type { OverlapConflict, ServiceCategory } from "@/lib/types";
import api from "@/lib/api";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

interface Customer {
  id: string;
  phone: string;
  first_name: string;
  last_name: string | null;
}

interface Service {
  id: string;
  name: string;
  duration_minutes: number;
  category: ServiceCategory;
}

interface StylistOption {
  id: string;
  name: string;
}

interface CreateAppointmentModalProps {
  isOpen: boolean;
  onClose: () => void;
  stylistId: string;
  selectedDate: Date | null;
  onSuccess: () => void;
  /** Optional pre-filled start time from calendar drag/click. */
  selectedStartTime?: Date | null;
  /** Optional pre-filled end time from calendar drag selection (unused in form but accepted for API parity). */
  selectedEndTime?: Date | null;
  /** Available stylists to choose from. When provided, shows a stylist selector. */
  availableStylists?: StylistOption[];
}

type CategoryFilter = "ALL" | "HAIRDRESSING" | "AESTHETICS";

const CATEGORY_FILTERS: { value: CategoryFilter; label: string }[] = [
  { value: "ALL", label: "Todos" },
  { value: "HAIRDRESSING", label: "Peluquería" },
  { value: "AESTHETICS", label: "Estética" },
];

function categoryMatches(service: Service, filter: CategoryFilter): boolean {
  if (filter === "ALL") return true;
  // Services tagged BOTH show in either filter
  if (service.category === "BOTH") return true;
  return service.category === filter;
}

export function CreateAppointmentModal({
  isOpen,
  onClose,
  stylistId,
  selectedDate,
  onSuccess,
  selectedStartTime,
  selectedEndTime: _selectedEndTime,
  availableStylists,
}: CreateAppointmentModalProps) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [serviceSearch, setServiceSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("ALL");

  // Customer combobox state
  const [customerPopoverOpen, setCustomerPopoverOpen] = useState(false);
  const [customerSearch, setCustomerSearch] = useState("");
  const [showInlineCreate, setShowInlineCreate] = useState(false);
  const [newCustomerForm, setNewCustomerForm] = useState({
    first_name: "",
    last_name: "",
    phone: "",
  });
  const [creatingCustomer, setCreatingCustomer] = useState(false);

  // Form state
  const [selectedCustomer, setSelectedCustomer] = useState<Customer | null>(null);
  const [selectedServices, setSelectedServices] = useState<string[]>([]);
  const [activeStylistId, setActiveStylistId] = useState(stylistId);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [notes, setNotes] = useState("");
  const [startTime, setStartTime] = useState("");
  const [sendNotification, setSendNotification] = useState(true);

  // Overlap check state
  const [pendingConflicts, setPendingConflicts] = useState<OverlapConflict[]>([]);
  const [showOverlapDialog, setShowOverlapDialog] = useState(false);
  const [allowOverlap, setAllowOverlap] = useState(false);

  const customerSearchRef = useRef<HTMLInputElement>(null);

  // Sync activeStylistId when modal opens or stylistId prop changes
  useEffect(() => {
    if (isOpen) {
      setActiveStylistId(stylistId);
    }
  }, [isOpen, stylistId]);

  // Reset internal state when the modal closes so the next open is clean.
  useEffect(() => {
    if (!isOpen) {
      setCustomerPopoverOpen(false);
      setCustomerSearch("");
      setShowInlineCreate(false);
      setNewCustomerForm({ first_name: "", last_name: "", phone: "" });
      setCategoryFilter("ALL");
      setServiceSearch("");
    }
  }, [isOpen]);

  // Load customers and services on mount
  useEffect(() => {
    async function loadData() {
      try {
        const [customersData, servicesData] = await Promise.all([
          api.list<Customer>("customers", { page_size: 500 }),
          api.list<Service>("services", { is_active: true, page_size: 200 }),
        ]);
        setCustomers(customersData.items);
        setServices(servicesData.items);
      } catch (error) {
        console.error("Error loading data:", error);
      }
    }
    if (isOpen) {
      loadData();
    }
  }, [isOpen]);

  // Pre-fill time: prefer selectedStartTime (from drag), fall back to selectedDate (from click)
  useEffect(() => {
    const timeSource = selectedStartTime ?? selectedDate;
    if (timeSource) {
      const madridTime = new Intl.DateTimeFormat('es-ES', {
        timeZone: 'Europe/Madrid',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }).format(timeSource);
      setStartTime(madridTime);
    }
  }, [selectedDate, selectedStartTime]);

  // Filter customers as the user types in the combobox
  const filteredCustomers = useMemo(() => {
    const q = customerSearch.trim().toLowerCase();
    if (!q) return customers.slice(0, 100);
    return customers.filter((c) => {
      const full = `${c.first_name} ${c.last_name ?? ""}`.toLowerCase();
      return (
        c.phone.toLowerCase().includes(q) ||
        full.includes(q)
      );
    }).slice(0, 100);
  }, [customers, customerSearch]);

  const filteredServices = useMemo(() => {
    const q = serviceSearch.trim().toLowerCase();
    return services.filter((s) => {
      if (!categoryMatches(s, categoryFilter)) return false;
      if (!q) return true;
      return s.name.toLowerCase().includes(q);
    });
  }, [services, serviceSearch, categoryFilter]);

  const handleSelectCustomer = (customer: Customer) => {
    setSelectedCustomer(customer);
    setFirstName(customer.first_name);
    setLastName(customer.last_name ?? "");
    setCustomerPopoverOpen(false);
    setCustomerSearch("");
    setShowInlineCreate(false);
  };

  const handleStartInlineCreate = () => {
    // Pre-seed the inline form with whatever the user has typed in the search.
    const tokens = customerSearch.trim().split(/\s+/);
    const looksLikePhone = /^\+?\d[\d\s]*$/.test(customerSearch.trim());
    setNewCustomerForm({
      first_name: looksLikePhone ? "" : tokens[0] ?? "",
      last_name: looksLikePhone ? "" : tokens.slice(1).join(" "),
      phone: looksLikePhone ? customerSearch.trim() : "",
    });
    setShowInlineCreate(true);
  };

  const handleCreateCustomer = async () => {
    if (!newCustomerForm.first_name || !newCustomerForm.phone) {
      toast.error("Nombre y teléfono son obligatorios");
      return;
    }
    setCreatingCustomer(true);
    try {
      const created = await api.create<Customer>("customers", {
        phone: newCustomerForm.phone.trim(),
        first_name: newCustomerForm.first_name.trim(),
        last_name: newCustomerForm.last_name.trim() || null,
      });
      setCustomers((prev) => [created, ...prev]);
      handleSelectCustomer(created);
      toast.success("Cliente creado");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Error desconocido";
      toast.error(`No se pudo crear el cliente: ${message}`);
    } finally {
      setCreatingCustomer(false);
    }
  };

  const handleSubmit = async () => {
    if (
      !selectedCustomer ||
      selectedServices.length === 0 ||
      !firstName ||
      !selectedDate ||
      !startTime
    ) {
      toast.error("Por favor completa todos los campos requeridos");
      return;
    }

    try {
      setIsLoading(true);

      // Combine date and time
      const [hours, minutes] = startTime.split(":");
      const appointmentDate = new Date(selectedDate);
      appointmentDate.setHours(parseInt(hours), parseInt(minutes), 0, 0);

      const startTimeISO = appointmentDate.toISOString();
      const totalDuration = selectedServices.reduce((total, serviceId) => {
        const service = services.find((s) => s.id === serviceId);
        return total + (service?.duration_minutes || 0);
      }, 0);

      // Check for overlaps if not already allowed
      if (!allowOverlap) {
        const overlapCheck = await api.checkOverlaps(
          activeStylistId,
          startTimeISO,
          totalDuration
        );

        if (overlapCheck.has_overlaps) {
          setPendingConflicts(overlapCheck.conflicts);
          setShowOverlapDialog(true);
          setIsLoading(false);
          return;
        }
      }

      await api.create("appointments", {
        customer_id: selectedCustomer.id,
        stylist_id: activeStylistId,
        service_ids: selectedServices,
        start_time: startTimeISO,
        first_name: firstName,
        last_name: lastName || null,
        notes: notes || null,
        send_notification: sendNotification,
      });

      // Reset form and state
      setSelectedCustomer(null);
      setSelectedServices([]);
      setActiveStylistId(stylistId);
      setServiceSearch("");
      setCategoryFilter("ALL");
      setFirstName("");
      setLastName("");
      setNotes("");
      setStartTime("");
      setSendNotification(true);
      setAllowOverlap(false);
      setPendingConflicts([]);

      onSuccess();
      onClose();
    } catch (error) {
      console.error("Error creating appointment:", error);
      toast.error("Error al crear la cita: " + (error instanceof Error ? error.message : "Unknown error"));
    } finally {
      setIsLoading(false);
    }
  };

  const handleConfirmOverlap = async () => {
    setAllowOverlap(true);
    setShowOverlapDialog(false);
    // Retry submission with allow_overlap flag
    await handleSubmit();
  };

  const handleCancelOverlap = () => {
    setShowOverlapDialog(false);
    setPendingConflicts([]);
    // Stay in the form - user can change time
  };

  const totalDuration = selectedServices.reduce((total, serviceId) => {
    const service = services.find((s) => s.id === serviceId);
    return total + (service?.duration_minutes || 0);
  }, 0);

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Crear Nueva Cita</DialogTitle>
          <DialogDescription>
            Completa los datos para crear una nueva cita
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Stylist Selector */}
          {availableStylists && availableStylists.length > 1 && (
            <div className="space-y-2">
              <Label htmlFor="stylist">Estilista *</Label>
              <Select value={activeStylistId} onValueChange={setActiveStylistId}>
                <SelectTrigger>
                  <SelectValue placeholder="Selecciona una estilista" />
                </SelectTrigger>
                <SelectContent>
                  {availableStylists.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Customer combobox + inline create */}
          <div className="space-y-2">
            <Label>Cliente *</Label>
            <Popover
              open={customerPopoverOpen}
              onOpenChange={(open) => {
                setCustomerPopoverOpen(open);
                if (open) {
                  setShowInlineCreate(false);
                  // Focus the search input after the popover paints
                  setTimeout(() => customerSearchRef.current?.focus(), 50);
                }
              }}
            >
              <PopoverTrigger asChild>
                <Button
                  type="button"
                  variant="outline"
                  role="combobox"
                  aria-expanded={customerPopoverOpen}
                  className="w-full justify-between font-normal"
                >
                  {selectedCustomer ? (
                    <span className="truncate">
                      {selectedCustomer.first_name} {selectedCustomer.last_name ?? ""}
                      {" · "}
                      <span className="text-muted-foreground">{selectedCustomer.phone}</span>
                    </span>
                  ) : (
                    <span className="text-muted-foreground">Buscar por nombre o teléfono…</span>
                  )}
                  <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                </Button>
              </PopoverTrigger>
              <PopoverContent
                className="w-[var(--radix-popover-trigger-width)] p-0"
                align="start"
              >
                {showInlineCreate ? (
                  <InlineCreateCustomer
                    form={newCustomerForm}
                    onChange={setNewCustomerForm}
                    onCancel={() => setShowInlineCreate(false)}
                    onCreate={handleCreateCustomer}
                    isCreating={creatingCustomer}
                  />
                ) : (
                  <div className="flex flex-col">
                    <div className="flex items-center gap-2 border-b border-line px-3 py-2">
                      <Search className="h-4 w-4 text-muted-foreground" />
                      <input
                        ref={customerSearchRef}
                        value={customerSearch}
                        onChange={(e) => setCustomerSearch(e.target.value)}
                        placeholder="Buscar por nombre o teléfono…"
                        className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                      />
                      {customerSearch && (
                        <button
                          type="button"
                          onClick={() => setCustomerSearch("")}
                          className="text-muted-foreground hover:text-foreground"
                          aria-label="Limpiar búsqueda"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                    <div className="max-h-64 overflow-y-auto py-1">
                      {filteredCustomers.length === 0 ? (
                        <div className="px-3 py-4 text-center text-sm text-muted-foreground">
                          Sin coincidencias.
                        </div>
                      ) : (
                        filteredCustomers.map((customer) => {
                          const isSelected = selectedCustomer?.id === customer.id;
                          return (
                            <button
                              key={customer.id}
                              type="button"
                              onClick={() => handleSelectCustomer(customer)}
                              className={cn(
                                "flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-muted/60",
                                isSelected && "bg-gold-soft/40"
                              )}
                            >
                              <span className="flex flex-col leading-tight min-w-0">
                                <span className="truncate font-medium text-foreground">
                                  {customer.first_name} {customer.last_name ?? ""}
                                </span>
                                <span className="truncate text-xs text-muted-foreground">
                                  {customer.phone}
                                </span>
                              </span>
                              {isSelected && <Check className="h-4 w-4 text-gold-dark flex-shrink-0" />}
                            </button>
                          );
                        })
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={handleStartInlineCreate}
                      className="flex items-center gap-2 border-t border-line px-3 py-2.5 text-sm font-medium text-gold-dark hover:bg-gold-soft/30"
                    >
                      <UserPlus className="h-4 w-4" />
                      Crear cliente nuevo
                      {customerSearch && (
                        <span className="ml-auto text-xs font-normal text-muted-foreground">
                          con &quot;{customerSearch}&quot;
                        </span>
                      )}
                    </button>
                  </div>
                )}
              </PopoverContent>
            </Popover>
          </div>

          {/* Services */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Servicios * (Duración total: {totalDuration} min)</Label>
            </div>
            <div className="flex items-center gap-1 p-0.5 bg-muted/50 rounded-[10px] w-fit">
              {CATEGORY_FILTERS.map((f) => (
                <button
                  key={f.value}
                  type="button"
                  onClick={() => setCategoryFilter(f.value)}
                  className={cn(
                    "px-3 py-1 text-xs font-semibold rounded-[8px] transition-colors",
                    categoryFilter === f.value
                      ? "bg-white text-ink shadow-sm"
                      : "text-ink-mute hover:text-ink"
                  )}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <Input
              type="text"
              placeholder="Buscar servicio…"
              value={serviceSearch}
              onChange={(e) => setServiceSearch(e.target.value)}
            />
            <div className="border rounded-md p-2 max-h-40 overflow-y-auto space-y-1">
              {filteredServices.length === 0 ? (
                <div className="px-2 py-3 text-center text-sm text-muted-foreground">
                  No hay servicios para esta categoría.
                </div>
              ) : (
                filteredServices.map((service) => (
                  <label
                    key={service.id}
                    className="flex items-center space-x-2 p-1 hover:bg-accent rounded cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={selectedServices.includes(service.id)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedServices([...selectedServices, service.id]);
                        } else {
                          setSelectedServices(
                            selectedServices.filter((id) => id !== service.id)
                          );
                        }
                      }}
                    />
                    <span className="text-sm">
                      {service.name} ({service.duration_minutes} min)
                    </span>
                  </label>
                ))
              )}
            </div>
          </div>

          {/* Date and Time */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="date">Fecha *</Label>
              <DatePicker
                value={selectedDate ?? undefined}
                onChange={() => {
                  // Read-only: date is set by calendar click
                }}
                disabled
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="time">Hora *</Label>
              <Input
                id="time"
                type="time"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
                required
              />
            </div>
          </div>

          {/* First Name */}
          <div className="space-y-2">
            <Label htmlFor="firstName">Nombre (para la cita) *</Label>
            <Input
              id="firstName"
              type="text"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              placeholder="Nombre"
              required
            />
            {selectedCustomer && (
              <p className="text-xs text-ink-mute">
                Autocompletado desde el cliente. Editalo si la cita es para otra persona.
              </p>
            )}
          </div>

          {/* Last Name */}
          <div className="space-y-2">
            <Label htmlFor="lastName">Apellido (para la cita)</Label>
            <Input
              id="lastName"
              type="text"
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              placeholder="Apellido (opcional)"
            />
          </div>

          {/* Notes */}
          <div className="space-y-2">
            <Label htmlFor="notes">Notas</Label>
            <Input
              id="notes"
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Notas adicionales (opcional)"
            />
          </div>

          {/* Send Notification Switch */}
          <div className="flex items-center justify-between py-2">
            <Label htmlFor="send-notification" className="text-sm font-medium">
              Enviar notificación al cliente
            </Label>
            <Switch
              id="send-notification"
              checked={sendNotification}
              onCheckedChange={setSendNotification}
            />
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={isLoading}>
            Cancelar
          </Button>
          <Button onClick={handleSubmit} disabled={isLoading}>
            {isLoading ? "Creando..." : "Crear Cita"}
          </Button>
        </div>
      </DialogContent>

      {/* Overlap Confirmation Dialog */}
      <OverlapConfirmDialog
        isOpen={showOverlapDialog}
        onClose={handleCancelOverlap}
        onConfirm={handleConfirmOverlap}
        conflicts={pendingConflicts}
        isSubmitting={isLoading}
      />
    </Dialog>
  );
}

// ── Inline customer creator ───────────────────────────────────────────────────

interface InlineCreateCustomerProps {
  form: { first_name: string; last_name: string; phone: string };
  onChange: (form: { first_name: string; last_name: string; phone: string }) => void;
  onCancel: () => void;
  onCreate: () => void;
  isCreating: boolean;
}

function InlineCreateCustomer({
  form,
  onChange,
  onCancel,
  onCreate,
  isCreating,
}: InlineCreateCustomerProps) {
  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center gap-2">
        <UserPlus className="h-4 w-4 text-gold-dark" />
        <span className="text-sm font-semibold text-ink">Nuevo cliente</span>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label className="text-xs">Nombre *</Label>
          <Input
            value={form.first_name}
            onChange={(e) => onChange({ ...form, first_name: e.target.value })}
            placeholder="María"
            disabled={isCreating}
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Apellido</Label>
          <Input
            value={form.last_name}
            onChange={(e) => onChange({ ...form, last_name: e.target.value })}
            placeholder="García (opcional)"
            disabled={isCreating}
          />
        </div>
      </div>
      <div className="space-y-1">
        <Label className="text-xs">Teléfono *</Label>
        <Input
          value={form.phone}
          onChange={(e) => onChange({ ...form, phone: e.target.value })}
          placeholder="+34 600 123 456"
          disabled={isCreating}
        />
      </div>
      <div className="flex justify-end gap-2 pt-1">
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={isCreating}>
          Cancelar
        </Button>
        <Button size="sm" onClick={onCreate} disabled={isCreating}>
          {isCreating ? "Creando…" : <><Plus className="mr-1 h-3.5 w-3.5" /> Crear</>}
        </Button>
      </div>
    </div>
  );
}
