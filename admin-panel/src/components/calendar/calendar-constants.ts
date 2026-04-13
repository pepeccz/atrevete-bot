// Color palette for stylists (8 distinct colors)
export const STYLIST_COLORS = [
  { bg: "#7C3AED", border: "#6D28D9", name: "Violet" },
  { bg: "#2563EB", border: "#1D4ED8", name: "Blue" },
  { bg: "#059669", border: "#047857", name: "Emerald" },
  { bg: "#DC2626", border: "#B91C1C", name: "Red" },
  { bg: "#D97706", border: "#B45309", name: "Amber" },
  { bg: "#7C2D12", border: "#6B2610", name: "Brown" },
  { bg: "#DB2777", border: "#BE185D", name: "Pink" },
  { bg: "#0891B2", border: "#0E7490", name: "Cyan" },
];

// Holiday color (special - no stylist)
export const HOLIDAY_COLOR = { bg: "#991B1B", border: "#7F1D1D" };

export interface StatusConfig {
  cssClass: string;
  label: string;
  badgeVariant: string;
  color: string;
}

export const STATUS_MAP: Record<string, StatusConfig> = {
  confirmed: { cssClass: "cal-status-confirmed", label: "Confirmada", badgeVariant: "default", color: "#16a34a" },
  pending: { cssClass: "cal-status-pending", label: "Pendiente", badgeVariant: "secondary", color: "#d97706" },
  cancelled: { cssClass: "cal-status-cancelled", label: "Cancelada", badgeVariant: "destructive", color: "#dc2626" },
  completed: { cssClass: "cal-status-completed", label: "Completada", badgeVariant: "outline", color: "#6b7280" },
  no_show: { cssClass: "cal-status-no_show", label: "No asistió", badgeVariant: "destructive", color: "#7f1d1d" },
};

/** Convert ISO weekday (1=Monday … 7=Sunday) to FullCalendar weekday (0=Sunday … 6=Saturday). */
export function isoToFcWeekday(isoDay: number): number {
  return (isoDay + 1) % 7;
}
