import { format } from "date-fns";
import { es } from "date-fns/locale";

/**
 * Format a date string for display in the admin panel.
 * Uses dd/MM/yyyy HH:mm format with Spanish locale.
 * Falls back to the original string on parse error.
 */
export function formatDate(dateString: string | null, includeTime = true): string {
  if (!dateString) return "-";
  try {
    const pattern = includeTime ? "dd/MM/yyyy HH:mm" : "dd/MM/yyyy";
    return format(new Date(dateString), pattern, { locale: es });
  } catch {
    return dateString;
  }
}

/**
 * Format a duration in minutes into a human-readable string.
 * e.g. 90 → "1h 30min", 45 → "45min", 60 → "1h"
 */
export function formatDuration(minutes: number): string {
  if (minutes <= 0) return "0min";
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hours === 0) return `${mins}min`;
  if (mins === 0) return `${hours}h`;
  return `${hours}h ${mins}min`;
}

/**
 * Format a phone number for display.
 * Currently returns as-is; extend with formatting logic if needed.
 */
export function formatPhone(phone: string | null | undefined): string {
  if (!phone) return "-";
  return phone;
}
