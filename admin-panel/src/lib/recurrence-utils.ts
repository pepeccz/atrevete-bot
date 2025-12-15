/**
 * Recurrence utilities for calculating blocking event dates.
 * Mirrors the backend's recurrence_service.py logic for frontend preview.
 */

import {
  addWeeks,
  addMonths,
  getDay,
  getDate,
  setDay,
  setDate,
  isBefore,
  isAfter,
  isSameDay,
  startOfDay,
  differenceInCalendarMonths,
} from "date-fns";

export type RecurrenceFrequency = "WEEKLY" | "MONTHLY";

export interface RecurrencePattern {
  frequency: RecurrenceFrequency;
  interval: number; // Every N weeks/months
  daysOfWeek?: number[]; // 0=Monday, 6=Sunday (ISO weekday)
  daysOfMonth?: number[]; // 1-31
}

/**
 * Convert JavaScript day (0=Sunday) to ISO weekday (0=Monday)
 */
function jsToIsoWeekday(jsDay: number): number {
  return jsDay === 0 ? 6 : jsDay - 1;
}

/**
 * Convert ISO weekday (0=Monday) to JavaScript day (0=Sunday)
 */
function isoToJsWeekday(isoDay: number): number {
  return isoDay === 6 ? 0 : isoDay + 1;
}

/**
 * Expand a recurrence pattern to concrete dates.
 *
 * @param startDate - First occurrence date
 * @param endDate - Last date to consider (inclusive)
 * @param pattern - Recurrence pattern configuration
 * @param maxOccurrences - Maximum number of occurrences (default 52, backend limit)
 * @returns Array of dates in chronological order
 */
export function expandRecurrence(
  startDate: Date,
  endDate: Date,
  pattern: RecurrencePattern,
  maxOccurrences: number = 52
): Date[] {
  const dates: Date[] = [];
  const start = startOfDay(startDate);
  const end = startOfDay(endDate);

  if (isAfter(start, end)) {
    return dates;
  }

  if (pattern.frequency === "WEEKLY") {
    return expandWeekly(start, end, pattern, maxOccurrences);
  } else {
    return expandMonthly(start, end, pattern, maxOccurrences);
  }
}

/**
 * Expand weekly recurrence pattern.
 */
function expandWeekly(
  startDate: Date,
  endDate: Date,
  pattern: RecurrencePattern,
  maxOccurrences: number
): Date[] {
  const dates: Date[] = [];
  const daysOfWeek = pattern.daysOfWeek || [];

  if (daysOfWeek.length === 0) {
    return dates;
  }

  // Sort days of week
  const sortedDays = [...daysOfWeek].sort((a, b) => a - b);

  let currentWeekStart = startOfDay(startDate);
  // Adjust to Monday of that week
  const currentJsDay = getDay(currentWeekStart);
  const currentIsoDay = jsToIsoWeekday(currentJsDay);
  currentWeekStart = setDay(currentWeekStart, isoToJsWeekday(0)); // Move to Monday

  let weekIndex = 0;

  while (dates.length < maxOccurrences) {
    // Only process weeks that match the interval
    if (weekIndex % pattern.interval === 0) {
      for (const isoDay of sortedDays) {
        const jsDay = isoToJsWeekday(isoDay);
        const dateInWeek = setDay(currentWeekStart, jsDay);

        // Skip dates before start or after end
        if (isBefore(dateInWeek, startDate) && !isSameDay(dateInWeek, startDate)) {
          continue;
        }
        if (isAfter(dateInWeek, endDate)) {
          return dates;
        }

        dates.push(dateInWeek);

        if (dates.length >= maxOccurrences) {
          return dates;
        }
      }
    }

    // Move to next week
    currentWeekStart = addWeeks(currentWeekStart, 1);
    weekIndex++;

    // Safety: don't loop forever (max ~2 years of weeks)
    if (weekIndex > 104) {
      break;
    }
  }

  return dates;
}

/**
 * Expand monthly recurrence pattern.
 */
