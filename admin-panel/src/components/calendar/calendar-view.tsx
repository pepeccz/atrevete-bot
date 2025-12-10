"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import esLocale from "@fullcalendar/core/locales/es";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Plus, Calendar, Ban } from "lucide-react";
import api from "@/lib/api";
import { CreateBlockingEventModal } from "./create-blocking-event-modal";

// Color palette for stylists (8 distinct colors)
const STYLIST_COLORS = [
  { bg: "#7C3AED", border: "#6D28D9", name: "Violet" },
  { bg: "#2563EB", border: "#1D4ED8", name: "Blue" },
  { bg: "#059669", border: "#047857", name: "Emerald" },
  { bg: "#DC2626", border: "#B91C1C", name: "Red" },
  { bg: "#D97706", border: "#B45309", name: "Amber" },
  { bg: "#7C2D12", border: "#6B2610", name: "Brown" },
  { bg: "#DB2777", border: "#BE185D", name: "Pink" },
  { bg: "#0891B2", border: "#0E7490", name: "Cyan" },
];

// Blocking event colors (darker/muted)
const BLOCKING_EVENT_COLORS = {
  vacation: { bg: "#EF4444", border: "#DC2626" }, // Red
  meeting: { bg: "#F97316", border: "#EA580C" }, // Orange
  break: { bg: "#22C55E", border: "#16A34A" }, // Green
  general: { bg: "#6B7280", border: "#4B5563" }, // Gray
  personal: { bg: "#EC4899", border: "#DB2777" }, // Pink
};

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
  };
}

interface Stylist {
  id: string;
  name: string;
  category: string;
  is_active: boolean;
}

