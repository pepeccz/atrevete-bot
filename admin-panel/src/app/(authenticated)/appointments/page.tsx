"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { ColumnDef } from "@tanstack/react-table";
import { format } from "date-fns";
import { es } from "date-fns/locale";
import {
  MoreHorizontal,
  Plus,
  Calendar,
  Clock,
  User,
  Scissors,
  ChevronLeft,
  ChevronRight,
  Search,
  UserPlus,
  Check,
  X,
  Loader2,
  Edit,
  RefreshCw,
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
import { ScrollArea } from "@/components/ui/scroll-area";
import { toast } from "sonner";
import api from "@/lib/api";
import { PendingActionsCard } from "@/components/appointments/pending-actions-card";
import type {
  Appointment,
  Stylist,
  Service,
  Customer,
  AppointmentStatus,
} from "@/lib/types";

// Format date for display
function formatDate(dateString: string): string {
  try {
    return format(new Date(dateString), "dd/MM/yyyy HH:mm", { locale: es });
  } catch {
    return dateString;
  }
}

// Status badge component
function StatusBadge({ status }: { status: AppointmentStatus }) {
  const variants: Record<
    AppointmentStatus,
    "default" | "success" | "warning" | "destructive" | "secondary"
  > = {
    pending: "warning",
    confirmed: "success",
    completed: "secondary",
    cancelled: "destructive",
    no_show: "destructive",
  };

  const labels: Record<AppointmentStatus, string> = {
    pending: "Pendiente",
    confirmed: "Confirmada",
    completed: "Completada",
    cancelled: "Cancelada",
    no_show: "No asistio",
  };

  return <Badge variant={variants[status]}>{labels[status]}</Badge>;
}

// ============================================================================
// Wizard Step Components
// ============================================================================

interface WizardState {
  step: 1 | 2 | 3 | 4;
  customer: Customer | null;
  selectedServices: Service[];
  startDate: string;
  endDate: string;
  selectedSlot: {
    time: string;
    end_time: string;
    full_datetime: string;
    stylist_id: string;
    stylist_name: string;
    date: string;
  } | null;
  firstName: string;  // Appointment-specific name (defaults to customer name)
  lastName: string;   // Appointment-specific last name (defaults to customer last name)
  notes: string;
}

// Step 1: Customer Selection
function CustomerStep({
  customers,
  selectedCustomer,
  onSelect,
  onCreateNew,
}: {
  customers: Customer[];
  selectedCustomer: Customer | null;
  onSelect: (customer: Customer) => void;
  onCreateNew: (customer: Customer) => void;
}) {
  const [search, setSearch] = useState("");
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newCustomer, setNewCustomer] = useState({
    phone: "",
    first_name: "",
    last_name: "",
  });
  const [creating, setCreating] = useState(false);

  const filteredCustomers = useMemo(() => {
    if (!search) return customers.slice(0, 50);
    const term = search.toLowerCase();
    return customers
      .filter(
        (c) =>
          c.first_name.toLowerCase().includes(term) ||
          (c.last_name?.toLowerCase() || "").includes(term) ||
          c.phone.includes(term)
      )
      .slice(0, 50);
  }, [customers, search]);

  const handleCreateCustomer = async () => {
    if (!newCustomer.phone || !newCustomer.first_name) {
      toast.error("Telefono y nombre son requeridos");
      return;
    }
    setCreating(true);
    try {
      const created = await api.create<Customer>("customers", {
        phone: newCustomer.phone,
        first_name: newCustomer.first_name,
        last_name: newCustomer.last_name || null,
      });
      toast.success("Cliente creado");
      onCreateNew(created);
      setShowCreateForm(false);
      setNewCustomer({ phone: "", first_name: "", last_name: "" });
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
            onClick={() => setShowCreateForm(false)}
          >
            <ChevronLeft className="h-4 w-4 mr-1" />
            Volver
          </Button>
          <span className="text-sm font-medium">Crear nuevo cliente</span>
        </div>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="phone">Telefono *</Label>
            <Input
              id="phone"
              placeholder="+34612345678"
              value={newCustomer.phone}
              onChange={(e) =>
                setNewCustomer((prev) => ({ ...prev, phone: e.target.value }))
              }
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="first_name">Nombre *</Label>
            <Input
              id="first_name"
              placeholder="Maria"
              value={newCustomer.first_name}
              onChange={(e) =>
                setNewCustomer((prev) => ({
                  ...prev,
                  first_name: e.target.value,
                }))
              }
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="last_name">Apellido</Label>
            <Input
              id="last_name"
              placeholder="Garcia"
              value={newCustomer.last_name}
              onChange={(e) =>
                setNewCustomer((prev) => ({
                  ...prev,
                  last_name: e.target.value,
                }))
              }
            />
          </div>
          <Button
            onClick={handleCreateCustomer}
            disabled={creating}
            className="w-full"
          >
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
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Buscar por nombre o telefono..."
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

      <ScrollArea className="h-[300px]">
        <div className="space-y-2">
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
            filteredCustomers.map((customer) => (
              <div
                key={customer.id}
                onClick={() => onSelect(customer)}
                className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                  selectedCustomer?.id === customer.id
                    ? "border-primary bg-primary/5"
                    : "hover:border-primary/50"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium">
                      {customer.first_name} {customer.last_name || ""}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {customer.phone}
                    </p>
                  </div>
                  {selectedCustomer?.id === customer.id && (
                    <Check className="h-5 w-5 text-primary" />
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

// Step 2: Service Selection
function ServiceStep({
  services,
  selectedServices,
  onToggle,
}: {
  services: Service[];
  selectedServices: Service[];
  onToggle: (service: Service) => void;
}) {
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");

  const filteredServices = useMemo(() => {
    let result = services.filter((s) => s.is_active);

    if (categoryFilter !== "all") {
      result = result.filter((s) => s.category === categoryFilter);
    }

    if (search) {
      const term = search.toLowerCase();
      result = result.filter((s) => s.name.toLowerCase().includes(term));
    }

    return result;
  }, [services, search, categoryFilter]);

  const totalDuration = selectedServices.reduce(
    (sum, s) => sum + s.duration_minutes,
    0
  );

  const selectedIds = new Set(selectedServices.map((s) => s.id));

  return (
    <div className="space-y-4">
      {/* Selected summary */}
      {selectedServices.length > 0 && (
        <div className="p-3 bg-primary/10 rounded-lg">
          <p className="text-sm font-medium">
            {selectedServices.length} servicio(s) seleccionado(s)
          </p>
          <p className="text-sm text-muted-foreground">
            Duracion total: {totalDuration} minutos
          </p>
          <div className="flex flex-wrap gap-1 mt-2">
            {selectedServices.map((s) => (
              <Badge
                key={s.id}
                variant="secondary"
                className="cursor-pointer"
                onClick={() => onToggle(s)}
              >
                {s.name}
                <X className="ml-1 h-3 w-3" />
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Buscar servicio..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select value={categoryFilter} onValueChange={setCategoryFilter}>
          <SelectTrigger className="w-[150px]">
            <SelectValue placeholder="Categoria" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Todas</SelectItem>
            <SelectItem value="HAIRDRESSING">Peluqueria</SelectItem>
            <SelectItem value="AESTHETICS">Estetica</SelectItem>
            <SelectItem value="BOTH">Ambas</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Service list */}
      <ScrollArea className="h-[280px]">
        <div className="space-y-2">
          {filteredServices.map((service) => (
            <div
              key={service.id}
              onClick={() => onToggle(service)}
              className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                selectedIds.has(service.id)
                  ? "border-primary bg-primary/5"
                  : "hover:border-primary/50"
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="flex-1">
                  <p className="font-medium">{service.name}</p>
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Clock className="h-3 w-3" />
                    <span>{service.duration_minutes} min</span>
                    <Badge variant="outline" className="text-xs">
                      {service.category === "HAIRDRESSING"
                        ? "Peluqueria"
                        : service.category === "AESTHETICS"
                          ? "Estetica"
                          : "Ambas"}
                    </Badge>
                  </div>
                </div>
                <Checkbox checked={selectedIds.has(service.id)} />
              </div>
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}

// Step 3: Date Range & Availability Selection
function AvailabilityStep({
  selectedServices,
  stylists,
  startDate,
  endDate,
  selectedSlot,
  onStartDateChange,
  onEndDateChange,
  onSlotSelect,
}: {
  selectedServices: Service[];
  stylists: Stylist[];
  startDate: string;
  endDate: string;
  selectedSlot: WizardState["selectedSlot"];
  onStartDateChange: (date: string) => void;
  onEndDateChange: (date: string) => void;
  onSlotSelect: (slot: WizardState["selectedSlot"]) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [stylistFilter, setStylistFilter] = useState<string>("all");
  const [availability, setAvailability] = useState<{
    days: Array<{
      date: string;
      day_name: string;
      is_closed: boolean;
      holiday: string | null;
      stylists: Array<{
        id: string;
        name: string;
        category: string;
        slots: Array<{
          time: string;
          end_time: string;
          full_datetime: string;
          stylist_id: string;
        }>;
      }>;
    }>;
    total_duration_minutes: number;
    service_category: string | null;
  } | null>(null);

  // Memoize serviceIds to prevent unnecessary re-renders
  const serviceIds = useMemo(
    () => selectedServices.map((s) => s.id),
    [selectedServices]
  );

  // Determine compatible stylists based on service category
  const compatibleStylists = useMemo(() => {
    const categories = new Set(selectedServices.map((s) => s.category));
    const needsBoth =
      categories.has("HAIRDRESSING") && categories.has("AESTHETICS");
    const needsAesthetics =
      categories.has("AESTHETICS") && !categories.has("HAIRDRESSING");

    return stylists.filter((s) => {
      if (!s.is_active) return false;
      if (needsBoth) return s.category === "BOTH";
      if (needsAesthetics)
        return s.category === "AESTHETICS" || s.category === "BOTH";
      return s.category === "HAIRDRESSING" || s.category === "BOTH";
    });
  }, [stylists, selectedServices]);

  // Manual search function - no useEffect dependency loops
  const handleSearch = async () => {
    if (!startDate || !endDate || serviceIds.length === 0) {
      toast.error("Selecciona fechas y servicios");
      return;
    }

    setLoading(true);
    try {
      const result = await api.searchAvailability(
        serviceIds,
        startDate,
        endDate,
        stylistFilter === "all" ? null : stylistFilter
      );
      setAvailability(result);
      onSlotSelect(null); // Reset slot when searching
    } catch (error) {
      toast.error("Error buscando disponibilidad");
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  // Today's date for min date
  const today = new Date().toISOString().split("T")[0];

  // Calculate max end date (14 days from start)
  const maxEndDate = useMemo(() => {
    if (!startDate) return "";
    const start = new Date(startDate);
    start.setDate(start.getDate() + 14);
    return start.toISOString().split("T")[0];
  }, [startDate]);

  return (
    <div className="space-y-4">
      {/* Date range pickers */}
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>Fecha inicio</Label>
          <Input
            type="date"
            value={startDate}
            onChange={(e) => {
              onStartDateChange(e.target.value);
              // Auto-set end date if not set or invalid
              if (!endDate || endDate < e.target.value) {
                onEndDateChange(e.target.value);
              }
            }}
            min={today}
          />
        </div>
        <div className="space-y-2">
          <Label>Fecha fin</Label>
          <Input
            type="date"
            value={endDate}
            onChange={(e) => onEndDateChange(e.target.value)}
            min={startDate || today}
            max={maxEndDate}
          />
        </div>
      </div>

      {/* Stylist filter */}
      <div className="space-y-2">
        <Label>Estilista</Label>
        <Select value={stylistFilter} onValueChange={setStylistFilter}>
          <SelectTrigger>
            <SelectValue placeholder="Todos los estilistas" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Todos los estilistas</SelectItem>
            {compatibleStylists.map((stylist) => (
              <SelectItem key={stylist.id} value={stylist.id}>
                {stylist.name} (
                {stylist.category === "HAIRDRESSING"
                  ? "Peluqueria"
                  : stylist.category === "AESTHETICS"
                    ? "Estetica"
                    : "Ambas"}
                )
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Search button */}
      <Button
        onClick={handleSearch}
        disabled={loading || !startDate || !endDate}
        className="w-full"
      >
        {loading ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Buscando...
          </>
        ) : (
          <>
            <Search className="mr-2 h-4 w-4" />
            Buscar Disponibilidad
          </>
        )}
      </Button>

      {/* Availability display */}
      {availability && (
        <ScrollArea className="h-[220px]">
          <div className="space-y-4">
            {availability.days.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                <p>No se encontraron dias disponibles</p>
              </div>
            ) : (
              availability.days.map((day) => (
                <div key={day.date} className="space-y-2">
                  {/* Day header */}
                  <div className="flex items-center gap-2 font-medium">
                    <Calendar className="h-4 w-4" />
                    <span>
                      {day.day_name} {format(new Date(day.date), "d/MM/yyyy")}
                    </span>
                    {day.is_closed && (
                      <Badge variant="secondary">Cerrado</Badge>
                    )}
                    {day.holiday && (
                      <Badge variant="destructive">{day.holiday}</Badge>
                    )}
                  </div>

                  {/* Stylists for this day */}
                  {!day.is_closed && !day.holiday && (
                    <div className="pl-6 space-y-3">
                      {day.stylists.length === 0 ? (
                        <p className="text-sm text-muted-foreground">
                          Sin estilistas disponibles
                        </p>
                      ) : (
                        day.stylists.map((stylist) => (
                          <div key={stylist.id} className="space-y-1">
                            <div className="flex items-center gap-2">
                              <Scissors className="h-3 w-3" />
                              <span className="text-sm font-medium">
                                {stylist.name}
                              </span>
                            </div>

                            {stylist.slots.length === 0 ? (
                              <p className="text-xs text-muted-foreground pl-5">
                                Sin huecos
                              </p>
                            ) : (
                              <div className="flex flex-wrap gap-1 pl-5">
                                {stylist.slots.slice(0, 12).map((slot) => {
                                  const isSelected =
                                    selectedSlot?.full_datetime ===
                                      slot.full_datetime &&
                                    selectedSlot?.stylist_id === stylist.id;
                                  return (
                                    <Button
                                      key={`${stylist.id}-${slot.time}`}
                                      variant={isSelected ? "default" : "outline"}
                                      size="sm"
                                      className="h-7 px-2 text-xs"
                                      onClick={() =>
                                        onSlotSelect({
                                          ...slot,
                                          stylist_id: stylist.id,
                                          stylist_name: stylist.name,
                                          date: day.date,
                                        })
                                      }
                                    >
                                      {slot.time}
                                    </Button>
                                  );
                                })}
                                {stylist.slots.length > 12 && (
                                  <span className="text-xs text-muted-foreground self-center">
                                    +{stylist.slots.length - 12} mas
                                  </span>
                                )}
                              </div>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}

// Step 4: Confirmation
function ConfirmationStep({
  customer,
  services,
  slot,
  firstName,
  lastName,
  notes,
  onFirstNameChange,
  onLastNameChange,
  onNotesChange,
}: {
  customer: Customer;
  services: Service[];
  slot: NonNullable<WizardState["selectedSlot"]>;
  firstName: string;
  lastName: string;
  notes: string;
  onFirstNameChange: (firstName: string) => void;
  onLastNameChange: (lastName: string) => void;
  onNotesChange: (notes: string) => void;
}) {
  const totalDuration = services.reduce(
    (sum, s) => sum + s.duration_minutes,
    0
  );

  return (
    <div className="space-y-4">
      <div className="p-4 bg-muted rounded-lg space-y-3">
        <div className="flex items-start gap-3">
          <User className="h-5 w-5 text-muted-foreground mt-0.5" />
          <div>
            <p className="text-sm text-muted-foreground">Cliente</p>
            <p className="font-medium">
              {customer.first_name} {customer.last_name || ""}
            </p>
            <p className="text-sm text-muted-foreground">{customer.phone}</p>
          </div>
        </div>

        <div className="flex items-start gap-3">
          <Scissors className="h-5 w-5 text-muted-foreground mt-0.5" />
          <div>
            <p className="text-sm text-muted-foreground">Servicios</p>
            <div className="flex flex-wrap gap-1 mt-1">
              {services.map((s) => (
                <Badge key={s.id} variant="secondary">
                  {s.name}
                </Badge>
              ))}
            </div>
            <p className="text-sm text-muted-foreground mt-1">
              Duracion total: {totalDuration} min
            </p>
          </div>
        </div>

        <div className="flex items-start gap-3">
          <Calendar className="h-5 w-5 text-muted-foreground mt-0.5" />
          <div>
            <p className="text-sm text-muted-foreground">Fecha y hora</p>
            <p className="font-medium">
              {format(new Date(slot.full_datetime), "EEEE d 'de' MMMM, HH:mm", {
                locale: es,
              })}
            </p>
            <p className="text-sm text-muted-foreground">
              hasta {slot.end_time}
            </p>
          </div>
        </div>

        <div className="flex items-start gap-3">
          <User className="h-5 w-5 text-muted-foreground mt-0.5" />
          <div>
            <p className="text-sm text-muted-foreground">Estilista</p>
            <p className="font-medium">{slot.stylist_name}</p>
          </div>
        </div>
      </div>

      {/* Appointment Name Section */}
      <div className="space-y-3 border-t pt-4">
        <div>
          <p className="text-sm font-medium">Nombre para la cita</p>
          <p className="text-xs text-muted-foreground">
            Por defecto el nombre del cliente. Modifica si la cita es para otra persona.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="firstName">Nombre *</Label>
            <Input
              id="firstName"
              value={firstName}
              onChange={(e) => onFirstNameChange(e.target.value)}
              placeholder="Nombre"
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="lastName">Apellidos</Label>
            <Input
              id="lastName"
              value={lastName}
              onChange={(e) => onLastNameChange(e.target.value)}
              placeholder="Apellidos (opcional)"
            />
          </div>
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="notes">Notas (opcional)</Label>
        <Textarea
          id="notes"
          value={notes}
          onChange={(e) => onNotesChange(e.target.value)}
          placeholder="Notas adicionales para la cita..."
          rows={3}
        />
      </div>
    </div>
  );
}

// ============================================================================
// Main Wizard Modal
// ============================================================================

function AppointmentWizardModal({
  open,
  onOpenChange,
  onSuccess,
  services,
  stylists,
  customers,
  refreshCustomers,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
  services: Service[];
  stylists: Stylist[];
  customers: Customer[];
  refreshCustomers: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [state, setState] = useState<WizardState>({
    step: 1,
    customer: null,
    selectedServices: [],
    startDate: "",
    endDate: "",
    selectedSlot: null,
    firstName: "",
    lastName: "",
    notes: "",
  });

  // Reset state when modal closes
  useEffect(() => {
    if (!open) {
      setState({
        step: 1,
        customer: null,
        selectedServices: [],
        startDate: "",
        endDate: "",
        selectedSlot: null,
        firstName: "",
        lastName: "",
        notes: "",
      });
    }
  }, [open]);

  const canProceed = () => {
    switch (state.step) {
      case 1:
        return state.customer !== null;
      case 2:
        return state.selectedServices.length > 0;
      case 3:
        return state.selectedSlot !== null;
      case 4:
        return state.firstName.trim().length > 0;
      default:
        return false;
    }
  };

  const handleNext = () => {
    if (state.step < 4) {
      setState((prev) => ({ ...prev, step: (prev.step + 1) as 1 | 2 | 3 | 4 }));
    }
  };

  const handleBack = () => {
    if (state.step > 1) {
      setState((prev) => ({ ...prev, step: (prev.step - 1) as 1 | 2 | 3 | 4 }));
    }
  };

  const handleSubmit = async () => {
    if (!state.customer || !state.selectedSlot) return;

    // Validate firstName is not empty
    const trimmedFirstName = state.firstName.trim();
    if (!trimmedFirstName) {
      toast.error("El nombre es obligatorio");
      return;
    }

    setLoading(true);
    try {
      await api.create("appointments", {
        customer_id: state.customer.id,
        stylist_id: state.selectedSlot.stylist_id,
        service_ids: state.selectedServices.map((s) => s.id),
        start_time: state.selectedSlot.full_datetime,
        first_name: trimmedFirstName,
        last_name: state.lastName.trim() || null,
        notes: state.notes || null,
      });

      toast.success("Cita creada correctamente");
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

  const stepTitles = [
    "Seleccionar Cliente",
    "Seleccionar Servicios",
    "Elegir Fecha y Hora",
    "Confirmar Cita",
  ];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>Nueva Cita</DialogTitle>
          <DialogDescription>
            Paso {state.step} de 4: {stepTitles[state.step - 1]}
          </DialogDescription>
        </DialogHeader>

        {/* Progress indicator */}
        <div className="flex gap-2 mb-4">
          {[1, 2, 3, 4].map((step) => (
            <div
              key={step}
              className={`h-1 flex-1 rounded-full transition-colors ${
                step <= state.step ? "bg-primary" : "bg-muted"
              }`}
            />
          ))}
        </div>

        {/* Step content */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {state.step === 1 && (
            <CustomerStep
              customers={customers}
              selectedCustomer={state.customer}
              onSelect={(customer) =>
                setState((prev) => ({
                  ...prev,
                  customer,
                  firstName: customer.first_name,
                  lastName: customer.last_name || "",
                }))
              }
              onCreateNew={(customer) => {
                setState((prev) => ({
                  ...prev,
                  customer,
                  firstName: customer.first_name,
                  lastName: customer.last_name || "",
                }));
                refreshCustomers();
              }}
            />
          )}

          {state.step === 2 && (
            <ServiceStep
              services={services}
              selectedServices={state.selectedServices}
              onToggle={(service) => {
                setState((prev) => {
                  const exists = prev.selectedServices.some(
                    (s) => s.id === service.id
                  );
                  return {
                    ...prev,
                    selectedServices: exists
                      ? prev.selectedServices.filter((s) => s.id !== service.id)
                      : [...prev.selectedServices, service],
                    // Reset slot when services change
                    selectedSlot: null,
                  };
                });
              }}
            />
          )}

          {state.step === 3 && (
            <AvailabilityStep
              selectedServices={state.selectedServices}
              stylists={stylists}
              startDate={state.startDate}
              endDate={state.endDate}
              selectedSlot={state.selectedSlot}
              onStartDateChange={(date) =>
                setState((prev) => ({ ...prev, startDate: date }))
              }
              onEndDateChange={(date) =>
                setState((prev) => ({ ...prev, endDate: date }))
              }
              onSlotSelect={(slot) =>
                setState((prev) => ({ ...prev, selectedSlot: slot }))
              }
            />
          )}

          {state.step === 4 && state.customer && state.selectedSlot && (
            <ConfirmationStep
              customer={state.customer}
              services={state.selectedServices}
              slot={state.selectedSlot}
              firstName={state.firstName}
              lastName={state.lastName}
              notes={state.notes}
              onFirstNameChange={(firstName) =>
                setState((prev) => ({ ...prev, firstName }))
              }
              onLastNameChange={(lastName) =>
                setState((prev) => ({ ...prev, lastName }))
              }
              onNotesChange={(notes) => setState((prev) => ({ ...prev, notes }))}
            />
          )}
        </div>

        {/* Navigation buttons */}
        <div className="flex justify-between pt-4 border-t mt-4">
          <Button
            variant="outline"
            onClick={state.step === 1 ? () => onOpenChange(false) : handleBack}
          >
            {state.step === 1 ? (
              "Cancelar"
            ) : (
              <>
                <ChevronLeft className="h-4 w-4 mr-1" />
                Atras
              </>
            )}
          </Button>

          {state.step < 4 ? (
            <Button onClick={handleNext} disabled={!canProceed()}>
              Siguiente
              <ChevronRight className="h-4 w-4 ml-1" />
            </Button>
          ) : (
            <Button onClick={handleSubmit} disabled={loading || !canProceed()}>
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Creando...
                </>
              ) : (
                <>
                  <Check className="h-4 w-4 mr-2" />
                  Crear Cita
                </>
              )}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ============================================================================
// Main Page Component
// ============================================================================

export default function AppointmentsPage() {
  const router = useRouter();
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [stylists, setStylists] = useState<Stylist[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [appointmentToDelete, setAppointmentToDelete] = useState<string | null>(
    null
  );
  const [filters, setFilters] = useState({
    stylist_id: "",
    status: "",
  });
  const [syncing, setSyncing] = useState(false);

  // Handle manual GCal sync
  const handleGcalSync = async () => {
    setSyncing(true);
    try {
      const result = await api.triggerGcalSync();
      if (result.success) {
        toast.success(result.message);
        // Reload appointments after sync
        await loadData();
      } else {
        toast.error(result.message);
      }
    } catch (error) {
      toast.error("Error al sincronizar con Google Calendar");
    } finally {
      setSyncing(false);
    }
  };

  // Create stylist and service maps for display
  const stylistMap = Object.fromEntries(stylists.map((s) => [s.id, s.name]));
  const serviceMap = Object.fromEntries(services.map((s) => [s.id, s.name]));

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [appointmentsRes, stylistsRes, servicesRes, customersRes] =
        await Promise.all([
          api.list<Appointment>("appointments", {
            page_size: 100,
            ...(filters.stylist_id && { stylist_id: filters.stylist_id }),
            ...(filters.status && { status: filters.status }),
          }),
          api.list<Stylist>("stylists", { page_size: 100 }),
          api.list<Service>("services", { page_size: 200 }),
          api.list<Customer>("customers", { page_size: 500 }),
        ]);

      setAppointments(appointmentsRes.items);
      setStylists(stylistsRes.items);
      setServices(servicesRes.items);
      setCustomers(customersRes.items);
    } catch (error) {
      toast.error("Error al cargar los datos");
      console.error(error);
    } finally {
      setLoading(false);
    }
  }, [filters]);

  const loadCustomers = useCallback(async () => {
    try {
      const res = await api.list<Customer>("customers", { page_size: 500 });
      setCustomers(res.items);
    } catch (error) {
      console.error("Error loading customers", error);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleDelete = async () => {
    if (!appointmentToDelete) return;

    try {
      await api.delete("appointments", appointmentToDelete);
      toast.success("Cita eliminada");
      loadData();
    } catch (error) {
      toast.error("Error al eliminar la cita");
      console.error(error);
    } finally {
      setDeleteDialogOpen(false);
      setAppointmentToDelete(null);
    }
  };

  const columns: ColumnDef<Appointment>[] = [
    {
      accessorKey: "start_time",
      header: ({ column }) => (
        <SortableHeader column={column}>
          <Calendar className="mr-2 h-4 w-4" />
          Fecha
        </SortableHeader>
      ),
      cell: ({ row }) => formatDate(row.getValue("start_time")),
    },
    {
      accessorKey: "first_name",
      header: () => (
        <div className="flex items-center">
          <User className="mr-2 h-4 w-4" />
          Cliente
        </div>
      ),
      cell: ({ row }) => {
        const appointment = row.original;
        return `${appointment.first_name} ${appointment.last_name || ""}`.trim();
      },
    },
    {
      accessorKey: "stylist_id",
      header: () => (
        <div className="flex items-center">
          <Scissors className="mr-2 h-4 w-4" />
          Estilista
        </div>
      ),
      cell: ({ row }) => stylistMap[row.getValue("stylist_id") as string] || "-",
    },
    {
      accessorKey: "service_ids",
      header: "Servicios",
      cell: ({ row }) => {
        const serviceIds = row.getValue("service_ids") as string[];
        if (!serviceIds || serviceIds.length === 0) {
          return <span className="text-muted-foreground">Sin servicios</span>;
        }

        const resolved = serviceIds.map((id) => serviceMap[id]);
        const validNames = resolved.filter(Boolean);
        const orphanCount = resolved.length - validNames.length;

        if (orphanCount > 0 && validNames.length === 0) {
          return (
            <Badge variant="destructive" className="text-xs">
              {orphanCount} servicio(s) no encontrado(s)
            </Badge>
          );
        }

        if (orphanCount > 0) {
          const names = validNames.join(", ");
          return (
            <div className="flex items-center gap-1">
              <span>{names.length > 25 ? names.substring(0, 25) + "..." : names}</span>
              <Badge variant="destructive" className="text-xs">
                +{orphanCount}
              </Badge>
            </div>
          );
        }

        const names = validNames.join(", ");
        return names.length > 40 ? names.substring(0, 40) + "..." : names;
      },
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
      accessorKey: "status",
      header: "Estado",
      cell: ({ row }) => (
        <StatusBadge status={row.getValue("status") as AppointmentStatus} />
      ),
    },
    {
      id: "actions",
      cell: ({ row }) => {
        const appointment = row.original;
        return (
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={() => router.push(`/appointments/${appointment.id}`)}
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
                    setAppointmentToDelete(appointment.id);
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
        title="Citas"
        description="Gestion de citas del salon"
        action={
          <div className="flex gap-2">
            <Button variant="outline" onClick={handleGcalSync} disabled={syncing}>
              <RefreshCw className={`mr-2 h-4 w-4 ${syncing ? "animate-spin" : ""}`} />
              Sync GCal
            </Button>
            <Button onClick={() => setCreateModalOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Nueva Cita
            </Button>
          </div>
        }
      />

      <div className="flex-1 p-6 space-y-6">
        {/* Pending Actions Card */}
        <PendingActionsCard />

        <Card>
          <CardContent className="pt-6">
            {/* Filters */}
            <div className="flex gap-4 mb-6">
              <div className="w-[200px]">
                <Select
                  value={filters.stylist_id}
                  onValueChange={(value) =>
                    setFilters((prev) => ({
                      ...prev,
                      stylist_id: value === "all" ? "" : value,
                    }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Filtrar por estilista" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Todos los estilistas</SelectItem>
                    {stylists.map((stylist) => (
                      <SelectItem key={stylist.id} value={stylist.id}>
                        {stylist.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="w-[200px]">
                <Select
                  value={filters.status}
                  onValueChange={(value) =>
                    setFilters((prev) => ({
                      ...prev,
                      status: value === "all" ? "" : value,
                    }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Filtrar por estado" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Todos los estados</SelectItem>
                    <SelectItem value="pending">Pendiente</SelectItem>
                    <SelectItem value="confirmed">Confirmada</SelectItem>
                    <SelectItem value="completed">Completada</SelectItem>
                    <SelectItem value="cancelled">Cancelada</SelectItem>
                    <SelectItem value="no_show">No asistio</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Data Table */}
            <DataTable
              columns={columns}
              data={appointments}
              isLoading={loading}
              searchKey="first_name"
              searchPlaceholder="Buscar por nombre..."
            />
          </CardContent>
        </Card>
      </div>

      {/* New Wizard Modal */}
      <AppointmentWizardModal
        open={createModalOpen}
        onOpenChange={setCreateModalOpen}
        onSuccess={loadData}
        services={services}
        stylists={stylists}
        customers={customers}
        refreshCustomers={loadCustomers}
      />

      {/* Delete Confirmation */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar cita</AlertDialogTitle>
            <AlertDialogDescription>
              Esta accion no se puede deshacer. La cita sera eliminada
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