function expandMonthly(
  startDate: Date,
  endDate: Date,
  pattern: RecurrencePattern,
  maxOccurrences: number
): Date[] {
  const dates: Date[] = [];
  const daysOfMonth = pattern.daysOfMonth || [];

  if (daysOfMonth.length === 0) {
    return dates;
  }

  // Sort days of month
  const sortedDays = [...daysOfMonth].sort((a, b) => a - b);

  let currentMonth = new Date(startDate.getFullYear(), startDate.getMonth(), 1);
  let monthIndex = 0;

  while (dates.length < maxOccurrences) {
    // Only process months that match the interval
    if (monthIndex % pattern.interval === 0) {
      for (const dayNum of sortedDays) {
        // Handle months with fewer days (e.g., Feb doesn't have 30)
        const daysInMonth = new Date(
          currentMonth.getFullYear(),
          currentMonth.getMonth() + 1,
          0
        ).getDate();

        if (dayNum > daysInMonth) {
          continue; // Skip invalid days for this month
        }

        const dateInMonth = setDate(currentMonth, dayNum);

        // Skip dates before start or after end
        if (isBefore(dateInMonth, startDate) && !isSameDay(dateInMonth, startDate)) {
          continue;
        }
        if (isAfter(dateInMonth, endDate)) {
          return dates;
        }

        dates.push(dateInMonth);

        if (dates.length >= maxOccurrences) {
          return dates;
        }
      }
    }

    // Move to next month
    currentMonth = addMonths(currentMonth, 1);
    monthIndex++;

    // Safety: don't loop forever (max ~3 years of months)
    if (monthIndex > 36) {
      break;
    }
  }

  return dates;
}

/**
 * Calculate count (number of occurrences) from end date.
 * Used to convert user-friendly "until date" to backend's "count" parameter.
 *
 * @param startDate - First occurrence date
 * @param endDate - Last date to consider
 * @param pattern - Recurrence pattern configuration
 * @returns Number of occurrences, capped at 52 (backend limit)
 */
export function calculateOccurrenceCount(
  startDate: Date,
  endDate: Date,
  pattern: RecurrencePattern
): number {
  const dates = expandRecurrence(startDate, endDate, pattern, 52);
  return dates.length;
}

/**
 * Calculate suggested end date from a given count.
 * Useful for showing "approximately until" when user enters count.
 *
 * @param startDate - First occurrence date
 * @param count - Number of occurrences
 * @param pattern - Recurrence pattern configuration
 * @returns Approximate end date for the given count
 */
export function estimateEndDate(
  startDate: Date,
  count: number,
  pattern: RecurrencePattern
): Date | null {
  if (count <= 0) return null;

  // Estimate a generous end date
  let estimatedEnd: Date;
  if (pattern.frequency === "WEEKLY") {
    // For weekly: count occurrences / days per week * interval * weeks
    const daysPerWeek = pattern.daysOfWeek?.length || 1;
    const weeksNeeded = Math.ceil(count / daysPerWeek) * pattern.interval;
    estimatedEnd = addWeeks(startDate, weeksNeeded + 4); // Add buffer
  } else {
    // For monthly: count occurrences / days per month * interval * months
    const daysPerMonth = pattern.daysOfMonth?.length || 1;
    const monthsNeeded = Math.ceil(count / daysPerMonth) * pattern.interval;
    estimatedEnd = addMonths(startDate, monthsNeeded + 2); // Add buffer
  }

  // Expand and find the actual last date
  const dates = expandRecurrence(startDate, estimatedEnd, pattern, count);
  return dates.length > 0 ? dates[dates.length - 1] : null;
}

/**
 * Check if count exceeds backend limit.
 *
 * @param count - Number of occurrences
 * @returns Warning message if exceeded, null otherwise
 */
export function checkCountLimit(count: number): string | null {
  if (count > 52) {
    return `El limite es 52 repeticiones. Se ajustara automaticamente.`;
  }
  return null;
}

/**
 * Format dates for display in preview.
 *
 * @param dates - Array of dates to format
 * @param maxShow - Maximum dates to show before truncating
 * @returns Formatted string
 */
export function formatDatesPreview(dates: Date[], maxShow: number = 5): string {
  if (dates.length === 0) return "Sin fechas";

  const formatter = new Intl.DateTimeFormat("es-ES", {
    day: "numeric",
    month: "short",
  });

  const formatted = dates.slice(0, maxShow).map((d) => formatter.format(d));

  if (dates.length > maxShow) {
    formatted.push(`... y ${dates.length - maxShow} mas`);
  }

  return formatted.join(", ");
}
