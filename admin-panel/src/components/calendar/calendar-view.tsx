"use client";

import { useState, useEffect, useRef, useCallback, forwardRef, useImperativeHandle } from "react";
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
import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Plus, Calendar, Ban, Filter, ZoomIn, ZoomOut } from "lucide-react";
import api from "@/lib/api";
import { BlockingEventModal } from "./blocking-event-modal";
import { CreateAppointmentModal } from "./create-appointment-modal";
import { SeriesEditDialog, type SeriesEditScope } from "./series-edit-dialog";
import { ExceptionWarningDialog } from "./exception-warning-dialog";
import { STYLIST_COLORS, HOLIDAY_COLOR, STATUS_MAP } from "./calendar-constants";
import "./calendar-styles.css";
import { CalendarFilters } from "./calendar-filters";
import { CalendarLegend } from "./calendar-legend";
import { useCalendarState } from "./use-calendar-state";
import { AppointmentPopover, type PopoverAppointmentData } from "./appointment-popover";
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
}

const ZOOM_LEVELS = [
  { slot: "00:30:00", label: "30 min", labelInterval: "01:00" },
  { slot: "00:15:00", label: "15 min", labelInterval: "01:00" },
  { slot: "00:10:00", label: "10 min", labelInterval: "00:30" },
  { slot: "00:05:00", label: "5 min", labelInterval: "00:15" },
] as const;

const DEFAULT_ZOOM = 1; // 15 min

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

