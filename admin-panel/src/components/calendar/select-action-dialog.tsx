"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { CalendarPlus, Ban } from "lucide-react";

interface SelectActionDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectAppointment: () => void;
  onSelectBlocking: () => void;
}

export function SelectActionDialog({
  isOpen,
  onClose,
  onSelectAppointment,
  onSelectBlocking,
}: SelectActionDialogProps) {
  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-xs">
        <DialogHeader>
          <DialogTitle>¿Qué querés crear?</DialogTitle>
          <DialogDescription>
            Seleccioná el tipo de evento para este horario
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3 pt-2">
          <Button
            variant="default"
            className="w-full justify-start gap-2"
            onClick={() => {
              onClose();
              onSelectAppointment();
            }}
          >
            <CalendarPlus className="h-4 w-4" />
            Nueva Cita
          </Button>
          <Button
            variant="outline"
            className="w-full justify-start gap-2"
            onClick={() => {
              onClose();
              onSelectBlocking();
            }}
          >
            <Ban className="h-4 w-4" />
            Nuevo Bloqueo
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