export function CalendarView() {
  const router = useRouter();
  const calendarRef = useRef<FullCalendar>(null);
  const [selectedStylistIds, setSelectedStylistIds] = useState<string[]>([]);
  const [stylists, setStylists] = useState<Stylist[]>([]);
  const [stylistColors, setStylistColors] = useState<Record<string, { bg: string; border: string }>>({});
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  // Modal states
  const [isBlockingModalOpen, setIsBlockingModalOpen] = useState(false);
  const [selectedDate, setSelectedDate] = useState<Date | null>(null);
  const [selectedStartTime, setSelectedStartTime] = useState<Date | null>(null);
  const [selectedEndTime, setSelectedEndTime] = useState<Date | null>(null);
  const [selectedStylistForModal, setSelectedStylistForModal] = useState<string | null>(null);

  // Assign colors to stylists
  const assignStylistColors = useCallback((stylistList: Stylist[]) => {
    const colors: Record<string, { bg: string; border: string }> = {};
    stylistList.forEach((stylist, index) => {
      const color = STYLIST_COLORS[index % STYLIST_COLORS.length];
      colors[stylist.id] = { bg: color.bg, border: color.border };
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
        // Select all stylists by default
        if (response.items.length > 0) {
          setSelectedStylistIds(response.items.map(s => s.id));
        }
      } catch (error) {
        console.error("Error fetching stylists:", error);
      }
    }
    fetchStylists();
  }, [assignStylistColors]);

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

      // Apply colors based on stylist and event type
      const coloredEvents = response.events.map(event => {
        let bgColor = event.backgroundColor;
        let borderColor = event.borderColor;

        if (event.extendedProps.type === "blocking_event") {
          // Use blocking event colors
          const eventType = event.extendedProps.event_type || "general";
          const blockColors = BLOCKING_EVENT_COLORS[eventType as keyof typeof BLOCKING_EVENT_COLORS] || BLOCKING_EVENT_COLORS.general;
          bgColor = blockColors.bg;
          borderColor = blockColors.border;
        } else {
          // Use stylist colors for appointments
          const stylistColor = stylistColors[event.extendedProps.stylist_id];
          if (stylistColor) {
            bgColor = stylistColor.bg;
            borderColor = stylistColor.border;
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

  // Handle date set (when calendar view changes)
  const handleDatesSet = (arg: { start: Date; end: Date }) => {
    fetchEvents(arg.start, arg.end);
  };

  // Handle event click
  const handleEventClick = (info: { event: { id: string; extendedProps: Record<string, unknown> } }) => {
    const props = info.event.extendedProps;
    console.log("Event clicked:", info.event.id, props);

    if (props.type === "blocking_event") {
      // TODO: Open blocking event details/delete modal
      alert(`Evento de bloqueo: ${props.event_type}\n${props.description || "Sin descripción"}`);
    } else {
      // TODO: Open appointment details modal
      alert(`Cita: ${props.status}\nNotas: ${props.notes || "Sin notas"}`);
    }
  };

  // Handle drag-select (for creating blocking events)
  const handleSelect = (info: { start: Date; end: Date; allDay: boolean }) => {
    if (selectedStylistIds.length === 0) {
      alert("Por favor selecciona al menos un estilista para crear un bloqueo");
      return;
    }

    // Save start and end times from drag selection
    setSelectedStartTime(info.start);
    setSelectedEndTime(info.end);
    setSelectedDate(info.start);

    // If only one stylist selected, use that one
    if (selectedStylistIds.length === 1) {
      setSelectedStylistForModal(selectedStylistIds[0]);
    } else {
      // Default to first selected stylist (modal will allow changing)
      setSelectedStylistForModal(selectedStylistIds[0]);
    }

    setIsBlockingModalOpen(true);
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
        {/* Stylist Multi-Select */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Label className="text-sm font-medium">Estilistas:</Label>
            <Button
              variant="ghost"
              size="sm"
              onClick={toggleAllStylists}
              className="text-xs h-6 px-2"
            >
              {selectedStylistIds.length === stylists.length ? "Ninguno" : "Todos"}
            </Button>
          </div>

          <div className="flex flex-wrap gap-3">
            {stylists.map((stylist) => {
              const color = stylistColors[stylist.id];
              const isSelected = selectedStylistIds.includes(stylist.id);

              return (
                <div key={stylist.id} className="flex items-center gap-2">
                  <Checkbox
                    id={`stylist-${stylist.id}`}
                    checked={isSelected}
                    onCheckedChange={() => toggleStylist(stylist.id)}
                    className="border-2"
                    style={{
                      borderColor: color?.bg || "#888",
                      backgroundColor: isSelected ? color?.bg : "transparent",
                    }}
                  />
                  <Label
                    htmlFor={`stylist-${stylist.id}`}
                    className="text-sm cursor-pointer flex items-center gap-1"
                  >
                    <span
                      className="w-3 h-3 rounded-full inline-block"
                      style={{ backgroundColor: color?.bg || "#888" }}
                    />
                    {stylist.name}
                  </Label>
                </div>
              );
            })}
          </div>
        </div>

        {/* Action Buttons */}
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
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        <span className="font-medium">Tipos de evento:</span>
        <div className="flex items-center gap-1">
          <span className="w-3 h-3 rounded" style={{ backgroundColor: "#7C3AED" }} />
          <span>Citas (color por estilista)</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="w-3 h-3 rounded" style={{ backgroundColor: BLOCKING_EVENT_COLORS.vacation.bg }} />
          <span>Vacaciones</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="w-3 h-3 rounded" style={{ backgroundColor: BLOCKING_EVENT_COLORS.meeting.bg }} />
          <span>Reuniones</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="w-3 h-3 rounded" style={{ backgroundColor: BLOCKING_EVENT_COLORS.break.bg }} />
          <span>Descansos</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="w-3 h-3 rounded" style={{ backgroundColor: BLOCKING_EVENT_COLORS.general.bg }} />
          <span>Bloqueos</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="w-3 h-3 rounded" style={{ backgroundColor: BLOCKING_EVENT_COLORS.personal.bg }} />
          <span>Asunto Propio</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="w-3 h-3 rounded" style={{ backgroundColor: "#991B1B" }} />
          <span>Festivos</span>
        </div>
      </div>

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
          plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
          initialView="timeGridWeek"
          locale={esLocale}
          timeZone="Europe/Madrid"
          headerToolbar={{
            left: "prev,next today",
            center: "title",
            right: "timeGridDay,timeGridWeek,dayGridMonth",
          }}
          buttonText={{
            today: "Hoy",
            day: "Dia",
            week: "Semana",
            month: "Mes",
          }}
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
          select={handleSelect}
          height="auto"
          slotDuration="00:15:00"
          slotLabelInterval="01:00"
          nowIndicator={true}
          eventTimeFormat={{
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          }}
        />
      </Card>

      {/* Create Blocking Event Modal */}
      {selectedStylistForModal && (
        <CreateBlockingEventModal
          isOpen={isBlockingModalOpen}
          onClose={() => setIsBlockingModalOpen(false)}
          stylistId={selectedStylistForModal}
          stylistName={getStylistName(selectedStylistForModal)}
          selectedDate={selectedDate}
          selectedStartTime={selectedStartTime}
          selectedEndTime={selectedEndTime}
          stylists={stylists.filter(s => selectedStylistIds.includes(s.id))}
          onSuccess={handleEventCreated}
        />
      )}
    </div>
  );
}
