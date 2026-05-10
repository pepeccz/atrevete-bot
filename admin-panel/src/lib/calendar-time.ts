/**
 * calendar-time.ts — Centralized time arithmetic helpers for the day view.
 *
 * All functions that accept ISO strings use Luxon for timezone-aware parsing.
 * Luxon is already available as a transitive dep via @fullcalendar/luxon3.
 *
 * Exported types:
 *   TimeRange
 *
 * Exported functions:
 *   minutesFromMidnight(iso, zone)        → number
 *   durationMinutes(startIso, endIso)     → number
 *   formatTimeRange(startIso, endIso, zone) → "HH:mm — HH:mm"
 *   currentMinuteOfDay(zone)              → number
 *   isToday(iso, zone)                    → boolean
 */

import { DateTime } from "luxon";

export interface TimeRange {
  start: string; // ISO 8601
  end: string;   // ISO 8601
}

// ---------------------------------------------------------------------------
// Private memo cache (keyed on ISO + zone, cleared on full page reload)
// ---------------------------------------------------------------------------
const _minuteCache = new Map<string, number>();
const _todayCache = new Map<string, boolean>();

/**
 * Returns the number of minutes elapsed from midnight (in the given timezone)
 * for the given ISO datetime string.
 */
export function minutesFromMidnight(iso: string, zone: string): number {
  const key = `${iso}::${zone}`;
  if (_minuteCache.has(key)) return _minuteCache.get(key)!;
  const dt = DateTime.fromISO(iso, { zone });
  const result = dt.hour * 60 + dt.minute;
  _minuteCache.set(key, result);
  return result;
}

/**
 * Returns the duration in minutes between two ISO datetime strings.
 * The result is always positive; if end < start returns 0.
 */
export function durationMinutes(startIso: string, endIso: string): number {
  const start = DateTime.fromISO(startIso);
  const end = DateTime.fromISO(endIso);
  const diff = end.diff(start, "minutes").minutes;
  return Math.max(0, Math.round(diff));
}

/**
 * Returns a formatted time range string, e.g. "9:00 — 10:00".
 * Times are rendered in the specified timezone.
 */
export function formatTimeRange(startIso: string, endIso: string, zone: string): string {
  const startDt = DateTime.fromISO(startIso, { zone });
  const endDt = DateTime.fromISO(endIso, { zone });

  const format = (dt: DateTime): string => {
    const h = dt.hour;
    const m = dt.minute;
    const minStr = m === 0 ? "00" : String(m).padStart(2, "0");
    return `${h}:${minStr}`;
  };

  return `${format(startDt)} — ${format(endDt)}`;
}

/**
 * Returns the current minute of day (0–1439) in the given timezone.
 * Not memoized — callers should cache/refresh via setInterval.
 */
export function currentMinuteOfDay(zone: string): number {
  const now = DateTime.now().setZone(zone);
  return now.hour * 60 + now.minute;
}

/**
 * Returns true if the given ISO date string falls on today in the specified timezone.
 */
export function isToday(iso: string, zone: string): boolean {
  const key = `${iso}::${zone}`;
  if (_todayCache.has(key)) return _todayCache.get(key)!;
  const dt = DateTime.fromISO(iso, { zone });
  const todayStr = DateTime.now().setZone(zone).toISODate();
  const result = dt.toISODate() === todayStr;
  _todayCache.set(key, result);
  return result;
}
