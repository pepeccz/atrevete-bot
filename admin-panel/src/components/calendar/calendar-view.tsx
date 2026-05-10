"use client";

import { useState, useEffect, useMemo, useRef, useCallback, forwardRef, useImperativeHandle } from "react";
import { useRouter } from "next/navigation";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin, { type EventResizeDoneArg } from "@fullcalendar/interaction";
import type { EventDropArg } from "@fullcalendar/core";
import listPlugin from "@fullcalendar/list";
import luxonPlugin from "@fullcalendar/luxon3";
import esLocale from "@fullcalendar/core/locales/es";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Calendar, Filter } from "lucide-react";
import api from "@/lib/api";
import { BlockingEventModal } from "./blocking-event-modal";
import { CreateAppointmentModal } from "./create-appointment-modal";
import { SeriesEditDialog, type SeriesEditScope } from "./series-edit-dialog";
import { ExceptionWarningDialog } from "./exception-warning-dialog";
import { STYLIST_COLORS, HOLIDAY_COLOR, STATUS_MAP, resolveStylistColor } from "./calendar-constants";
import "./calendar-styles.css";
import { useCalendarState, ZOOM_SLOT_MAP, ZOOM_LABEL_MAP, ZOOM_SLOT_MIN, ZOOM_SLOT_PX } from "./use-calendar-state";
import { CalendarToolbar } from "./calendar-toolbar";
import { StylistChipFilter, type AppointmentStatus } from "./stylist-chip-filter";
import { ApptCard } from "./appt-card";
import { AppointmentPopover, type PopoverAppointmentData } from "./appointment-popover";
import { CalendarDayView, type DayViewEvent, type DayViewStylist } from "./calendar-day-view";
import { DateTime } from "luxon";
import { SelectActionDialog } from "./select-action-dialog";
import { AppointmentWizard } from "@/app/(authenticated)/appointments/components/wizard/appointment-wizard";
import { OverlapConfirmDialog } from "./overlap-confirm-dialog";
import type { Service, Customer, Stylist as FullStylist, OverlapConflict } from "@/lib/types";

interface CalendarEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  backgroundColor: string;
  borderColor: string;
  allDay?: boolean;
  durationEditable?: boolean;
  startEditable?: boolean;
  extendedProps: {
    appointment_id?: string;
    blocking_event_id?: string;
    holiday_id?: string;
    customer_id?: string;
    stylist_id?: string;
    status?: string;
    duration_minutes?: number;
    notes?: string | null;
    description?: string | null;
    event_type?: string;
    type: "appointment" | "blocking_event" | "holiday";
    // Recurring series info
    recurring_series_id?: string | null;
    occurrence_index?: number | null;
    customer_name?: string;
    service_names?: string[];
  };
}

interface Stylist {
  id: string;
  name: string;
  category: string;
  is_active: boolean;
  color?: string;
}

interface EditingBlockingEvent {
  id: string;
  title: string;
  description: string | null;
  event_type: string;
  start_time: string;
  end_time: string;
  stylist_id: string;
}

// Ref interface for external control
export interface CalendarViewRef {
  refresh: () => void;
  /** Reset view to 'week' — used by CalendarErrorBoundary to recover from errors. */
  resetToWeek: () => void;
}

// ---------------------------------------------------------------------------
// DayViewPill — gold summary pill shown in toolbar when selectedView === 'day'
// ---------------------------------------------------------------------------
function DayViewPill({
  events,
  stylists,
  gridStartHour,
  gridEndHour,
}: {
  events: CalendarEvent[];
  stylists: Stylist[];
  gridStartHour: number;
  gridEndHour: number;
}) {
  const appts = events.filter(
    e => e.extendedProps.type === "appointment"
      && e.extendedProps.status !== "cancelled"
      && e.extendedProps.status !== "no_show"
  );
  const totalBooked = appts.reduce(
    (acc, e) => acc + (e.extendedProps.duration_minutes ?? 0), 0
  );
  const businessMin = (gridEndHour - gridStartHour) * 60;
  const totalCapacity = businessMin * Math.max(stylists.length, 1);
  const pct = totalCapacity > 0 ? Math.round((totalBooked / totalCapacity) * 100) : 0;

  return (
    <span
      className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold"
      style={{
        backgroundColor: "hsl(var(--gold-soft))",
        border: "1px solid hsl(var(--gold-line))",
        color: "hsl(var(--gold-dark))",
      }}
    >
      {appts.length} {appts.length === 1 ? "cita hoy" : "citas hoy"} · ocupación {pct}%
    </span>
  );
}

// ---------------------------------------------------------------------------
// Legacy zoom config kept for backwards compat with zoomTowardPoint logic
// ---------------------------------------------------------------------------
const LEGACY_ZOOM_LEVELS = [
  { slot: "00:30:00", label: "30 min", labelInterval: "01:00" },
  { slot: "00:15:00", label: "15 min", labelInterval: "01:00" },
  { slot: "00:10:00", label: "10 min", labelInterval: "00:30" },
  { slot: "00:05:00", label: "5 min", labelInterval: "00:15" },
] as const;

const DEFAULT_LEGACY_ZOOM = 1; // 15 min

// Discriminated union for pending drag operations
interface ResizeOperation {
  type: "resize";
  appointmentId: string;
  durationMinutes: number;
  revert: () => void;
  conflicts: OverlapConflict[];
}
interface MoveOperation {
  type: "move";
  appointmentId: string;
  startTime: string;
  revert: () => void;
  conflicts: OverlapConflict[];
}
type PendingDragOperation = ResizeOperation | MoveOperation | null;

interface CalendarViewProps {
  /**
   * Notifies the parent page whenever the view (day/week/month) or the
   * number of active stylists changes, so the page can render an
   * adaptive subtitle in <Header />.
   */
  onContextChange?: (ctx: { view: "day" | "week" | "month"; activeStylists: number }) => void;
}

