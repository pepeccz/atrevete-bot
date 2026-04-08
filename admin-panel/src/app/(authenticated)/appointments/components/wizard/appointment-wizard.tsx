"use client";

import { useState, useEffect, useRef } from "react";
import { ChevronLeft, ChevronRight, Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import api from "@/lib/api";
import { OverlapConfirmDialog } from "@/components/calendar/overlap-confirm-dialog";
import type { Service, Stylist, Customer, OverlapConflict } from "@/lib/types";
import type { WizardState } from "./types";
import type { ConfirmStepValues } from "./schemas";
import { CustomerStep } from "./customer-step";
import { ServicesStep } from "./services-step";
import { SlotStep } from "./slot-step";
import { ConfirmStep } from "./confirm-step";

const INITIAL_STATE: WizardState = {
  step: 1,
  customer: null,
  selectedServices: [],
  startDate: "",
  endDate: "",
  selectedSlot: null,
  firstName: "",
  lastName: "",
  notes: "",
  sendNotification: true,
};

const STEP_TITLES = [
  "Seleccionar Cliente",
  "Seleccionar Servicios",
  "Elegir Fecha y Hora",
  "Confirmar Cita",
];

interface AppointmentWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
  services: Service[];
  stylists: Stylist[];
  customers: Customer[];
  refreshCustomers: () => void;
}

export function AppointmentWizard({
  open,
  onOpenChange,
  onSuccess,
  services,
  stylists,
  customers,
  refreshCustomers,
}: AppointmentWizardProps) {
  const [loading, setLoading] = useState(false);
  const [state, setState] = useState<WizardState>(INITIAL_STATE);

  // Overlap check state
  const [overlapDialogOpen, setOverlapDialogOpen] = useState(false);
  const [overlapConflicts, setOverlapConflicts] = useState<OverlapConflict[]>([]);
  const [allowOverlap, setAllowOverlap] = useState(false);

  // Ref to ConfirmStep's form validator (set via onFormReady)
  const confirmFormGetValues = useRef<(() => ConfirmStepValues | null) | null>(null);

  // Reset state when modal closes
  useEffect(() => {
    if (!open) {
      setState(INITIAL_STATE);
      setOverlapDialogOpen(false);
      setOverlapConflicts([]);
      setAllowOverlap(false);
      confirmFormGetValues.current = null;
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

  const handleSubmit = async (forceAllowOverlap = false) => {
    if (!state.customer || !state.selectedSlot) return;

    // Validate confirm step via zod if available
    if (confirmFormGetValues.current) {
      const values = confirmFormGetValues.current();
      if (!values) {
        // Validation failed — FormMessage shown inline by ConfirmStep
        return;
      }
    }

    const trimmedFirstName = state.firstName.trim();
    if (!trimmedFirstName) {
      toast.error("El nombre es obligatorio");
      return;
    }

    const totalDurationMinutes = state.selectedServices.reduce(
      (sum, s) => sum + s.duration_minutes,
      0
    );

    // Check for overlaps first
    if (!forceAllowOverlap && !allowOverlap) {
      setLoading(true);
      try {
        const overlapResult = await api.checkOverlaps(
          state.selectedSlot.stylist_id,
          state.selectedSlot.full_datetime,
          totalDurationMinutes
        );

        if (overlapResult.has_overlaps && overlapResult.conflicts.length > 0) {
          setOverlapConflicts(overlapResult.conflicts);
          setOverlapDialogOpen(true);
          setLoading(false);
          return;
        }
      } catch (error) {
        console.warn("Error checking overlaps:", error);
      } finally {
        setLoading(false);
      }
    }

    // Create the appointment
    setLoading(true);
    try {
      const payload: Record<string, unknown> = {
        customer_id: state.customer.id,
        stylist_id: state.selectedSlot.stylist_id,
        service_ids: state.selectedServices.map((s) => s.id),
        start_time: state.selectedSlot.full_datetime,
        first_name: trimmedFirstName,
        last_name: state.lastName.trim() || null,
        notes: state.notes || null,
        send_notification: state.sendNotification,
      };

      if (forceAllowOverlap || allowOverlap) {
        payload.allow_overlap = true;
      }

      await api.create("appointments", payload);

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

  const handleOverlapConfirm = () => {
    setAllowOverlap(true);
    setOverlapDialogOpen(false);
    handleSubmit(true);
  };

  const handleOverlapCancel = () => {
    setOverlapDialogOpen(false);
    setOverlapConflicts([]);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>Nueva Cita</DialogTitle>
          <DialogDescription>
            Paso {state.step} de 4: {STEP_TITLES[state.step - 1]}
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
            <ServicesStep
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
                    selectedSlot: null,
                  };
                });
              }}
            />
          )}

          {state.step === 3 && (
            <SlotStep
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
            <ConfirmStep
              customer={state.customer}
              services={state.selectedServices}
              slot={state.selectedSlot}
              firstName={state.firstName}
              lastName={state.lastName}
              notes={state.notes}
              sendNotification={state.sendNotification}
              onFirstNameChange={(firstName) =>
                setState((prev) => ({ ...prev, firstName }))
              }
              onLastNameChange={(lastName) =>
                setState((prev) => ({ ...prev, lastName }))
              }
              onNotesChange={(notes) =>
                setState((prev) => ({ ...prev, notes }))
              }
              onSendNotificationChange={(sendNotification) =>
                setState((prev) => ({ ...prev, sendNotification }))
              }
              onFormReady={(getValues) => {
                confirmFormGetValues.current = getValues;
              }}
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
                Atrás
              </>
            )}
          </Button>

          {state.step < 4 ? (
            <Button onClick={handleNext} disabled={!canProceed()}>
              Siguiente
              <ChevronRight className="h-4 w-4 ml-1" />
            </Button>
          ) : (
            <Button
              onClick={() => handleSubmit()}
              disabled={loading || !canProceed()}
            >
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

        {/* Overlap Confirmation Dialog */}
        <OverlapConfirmDialog
          isOpen={overlapDialogOpen}
          onClose={handleOverlapCancel}
          onConfirm={handleOverlapConfirm}
          conflicts={overlapConflicts}
          isSubmitting={loading}
        />
      </DialogContent>
    </Dialog>
  );
}
