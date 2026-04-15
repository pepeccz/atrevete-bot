"use client";

import { AlertTriangle } from "lucide-react";
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
import type { OverlapConflict } from "@/lib/types";

interface OverlapConfirmDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  conflicts: OverlapConflict[];
  isSubmitting?: boolean;
  operationType?: "create" | "resize" | "move";
}

const ACTION_TEXT = {
  create: { question: "crear la cita", button: "Crear de todos modos", gerund: "Creando..." },
  resize: { question: "cambiar la duración", button: "Cambiar de todos modos", gerund: "Actualizando..." },
  move: { question: "mover la cita", button: "Mover de todos modos", gerund: "Moviendo..." },
} as const;

export function OverlapConfirmDialog({
  isOpen,
  onClose,
  onConfirm,
  conflicts,
  isSubmitting = false,
  operationType = "create",
}: OverlapConfirmDialogProps) {
  const actionText = ACTION_TEXT[operationType];
  // Format datetime for display
  const formatDateTime = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleString("es-ES", {
      weekday: "short",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  // Format time range
  const formatTimeRange = (startStr: string, endStr: string) => {
    const start = new Date(startStr);
    const end = new Date(endStr);
    const timeOptions: Intl.DateTimeFormatOptions = {
      hour: "2-digit",
      minute: "2-digit",
    };
    return `${start.toLocaleTimeString("es-ES", timeOptions)} - ${end.toLocaleTimeString("es-ES", timeOptions)}`;
  };

  return (
    <AlertDialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2 text-amber-600">
            <AlertTriangle className="h-5 w-5" />
            Cita superpuesta detectada
          </AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="text-sm text-muted-foreground space-y-4">
            <span>
              La nueva cita se solaparía con {conflicts.length} cita{conflicts.length !== 1 ? "s" : ""} existente{conflicts.length !== 1 ? "s" : ""}:
            </span>

            <div className="border rounded-md p-3 space-y-2 bg-amber-50 dark:bg-amber-950/20">
              {conflicts.map((conflict) => (
                <div
                  key={conflict.appointment_id}
                  className="text-sm border-b last:border-b-0 pb-2 last:pb-0"
                >
                  <div className="font-medium text-amber-800 dark:text-amber-200">
                    {conflict.customer_name}
                  </div>
                  <div className="text-amber-700 dark:text-amber-300">
                    {conflict.service_names}
                  </div>
                  <div className="text-amber-600 dark:text-amber-400 text-xs">
                    {formatDateTime(conflict.start_time)} ({formatTimeRange(conflict.start_time, conflict.end_time)})
                  </div>
                </div>
              ))}
            </div>

            <span className="block font-medium text-amber-700 dark:text-amber-300">
              ¿Deseas {actionText.question} de todos modos? Esto creará una superposición en el calendario.
            </span>
          </div></AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter className="gap-2">
          <AlertDialogCancel disabled={isSubmitting}>Cancelar</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            disabled={isSubmitting}
            className="bg-amber-600 text-white hover:bg-amber-700"
          >
            {isSubmitting ? actionText.gerund : actionText.button}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
