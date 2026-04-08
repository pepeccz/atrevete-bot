import { Badge } from "@/components/ui/badge";
import type { AppointmentStatus } from "@/lib/types";

const STATUS_VARIANTS: Record<
  AppointmentStatus,
  "default" | "success" | "warning" | "destructive" | "secondary"
> = {
  pending: "warning",
  confirmed: "success",
  completed: "secondary",
  cancelled: "destructive",
  no_show: "destructive",
};

const STATUS_LABELS: Record<AppointmentStatus, string> = {
  pending: "Pendiente",
  confirmed: "Confirmada",
  completed: "Completada",
  cancelled: "Cancelada",
  no_show: "No asistió",
};

interface StatusBadgeProps {
  status: AppointmentStatus;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <Badge variant={STATUS_VARIANTS[status]}>
      {STATUS_LABELS[status]}
    </Badge>
  );
}
