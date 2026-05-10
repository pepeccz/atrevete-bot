import { cn } from "@/lib/utils";
import type { AppointmentStatus } from "@/lib/types";

const STATUS_CONFIG: Record<
  AppointmentStatus,
  { label: string; dotBg: string; pillBg: string; textColor: string }
> = {
  confirmed: {
    label: "Confirmada",
    dotBg: "bg-[hsl(var(--status-confirm))]",
    pillBg: "bg-[hsl(var(--status-confirm-bg))]",
    textColor: "text-[hsl(var(--status-confirm))]",
  },
  pending: {
    label: "Pendiente",
    dotBg: "bg-[hsl(var(--status-pending))]",
    pillBg: "bg-[hsl(var(--status-pending-bg))]",
    textColor: "text-[hsl(var(--status-pending-fg,var(--status-pending)))]",
  },
  cancelled: {
    label: "Cancelada",
    dotBg: "bg-[hsl(var(--status-cancel))]",
    pillBg: "bg-[hsl(var(--status-cancel-bg))]",
    textColor: "text-[hsl(var(--status-cancel))]",
  },
  completed: {
    label: "Completada",
    dotBg: "bg-[hsl(var(--status-done))]",
    pillBg: "bg-[hsl(var(--status-done-bg))]",
    textColor: "text-[hsl(var(--status-done))]",
  },
  no_show: {
    label: "No asistió",
    dotBg: "bg-[hsl(var(--status-done))]",
    pillBg: "bg-[hsl(var(--status-done-bg))]",
    textColor: "text-[hsl(var(--status-done))]",
  },
};

interface StatusPillProps {
  status: AppointmentStatus;
  className?: string;
}

export function StatusPill({ status, className }: StatusPillProps) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.pending;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-[5px] rounded-pill px-[9px] py-[4px] text-[11.5px] font-semibold",
        cfg.pillBg,
        cfg.textColor,
        className
      )}
    >
      <span className={cn("h-[5px] w-[5px] rounded-full flex-shrink-0", cfg.dotBg)} />
      {cfg.label}
    </span>
  );
}
