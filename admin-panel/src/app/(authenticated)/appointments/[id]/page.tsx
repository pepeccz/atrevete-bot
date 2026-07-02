"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter, useParams } from "next/navigation";
import { format, parseISO } from "date-fns";
import { es } from "date-fns/locale";
import {
  ArrowLeft,
  Ban,
  Calendar,
  CalendarClock,
  Check,
  Clock,
  User,
  Scissors,
  Save,
  Loader2,
  Trash2,
} from "lucide-react";

import { Header } from "@/components/layout/header";
import { formatCategory } from "@/lib/category-labels";
import { DatePicker } from "@/components/shared/date-picker";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageSkeleton } from "@/components/shared/loading-skeleton";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
import api, { ApiRequestError } from "@/lib/api";
import type { Stylist, AppointmentStatus, ServiceCategory } from "@/lib/types";
import { RescheduleModal } from "@/components/appointments/reschedule-modal";
import { StatusBadge } from "@/components/shared/status-badge";

// StatusBadge imported from @/components/shared/status-badge

interface AppointmentDetail {
  id: string;
  customer_id: string;
  stylist_id: string;
  start_time: string;
  duration_minutes: number;
  status: AppointmentStatus;
  first_name: string;
  last_name: string | null;
  notes: string | null;
  services: Array<{
    id: string;
    name: string;
    category: ServiceCategory;
    duration_minutes: number;
  }>;
  customer: {
    id: string;
    phone: string;
    first_name: string | null;
    last_name: string | null;
  };
  stylist: {
    id: string;
    name: string;
    category: string;
  };
  created_at: string;
  updated_at: string;
}

