"use client";

import { useEffect, useState, useCallback } from "react";
import { Plus, CalendarOff } from "lucide-react";
import { Header } from "@/components/layout/header";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
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
import { toast } from "sonner";
import api from "@/lib/api";
import { PendingActionsCard } from "@/components/appointments/pending-actions-card";
import { AppointmentFilters } from "./components/appointment-filters";
import { AppointmentsTable } from "./components/appointments-table";
import { AppointmentWizard } from "./components/wizard/appointment-wizard";
import { EmptyState } from "@/components/shared/empty-state";
import type { Appointment, Stylist, Service, Customer } from "@/lib/types";

export default function AppointmentsPage() {
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [stylists, setStylists] = useState<Stylist[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [appointmentToDelete, setAppointmentToDelete] = useState<string | null>(null);
  const [filters, setFilters] = useState({ stylist_id: "", status: "" });
  // R6: client-side GCal-failed toggle (no server param needed — data already loaded)
  const [gcalFailedOnly, setGcalFailedOnly] = useState(false);

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

  // Refresh when the global Sync GCal button completes a sync.
  useEffect(() => {
    const handler = () => loadData();
    window.addEventListener("atrevete:gcal-synced", handler);
    return () => window.removeEventListener("atrevete:gcal-synced", handler);
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

  return (
    <div className="flex flex-col">
      <Header
        title="Citas"
        subtitle="Gestión de citas del salón"
        primaryAction={
          <Button onClick={() => setCreateModalOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Nueva Cita
          </Button>
        }
      />

      <div className="flex-1 p-4 md:p-6 space-y-6">
        <PendingActionsCard />

        <Card>
          <CardContent className="pt-6">
            <AppointmentFilters
              stylists={stylists}
              stylistId={filters.stylist_id}
              status={filters.status}
              onStylistChange={(value) =>
                setFilters((prev) => ({ ...prev, stylist_id: value }))
              }
              onStatusChange={(value) =>
                setFilters((prev) => ({ ...prev, status: value }))
              }
            />
            {!loading && appointments.length === 0 ? (
              <EmptyState
                icon={CalendarOff}
                title="No hay citas programadas"
                description="Agenda la primera cita para comenzar a gestionar el calendario."
                action={{ label: "Nueva cita", onClick: () => setCreateModalOpen(true) }}
              />
            ) : (
              <AppointmentsTable
                appointments={appointments}
                stylistMap={stylistMap}
                serviceMap={serviceMap}
                isLoading={loading}
                onDeleteRequest={(id) => {
                  setAppointmentToDelete(id);
                  setDeleteDialogOpen(true);
                }}
                gcalFailedOnly={gcalFailedOnly}
                onGcalFailedToggle={() => setGcalFailedOnly((prev) => !prev)}
              />
            )}
          </CardContent>
        </Card>
      </div>

      <AppointmentWizard
        open={createModalOpen}
        onOpenChange={setCreateModalOpen}
        onSuccess={loadData}
        services={services}
        stylists={stylists}
        customers={customers}
        refreshCustomers={loadCustomers}
      />

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar cita</AlertDialogTitle>
            <AlertDialogDescription>
              Esta acción no se puede deshacer. La cita será eliminada permanentemente.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
              Eliminar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
