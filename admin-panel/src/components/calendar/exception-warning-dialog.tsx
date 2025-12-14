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
import { AlertTriangle } from "lucide-react";

interface ExceptionWarningDialogProps {
  isOpen: boolean;
  onClose: () => void;
  exceptionCount: number;
  onConfirm: (overwriteExceptions: boolean) => void;
  isLoading?: boolean;
}

export function ExceptionWarningDialog({
  isOpen,
  onClose,
  exceptionCount,
  onConfirm,
  isLoading = false,
}: ExceptionWarningDialogProps) {
  const [choice, setChoice] = useState<"skip" | "overwrite">("skip");

  const handleConfirm = () => {
    onConfirm(choice === "overwrite");
  };

  return (
    <AlertDialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-amber-500" />
            Instancias modificadas detectadas
          </AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="space-y-3">
              <p>
                Se encontraron <strong>{exceptionCount}</strong> instancia(s)
                que fueron modificadas individualmente anteriormente.
              </p>
              <p>¿Qué deseas hacer con estas instancias?</p>
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>

        <RadioGroup
          value={choice}
          onValueChange={(v) => setChoice(v as "skip" | "overwrite")}
          className="py-4 space-y-3"
        >
          <div className="flex items-start space-x-3 p-2 rounded hover:bg-muted/50 cursor-pointer">
            <RadioGroupItem value="skip" id="choice-skip" className="mt-0.5" />
            <div>
              <Label htmlFor="choice-skip" className="cursor-pointer font-medium">
                Saltar instancias modificadas
              </Label>
              <p className="text-sm text-muted-foreground">
                Mantener los cambios individuales previos. Solo se actualizarán
                las instancias no modificadas.
              </p>
            </div>
          </div>

          <div className="flex items-start space-x-3 p-2 rounded hover:bg-muted/50 cursor-pointer">
            <RadioGroupItem value="overwrite" id="choice-overwrite" className="mt-0.5" />
            <div>
              <Label htmlFor="choice-overwrite" className="cursor-pointer font-medium">
                Sobrescribir todas
              </Label>
              <p className="text-sm text-muted-foreground">
                Los cambios se aplicarán a todas las instancias, incluyendo
                las que fueron modificadas individualmente.
              </p>
            </div>
          </div>
        </RadioGroup>

        <AlertDialogFooter>
          <AlertDialogCancel disabled={isLoading}>Cancelar</AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirm}
            disabled={isLoading}
          >
            {isLoading ? "Procesando..." : "Continuar"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
