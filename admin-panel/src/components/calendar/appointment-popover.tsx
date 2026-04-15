"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ExternalLink, Loader2, X } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverAnchor,
} from "@/components/ui/popover";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from "@/components/ui/alert-dialog";
import { STATUS_MAP } from "./calendar-constants";
import api from "@/lib/api";

export interface PopoverAppointmentData {
  appointmentId: string;
  customerName: string;
  serviceNames: string[];
  status: string;
  duration: number;
  notes: string | null;
  stylistColor: string;
  title: string;
  start: Date | null;
  end: Date | null;
}

interface AppointmentPopoverProps {
  open: boolean;
  anchorEl: HTMLElement | null;
  data: PopoverAppointmentData | null;
  onClose: () => void;
  onCancelSuccess: () => void;
  onNavigate: (appointmentId: string) => void;
}

function formatTimeRange(start: Date | null, end: Date | null): string {
  if (!start) return "—";
  const fmt = (d: Date) =>
    d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", hour12: false });
  return end ? `${fmt(start)} – ${fmt(end)}` : fmt(start);
}

export function AppointmentPopover({
  open,
  anchorEl,
  data,
  onClose,
  onCancelSuccess,
  onNavigate,
}: AppointmentPopoverProps) {
  const anchorRef = useRef<HTMLDivElement>(null);
  const [cancelDialogOpen, setCancelDialogOpen] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [isConfirming, setIsConfirming] = useState(false);

  // Position the virtual anchor element at the clicked calendar event
  const [anchorPos, setAnchorPos] = useState({ top: 0, left: 0 });

  useEffect(() => {
    if (anchorEl && open) {
      const rect = anchorEl.getBoundingClientRect();
      setAnchorPos({
        top: rect.top + rect.height / 2,
        left: rect.right,
      });
    }
  }, [anchorEl, open]);

  // Reset state when popover closes
  useEffect(() => {
    if (!open) {
      setCancelDialogOpen(false);
      setCancelError(null);
      setIsCancelling(false);
      setIsConfirming(false);
    }
  }, [open]);

  const statusConfig = data?.status ? STATUS_MAP[data.status] : null;

  const handleConfirmAppointment = async () => {
    if (!data) return;
    setIsConfirming(true);
    try {
      await api.updateAppointment(data.appointmentId, { status: "confirmed" });
      onClose();
      onCancelSuccess(); // reuses the same refresh callback
    } catch {
      // silently fail — user can retry or use detail page
    } finally {
      setIsConfirming(false);
    }
  };

  const handleConfirmCancel = async () => {
    if (!data) return;
    setIsCancelling(true);
    setCancelError(null);
    try {
      await api.updateAppointment(data.appointmentId, { status: "cancelled" });
      setCancelDialogOpen(false);
      onClose();
      onCancelSuccess();
    } catch {
      setCancelError("Error al cancelar la cita. Inténtalo de nuevo.");
    } finally {
      setIsCancelling(false);
    }
  };

  return (
    <>
      <Popover
        open={open}
        onOpenChange={(o) => {
          if (!o && !cancelDialogOpen) onClose();
        }}
      >
        {/* Virtual anchor — zero-size div positioned at the event element */}
        <PopoverAnchor asChild>
          <div
            ref={anchorRef}
            className="fixed pointer-events-none z-0"
            style={{
              top: anchorPos.top,
              left: anchorPos.left,
              width: 1,
              height: 1,
            }}
          />
        </PopoverAnchor>

        <PopoverContent
          side="right"
          align="center"
          sideOffset={8}
          className="w-72 p-0 z-50"
          onInteractOutside={(e) => {
            if (cancelDialogOpen) {
              e.preventDefault();
              return;
            }
            onClose();
          }}
        >
          {data && (
            <>
              {/* Header */}
              <div className="flex items-center gap-2 p-3 pr-2">
                <span
                  className="shrink-0 h-3 w-3 rounded-full"
                  style={{ backgroundColor: data.stylistColor }}
                />
                <p className="flex-1 text-sm font-semibold truncate leading-tight">
                  {data.title}
                </p>
                <button
                  onClick={onClose}
                  className="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
                  aria-label="Cerrar"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <Separator />

              {/* Data rows */}
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 p-3 text-sm">
                <dt className="text-muted-foreground">Cliente</dt>
                <dd className="font-medium truncate">{data.customerName || "—"}</dd>

                <dt className="text-muted-foreground">Servicios</dt>
                <dd className="font-medium leading-tight">
                  {data.serviceNames.length > 0
                    ? data.serviceNames.join(", ")
                    : "—"}
                </dd>

                <dt className="text-muted-foreground">Hora</dt>
                <dd className="font-medium">{formatTimeRange(data.start, data.end)}</dd>

                <dt className="text-muted-foreground">Duración</dt>
                <dd className="font-medium">{data.duration} min</dd>

                <dt className="text-muted-foreground">Estado</dt>
                <dd>
                  {statusConfig ? (
                    <Badge
                      variant={
                        statusConfig.badgeVariant as
                          | "default"
                          | "secondary"
                          | "destructive"
                          | "outline"
                      }
                    >
                      {statusConfig.label}
                    </Badge>
                  ) : (
                    <span className="font-medium">{data.status}</span>
                  )}
                </dd>

                {data.notes && (
                  <>
                    <dt className="text-muted-foreground">Notas</dt>
                    <dd className="font-medium leading-tight break-words">{data.notes}</dd>
                  </>
                )}
              </dl>

              <Separator />

              {/* Actions */}
              <div className="flex gap-2 p-3">
                <Button
                  variant="outline"
                  size="sm"
                  className="flex-1"
                  onClick={() => onNavigate(data.appointmentId)}
                >
                  <ExternalLink className="h-3 w-3 mr-1" />
                  Detalle
                </Button>
                {data.status === "pending" && (
                  <Button
                    size="sm"
                    className="flex-1 bg-green-600 text-white hover:bg-green-700"
                    onClick={handleConfirmAppointment}
                    disabled={isConfirming}
                  >
                    {isConfirming ? (
                      <Loader2 className="h-3 w-3 animate-spin mr-1" />
                    ) : (
                      <Check className="h-3 w-3 mr-1" />
                    )}
                    Confirmar
                  </Button>
                )}
                <Button
                  variant="destructive"
                  size="sm"
                  className="flex-1"
                  onClick={() => {
                    setCancelError(null);
                    setCancelDialogOpen(true);
                  }}
                  disabled={data.status === "cancelled"}
                >
                  Cancelar
                </Button>
              </div>
            </>
          )}
        </PopoverContent>
      </Popover>

      {/* Cancel confirmation dialog */}
      <AlertDialog open={cancelDialogOpen} onOpenChange={setCancelDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Cancelar cita?</AlertDialogTitle>
            <AlertDialogDescription>
              ¿Cancelar la cita de {data?.customerName}? Esta acción no se puede deshacer.
            </AlertDialogDescription>
          </AlertDialogHeader>

          {cancelError && (
            <p className="text-sm text-destructive px-1">{cancelError}</p>
          )}

          <AlertDialogFooter>
            <AlertDialogCancel disabled={isCancelling}>
              No, volver
            </AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={isCancelling}
              onClick={(e) => {
                e.preventDefault();
                handleConfirmCancel();
              }}
            >
              {isCancelling ? <><Loader2 className="h-4 w-4 animate-spin mr-1" />Cancelando...</> : "Sí, cancelar"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