export const CalendarView = forwardRef<CalendarViewRef>(function CalendarView(_props, ref) {
  const router = useRouter();
  const calendarRef = useRef<FullCalendar>(null);
  const fetchEventsRef = useRef<(start: Date, end: Date) => void>(() => {});
  const [selectedStylistIds, setSelectedStylistIds] = useState<string[]>([]);
  const [stylists, setStylists] = useState<Stylist[]>([]);
  const [stylistColors, setStylistColors] = useState<Record<string, { bg: string; border: string }>>({});
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [zoomLevel, setZoomLevel] = useState(DEFAULT_ZOOM);
  const calendarCardRef = useRef<HTMLDivElement>(null);

  // localStorage persistence + business hours + mobile detection
  const { getPersistedStylistIds, persistStylistIds, businessHours, isMobile } = useCalendarState();

  // Mobile filter sheet state
  const [isFilterSheetOpen, setIsFilterSheetOpen] = useState(false);

  // Badge count: number of selected stylists when not all are selected
  const filterBadgeCount =
    selectedStylistIds.length > 0 && selectedStylistIds.length < stylists.length
      ? selectedStylistIds.length
      : null;

  // Modal states (blocking events)
  const [isBlockingModalOpen, setIsBlockingModalOpen] = useState(false);
  const [selectedDate, setSelectedDate] = useState<Date | null>(null);
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
  const [pendingSelectInfo, setPendingSelectInfo] = useState<{ start: Date; end: Date } | null>(null);

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
        // Restore persisted selection, falling back to all active stylists
        if (response.items.length > 0) {
          const allIds = response.items.map(s => s.id);
          setSelectedStylistIds(getPersistedStylistIds(allIds));
        }
      } catch (error) {
        console.error("Error fetching stylists:", error);
      }
    }
    fetchStylists();
  }, [assignStylistColors, getPersistedStylistIds]);

  // Persist stylist selection whenever it changes (only after stylists are loaded)
  useEffect(() => {
    if (stylists.length > 0) {
      persistStylistIds(selectedStylistIds);
    }
  }, [selectedStylistIds, stylists.length, persistStylistIds]);

  // Toggle stylist selection
  const toggleStylist = (stylistId: string) => {
    setSelectedStylistIds(prev => {
      if (prev.includes(stylistId)) {
        return prev.filter(id => id !== stylistId);
      } else {
        return [...prev, stylistId];
      }
    });
  };

  // Select/deselect all stylists
  const toggleAllStylists = () => {
    if (selectedStylistIds.length === stylists.length) {
      setSelectedStylistIds([]);
    } else {
      setSelectedStylistIds(stylists.map(s => s.id));
    }
  };

  // Fetch events when stylists or date range changes
  const fetchEvents = useCallback(async (start: Date, end: Date) => {
    if (selectedStylistIds.length === 0) {
      setEvents([]);
      setIsLoading(false);
      return;
    }

    try {
      setIsLoading(true);
      console.log("[Calendar] Fetching events:", {
        stylists: selectedStylistIds,
        start: start.toISOString(),
        end: end.toISOString(),
      });

      const response = await api.getCalendarEvents(
        selectedStylistIds,
        start.toISOString(),
        end.toISOString()
      );

      console.log("[Calendar] Received events:", response);
      console.log("[Calendar] Number of events:", response.events.length);

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

  // Ctrl+Wheel zoom on calendar
  useEffect(() => {
    const el = calendarCardRef.current;
    if (!el) return;

    const handleWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      setZoomLevel(prev => {
        const next = prev + (e.deltaY > 0 ? -1 : 1);
        return Math.max(0, Math.min(next, ZOOM_LEVELS.length - 1));
      });
    };

    el.addEventListener("wheel", handleWheel, { passive: false });
    return () => el.removeEventListener("wheel", handleWheel);
  }, []);

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

  // Expose refresh method via ref
  useImperativeHandle(ref, () => ({
    refresh: () => {
      if (calendarRef.current) {
        const calendarApi = calendarRef.current.getApi();
        const view = calendarApi.view;
        fetchEvents(view.activeStart, view.activeEnd || new Date());
      }
    },
  }), [fetchEvents]);

  // Switch calendar view when screen size changes
  useEffect(() => {
    const api = calendarRef.current?.getApi();
    if (!api) return;
    const currentView = api.view.type;
    if (isMobile && currentView === "timeGridWeek") {
      api.changeView("listWeek");
    } else if (!isMobile && currentView === "listWeek") {
      api.changeView("timeGridWeek");
    }
  }, [isMobile]);

  // Handle date set (when calendar view changes)
  const handleDatesSet = (arg: { start: Date; end: Date }) => {
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
    console.log("Event clicked:", info.event.id, props);

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

  // Handle single date/time click — opens CreateAppointmentModal
  const handleDateClick = (info: { date: Date; allDay: boolean }) => {
    if (info.allDay) return; // skip all-day header clicks

    if (selectedStylistIds.length === 0) {
      alert("Por favor selecciona al menos un estilista");
      return;
    }

    setSelectedDateForModal(info.date);
    setSelectedStartTimeForModal(info.date);
    setSelectedEndTimeForModal(null);
    setSelectedStylistForAppointmentModal(selectedStylistIds[0]);
    setIsAppointmentModalOpen(true);
  };

  // Handle drag-select — shows action choice dialog (cita vs bloqueo)
  const handleSelect = (info: { start: Date; end: Date; allDay: boolean }) => {
    if (info.allDay) return;
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
    setSelectedStylistForAppointmentModal(selectedStylistIds[0]);
    setIsAppointmentModalOpen(true);
    setPendingSelectInfo(null);
  };

  const handleSelectBlocking = () => {
    if (!pendingSelectInfo) return;
    setSelectedStylistForModal(selectedStylistIds[0]);
    setSelectedDate(pendingSelectInfo.start);
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
    setSelectedDate(new Date());
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

  return (
    <div className="space-y-4">
      {/* Header with controls */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        {isMobile ? (
          /* Mobile: filter button + icon-only action buttons */
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setIsFilterSheetOpen(true)}
              className="relative"
            >
              <Filter className="h-4 w-4" />
              {filterBadgeCount !== null && (
                <Badge
                  variant="destructive"
                  className="absolute -top-2 -right-2 h-5 w-5 flex items-center justify-center p-0 text-xs"
                >
                  {filterBadgeCount}
                </Badge>
              )}
            </Button>

            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleCreateBlockingEvent}
                disabled={selectedStylistIds.length === 0}
                title="Crear Bloqueo"
              >
                <Ban className="h-4 w-4" />
              </Button>
              <Button
                variant="default"
                size="sm"
                onClick={handleCreateAppointment}
                title="Nueva Cita"
              >
                <Plus className="h-4 w-4" />
              </Button>
            </div>
          </>
        ) : (
          /* Desktop: inline filters + labelled action buttons */
          <>
            <CalendarFilters
              stylists={stylists}
              selectedStylistIds={selectedStylistIds}
              stylistColors={stylistColors}
              onToggle={toggleStylist}
              onToggleAll={toggleAllStylists}
            />

            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleCreateBlockingEvent}
                disabled={selectedStylistIds.length === 0}
              >
                <Ban className="h-4 w-4 mr-1" />
                Crear Bloqueo
              </Button>
              <Button
                variant="default"
                size="sm"
                onClick={handleCreateAppointment}
              >
                <Plus className="h-4 w-4 mr-1" />
                Nueva Cita
              </Button>
            </div>
          </>
        )}
      </div>

      {/* Mobile filter Sheet */}
      {isMobile && (
        <Sheet open={isFilterSheetOpen} onOpenChange={setIsFilterSheetOpen}>
          <SheetContent side="left" className="w-64">
            <SheetHeader>
              <SheetTitle>Filtrar estilistas</SheetTitle>
            </SheetHeader>
            <CalendarFilters
              stylists={stylists}
              selectedStylistIds={selectedStylistIds}
              stylistColors={stylistColors}
              onToggle={toggleStylist}
              onToggleAll={toggleAllStylists}
            />
          </SheetContent>
        </Sheet>
      )}

      {/* Legend — hidden on mobile */}
      {!isMobile && <CalendarLegend stylistColors={stylistColors} stylists={stylists} />}

      {/* Calendar */}
      <Card ref={calendarCardRef} className="p-4 relative">
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
              : { left: "prev,next today", center: "title", right: "timeGridDay,timeGridWeek,dayGridMonth,listWeek" }
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
          height="auto"
          slotDuration={ZOOM_LEVELS[zoomLevel].slot}
          slotLabelInterval={ZOOM_LEVELS[zoomLevel].labelInterval}
          nowIndicator={true}
          eventTimeFormat={{
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          }}
          eventClassNames={(arg) => {
            const type = arg.event.extendedProps.type;
            const status = arg.event.extendedProps.status;
            if (type !== "appointment" || !status) return [];
            const config = STATUS_MAP[status as keyof typeof STATUS_MAP];
            return config ? [config.cssClass] : [];
          }}
        />
        {/* Zoom controls */}
        {!isMobile && (
          <div className="absolute bottom-3 right-3 flex items-center gap-1 bg-background/90 border rounded-md px-1.5 py-1 shadow-sm z-10">
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => setZoomLevel(prev => Math.max(0, prev - 1))}
              disabled={zoomLevel === 0}
            >
              <ZoomOut className="h-3.5 w-3.5" />
            </Button>
            <span className="text-xs text-muted-foreground w-12 text-center font-mono">
              {ZOOM_LEVELS[zoomLevel].label}
            </span>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => setZoomLevel(prev => Math.min(ZOOM_LEVELS.length - 1, prev + 1))}
              disabled={zoomLevel === ZOOM_LEVELS.length - 1}
            >
              <ZoomIn className="h-3.5 w-3.5" />
            </Button>
          </div>
        )}
      </Card>

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
        selectedDate={selectedDate}
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
