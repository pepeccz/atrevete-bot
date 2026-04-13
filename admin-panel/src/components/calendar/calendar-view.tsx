"use client";

import { useState, useEffect, useRef, useCallback, forwardRef, useImperativeHandle } from "react";
import { useRouter } from "next/navigation";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import listPlugin from "@fullcalendar/list";
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
import { Plus, Calendar, Ban, Filter } from "lucide-react";
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

interface CalendarEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  backgroundColor: string;
  borderColor: string;
  allDay?: boolean;
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

export const CalendarView = forwardRef<CalendarViewRef>(function CalendarView(_props, ref) {
  const router = useRouter();
  const calendarRef = useRef<FullCalendar>(null);
  const [selectedStylistIds, setSelectedStylistIds] = useState<string[]>([]);
  const [stylists, setStylists] = useState<Stylist[]>([]);
  const [stylistColors, setStylistColors] = useState<Record<string, { bg: string; border: string }>>({});
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [isLoading, setIsLoading] = useState(true);

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

        return {
          ...event,
          backgroundColor: bgColor,
          borderColor: borderColor,
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
        handleEventCreated(); // Refresh calendar
      } else {
        // Edit action
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

  // Handle creating appointment - redirect to wizard
  const handleCreateAppointment = () => {
    router.push('/appointments?new=true');
  };

  // Handle event creation success
  const handleEventCreated = () => {
    const calendarApi = calendarRef.current?.getApi();
    if (calendarApi) {
      const { start, end } = calendarApi.view.activeStart
        ? {
            start: calendarApi.view.activeStart,
            end: calendarApi.view.activeEnd || new Date(),
          }
        : { start: new Date(), end: new Date() };
      fetchEvents(start, end);
    }
  };

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
      <Card className="p-4 relative">
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
          plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin, listPlugin]}
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
          slotDuration="00:15:00"
          slotLabelInterval="01:00"
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
        onSuccess={handleEventCreated}
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
        onSuccess={handleEventCreated}
        editScope={pendingEditScope}
        overwriteExceptions={pendingOverwriteExceptions}
      />

      {/* Series Edit Dialog (for recurring events) */}
      {seriesInfo && pendingSeriesEvent && (
        <SeriesEditDialog
          isOpen={isSeriesDialogOpen}
          onClose={() => {
            setIsSeriesDialogOpen(false);
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

      {/* Appointment Popover (CAL-06) */}
      <AppointmentPopover
        open={popoverState.open}
        anchorEl={popoverState.anchorEl}
        data={popoverState.data}
        onClose={() => setPopoverState({ open: false, anchorEl: null, data: null })}
        onCancelSuccess={handleEventCreated}
        onNavigate={(appointmentId) => {
          setPopoverState({ open: false, anchorEl: null, data: null });
          router.push(`/appointments/${appointmentId}`);
        }}
      />
    </div>
  );
});
