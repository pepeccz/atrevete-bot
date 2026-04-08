"use client";

import { type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";

interface EmptyStateAction {
  label: string;
  onClick: () => void;
}

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: EmptyStateAction;
}

/**
 * EmptyState — componente reutilizable para estados vacíos.
 *
 * Uso:
 *   <EmptyState
 *     icon={CalendarOff}
 *     title="No hay citas programadas"
 *     description="Creá la primera cita para comenzar."
 *     action={{ label: "Nueva cita", onClick: () => setOpen(true) }}
 *   />
 */
export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
      {/* Icono con fondo sutil */}
      <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-muted/60 text-muted-foreground">
        <Icon className="h-8 w-8" strokeWidth={1.5} />
      </div>

      {/* Título */}
      <h3 className="mb-1 text-base font-semibold text-foreground">{title}</h3>

      {/* Descripción opcional */}
      {description && (
        <p className="mb-4 max-w-xs text-sm text-muted-foreground leading-relaxed">
          {description}
        </p>
      )}

      {/* Acción opcional */}
      {action && (
        <Button
          onClick={action.onClick}
          size="sm"
          className="mt-2"
        >
          {action.label}
        </Button>
      )}
    </div>
  );
}
