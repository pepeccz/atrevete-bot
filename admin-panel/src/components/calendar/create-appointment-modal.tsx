"use client";

import { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import api from "@/lib/api";

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
}

interface CreateAppointmentModalProps {
  isOpen: boolean;
  onClose: () => void;
  stylistId: string;
  selectedDate: Date | null;
  onSuccess: () => void;
}

export function CreateAppointmentModal({
  isOpen,
  onClose,
  stylistId,
  selectedDate,
  onSuccess,
}: CreateAppointmentModalProps) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // Form state
  const [selectedCustomer, setSelectedCustomer] = useState<string>("");
  const [selectedServices, setSelectedServices] = useState<string[]>([]);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [notes, setNotes] = useState("");
  const [startTime, setStartTime] = useState("");
  const [sendNotification, setSendNotification] = useState(true);

  // Load customers and services on mount
  useEffect(() => {
    async function loadData() {
      try {
        const [customersData, servicesData] = await Promise.all([
          api.list<Customer>("customers", { page_size: 100 }),
          api.list<Service>("services", { is_active: true, page_size: 100 }),
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

  // Pre-fill date/time when selected
  useEffect(() => {
    if (selectedDate) {
      const hours = selectedDate.getHours().toString().padStart(2, "0");
      const minutes = selectedDate.getMinutes().toString().padStart(2, "0");
      setStartTime(`${hours}:${minutes}`);
    }
  }, [selectedDate]);

  const filteredCustomers = customers.filter(
    (c) =>
      c.phone.includes(searchQuery) ||
      c.first_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (c.last_name &&
        c.last_name.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  const handleSubmit = async () => {
    if (
      !selectedCustomer ||
      selectedServices.length === 0 ||
      !firstName ||
      !selectedDate ||
      !startTime
    ) {
      alert("Por favor completa todos los campos requeridos");
      return;
    }

    try {
      setIsLoading(true);

      // Combine date and time
      const [hours, minutes] = startTime.split(":");
      const appointmentDate = new Date(selectedDate);
      appointmentDate.setHours(parseInt(hours), parseInt(minutes), 0, 0);

      await api.create("appointments", {
        customer_id: selectedCustomer,
        stylist_id: stylistId,
        service_ids: selectedServices,
        start_time: appointmentDate.toISOString(),
        first_name: firstName,
        last_name: lastName || null,
        notes: notes || null,
        send_notification: sendNotification,
      });

      // Reset form
      setSelectedCustomer("");
      setSelectedServices([]);
      setFirstName("");
      setLastName("");
      setNotes("");
      setStartTime("");
      setSendNotification(true);

      onSuccess();
      onClose();
    } catch (error) {
      console.error("Error creating appointment:", error);
      alert("Error al crear la cita: " + (error instanceof Error ? error.message : "Unknown error"));
    } finally {
      setIsLoading(false);
    }
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
          {/* Customer Search/Select */}
          <div className="space-y-2">
            <Label htmlFor="customer">Cliente *</Label>
            <Input
              id="customer-search"
              type="text"
              placeholder="Buscar por teléfono o nombre..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <Select value={selectedCustomer} onValueChange={setSelectedCustomer}>
              <SelectTrigger>
                <SelectValue placeholder="Selecciona un cliente" />
              </SelectTrigger>
              <SelectContent>
                {filteredCustomers.map((customer) => (
                  <SelectItem key={customer.id} value={customer.id}>
                    {customer.first_name} {customer.last_name} - {customer.phone}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Services Multi-Select */}
          <div className="space-y-2">
            <Label>Servicios * (Duración total: {totalDuration} min)</Label>
            <div className="border rounded-md p-2 max-h-40 overflow-y-auto space-y-1">
              {services.map((service) => (
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
              ))}
            </div>
          </div>

          {/* Date and Time */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="date">Fecha *</Label>
              <Input
                id="date"
                type="date"
                value={selectedDate?.toISOString().split("T")[0] || ""}
                readOnly
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
    </Dialog>
  );
}
