// Color palette for stylists (8 distinct colors).
// Default 5 mirror the hifi handoff palette so the warm/cream design tokens
// in stylist-colors.ts can derive coherent soft + text variants.
export const STYLIST_COLORS = [
  { bg: "#3066d8", border: "#1F3F88", name: "Blue" },
  { bg: "#1ba8c4", border: "#155E6D", name: "Cyan" },
  { bg: "#3a9a4d", border: "#1F5A2C", name: "Green" },
  { bg: "#cc3a3a", border: "#7A2424", name: "Red" },
  { bg: "#d97a1f", border: "#854710", name: "Orange" },
  { bg: "#7C3AED", border: "#6D28D9", name: "Violet" },
  { bg: "#DB2777", border: "#BE185D", name: "Pink" },
  { bg: "#7C2D12", border: "#6B2610", name: "Brown" },
];

// Handoff-aligned name → color map for the known seeded stylists.
// Acts as a fallback when DB color is null and as the canonical seed value.
export const KNOWN_STYLIST_COLOR: Record<string, string> = {
  Marta: "#3066d8",
  Pilar: "#1ba8c4",
  Victor: "#3a9a4d",
  Harolyn: "#cc3a3a",
  Rosa: "#d97a1f",
};

export function resolveStylistColor(
  stylist: { name: string; color?: string | null },
  index: number,
): string {
  if (stylist.color) return stylist.color;
  if (stylist.name && KNOWN_STYLIST_COLOR[stylist.name]) {
    return KNOWN_STYLIST_COLOR[stylist.name];
  }
  return STYLIST_COLORS[index % STYLIST_COLORS.length].bg;
}

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