export const CalendarView = forwardRef<CalendarViewRef, CalendarViewProps>(function CalendarView(props, ref) {
  const { onContextChange } = props;
  const router = useRouter();
  const calendarRef = useRef<FullCalendar>(null);
  const fetchEventsRef = useRef<(start: Date, end: Date) => void>(() => {});
  const [stylists, setStylists] = useState<Stylist[]>([]);
  const [stylistColors, setStylistColors] = useState<Record<string, { bg: string; border: string }>>({});
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  // Legacy zoom index (for scroll-preserve logic during ctrl+wheel)
  const [_legacyZoomIndex, setLegacyZoomIndex] = useState(DEFAULT_LEGACY_ZOOM);
  const calendarCardRef = useRef<HTMLDivElement>(null);

  // Calendar state — view, zoom, activeStylists (all persisted)
  const {
    selectedView,
    selectedDate,
    activeStylists,
    zoomLevel,
    businessHours,
    isMobile,
    persistStylistIds,
    initActiveStylists,
    toggleStylist,
    toggleAllStylists,
    setView,
    setZoom,
    setDate: setSelectedDate,
  } = useCalendarState();

  // Derive selectedStylistIds array from Set with stable identity
  // (activeStylists Set identity only changes when toggled — without useMemo
  // every render produces a new array, which cascades into a new fetchEvents
  // callback and re-fires the useEffect that reads it, causing an infinite loop).
  const selectedStylistIds = useMemo(
    () => Array.from(activeStylists),
    [activeStylists],
  );

  // Surface (view, activeStylists count) to the page so it can render the
  // subtitle that matches the active view.
  useEffect(() => {
    onContextChange?.({ view: selectedView, activeStylists: selectedStylistIds.length });
  }, [onContextChange, selectedView, selectedStylistIds.length]);

  // Mobile filter sheet state
  const [isFilterSheetOpen, setIsFilterSheetOpen] = useState(false);

  // Modal states (blocking events)
  const [isBlockingModalOpen, setIsBlockingModalOpen] = useState(false);
  const [selectedDateForBlocking, setSelectedDateForBlocking] = useState<Date | null>(null);
  const [selectedStartTime, setSelectedStartTime] = useState<Date | null>(null);
  const [selectedEndTime, setSelectedEndTime] = useState<Date | null>(null);
  const [selectedStylistForModal, setSelectedStylistForModal] = useState<string | null>(null);

  // Appointment modal states (Task 1.3)
  const [isAppointmentModalOpen, setIsAppointmentModalOpen] = useState(false);
  const [selectedDateForModal, setSelectedDateForModal] = useState<Date | null>(null);
  const [selectedStartTimeForModal, setSelectedStartTimeForModal] = useState<Date | null>(null);
  const [selectedEndTimeForModal, setSelectedEndTimeForModal] = useState<Date | null>(null);
  const [selectedStylistForAppointmentModal, setSelectedStylistForAppointmentModal] = useState<string | null>(null);

  // Edit mode states
  const [blockingModalMode, setBlockingModalMode] = useState<"create" | "edit">("create");
  const [editingBlockingEvent, setEditingBlockingEvent] = useState<EditingBlockingEvent | null>(null);

  // Series edit dialog states
  const [isSeriesDialogOpen, setIsSeriesDialogOpen] = useState(false);
  const [seriesDialogAction, setSeriesDialogAction] = useState<"edit" | "delete">("edit");
  const [seriesInfo, setSeriesInfo] = useState<{
    series_id: string;
    total_instances: number;
    instance_index: number;
    remaining_instances: number;
    frequency: string;
    interval: number;
    days: string | null;
  } | null>(null);
  const [pendingSeriesEvent, setPendingSeriesEvent] = useState<{
    id: string;
    title: string;
    props: Record<string, unknown>;
    startStr: string;
    endStr: string;
  } | null>(null);
  const [isSeriesLoading, setIsSeriesLoading] = useState(false);

  // Exception warning dialog states (for series edits)
  const [isExceptionDialogOpen, setIsExceptionDialogOpen] = useState(false);
  const [exceptionsInfo, setExceptionsInfo] = useState<{
    has_exceptions: boolean;
    exception_count: number;
    exceptions: Array<{ id: string; title: string; start_time: string; occurrence_index: number }>;
  } | null>(null);
  const [pendingEditScope, setPendingEditScope] = useState<SeriesEditScope | null>(null);
  const [pendingOverwriteExceptions, setPendingOverwriteExceptions] = useState<boolean>(false);

  // Action selection dialog state (drag-select: cita vs bloqueo)
  const [isActionDialogOpen, setIsActionDialogOpen] = useState(false);
  // stylistId is set when the day-view drag-select knows the column;
  // FC week-view selects don't carry a stylist so it falls back to the
  // first selected stylist in handleSelectAppointment / handleSelectBlocking.
  const [pendingSelectInfo, setPendingSelectInfo] = useState<{ start: Date; end: Date | null; stylistId?: string } | null>(null);

  // Appointment popover state (CAL-06)
  const [popoverState, setPopoverState] = useState<{
    open: boolean;
    anchorEl: HTMLElement | null;
    data: PopoverAppointmentData | null;
  }>({ open: false, anchorEl: null, data: null });

  // Drag/resize pending operation (single discriminated union)
  const seriesRevertRef = useRef<(() => void) | null>(null);
  const [pendingDragOp, setPendingDragOp] = useState<PendingDragOperation>(null);
  const [isProcessingDrag, setIsProcessingDrag] = useState(false);
  // Derived state — no separate useState needed
  const isOverlapDialogOpen = pendingDragOp !== null;
  const overlapConflicts = pendingDragOp?.conflicts ?? [];

  // Appointment Wizard state (for "Nueva Cita" button)
  const [isWizardOpen, setIsWizardOpen] = useState(false);
  const [wizardServices, setWizardServices] = useState<Service[]>([]);
  const [wizardCustomers, setWizardCustomers] = useState<Customer[]>([]);

  const loadWizardData = useCallback(async () => {
    try {
      const [servicesRes, customersRes] = await Promise.all([
        api.list<Service>("services", { is_active: true, page_size: 200 }),
        api.list<Customer>("customers", { page_size: 500 }),
      ]);
      setWizardServices(servicesRes.items);
      setWizardCustomers(customersRes.items);
    } catch (error) {
      console.error("Error loading wizard data:", error);
    }
  }, []);

  const refreshWizardCustomers = useCallback(async () => {
    try {
      const res = await api.list<Customer>("customers", { page_size: 500 });
      setWizardCustomers(res.items);
    } catch (error) {
      console.error("Error refreshing customers:", error);
    }
  }, []);

  // Generate darker border color from background color
  const getDarkerColor = (hex: string): string => {
    // Remove # and parse RGB
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    // Darken by 15%
    const darken = (c: number) => Math.max(0, Math.floor(c * 0.85));
    return `#${darken(r).toString(16).padStart(2, '0')}${darken(g).toString(16).padStart(2, '0')}${darken(b).toString(16).padStart(2, '0')}`;
  };

  // Assign colors to stylists (use stored color if available, fallback to palette)
  const assignStylistColors = useCallback((stylistList: Stylist[]) => {
    const colors: Record<string, { bg: string; border: string }> = {};
    stylistList.forEach((stylist, index) => {
      if (stylist.color) {
        // Use the stylist's custom color
        colors[stylist.id] = { bg: stylist.color, border: getDarkerColor(stylist.color) };
      } else {
        // Fallback to palette based on index
        const color = STYLIST_COLORS[index % STYLIST_COLORS.length];
        colors[stylist.id] = { bg: color.bg, border: color.border };
      }
    });
    setStylistColors(colors);
  }, []);

  // Fetch stylists on mount
  useEffect(() => {
    async function fetchStylists() {
      try {
        const response = await api.list<Stylist>("stylists", { is_active: true });
        setStylists(response.items);
        assignStylistColors(response.items);
        if (response.items.length > 0) {
          const allIds = response.items.map(s => s.id);
          initActiveStylists(allIds);
        }
      } catch (error) {
        console.error("Error fetching stylists:", error);
      }
    }
    fetchStylists();
  }, [assignStylistColors, initActiveStylists]);

  // Persist stylist selection whenever it changes (only after stylists are loaded)
  useEffect(() => {
    if (stylists.length > 0) {
      persistStylistIds(selectedStylistIds);
    }
  }, [selectedStylistIds, stylists.length, persistStylistIds]);

  // Fetch events when stylists or date range changes
  const fetchEvents = useCallback(async (start: Date, end: Date) => {
    if (selectedStylistIds.length === 0) {
      setEvents([]);
      setIsLoading(false);
      return;
    }

    try {
      setIsLoading(true);

      const response = await api.getCalendarEvents(
        selectedStylistIds,
        start.toISOString(),
        end.toISOString()
      );

      // Apply colors based on stylist (ALL events use stylist color, except holidays)
      const coloredEvents = response.events.map(event => {
        let bgColor = event.backgroundColor;
        let borderColor = event.borderColor;

        if (event.extendedProps.type === "holiday") {
          // Holidays have special color (no stylist)
          bgColor = HOLIDAY_COLOR.bg;
          borderColor = HOLIDAY_COLOR.border;
        } else {
          // ALL other events (appointments AND blocking events) use stylist color
          const stylistId = event.extendedProps.stylist_id;
          if (stylistId) {
            const stylistColor = stylistColors[stylistId];
            if (stylistColor) {
              bgColor = stylistColor.bg;
              borderColor = stylistColor.border;
            }
          }
        }

        // Determine if event is resizable
        let durationEditable = false;
        if (event.extendedProps.type === "appointment") {
          const status = event.extendedProps.status;
          durationEditable = status === "pending" || status === "confirmed";
        } else if (event.extendedProps.type === "blocking_event") {
          durationEditable = true;
        }

        return {
          ...event,
          backgroundColor: bgColor,
          borderColor: borderColor,
          durationEditable,
          startEditable: durationEditable,
        };
      });

      setEvents(coloredEvents);
    } catch (error) {
      console.error("Error fetching events:", error);
      setEvents([]);
      const errorMessage = error instanceof Error ? error.message : "Error desconocido";
      alert(`Error cargando eventos del calendario: ${errorMessage}`);
    } finally {
      setIsLoading(false);
    }
  }, [selectedStylistIds, stylistColors]);

  // Get the FullCalendar scroll container
  const getScrollEl = useCallback((): HTMLElement | null => {
    return calendarCardRef.current?.querySelector(".fc-scroller-liquid-absolute") as HTMLElement | null;
  }, []);

  // Zoom toward a point: keeps the same time at the same pixel position
  const zoomTowardPoint = useCallback((direction: 1 | -1, cursorYInViewport?: number) => {
    const scrollEl = getScrollEl();
    let ratio = 0.5;
    let cursorOffset = 0;
    if (scrollEl) {
      const containerRect = scrollEl.getBoundingClientRect();
      cursorOffset = cursorYInViewport !== undefined
        ? cursorYInViewport - containerRect.top
        : containerRect.height / 2;
      ratio = (scrollEl.scrollTop + cursorOffset) / scrollEl.scrollHeight;
    }

    setLegacyZoomIndex(prev => {
      const next = prev + direction;
      const clamped = Math.max(0, Math.min(next, LEGACY_ZOOM_LEVELS.length - 1));
      if (clamped !== prev) {
        setTimeout(() => {
          const el = getScrollEl();
          if (el) {
            el.scrollTop = ratio * el.scrollHeight - cursorOffset;
          }
        }, 50);
        // Sync to new zoom state
        const zoomMap: Record<number, import("./use-calendar-state").ZoomLevel> = {
          0: "30min", 1: "15min", 2: "5min", 3: "5min",
        };
        setZoom(zoomMap[clamped] ?? "15min");
      }
      return clamped;
    });
  }, [getScrollEl, setZoom]);

  // Ctrl+Wheel zoom on calendar — zoom toward cursor position
  useEffect(() => {
    const el = calendarCardRef.current;
    if (!el) return;

    const handleWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      zoomTowardPoint(e.deltaY > 0 ? -1 : 1, e.clientY);
    };

    el.addEventListener("wheel", handleWheel, { passive: false });
    return () => el.removeEventListener("wheel", handleWheel);
  }, [zoomTowardPoint]);

  // Keep ref in sync so resize handlers always use latest fetchEvents
  useEffect(() => { fetchEventsRef.current = fetchEvents; }, [fetchEvents]);

  // Fetch events when stylists change
  useEffect(() => {
    if (calendarRef.current) {
      const calendarApi = calendarRef.current.getApi();
      const view = calendarApi.view;
      fetchEvents(view.activeStart, view.activeEnd || new Date());
    }
  }, [selectedStylistIds, fetchEvents]);

  // Expose refresh + resetToWeek via ref
  useImperativeHandle(ref, () => ({
    refresh: () => {
      if (calendarRef.current) {
        const calendarApi = calendarRef.current.getApi();
        const view = calendarApi.view;
        fetchEvents(view.activeStart, view.activeEnd || new Date());
      }
    },
    resetToWeek: () => {
      setView("week");
    },
  }), [fetchEvents, setView]);

  // Sync FullCalendar view when selectedView or mobile changes
  useEffect(() => {
    const fcApi = calendarRef.current?.getApi();
    if (!fcApi) return;
    if (isMobile) {
      fcApi.changeView("listWeek");
      return;
    }
    const fcView = selectedView === "day"
      ? "timeGridDay"
      : selectedView === "month"
      ? "dayGridMonth"
      : "timeGridWeek";
    const currentFcView = fcApi.view.type;
    if (currentFcView !== fcView) {
      fcApi.changeView(fcView);
      // When entering Día, FC's internal pointer is whatever start-of-range
      // datesSet last fired with (Monday for a week view). Without this jump,
      // the day view would silently land on Monday instead of today.
      if (selectedView === "day") {
        fcApi.gotoDate(new Date());
      }
    }
  }, [selectedView, isMobile]);

  // Handle date set (when calendar view changes) — S4.10: also update selectedDate
  const handleDatesSet = (arg: { start: Date; end: Date }) => {
    setSelectedDate(arg.start);
    fetchEvents(arg.start, arg.end);
  };

  // Handle event click
  const handleEventClick = async (info: {
    el: HTMLElement;
    event: {
      id: string;
      title: string;
      startStr: string;
      endStr: string;
      start: Date | null;
      end: Date | null;
      backgroundColor: string;
      extendedProps: Record<string, unknown>;
    };
  }) => {
    const props = info.event.extendedProps;

    if (props.type === "blocking_event") {
      const blockingEventId = props.blocking_event_id as string;
      const recurringSeriesId = props.recurring_series_id as string | null;

      if (recurringSeriesId) {
        // This is a recurring event - fetch series info and show dialog
        setPendingSeriesEvent({
          id: blockingEventId,
          title: info.event.title,
          props,
          startStr: info.event.startStr,
          endStr: info.event.endStr,
        });
        setSeriesDialogAction("edit");
        setIsSeriesLoading(true);

        try {
          const series = await api.getBlockingEventSeries(blockingEventId);
          setSeriesInfo(series);
          setIsSeriesDialogOpen(true);
        } catch (error) {
          console.error("Error fetching series info:", error);
          // Fallback: open normal edit modal for this single event
          openBlockingEditModal(blockingEventId, info.event.title, props, info.event.startStr, info.event.endStr);
        } finally {
          setIsSeriesLoading(false);
        }
      } else {
        // Normal single blocking event - open edit modal directly
        openBlockingEditModal(blockingEventId, info.event.title, props, info.event.startStr, info.event.endStr);
      }
    } else if (props.type === "appointment" && props.appointment_id) {
      if (isMobile) {
        // On mobile, navigate directly instead of showing popover
        router.push(`/appointments/${props.appointment_id as string}`);
      } else {
        // Open appointment popover instead of navigating
        setPopoverState({
          open: true,
          anchorEl: info.el,
          data: {
            appointmentId: props.appointment_id as string,
            customerName: (props.customer_name as string) || "",
            serviceNames: (props.service_names as string[]) || [],
            status: (props.status as string) || "",
            duration: (props.duration_minutes as number) || 0,
            notes: (props.notes as string | null) || null,
            stylistColor: info.event.backgroundColor,
            title: info.event.title,
            start: info.event.start,
            end: info.event.end,
          },
        });
      }
    }
    // Holidays: no action on click
  };

  // Helper to open blocking event edit modal
  const openBlockingEditModal = (
    id: string,
    title: string,
    props: Record<string, unknown>,
    startStr: string,
    endStr: string
  ) => {
    setEditingBlockingEvent({
      id,
      title,
      description: props.description as string | null,
      event_type: props.event_type as string,
      start_time: startStr,
      end_time: endStr,
      stylist_id: props.stylist_id as string,
    });
    setBlockingModalMode("edit");
    setIsBlockingModalOpen(true);
  };

  // Handle series edit dialog confirm
  const handleSeriesEditConfirm = async (scope: SeriesEditScope) => {
    if (!pendingSeriesEvent || !seriesInfo) return;

    setIsSeriesLoading(true);

    try {
      if (seriesDialogAction === "delete") {
        // Delete with scope
        await api.deleteBlockingEventWithScope(pendingSeriesEvent.id, scope);
        refreshCalendar(); // Refresh calendar
      } else if (pendingSeriesEvent.props.new_end_time || pendingSeriesEvent.props.new_start_time) {
        // Resize or move origin — apply time change directly
        const updateData: { start_time?: string; end_time?: string } = {};
        if (pendingSeriesEvent.props.new_start_time) {
          updateData.start_time = pendingSeriesEvent.props.new_start_time as string;
        }
        if (pendingSeriesEvent.props.new_end_time) {
          updateData.end_time = pendingSeriesEvent.props.new_end_time as string;
        }
        try {
          await api.updateBlockingEventWithScope(
            pendingSeriesEvent.id,
            updateData,
            scope
          );
          seriesRevertRef.current = null;
          refreshCalendar();
        } catch (err) {
          console.error("Failed to resize recurring blocking event:", err);
          seriesRevertRef.current?.();
          seriesRevertRef.current = null;
        }
      } else {
        // Edit action (click-to-edit flow)
        if (scope === "this_only") {
          // Simple case: open modal, it will use regular update endpoint
          openBlockingEditModal(
            pendingSeriesEvent.id,
            pendingSeriesEvent.title,
            pendingSeriesEvent.props,
            pendingSeriesEvent.startStr,
            pendingSeriesEvent.endStr
          );
        } else {
          // For this_and_future or all, check for exceptions first
          const exceptions = await api.checkSeriesExceptions(
            pendingSeriesEvent.id,
            scope as "this_and_future" | "all"
          );

          if (exceptions.has_exceptions) {
            // Show exception warning dialog
            setExceptionsInfo(exceptions);
            setPendingEditScope(scope);
            setIsExceptionDialogOpen(true);
            // Don't close series dialog yet - wait for exception choice
          } else {
            // No exceptions, proceed directly to edit modal with scope
            openBlockingEditModalWithScope(scope, false);
          }
        }
      }
    } catch (error) {
      console.error("Error handling series action:", error);
      alert(error instanceof Error ? error.message : "Error procesando la acción");
    } finally {
      setIsSeriesLoading(false);
      setIsSeriesDialogOpen(false);
      // Note: We don't clear pendingSeriesEvent and seriesInfo here
      // because they may be needed by the exception dialog
      if (seriesDialogAction === "delete") {
        setPendingSeriesEvent(null);
        setSeriesInfo(null);
      }
    }
  };

  // Handle exception warning dialog confirm
  const handleExceptionDialogConfirm = (overwriteExceptions: boolean) => {
    if (!pendingEditScope) return;

    setPendingOverwriteExceptions(overwriteExceptions);
    setIsExceptionDialogOpen(false);
    setExceptionsInfo(null);

    // Open the edit modal with scope
    openBlockingEditModalWithScope(pendingEditScope, overwriteExceptions);
  };

  // Helper to open blocking edit modal with scope
  const openBlockingEditModalWithScope = (scope: SeriesEditScope, overwriteExceptions: boolean) => {
    if (!pendingSeriesEvent) return;

    setEditingBlockingEvent({
      id: pendingSeriesEvent.id,
      title: pendingSeriesEvent.title,
      description: pendingSeriesEvent.props.description as string | null,
      event_type: pendingSeriesEvent.props.event_type as string,
      start_time: pendingSeriesEvent.startStr,
      end_time: pendingSeriesEvent.endStr,
      stylist_id: pendingSeriesEvent.props.stylist_id as string,
    });
    setPendingEditScope(scope);
    setPendingOverwriteExceptions(overwriteExceptions);
    setBlockingModalMode("edit");
    setIsBlockingModalOpen(true);
  };

  // Handle single date/time click — shows action choice dialog (cita vs bloqueo)
  const handleDateClick = (info: { date: Date; allDay: boolean }) => {
    if (info.allDay) return; // skip all-day header clicks

    if (selectedStylistIds.length === 0) {
      alert("Por favor selecciona al menos un estilista");
      return;
    }

    setPendingSelectInfo({ start: info.date, end: null });
    setIsActionDialogOpen(true);
  };

  // Handle drag-select — shows action choice dialog (cita vs bloqueo)
  // Skip zero-duration clicks (handled by dateClick instead)
  const handleSelect = (info: { start: Date; end: Date; allDay: boolean }) => {
    if (info.allDay) return;
    if (info.start.getTime() === info.end.getTime()) return;
    if (selectedStylistIds.length === 0) {
      alert("Por favor selecciona al menos un estilista");
      return;
    }

    setPendingSelectInfo({ start: info.start, end: info.end });
    setIsActionDialogOpen(true);
  };

  // Action dialog handlers
  const handleSelectAppointment = () => {
    if (!pendingSelectInfo) return;
    setSelectedDateForModal(pendingSelectInfo.start);
    setSelectedStartTimeForModal(pendingSelectInfo.start);
    setSelectedEndTimeForModal(pendingSelectInfo.end);
    setSelectedStylistForAppointmentModal(pendingSelectInfo.stylistId ?? selectedStylistIds[0]);
    setIsAppointmentModalOpen(true);
    setPendingSelectInfo(null);
  };

  const handleSelectBlocking = () => {
    if (!pendingSelectInfo) return;
    setSelectedStylistForModal(pendingSelectInfo.stylistId ?? selectedStylistIds[0]);
    setSelectedDateForBlocking(pendingSelectInfo.start);
    setSelectedStartTime(pendingSelectInfo.start);
    setSelectedEndTime(pendingSelectInfo.end);
    setBlockingModalMode("create");
    setEditingBlockingEvent(null);
    setIsBlockingModalOpen(true);
    setPendingSelectInfo(null);
  };

  // Handle creating blocking event from button (uses current date/time)
  const handleCreateBlockingEvent = () => {
    if (selectedStylistIds.length === 0) {
      alert("Por favor selecciona al menos un estilista");
      return;
    }

    // Default to first selected stylist
    setSelectedStylistForModal(selectedStylistIds[0]);
    setSelectedDateForBlocking(new Date());
    setSelectedStartTime(null);  // Will use defaults in modal
    setSelectedEndTime(null);
    setBlockingModalMode("create");
    setEditingBlockingEvent(null);
    setIsBlockingModalOpen(true);
  };

  // Handle creating appointment - open wizard modal
  const handleCreateAppointment = async () => {
    await loadWizardData();
    setIsWizardOpen(true);
  };

  // Stable refetch that always uses latest fetchEvents (avoids stale closures)
  const refreshCalendar = useCallback(() => {
    const calendarApi = calendarRef.current?.getApi();
    if (calendarApi) {
      const start = calendarApi.view.activeStart;
      const end = calendarApi.view.activeEnd || new Date();
      fetchEventsRef.current(start, end);
    }
  }, []);

  // Handle appointment resize with overlap check
  const handleAppointmentResize = useCallback(async (
    props: Record<string, unknown>,
    start: Date,
    newDurationMinutes: number,
    revert: () => void
  ) => {
    const appointmentId = props.appointment_id as string;
    const stylistId = props.stylist_id as string;

    try {
      setIsProcessingDrag(true);
      const overlapResult = await api.checkOverlaps(
        stylistId,
        start.toISOString(),
        newDurationMinutes,
        appointmentId
      );

      if (overlapResult.has_overlaps) {
        setPendingDragOp({
          type: "resize",
          appointmentId,
          durationMinutes: newDurationMinutes,
          revert,
          conflicts: overlapResult.conflicts,
        });
        setIsProcessingDrag(false);
        return;
      }

      await api.updateAppointment(appointmentId, { duration_minutes: newDurationMinutes });
      refreshCalendar();
    } catch (error) {
      console.error("Failed to resize appointment:", error);
      revert();
    } finally {
      setIsProcessingDrag(false);
    }
  }, [refreshCalendar]);

  // Handle blocking event resize
  const handleBlockingEventResize = useCallback(async (
    props: Record<string, unknown>,
    newEnd: Date,
    revert: () => void
  ) => {
    const blockingEventId = props.blocking_event_id as string;
    const isRecurring = !!props.recurring_series_id;

    try {
      if (isRecurring) {
        // Store revert for async series dialog flow
        seriesRevertRef.current = revert;
        setIsSeriesLoading(true);

        const seriesData = await api.getBlockingEventSeries(blockingEventId);
        setSeriesInfo(seriesData);
        setPendingSeriesEvent({
          id: blockingEventId,
          title: (props.title as string) || "",
          props: { ...props, new_end_time: newEnd.toISOString() },
          startStr: "",
          endStr: newEnd.toISOString(),
        });
        setSeriesDialogAction("edit");
        setIsSeriesDialogOpen(true);
        setIsSeriesLoading(false);
        return;
      }

      await api.updateBlockingEvent(blockingEventId, { end_time: newEnd.toISOString() });
      refreshCalendar();
    } catch (error) {
      console.error("Failed to resize blocking event:", error);
      revert();
    }
  }, [refreshCalendar]);

  // Main resize dispatcher
  const handleEventResize = useCallback(async (info: EventResizeDoneArg) => {
    const { event, revert } = info;
    const props = event.extendedProps;
    const newEnd = event.end;
    const start = event.start;

    if (!newEnd || !start) { revert(); return; }

    const newDurationMinutes = Math.round(
      (newEnd.getTime() - start.getTime()) / 60000
    );

    if (props.type === "appointment") {
      await handleAppointmentResize(props, start, newDurationMinutes, revert);
    } else if (props.type === "blocking_event") {
      await handleBlockingEventResize(props, newEnd, revert);
    } else {
      revert();
    }
  }, [handleAppointmentResize, handleBlockingEventResize]);

  // Handle appointment drag-to-move
  const handleAppointmentDrop = useCallback(async (
    props: Record<string, unknown>,
    newStart: Date,
    newEnd: Date,
    revert: () => void
  ) => {
    const appointmentId = props.appointment_id as string;
    const stylistId = props.stylist_id as string;
    const durationMinutes = props.duration_minutes as number;

    try {
      const overlapResult = await api.checkOverlaps(
        stylistId,
        newStart.toISOString(),
        durationMinutes,
        appointmentId
      );

      if (overlapResult.has_overlaps) {
        setPendingDragOp({
          type: "move",
          appointmentId,
          startTime: newStart.toISOString(),
          revert,
          conflicts: overlapResult.conflicts,
        });
        return;
      }

      await api.updateAppointment(appointmentId, { start_time: newStart.toISOString() });
      refreshCalendar();
    } catch (error) {
      console.error("Failed to move appointment:", error);
      revert();
    }
  }, [refreshCalendar]);

  // Handle blocking event drag-to-move
  const handleBlockingEventDrop = useCallback(async (
    props: Record<string, unknown>,
    newStart: Date,
    newEnd: Date,
    revert: () => void
  ) => {
    const blockingEventId = props.blocking_event_id as string;
    const isRecurring = !!props.recurring_series_id;

    try {
      if (isRecurring) {
        seriesRevertRef.current = revert;
        setIsSeriesLoading(true);
        const seriesData = await api.getBlockingEventSeries(blockingEventId);
        setSeriesInfo(seriesData);
        setPendingSeriesEvent({
          id: blockingEventId,
          title: (props.title as string) || "",
          props: {
            ...props,
            new_start_time: newStart.toISOString(),
            new_end_time: newEnd.toISOString(),
          },
          startStr: newStart.toISOString(),
          endStr: newEnd.toISOString(),
        });
        setSeriesDialogAction("edit");
        setIsSeriesDialogOpen(true);
        setIsSeriesLoading(false);
        return;
      }

      await api.updateBlockingEvent(blockingEventId, {
        start_time: newStart.toISOString(),
        end_time: newEnd.toISOString(),
      });
      refreshCalendar();
    } catch (error) {
      console.error("Failed to move blocking event:", error);
      revert();
    }
  }, [refreshCalendar]);

  // Main drag-to-move dispatcher
  const handleEventDrop = useCallback(async (info: EventDropArg) => {
    const { event, revert } = info;
    const props = event.extendedProps;
    const newStart = event.start;
    const newEnd = event.end;

    if (!newStart || !newEnd) { revert(); return; }

    if (props.type === "appointment") {
      await handleAppointmentDrop(props, newStart, newEnd, revert);
    } else if (props.type === "blocking_event") {
      await handleBlockingEventDrop(props, newStart, newEnd, revert);
    } else {
      revert();
    }
  }, [handleAppointmentDrop, handleBlockingEventDrop]);

  // Handle overlap dialog confirm — dispatches by operation type
  const handleOverlapConfirm = useCallback(async () => {
    if (!pendingDragOp) return;
    try {
      setIsProcessingDrag(true);
      switch (pendingDragOp.type) {
        case "resize":
          await api.updateAppointment(pendingDragOp.appointmentId, {
            duration_minutes: pendingDragOp.durationMinutes,
          });
          break;
        case "move":
          await api.updateAppointment(pendingDragOp.appointmentId, {
            start_time: pendingDragOp.startTime,
          });
          break;
      }
      setPendingDragOp(null);
      refreshCalendar();
    } catch (error) {
      console.error("Failed to update appointment after overlap confirm:", error);
      pendingDragOp.revert();
      setPendingDragOp(null);
    } finally {
      setIsProcessingDrag(false);
    }
  }, [pendingDragOp, refreshCalendar]);

  // Handle overlap dialog cancel — reverts and clears atomically
  const handleOverlapCancel = useCallback(() => {
    pendingDragOp?.revert();
    setPendingDragOp(null);
  }, [pendingDragOp]);

  // Get stylist name by ID
  const getStylistName = (id: string) => {
    return stylists.find(s => s.id === id)?.name || "Estilista";
  };

  // Compute status counts from visible events for legend
  const statusCounts = (() => {
    const counts: Record<string, number> = {};
    events.forEach(e => {
      if (e.extendedProps.type === "appointment" && e.extendedProps.status) {
        const s = e.extendedProps.status as string;
        counts[s] = (counts[s] || 0) + 1;
      }
    });
    return (["confirmed", "pending", "cancelled"] as AppointmentStatus[])
      .map(s => ({ status: s, count: counts[s] || 0 }))
      .filter(sc => sc.count > 0);
  })();

  // Toolbar navigation handler.
  // Week/month views are owned by FullCalendar (datesSet -> selectedDate).
  // The greenfield day view reads selectedDate from the hook directly, so
  // the FC handle is unmounted there — we update the hook state instead.
  const handleToolbarNav = useCallback((dir: "prev" | "next" | "today") => {
    if (selectedView === "day") {
      if (dir === "today") {
        setSelectedDate(new Date());
        return;
      }
      const next = new Date(selectedDate);
      next.setDate(next.getDate() + (dir === "next" ? 1 : -1));
      setSelectedDate(next);
      return;
    }
    const fcApi = calendarRef.current?.getApi();
    if (!fcApi) return;
    if (dir === "prev") fcApi.prev();
    else if (dir === "next") fcApi.next();
    else fcApi.today();
  }, [selectedView, selectedDate, setSelectedDate]);

  return (
    <div className="space-y-0">
      {isMobile ? (
        /* Mobile: minimal header with sheet filter */
        <div className="flex flex-wrap items-start justify-between gap-4 pb-4">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setIsFilterSheetOpen(true)}
          >
            <Filter className="h-4 w-4 mr-1" />
            Estilistas
          </Button>
        </div>
      ) : (
        /* Desktop: new toolbar + chip filter */
        <>
          <CalendarToolbar
            currentDate={selectedDate}
            view={selectedView}
            zoomLevel={zoomLevel}
            onNav={handleToolbarNav}
            onViewChange={(v) => setView(v)}
            onZoomChange={(z) => setZoom(z)}
            onCreate={handleCreateAppointment}
            onBlock={handleCreateBlockingEvent}
            rightPill={selectedView === "day" ? <DayViewPill events={events} stylists={stylists} gridStartHour={9} gridEndHour={21} /> : undefined}
          />
          <StylistChipFilter
            stylists={stylists.map((s, i) => ({ id: s.id, name: s.name, color: resolveStylistColor(s, i) }))}
            active={activeStylists}
            onToggle={toggleStylist}
            onToggleAll={toggleAllStylists}
            statusCounts={statusCounts}
          />
        </>
      )}

      {/* Mobile filter Sheet */}
      {isMobile && (
        <Sheet open={isFilterSheetOpen} onOpenChange={setIsFilterSheetOpen}>
          <SheetContent side="left" className="w-64">
            <SheetHeader>
              <SheetTitle>Filtrar estilistas</SheetTitle>
            </SheetHeader>
            <div className="space-y-2 pt-4">
              {stylists.map(s => (
                <button
                  key={s.id}
                  onClick={() => toggleStylist(s.id)}
                  className={`w-full text-left px-3 py-2 rounded-lg text-sm font-medium transition-colors ${activeStylists.has(s.id) ? "bg-gold-soft text-gold-dark" : "text-ink-mute hover:text-ink"}`}
                >
                  {s.name}
                </button>
              ))}
            </div>
          </SheetContent>
        </Sheet>
      )}

      {/* Calendar — day view (greenfield) or FullCalendar (week/month) */}
      {!isMobile && selectedView === "day" ? (
        <div className="relative">
          {isLoading && (
            <div className="absolute inset-0 flex items-center justify-center bg-background/50 z-10 rounded-[14px]">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Calendar className="h-5 w-5 animate-pulse" />
                <span>Cargando eventos...</span>
              </div>
            </div>
          )}
          <CalendarDayView
            appointments={events.filter(e => e.extendedProps.type !== "holiday") as DayViewEvent[]}
            stylists={stylists
              .filter(s => activeStylists.has(s.id))
              .map((s, i): DayViewStylist => ({ id: s.id, name: s.name, color: resolveStylistColor(s, i) }))}
            date={DateTime.fromJSDate(selectedDate, { zone: "Europe/Madrid" })}
            gridStartHour={9}
            gridEndHour={21}
            slotMin={ZOOM_SLOT_MIN[zoomLevel]}
            slotPx={ZOOM_SLOT_PX[zoomLevel]}
            onAppointmentClick={(eventId) => {
              const ev = events.find(
                e => e.extendedProps.appointment_id === eventId
                  || e.extendedProps.blocking_event_id === eventId
                  || e.id === eventId
              );
              if (!ev) return;
              const props = ev.extendedProps;
              if (props.type === "blocking_event") {
                const blockingEventId = (props.blocking_event_id as string) || ev.id;
                const recurringSeriesId = props.recurring_series_id as string | null;

                if (recurringSeriesId) {
                  // Recurring block — mirror week-view: open SeriesEditDialog first
                  const startStr = typeof ev.start === "string" ? ev.start : new Date(ev.start as Date).toISOString();
                  const endStr = typeof ev.end === "string" ? ev.end : new Date(ev.end as Date).toISOString();
                  setPendingSeriesEvent({
                    id: blockingEventId,
                    title: ev.title,
                    props,
                    startStr,
                    endStr,
                  });
                  setSeriesDialogAction("edit");
                  setIsSeriesLoading(true);
                  api.getBlockingEventSeries(blockingEventId)
                    .then((series) => {
                      setSeriesInfo(series);
                      setIsSeriesDialogOpen(true);
                    })
                    .catch((error) => {
                      console.error("Error fetching series info:", error);
                      // Fallback: open plain edit modal for this occurrence
                      openBlockingEditModal(blockingEventId, ev.title, props, startStr, endStr);
                    })
                    .finally(() => setIsSeriesLoading(false));
                  return;
                }

                // Non-recurring blocking event — open edit modal directly
                setEditingBlockingEvent({
                  id: blockingEventId,
                  title: ev.title,
                  description: (props.description as string | null) ?? null,
                  event_type: (props.event_type as string) || "other",
                  start_time: typeof ev.start === "string" ? ev.start : new Date(ev.start as Date).toISOString(),
                  end_time: typeof ev.end === "string" ? ev.end : new Date(ev.end as Date).toISOString(),
                  stylist_id: (props.stylist_id as string) || "",
                });
                setBlockingModalMode("edit");
                setIsBlockingModalOpen(true);
                return;
              }
              // Appointment → existing popover flow
              setPopoverState({
                open: true,
                anchorEl: null,
                data: {
                  appointmentId: eventId,
                  customerName: (props.customer_name as string) || "",
                  serviceNames: (props.service_names as string[]) || [],
                  status: (props.status as string) || "",
                  duration: (props.duration_minutes as number) || 0,
                  notes: (props.notes as string | null) || null,
                  stylistColor: ev.backgroundColor,
                  title: ev.title,
                  start: ev.start ? new Date(ev.start) : null,
                  end: ev.end ? new Date(ev.end) : null,
                },
              });
            }}
            onEmptySlotClick={(stylistId, datetime) => {
              const dt = new Date(datetime);
              setSelectedDateForModal(dt);
              setSelectedStartTimeForModal(dt);
              setSelectedEndTimeForModal(null);
              setSelectedStylistForAppointmentModal(stylistId);
              setIsAppointmentModalOpen(true);
            }}
            onSelect={(stylistId, startISO, endISO) => {
              if (selectedStylistIds.length === 0) return;
              setPendingSelectInfo({ start: new Date(startISO), end: new Date(endISO), stylistId });
              setIsActionDialogOpen(true);
            }}
          />
        </div>
      ) : (
      <Card ref={calendarCardRef} className={`relative ${isMobile ? "" : "rounded-t-none border-t-0"}`}>
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/50 z-10 rounded-lg">
            <div className="flex items-center gap-2 text-muted-foreground">
              <Calendar className="h-5 w-5 animate-pulse" />
              <span>Cargando eventos...</span>
            </div>
          </div>
        )}
        <FullCalendar
          ref={calendarRef}
          plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin, listPlugin, luxonPlugin]}
          initialView={isMobile ? "listWeek" : "timeGridWeek"}
          locale={esLocale}
          timeZone="Europe/Madrid"
          headerToolbar={
            isMobile
              ? { left: "prev,next", center: "title", right: "listWeek,timeGridDay" }
              : false
          }
          buttonText={{
            today: "Hoy",
            day: "Dia",
            week: "Semana",
            month: "Mes",
            list: "Lista",
          }}
          noEventsText="No hay eventos en este período"
          slotMinTime="09:00:00"
          slotMaxTime="21:00:00"
          allDaySlot={true}
          weekends={true}
          editable={false}
          eventStartEditable={true}
          eventDurationEditable={true}
          eventResizableFromStart={false}
          eventResize={handleEventResize}
          eventDrop={handleEventDrop}
          selectable={true}
          selectMirror={true}
          dayMaxEvents={true}
          events={events}
          datesSet={handleDatesSet}
          eventClick={handleEventClick}
          dateClick={handleDateClick}
          select={handleSelect}
          businessHours={businessHours || undefined}
          height="calc(100vh - 200px)"
          slotDuration={ZOOM_SLOT_MAP[zoomLevel]}
          slotLabelInterval={ZOOM_LABEL_MAP[zoomLevel]}
          nowIndicator={true}
          eventTimeFormat={{
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          }}
          dayHeaderContent={(arg) => {
            // Stacked header per handoff: small uppercase weekday + large day number.
            const weekday = arg.date
              .toLocaleDateString("es-ES", { weekday: "short" })
              .replace(".", "")
              .toUpperCase();
            return {
              html: `<div class="flex flex-col items-center gap-1 leading-none">
                <span class="text-[11px] font-semibold uppercase tracking-widest text-ink-mute">${weekday}</span>
                <span class="text-[20px] font-bold text-ink tabular-nums">${arg.date.getDate()}</span>
              </div>`,
            };
          }}
          dayCellClassNames={(arg) => {
            // Gold-pastel highlight for days that have holiday events
            const dateStr = arg.date.toISOString().slice(0, 10);
            const hasHoliday = events.some(
              e => e.extendedProps.type === "holiday" && e.start.slice(0, 10) === dateStr
            );
            return hasHoliday ? ["fc-day-has-holiday"] : [];
          }}
          eventContent={(arg) => {
            const props = arg.event.extendedProps;
            if (props.type !== "appointment") {
              // Non-appointment events (holidays, blocking events) use default FC rendering
              return undefined;
            }
            return (
              <ApptCard
                extendedProps={props as Parameters<typeof ApptCard>[0]["extendedProps"]}
                stylistColor={arg.event.backgroundColor || "#928679"}
                start={arg.event.start}
                end={arg.event.end}
                mode="week"
              />
            );
          }}
          eventClassNames={(arg) => {
            const type = arg.event.extendedProps.type;
            const status = arg.event.extendedProps.status;
            if (type === "holiday") return ["cal-event-holiday"];
            if (type !== "appointment" || !status) return [];
            const config = STATUS_MAP[status as keyof typeof STATUS_MAP];
            // For appointment events rendered via eventContent, suppress the left border
            // (ApptCard renders its own 3px border-left)
            return config ? ["cal-appt-custom"] : [];
          }}
        />
      </Card>
      )}

      {/* Action Selection Dialog (drag-select: cita vs bloqueo) */}
      <SelectActionDialog
        isOpen={isActionDialogOpen}
        onClose={() => {
          setIsActionDialogOpen(false);
          setPendingSelectInfo(null);
        }}
        onSelectAppointment={handleSelectAppointment}
        onSelectBlocking={handleSelectBlocking}
      />

      {/* Appointment Modal (from dateClick / drag-select) */}
      <CreateAppointmentModal
        isOpen={isAppointmentModalOpen}
        onClose={() => {
          setIsAppointmentModalOpen(false);
          setSelectedDateForModal(null);
          setSelectedStartTimeForModal(null);
          setSelectedEndTimeForModal(null);
          setSelectedStylistForAppointmentModal(null);
        }}
        stylistId={selectedStylistForAppointmentModal || selectedStylistIds[0] || ""}
        selectedDate={selectedDateForModal}
        selectedStartTime={selectedStartTimeForModal}
        selectedEndTime={selectedEndTimeForModal}
        onSuccess={refreshCalendar}
        availableStylists={stylists
          .filter(s => selectedStylistIds.includes(s.id))
          .map(s => ({ id: s.id, name: s.name }))}
      />

      {/* Blocking Event Modal (Create/Edit) */}
      <BlockingEventModal
        isOpen={isBlockingModalOpen}
        onClose={() => {
          setIsBlockingModalOpen(false);
          setEditingBlockingEvent(null);
          setBlockingModalMode("create");
          setPendingEditScope(null);
          setPendingOverwriteExceptions(false);
          setPendingSeriesEvent(null);
          setSeriesInfo(null);
        }}
        mode={blockingModalMode}
        blockingEvent={editingBlockingEvent}
        stylistId={selectedStylistForModal || selectedStylistIds[0]}
        stylistName={getStylistName(selectedStylistForModal || selectedStylistIds[0])}
        selectedDate={selectedDateForBlocking}
        selectedStartTime={selectedStartTime}
        selectedEndTime={selectedEndTime}
        stylists={stylists.filter(s => selectedStylistIds.includes(s.id))}
        onSuccess={refreshCalendar}
        editScope={pendingEditScope}
        overwriteExceptions={pendingOverwriteExceptions}
      />

      {/* Series Edit Dialog (for recurring events) */}
      {seriesInfo && pendingSeriesEvent && (
        <SeriesEditDialog
          isOpen={isSeriesDialogOpen}
          onClose={() => {
            setIsSeriesDialogOpen(false);
            // Revert resize/move if this was a drag-triggered dialog
            if (pendingSeriesEvent?.props?.new_end_time || pendingSeriesEvent?.props?.new_start_time) {
              seriesRevertRef.current?.();
              seriesRevertRef.current = null;
            }
            setPendingSeriesEvent(null);
            setSeriesInfo(null);
          }}
          action={seriesDialogAction}
          eventTitle={pendingSeriesEvent.title}
          seriesInfo={seriesInfo}
          onConfirm={handleSeriesEditConfirm}
          isLoading={isSeriesLoading}
        />
      )}

      {/* Exception Warning Dialog (when editing series with modified instances) */}
      <ExceptionWarningDialog
        isOpen={isExceptionDialogOpen}
        onClose={() => {
          setIsExceptionDialogOpen(false);
          setExceptionsInfo(null);
          setPendingEditScope(null);
          setPendingSeriesEvent(null);
          setSeriesInfo(null);
        }}
        exceptionCount={exceptionsInfo?.exception_count || 0}
        onConfirm={handleExceptionDialogConfirm}
      />

      {/* Appointment Wizard (from "Nueva Cita" button) */}
      <AppointmentWizard
        open={isWizardOpen}
        onOpenChange={setIsWizardOpen}
        onSuccess={refreshCalendar}
        services={wizardServices}
        stylists={stylists as unknown as FullStylist[]}
        customers={wizardCustomers}
        refreshCustomers={refreshWizardCustomers}
      />

      {/* Appointment Popover (CAL-06) */}
      <AppointmentPopover
        open={popoverState.open}
        anchorEl={popoverState.anchorEl}
        data={popoverState.data}
        onClose={() => setPopoverState({ open: false, anchorEl: null, data: null })}
        onCancelSuccess={refreshCalendar}
        onNavigate={(appointmentId) => {
          setPopoverState({ open: false, anchorEl: null, data: null });
          router.push(`/appointments/${appointmentId}`);
        }}
      />

      {/* Overlap Confirm Dialog (for resize) */}
      <OverlapConfirmDialog
        isOpen={isOverlapDialogOpen}
        onClose={handleOverlapCancel}
        onConfirm={handleOverlapConfirm}
        conflicts={overlapConflicts}
        isSubmitting={isProcessingDrag}
        operationType={pendingDragOp?.type}
      />
    </div>
  );
});
