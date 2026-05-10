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

export type CalendarView = "day" | "week" | "month";
export type ZoomLevel = "5min" | "15min" | "30min" | "1h";

const STORAGE_KEY_STYLISTS = "atrevete.calendar.activeStylists";
const STORAGE_KEY_VIEW = "atrevete.calendar.view";
const STORAGE_KEY_ZOOM = "atrevete.calendar.zoom";

/** Map zoom level label to FullCalendar slotDuration string */
export const ZOOM_SLOT_MAP: Record<ZoomLevel, string> = {
  "5min": "00:05:00",
  "15min": "00:15:00",
  "30min": "00:30:00",
  "1h": "01:00:00",
};

/** Map zoom level to slotLabelInterval */
export const ZOOM_LABEL_MAP: Record<ZoomLevel, string> = {
  "5min": "00:15",
  "15min": "01:00",
  "30min": "01:00",
  "1h": "01:00",
};

const VALID_VIEWS: CalendarView[] = ["day", "week", "month"];
const VALID_ZOOMS: ZoomLevel[] = ["5min", "15min", "30min", "1h"];

function safeReadLS<T>(key: string, validator: (v: unknown) => v is T, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    return validator(parsed) ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function isCalendarView(v: unknown): v is CalendarView {
  return typeof v === "string" && (VALID_VIEWS as string[]).includes(v);
}

function isZoomLevel(v: unknown): v is ZoomLevel {
  return typeof v === "string" && (VALID_ZOOMS as string[]).includes(v);
}

export function useCalendarState() {
  const isMobile = useMediaQuery("(max-width: 767px)");

  // -------------------------------------------------------------------------
  // View state (persisted)
  // -------------------------------------------------------------------------
  const [selectedView, setSelectedViewState] = useState<CalendarView>("week");

  // -------------------------------------------------------------------------
  // Zoom level (persisted)
  // -------------------------------------------------------------------------
  const [zoomLevel, setZoomLevelState] = useState<ZoomLevel>("15min");

  // -------------------------------------------------------------------------
  // Active stylists Set (persisted)
  // -------------------------------------------------------------------------
  const [activeStylists, setActiveStylists] = useState<Set<string>>(new Set());
  const [allStylistIds, setAllStylistIds] = useState<string[]>([]);

  // -------------------------------------------------------------------------
  // Selected date (NOT persisted — always today on load)
  // -------------------------------------------------------------------------
  const [selectedDate, setSelectedDate] = useState<Date>(new Date());

  // -------------------------------------------------------------------------
  // Business hours — fetched once on mount
  // -------------------------------------------------------------------------
  const [businessHours, setBusinessHours] = useState<BusinessHoursFC[] | false>(false);

  // Hydrate from localStorage on mount
  useEffect(() => {
    const view = safeReadLS<CalendarView>(STORAGE_KEY_VIEW, isCalendarView, "week");
    const zoom = safeReadLS<ZoomLevel>(STORAGE_KEY_ZOOM, isZoomLevel, "15min");
    setSelectedViewState(view);
    setZoomLevelState(zoom);
  }, []);

  useEffect(() => {
    async function fetchBusinessHours() {
      try {
        const response = await api.list<{
          id: string;
          day_of_week: number;
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
        setBusinessHours(false);
      }
    }

    fetchBusinessHours();
  }, []);

  // -------------------------------------------------------------------------
  // Persist view
  // -------------------------------------------------------------------------
  const setView = useCallback((view: CalendarView) => {
    setSelectedViewState(view);
    try { localStorage.setItem(STORAGE_KEY_VIEW, JSON.stringify(view)); } catch { /* silent */ }
  }, []);

  // -------------------------------------------------------------------------
  // Persist zoom
  // -------------------------------------------------------------------------
  const setZoom = useCallback((zoom: ZoomLevel) => {
    setZoomLevelState(zoom);
    try { localStorage.setItem(STORAGE_KEY_ZOOM, JSON.stringify(zoom)); } catch { /* silent */ }
  }, []);

  // -------------------------------------------------------------------------
  // Stylist persistence helpers (legacy compat key for reading, new key for writing)
  // -------------------------------------------------------------------------
  const LEGACY_KEY = "atrevete-calendar-stylists";

  const getPersistedStylistIds = useCallback((availableIds: string[]): string[] => {
    // Try new key first, fall back to legacy key
    try {
      const newStored = localStorage.getItem(STORAGE_KEY_STYLISTS);
      const legacyStored = localStorage.getItem(LEGACY_KEY);
      const raw = newStored ?? legacyStored;
      if (!raw) return availableIds;
      const parsed: string[] = JSON.parse(raw);
      const intersected = parsed.filter(id => availableIds.includes(id));
      return intersected.length > 0 ? intersected : availableIds;
    } catch {
      return availableIds;
    }
  }, []);

  const persistStylistIds = useCallback((ids: string[]) => {
    try {
      localStorage.setItem(STORAGE_KEY_STYLISTS, JSON.stringify(ids));
    } catch { /* silent */ }
  }, []);

  // -------------------------------------------------------------------------
  // Initialize activeStylists from available stylists + localStorage
  // Called by CalendarView after fetching stylists
  // -------------------------------------------------------------------------
  const initActiveStylists = useCallback((stylistIds: string[]) => {
    setAllStylistIds(stylistIds);
    const persisted = getPersistedStylistIds(stylistIds);
    setActiveStylists(new Set(persisted));
  }, [getPersistedStylistIds]);

  const toggleStylist = useCallback((id: string) => {
    setActiveStylists(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      persistStylistIds(Array.from(next));
      return next;
    });
  }, [persistStylistIds]);

  const toggleAllStylists = useCallback(() => {
    setActiveStylists(prev => {
      const allSelected = allStylistIds.every(id => prev.has(id));
      const next = allSelected ? new Set<string>() : new Set(allStylistIds);
      persistStylistIds(Array.from(next));
      return next;
    });
  }, [allStylistIds, persistStylistIds]);

  return {
    // State
    selectedView,
    selectedDate,
    activeStylists,
    zoomLevel,
    businessHours,
    isMobile,
    allStylistIds,
    // Setters
    setView,
    setDate: setSelectedDate,
    toggleStylist,
    toggleAllStylists,
    initActiveStylists,
    // Legacy compat (still used in CalendarView during transition)
    getPersistedStylistIds,
    persistStylistIds,
  };
}
