"use client";

import { useState } from "react";
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
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Label } from "@/components/ui/label";

export type SeriesEditScope = "this_only" | "this_and_future" | "all";

interface SeriesInfo {
  series_id: string;
  total_instances: number;
  instance_index: number;
  remaining_instances: number;
  frequency: string;
  interval: number;
  days: string | null;
}

interface SeriesEditDialogProps {
  isOpen: boolean;
  onClose: () => void;
  action: "edit" | "delete";
  eventTitle: string;
  seriesInfo: SeriesInfo;
  onConfirm: (scope: SeriesEditScope) => void;
  isLoading?: boolean;
}

export function SeriesEditDialog({
  isOpen,
  onClose,
  action,
  eventTitle,
  seriesInfo,
  onConfirm,
  isLoading = false,
}: SeriesEditDialogProps) {
  const [scope, setScope] = useState<SeriesEditScope>("this_only");

  const handleConfirm = () => {
    onConfirm(scope);
  };

  // Format frequency for display
  const formatFrequency = () => {
    const freq = seriesInfo.frequency === "WEEKLY" ? "semanal" : "mensual";
    const interval = seriesInfo.interval > 1 ? `cada ${seriesInfo.interval} ` : "";
    const unit = seriesInfo.frequency === "WEEKLY" ? "semanas" : "meses";
    return seriesInfo.interval > 1 ? `${interval}${unit}` : freq;
  };

  return (
    <AlertDialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {action === "edit" ? "Editar evento recurrente" : "Eliminar evento recurrente"}
          </AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="space-y-3">
              <p>
                Este evento &quot;<strong>{eventTitle}</strong>&quot; forma parte de una serie{" "}
                {formatFrequency()}.
              </p>
              <p className="text-sm text-muted-foreground">
                Instancia {seriesInfo.instance_index} de {seriesInfo.total_instances} •{" "}
                {seriesInfo.remaining_instances} restantes
              </p>
              <p>¿Qué deseas hacer?</p>
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>

        <RadioGroup
          value={scope}
          onValueChange={(v) => setScope(v as SeriesEditScope)}
          className="py-4 space-y-3"
        >
          <div className="flex items-start space-x-3 p-2 rounded hover:bg-muted/50 cursor-pointer">
            <RadioGroupItem value="this_only" id="scope-this-only" className="mt-0.5" />
            <div>
              <Label htmlFor="scope-this-only" className="cursor-pointer font-medium">
                Solo esta ocurrencia
              </Label>
              <p className="text-sm text-muted-foreground">
                {action === "edit"
                  ? "Modificar solo este bloqueo, sin afectar los demás."
                  : "Eliminar solo este bloqueo, manteniendo el resto de la serie."}
              </p>
            </div>
          </div>

          <div className="flex items-start space-x-3 p-2 rounded hover:bg-muted/50 cursor-pointer">
            <RadioGroupItem value="this_and_future" id="scope-this-future" className="mt-0.5" />
            <div>
              <Label htmlFor="scope-this-future" className="cursor-pointer font-medium">
                Esta y todas las futuras
              </Label>
              <p className="text-sm text-muted-foreground">
                {action === "edit"
                  ? `Modificar este bloqueo y los ${seriesInfo.remaining_instances - 1} siguientes.`
                  : `Eliminar este bloqueo y los ${seriesInfo.remaining_instances - 1} siguientes.`}
              </p>
            </div>
          </div>

          <div className="flex items-start space-x-3 p-2 rounded hover:bg-muted/50 cursor-pointer">
            <RadioGroupItem value="all" id="scope-all" className="mt-0.5" />
            <div>
              <Label htmlFor="scope-all" className="cursor-pointer font-medium">
                Toda la serie
              </Label>
              <p className="text-sm text-muted-foreground">
                {action === "edit"
                  ? `Modificar los ${seriesInfo.total_instances} bloqueos de la serie completa.`
                  : `Eliminar los ${seriesInfo.total_instances} bloqueos de la serie completa.`}
              </p>
            </div>
          </div>
        </RadioGroup>

        <AlertDialogFooter>
          <AlertDialogCancel disabled={isLoading}>Cancelar</AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirm}
            disabled={isLoading}
            className={action === "delete" ? "bg-destructive hover:bg-destructive/90" : ""}
          >
            {isLoading ? "Procesando..." : action === "edit" ? "Editar" : "Eliminar"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
