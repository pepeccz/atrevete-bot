"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import { format, parseISO } from "date-fns";
import { es } from "date-fns/locale";
import {
  ArrowLeft,
  Calendar,
  Clock,
  User,
  Scissors,
  Save,
  Loader2,
  Trash2,
} from "lucide-react";

import { Header } from "@/components/layout/header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import api from "@/lib/api";
import type { Stylist, AppointmentStatus } from "@/lib/types";

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
    category: string;
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
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

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

  if (isLoading) {
    return (
      <div className="flex flex-col min-h-screen">
        <Header title="Cargando cita..." />
        <main className="flex-1 p-6 flex items-center justify-center">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Cargando...</span>
          </div>
        </main>
      </div>
    );
  }

  if (!appointment) {
    return (
      <div className="flex flex-col min-h-screen">
        <Header title="Cita no encontrada" />
        <main className="flex-1 p-6 flex items-center justify-center">
          <div className="text-center">
            <p className="text-muted-foreground mb-4">No se encontro la cita</p>
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
      <main className="flex-1 p-6">
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
                  Duracion total: {appointment.duration_minutes} minutos
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
                        {stylist.name} ({stylist.category})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Date and Time */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="date">Fecha</Label>
                  <Input
                    id="date"
                    type="date"
                    value={selectedDate}
                    onChange={(e) => setSelectedDate(e.target.value)}
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
                    <SelectItem value="no_show">No asistio</SelectItem>
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
                    onClick={() => router.push("/appointments")}
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
        </div>
      </main>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Eliminar esta cita?</AlertDialogTitle>
            <AlertDialogDescription>
              Esta accion no se puede deshacer. La cita sera eliminada permanentemente.
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
    </div>
  );
}
