"use client";

import { useState } from "react";
import { format, parseISO } from "date-fns";
import { es } from "date-fns/locale";
import { CalendarClock, Loader2, ArrowRight, User, Scissors, Clock } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import api from "@/lib/api";
import type { Stylist, ServiceCategory, AppointmentStatus } from "@/lib/types";
import { AvailabilityPicker, SelectedSlot } from "./availability-picker";

// Appointment detail type matching the page component
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

export interface RescheduleModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  appointment: AppointmentDetail;
  stylists: Stylist[];
  onSuccess: () => void;
}

export function RescheduleModal({
  open,
  onOpenChange,
  appointment,
  stylists,
  onSuccess,
}: RescheduleModalProps) {
  const [selectedSlot, setSelectedSlot] = useState<SelectedSlot | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Extract data from appointment
  const serviceIds = appointment.services.map((s) => s.id);
  const serviceCategories = appointment.services.map((s) => s.category);
  const totalDuration = appointment.services.reduce(
    (sum, s) => sum + s.duration_minutes,
    0
  );

  // Format current appointment time
  const currentDateTime = parseISO(appointment.start_time);
  const currentSlotDisplay = format(currentDateTime, "EEEE d/MM/yyyy 'a las' HH:mm", {
    locale: es,
  });

  // Handle reschedule confirmation
  const handleConfirm = async () => {
    if (!selectedSlot) return;

    // Validate that it's actually a different slot
    const newDateTime = selectedSlot.full_datetime;
    const currentDateTimeISO = appointment.start_time;

    if (
      newDateTime === currentDateTimeISO &&
      selectedSlot.stylist_id === appointment.stylist_id
    ) {
      toast.error("Selecciona un horario diferente al actual");
      return;
    }

    setIsSubmitting(true);
    try {
      await api.updateAppointment(appointment.id, {
        start_time: selectedSlot.full_datetime,
        stylist_id: selectedSlot.stylist_id,
      });

      const newDateDisplay = format(
        parseISO(selectedSlot.full_datetime),
        "EEEE d/MM 'a las' HH:mm",
        { locale: es }
      );

      toast.success(`Cita reagendada para ${newDateDisplay} con ${selectedSlot.stylist_name}`);
      onOpenChange(false);
      onSuccess();
    } catch (error) {
      console.error("Error rescheduling appointment:", error);
      toast.error("Error al reagendar la cita");
    } finally {
      setIsSubmitting(false);
    }
  };

  // Reset state when modal closes
  const handleOpenChange = (newOpen: boolean) => {
    if (!newOpen) {
      setSelectedSlot(null);
    }
    onOpenChange(newOpen);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CalendarClock className="h-5 w-5" />
            Reagendar Cita
          </DialogTitle>
          <DialogDescription>
            Busca un nuevo horario disponible para esta cita
          </DialogDescription>
        </DialogHeader>

        {/* Current appointment summary */}
        <div className="space-y-4">
          <div className="bg-muted/50 p-4 rounded-lg space-y-3">
            <h4 className="font-medium text-sm">Cita actual</h4>

            {/* Customer */}
            <div className="flex items-center gap-2 text-sm">
              <User className="h-4 w-4 text-muted-foreground" />
              <span>
                {appointment.first_name} {appointment.last_name || ""}
              </span>
              <span className="text-muted-foreground">
                ({appointment.customer.phone})
              </span>
            </div>

            {/* Services */}
            <div className="flex items-start gap-2 text-sm">
              <Scissors className="h-4 w-4 text-muted-foreground mt-0.5" />
              <div className="flex flex-wrap gap-1">
                {appointment.services.map((service) => (
                  <Badge key={service.id} variant="outline" className="text-xs">
                    {service.name}
                  </Badge>
                ))}
              </div>
            </div>

            {/* Current slot */}
            <div className="flex items-center gap-2 text-sm">
              <Clock className="h-4 w-4 text-muted-foreground" />
              <span className="font-medium">{currentSlotDisplay}</span>
              <span className="text-muted-foreground">
                con {appointment.stylist.name}
              </span>
            </div>
          </div>

          {/* New slot selection comparison */}
          {selectedSlot && (
            <div className="bg-primary/5 border border-primary/20 p-4 rounded-lg">
              <h4 className="font-medium text-sm mb-2">Nuevo horario seleccionado</h4>
              <div className="flex items-center gap-2 text-sm">
                <Badge variant="secondary" className="font-normal">
                  {format(parseISO(appointment.start_time), "EEE d/MM HH:mm", { locale: es })}
                  {" "}({appointment.stylist.name})
                </Badge>
                <ArrowRight className="h-4 w-4 text-primary" />
                <Badge variant="default" className="font-normal">
                  {format(parseISO(selectedSlot.full_datetime), "EEE d/MM HH:mm", { locale: es })}
                  {" "}({selectedSlot.stylist_name})
                </Badge>
              </div>
            </div>
          )}

          {/* Availability picker */}
          <div className="border-t pt-4">
            <h4 className="font-medium text-sm mb-3">Buscar nuevo horario</h4>
            <AvailabilityPicker
              serviceIds={serviceIds}
              stylists={stylists}
              serviceCategories={serviceCategories}
              totalDuration={totalDuration}
              selectedSlot={selectedSlot}
              onSlotSelect={setSelectedSlot}
              initialStylistId={appointment.stylist_id}
              maxHeight="250px"
            />
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={isSubmitting}
          >
            Cancelar
          </Button>
          <Button
            onClick={handleConfirm}
            disabled={!selectedSlot || isSubmitting}
          >
            {isSubmitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Reagendando...
              </>
            ) : (
              <>
                <CalendarClock className="mr-2 h-4 w-4" />
                Confirmar Reagendamiento
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