export default function AppointmentDetailPage() {
  const router = useRouter();
  const params = useParams();
  const appointmentId = params.id as string;

  const [appointment, setAppointment] = useState<AppointmentDetail | null>(null);
  const [stylists, setStylists] = useState<Stylist[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isActionLoading, setIsActionLoading] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);
  // Separate state for operator "cancel appointment" action (NOT the form discard or DELETE flows)
  const [showAppointmentCancelConfirm, setShowAppointmentCancelConfirm] = useState(false);
  const [rescheduleModalOpen, setRescheduleModalOpen] = useState(false);

  // Snapshot of initial form values for dirty-check
  const initialRef = useRef<{
    stylistId: string; date: string; time: string;
    firstName: string; lastName: string; notes: string; status: string;
  } | null>(null);

  // Form state
  const [selectedStylistId, setSelectedStylistId] = useState("");
  const [selectedDate, setSelectedDate] = useState("");
  const [selectedTime, setSelectedTime] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [notes, setNotes] = useState("");
  const [status, setStatus] = useState<AppointmentStatus>("confirmed");

  // Fetch appointment and stylists
  const fetchData = useCallback(async () => {
    try {
      setIsLoading(true);
      const [apptData, stylistsData] = await Promise.all([
        api.getAppointment(appointmentId),
        api.list<Stylist>("stylists", { is_active: true }),
      ]);

      setAppointment(apptData as AppointmentDetail);
      setStylists(stylistsData.items);

      // Initialize form with appointment data
      const startDate = parseISO(apptData.start_time);
      setSelectedStylistId(apptData.stylist_id);
      setSelectedDate(format(startDate, "yyyy-MM-dd"));
      setSelectedTime(format(startDate, "HH:mm"));
      setFirstName(apptData.first_name);
      setLastName(apptData.last_name || "");
      setNotes(apptData.notes || "");
      setStatus(apptData.status as AppointmentStatus);

      // Snapshot initial values for dirty-check
      initialRef.current = {
        stylistId: apptData.stylist_id,
        date: format(startDate, "yyyy-MM-dd"),
        time: format(startDate, "HH:mm"),
        firstName: apptData.first_name,
        lastName: apptData.last_name || "",
        notes: apptData.notes || "",
        status: apptData.status,
      };
    } catch (error) {
      console.error("Error fetching appointment:", error);
      toast.error("Error al cargar la cita");
      router.push("/appointments");
    } finally {
      setIsLoading(false);
    }
  }, [appointmentId, router]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const isDirty = () => {
    const init = initialRef.current;
    if (!init) return false;
    return (
      selectedStylistId !== init.stylistId ||
      selectedDate !== init.date ||
      selectedTime !== init.time ||
      firstName.trim() !== init.firstName.trim() ||
      lastName.trim() !== init.lastName.trim() ||
      notes.trim() !== init.notes.trim() ||
      status !== init.status
    );
  };

  const handleSave = async () => {
    if (!appointment) return;

    // Validate required fields
    if (!firstName.trim()) {
      toast.error("El nombre es requerido");
      return;
    }

    if (!selectedDate || !selectedTime) {
      toast.error("La fecha y hora son requeridas");
      return;
    }

    setIsSaving(true);
    try {
      const startDateTime = `${selectedDate}T${selectedTime}:00`;

      await api.updateAppointment(appointmentId, {
        stylist_id: selectedStylistId,
        start_time: startDateTime,
        first_name: firstName.trim(),
        last_name: lastName.trim() || undefined,
        notes: notes.trim() || undefined,
        status: status,
      });

      toast.success("Cita actualizada correctamente");
      router.push("/appointments");
    } catch (error) {
      console.error("Error updating appointment:", error);
      toast.error("Error al actualizar la cita");
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!appointment) return;

    setIsSaving(true);
    try {
      await api.delete("appointments", appointmentId);
      toast.success("Cita eliminada");
      router.push("/appointments");
    } catch (error) {
      console.error("Error deleting appointment:", error);
      toast.error("Error al eliminar la cita");
    } finally {
      setIsSaving(false);
      setShowDeleteConfirm(false);
    }
  };

  // Operator quick-action: confirm a PENDING appointment (S2-R3)
  const handleConfirm = async () => {
    if (!appointment) return;
    setIsActionLoading(true);
    try {
      const result = await api.updateAppointment(appointmentId, { status: "confirmed" });
      setAppointment({ ...appointment, status: result.status as AppointmentStatus });
      toast.success("Cita confirmada correctamente");
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 409) {
        toast.error("La cita ya no está pendiente de confirmación");
      } else {
        console.error("Error confirming appointment:", error);
        toast.error("Error al confirmar la cita");
      }
    } finally {
      setIsActionLoading(false);
    }
  };

  // Operator quick-action: cancel an appointment (S2-R4).
  // Separate from the DELETE flow (handleDelete) and the form-discard flow (showCancelConfirm).
  const handleCancelAction = async () => {
    if (!appointment) return;
    setIsActionLoading(true);
    try {
      const result = await api.updateAppointment(appointmentId, { status: "cancelled" });
      setAppointment({ ...appointment, status: result.status as AppointmentStatus });
      setShowAppointmentCancelConfirm(false);
      toast.success("Cita cancelada");
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 409) {
        toast.error("La cita ya está cancelada o completada");
      } else {
        console.error("Error cancelling appointment:", error);
        toast.error("Error al cancelar la cita");
      }
      setShowAppointmentCancelConfirm(false);
    } finally {
      setIsActionLoading(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex flex-col min-h-screen">
        <Header title="Cita" />
        <PageSkeleton sections={2} />
      </div>
    );
  }

  if (!appointment) {
    return (
      <div className="flex flex-col min-h-screen">
        <Header title="Cita no encontrada" />
        <main className="flex-1 p-4 md:p-6 flex items-center justify-center">
          <div className="text-center">
            <p className="text-muted-foreground mb-4">No se encontró la cita</p>
            <Button onClick={() => router.push("/appointments")}>
              <ArrowLeft className="h-4 w-4 mr-2" />
              Volver a citas
            </Button>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="flex flex-col min-h-screen">
      <Header title="Editar Cita" />
      <main className="flex-1 p-4 md:p-6">
        <div className="max-w-2xl mx-auto space-y-6">
          {/* Back button */}
          <Button
            variant="ghost"
            onClick={() => router.push("/appointments")}
            className="mb-4"
          >
            <ArrowLeft className="h-4 w-4 mr-2" />
            Volver a citas
          </Button>

          {/* Appointment Info Card */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2">
                  <Calendar className="h-5 w-5" />
                  Detalles de la Cita
                </CardTitle>
                <StatusBadge status={appointment.status} />
              </div>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Customer Info (read-only) */}
              <div className="bg-muted/50 p-4 rounded-lg space-y-2">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <User className="h-4 w-4" />
                  Cliente
                </div>
                <p className="text-sm">
                  {appointment.customer.first_name} {appointment.customer.last_name}
                </p>
                <p className="text-sm text-muted-foreground">
                  {appointment.customer.phone}
                </p>
              </div>

              {/* Services (read-only) */}
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Scissors className="h-4 w-4" />
                  Servicios
                </div>
                <div className="flex flex-wrap gap-2">
                  {appointment.services.map((service) => (
                    <Badge key={service.id} variant="outline">
                      {service.name} ({service.duration_minutes} min)
                    </Badge>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  Duración total: {appointment.duration_minutes} minutos
                </p>
              </div>

              {/* Stylist Selection */}
              <div className="space-y-2">
                <Label htmlFor="stylist">Estilista</Label>
                <Select
                  value={selectedStylistId}
                  onValueChange={setSelectedStylistId}
                >
                  <SelectTrigger id="stylist">
                    <SelectValue placeholder="Seleccionar estilista" />
                  </SelectTrigger>
                  <SelectContent>
                    {stylists.map((stylist) => (
                      <SelectItem key={stylist.id} value={stylist.id}>
                        {stylist.name} ({formatCategory(stylist.category)})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Date and Time */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="date">Fecha</Label>
                  <DatePicker
                    value={selectedDate ? new Date(selectedDate + "T00:00:00") : undefined}
                    onChange={(date) => {
                      if (date) {
                        setSelectedDate(date.toISOString().split("T")[0]);
                      } else {
                        setSelectedDate("");
                      }
                    }}
                    placeholder="Selecciona fecha"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="time">Hora</Label>
                  <Input
                    id="time"
                    type="time"
                    value={selectedTime}
                    onChange={(e) => setSelectedTime(e.target.value)}
                  />
                </div>
              </div>

              {/* Status */}
              <div className="space-y-2">
                <Label htmlFor="status">Estado</Label>
                <Select
                  value={status}
                  onValueChange={(value) => setStatus(value as AppointmentStatus)}
                >
                  <SelectTrigger id="status">
                    <SelectValue placeholder="Seleccionar estado" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="pending">Pendiente</SelectItem>
                    <SelectItem value="confirmed">Confirmada</SelectItem>
                    <SelectItem value="completed">Completada</SelectItem>
                    <SelectItem value="cancelled">Cancelada</SelectItem>
                    <SelectItem value="no_show">No asistió</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Customer Name (editable for appointment) */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="first_name">Nombre *</Label>
                  <Input
                    id="first_name"
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    placeholder="Nombre"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="last_name">Apellido</Label>
                  <Input
                    id="last_name"
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    placeholder="Apellido"
                  />
                </div>
              </div>

              {/* Notes */}
              <div className="space-y-2">
                <Label htmlFor="notes">Notas</Label>
                <Textarea
                  id="notes"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Notas adicionales..."
                  rows={3}
                />
              </div>

              {/* Metadata */}
              <div className="text-xs text-muted-foreground space-y-1 pt-4 border-t">
                <p>
                  <Clock className="h-3 w-3 inline mr-1" />
                  Creada: {format(parseISO(appointment.created_at), "dd/MM/yyyy HH:mm", { locale: es })}
                </p>
                <p>
                  <Clock className="h-3 w-3 inline mr-1" />
                  Actualizada: {format(parseISO(appointment.updated_at), "dd/MM/yyyy HH:mm", { locale: es })}
                </p>
              </div>

              {/* Actions */}
              <div className="flex justify-between pt-4">
                <Button
                  variant="destructive"
                  onClick={() => setShowDeleteConfirm(true)}
                  disabled={isSaving}
                >
                  <Trash2 className="h-4 w-4 mr-2" />
                  Eliminar
                </Button>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    onClick={() => setRescheduleModalOpen(true)}
                    disabled={isSaving || status === "cancelled" || status === "completed"}
                  >
                    <CalendarClock className="h-4 w-4 mr-2" />
                    Reagendar
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      if (isDirty()) setShowCancelConfirm(true);
                      else router.push("/appointments");
                    }}
                    disabled={isSaving}
                  >
                    Cancelar
                  </Button>
                  <Button onClick={handleSave} disabled={isSaving}>
                    {isSaving ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        Guardando...
                      </>
                    ) : (
                      <>
                        <Save className="h-4 w-4 mr-2" />
                        Guardar cambios
                      </>
                    )}
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Acciones rápidas — Slice 2: operator confirm / cancel */}
          {appointment.status !== "completed" && appointment.status !== "no_show" && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Acciones rápidas</CardTitle>
              </CardHeader>
              <CardContent>
                {appointment.status === "pending" && (
                  <div className="flex flex-col gap-3 sm:flex-row">
                    <Button
                      onClick={handleConfirm}
                      disabled={isActionLoading}
                      className="flex-1"
                    >
                      <Check className="h-4 w-4 mr-2" />
                      {isActionLoading ? "Procesando..." : "Confirmar cita"}
                    </Button>
                    <Button
                      variant="destructive"
                      onClick={() => setShowAppointmentCancelConfirm(true)}
                      disabled={isActionLoading}
                      className="flex-1"
                    >
                      <Ban className="h-4 w-4 mr-2" />
                      Cancelar cita
                    </Button>
                  </div>
                )}
                {appointment.status === "confirmed" && (
                  <Button
                    variant="destructive"
                    onClick={() => setShowAppointmentCancelConfirm(true)}
                    disabled={isActionLoading}
                  >
                    <Ban className="h-4 w-4 mr-2" />
                    {isActionLoading ? "Procesando..." : "Cancelar cita"}
                  </Button>
                )}
                {appointment.status === "cancelled" && (
                  <p className="text-sm text-muted-foreground">
                    Esta cita está cancelada y no admite más acciones.
                  </p>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </main>

      {/* Operator cancel appointment confirmation (distinct from DELETE and form-discard dialogs) */}
      <AlertDialog
        open={showAppointmentCancelConfirm}
        onOpenChange={setShowAppointmentCancelConfirm}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Cancelar esta cita?</AlertDialogTitle>
            <AlertDialogDescription>
              Se marcará la cita como cancelada. Esta acción no se puede deshacer.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isActionLoading}>Volver</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleCancelAction}
              disabled={isActionLoading}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {isActionLoading ? "Cancelando..." : "Cancelar cita"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Eliminar esta cita?</AlertDialogTitle>
            <AlertDialogDescription>
              Esta acción no se puede deshacer. La cita será eliminada permanentemente.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isSaving}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={isSaving}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {isSaving ? "Eliminando..." : "Eliminar"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Discard Changes Confirmation Dialog */}
      <AlertDialog open={showCancelConfirm} onOpenChange={setShowCancelConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Descartar cambios?</AlertDialogTitle>
            <AlertDialogDescription>
              Tienes cambios sin guardar. Si sales ahora se perderán.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Seguir editando</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => router.push("/appointments")}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Descartar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Reschedule Modal */}
      {appointment && (
        <RescheduleModal
          open={rescheduleModalOpen}
          onOpenChange={setRescheduleModalOpen}
          appointment={appointment}
          stylists={stylists}
          onSuccess={fetchData}
        />
      )}
    </div>
  );
}
