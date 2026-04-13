"use client";

import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { useMediaQuery } from "@/hooks/use-media-query";

/** Shape of a FullCalendar businessHours entry. */
export interface BusinessHoursFC {
  daysOfWeek: number[];
  startTime: string;
  endTime: string;
}

const STORAGE_KEY = "atrevete-calendar-stylists";

export function useCalendarState() {
  const isMobile = useMediaQuery("(max-width: 767px)");

  // -------------------------------------------------------------------------
  // localStorage persistence helpers
  // -------------------------------------------------------------------------
  const getPersistedStylistIds = useCallback((activeStylistIds: string[]): string[] => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (!stored) return activeStylistIds;
      const parsed: string[] = JSON.parse(stored);
      const intersected = parsed.filter(id => activeStylistIds.includes(id));
      return intersected.length > 0 ? intersected : activeStylistIds;
    } catch {
      return activeStylistIds;
    }
  }, []);

  const persistStylistIds = useCallback((ids: string[]) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
    } catch { /* silent fail */ }
  }, []);

  // -------------------------------------------------------------------------
  // Business hours — fetched once on mount
  // false = not yet loaded (FullCalendar hides shading), array = loaded data
  // -------------------------------------------------------------------------
  const [businessHours, setBusinessHours] = useState<BusinessHoursFC[] | false>(false);

  useEffect(() => {
    async function fetchBusinessHours() {
      try {
        const response = await api.list<{
          id: string;
          day_of_week: number;   // 0=Mon … 6=Sun
          is_closed: boolean;
          start_hour: number;
          start_minute: number;
          end_hour: number;
          end_minute: number;
        }>("business-hours");

        const openDays = response.items.filter(h => !h.is_closed);

        if (openDays.length === 0) {
          setBusinessHours([]);
          return;
        }

        // Group by identical open/close times to produce compact FC entries.
        // DB day_of_week: 0=Mon … 6=Sun → FC daysOfWeek: 0=Sun … 6=Sat
        // Conversion: (db_day + 1) % 7
        const groups: Map<string, { daysOfWeek: number[]; startTime: string; endTime: string }> =
          new Map();

        for (const h of openDays) {
          const startTime = `${String(h.start_hour).padStart(2, "0")}:${String(h.start_minute).padStart(2, "0")}`;
          const endTime = `${String(h.end_hour).padStart(2, "0")}:${String(h.end_minute).padStart(2, "0")}`;
          const key = `${startTime}-${endTime}`;
          const fcDay = (h.day_of_week + 1) % 7;

          if (groups.has(key)) {
            groups.get(key)!.daysOfWeek.push(fcDay);
          } else {
            groups.set(key, { daysOfWeek: [fcDay], startTime, endTime });
          }
        }

        setBusinessHours(Array.from(groups.values()));
      } catch (error) {
        console.error("[Calendar] Error fetching business hours:", error);
        // On error keep false so FullCalendar renders without shading
        setBusinessHours(false);
      }
    }

    fetchBusinessHours();
  }, []);

  return { getPersistedStylistIds, persistStylistIds, businessHours, isMobile };
}
