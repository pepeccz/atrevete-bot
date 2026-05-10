"use client";

import { useState, useEffect, useRef, useCallback, type CSSProperties } from "react";
import { DateTime } from "luxon";
import { StylistColumnHeader } from "./stylist-column-header";
import { ApptCard } from "./appt-card";
import { NowLine } from "./now-line";
import { splitOverlapping, positionForAppointment } from "@/lib/calendar-layout";
import { minutesFromMidnight, currentMinuteOfDay } from "@/lib/calendar-time";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

const TZ = "Europe/Madrid";

/** Minimal CalendarEvent shape needed by day view */
export interface DayViewEvent {
  id: string;
  start: string; // ISO 8601
  end: string;   // ISO 8601
  extendedProps: {
    appointment_id?: string;
    customer_id?: string;
    stylist_id?: string;
    status?: string;
    duration_minutes?: number;
    notes?: string | null;
    event_type?: string;
    type: "appointment" | "blocking_event" | "holiday";
    recurring_series_id?: string | null;
    occurrence_index?: number | null;
    customer_name?: string;
    service_names?: string[];
  };
}

export interface DayViewStylist {
  id: string;
  name: string;
  color: string;
}

interface CalendarDayViewProps {
  /** Appointments and events for the current day */
  appointments: DayViewEvent[];
  /** Active stylists to show as columns */
  stylists: DayViewStylist[];
  /** Selected date as a Luxon DateTime */
  date: DateTime;
  /** Grid start hour (e.g. 9) */
  gridStartHour?: number;
  /** Grid end hour (e.g. 21) */
  gridEndHour?: number;
  /** Slot size in minutes (drives zoom) */
  slotMin?: number;
  /** Pixel height per slot */
  slotPx?: number;
  onAppointmentClick: (id: string) => void;
  onEmptySlotClick: (stylistId: string, datetime: string) => void;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const GUTTER_WIDTH = 80; // px
const HEADER_HEIGHT = 84; // px — matches StylistColumnHeader

// ---------------------------------------------------------------------------
// Time gutter helpers
// ---------------------------------------------------------------------------

function buildHourLabels(startHour: number, endHour: number): number[] {
  const hours: number[] = [];
  for (let h = startHour; h <= endHour; h++) {
    hours.push(h);
  }
  return hours;
}

function formatHour(h: number): string {
  return `${String(h).padStart(2, "0")}:00`;
}

// ---------------------------------------------------------------------------
// Metric helpers
// ---------------------------------------------------------------------------

function computeMetrics(
  appointments: DayViewEvent[],
  stylistId: string,
  businessMinutes: number
): { appointmentsCount: number; totalMinutes: number; utilizationPct: number } {
  const stylistAppts = appointments.filter(
    a => a.extendedProps.stylist_id === stylistId
      && a.extendedProps.type === "appointment"
      && a.extendedProps.status !== "cancelled"
      && a.extendedProps.status !== "no_show"
  );
  const totalMinutes = stylistAppts.reduce(
    (acc, a) => acc + (a.extendedProps.duration_minutes ?? 0),
    0
  );
  const utilizationPct = businessMinutes > 0
    ? Math.round((totalMinutes / businessMinutes) * 100)
    : 0;
  return { appointmentsCount: stylistAppts.length, totalMinutes, utilizationPct };
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CalendarDayView({
  appointments,
  stylists,
  date,
  gridStartHour = 9,
  gridEndHour = 21,
  slotMin = 15,
  slotPx = 24,
  onAppointmentClick,
  onEmptySlotClick,
}: CalendarDayViewProps) {
  const pxPerMin = slotPx / slotMin;
  const gridStartMin = gridStartHour * 60;
  const gridEndMin = gridEndHour * 60;
  const businessMinutes = gridEndMin - gridStartMin;
  const totalGridHeight = businessMinutes * pxPerMin;

  // Current minute of day for NowLine
  const [nowMinute, setNowMinute] = useState<number>(() => currentMinuteOfDay(TZ));

  useEffect(() => {
    const id = setInterval(() => setNowMinute(currentMinuteOfDay(TZ)), 60_000);
    return () => clearInterval(id);
  }, []);

  const isNowVisible = nowMinute >= gridStartMin && nowMinute <= gridEndMin;

  // Group appointments by stylist
  const appointmentsByStylist = useCallback(
    (stylistId: string) =>
      appointments.filter(
        a => a.extendedProps.stylist_id === stylistId
          && a.extendedProps.type === "appointment"
      ),
    [appointments]
  );

  // Handle empty slot click
  const handleColumnClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>, stylistId: string, columnEl: HTMLDivElement) => {
      // If click target is an appointment card, ignore (the card handles its own click)
      if ((e.target as HTMLElement).closest("[data-appt-card]")) return;

      const rect = columnEl.getBoundingClientRect();
      const clickY = e.clientY - rect.top;
      const clickedMinutes = gridStartMin + clickY / pxPerMin;
      const roundedMinutes = Math.round(clickedMinutes / slotMin) * slotMin;
      const dt = date.set({
        hour: Math.floor(roundedMinutes / 60),
        minute: roundedMinutes % 60,
        second: 0,
        millisecond: 0,
      });
      onEmptySlotClick(stylistId, dt.toISO() ?? "");
    },
    [gridStartMin, pxPerMin, slotMin, date, onEmptySlotClick]
  );

  // Column ref map for click coordinate calculation
  const columnRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  const hourLabels = buildHourLabels(gridStartHour, gridEndHour);

  // Aggregate metrics for gold pill (passed up via data attributes — parent reads if needed)
  const allAppts = appointments.filter(
    a => a.extendedProps.type === "appointment"
      && a.extendedProps.status !== "cancelled"
      && a.extendedProps.status !== "no_show"
  );
  const totalBookedMin = allAppts.reduce(
    (acc, a) => acc + (a.extendedProps.duration_minutes ?? 0), 0
  );
  const totalCapacityMin = businessMinutes * stylists.length;
  const overallPct = totalCapacityMin > 0
    ? Math.round((totalBookedMin / totalCapacityMin) * 100)
    : 0;

  if (stylists.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-24 text-center bg-white rounded-[14px] border border-line">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="h-8 w-8 text-ink-faint"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
          <circle cx="9" cy="7" r="4" />
          <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
          <path d="M16 3.13a4 4 0 0 1 0 7.75" />
        </svg>
        <span className="text-[13px] text-ink-mute">
          Activá al menos un estilista para ver citas
        </span>
      </div>
    );
  }

  const columnCount = stylists.length;

  return (
    <div
      className="rounded-[14px] border border-line bg-white overflow-hidden"
      data-appt-count={allAppts.length}
      data-occupancy-pct={overallPct}
    >
      {/* ------------------------------------------------------------------ */}
      {/* CSS grid: gutter | col1 | col2 | ... */}
      {/* Row 1: headers (84px) */}
      {/* Row 2: body (scrollable) */}
      {/* ------------------------------------------------------------------ */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: `${GUTTER_WIDTH}px repeat(${columnCount}, minmax(140px, 1fr))`,
        } as CSSProperties}
      >
        {/* ---- Header row ---- */}
        {/* Gutter header corner */}
        <div
          className="border-b border-r border-line bg-white"
          style={{ height: `${HEADER_HEIGHT}px`, position: "sticky", top: 0, zIndex: 6 } as CSSProperties}
        />
        {/* Stylist column headers */}
        {stylists.map(s => (
          <StylistColumnHeader
            key={s.id}
            stylist={s}
            metrics={computeMetrics(appointments, s.id, businessMinutes)}
          />
        ))}
      </div>

      {/* ---- Scrollable body ---- */}
      <div
        className="overflow-y-auto"
        style={{ maxHeight: "calc(100vh - 280px)" }}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: `${GUTTER_WIDTH}px repeat(${columnCount}, minmax(140px, 1fr))`,
            position: "relative",
          } as CSSProperties}
        >
          {/* Time gutter */}
          <div
            className="border-r border-line bg-white"
            style={{ height: `${totalGridHeight}px`, position: "relative" } as CSSProperties}
          >
            {hourLabels.map(h => {
              const top = (h * 60 - gridStartMin) * pxPerMin;
              return (
                <div
                  key={h}
                  className="absolute right-0 pr-2 text-[11px] text-ink-mute tabular-nums font-medium select-none"
                  style={{ top: `${top}px`, transform: "translateY(-50%)" } as CSSProperties}
                >
                  {formatHour(h)}
                </div>
              );
            })}
          </div>

          {/* Per-stylist columns */}
          {stylists.map(s => {
            const stylistAppts = appointmentsByStylist(s.id);

            // Prepare items for overlap layout
            const overlapItems = stylistAppts.map(a => ({
              id: a.id,
              startMin: minutesFromMidnight(a.start, TZ),
              endMin: minutesFromMidnight(a.end, TZ),
            }));
            const placed = splitOverlapping(overlapItems);
            const placementMap = new Map(placed.map(p => [p.id, p]));

            return (
              <div
                key={s.id}
                ref={el => {
                  if (el) columnRefs.current.set(s.id, el);
                  else columnRefs.current.delete(s.id);
                }}
                className="border-r border-line"
                style={{ height: `${totalGridHeight}px`, position: "relative", cursor: "pointer" } as CSSProperties}
                onClick={e => {
                  const colEl = columnRefs.current.get(s.id);
                  if (colEl) handleColumnClick(e, s.id, colEl);
                }}
              >
                {/* Grid lines */}
                {hourLabels.map(h => {
                  const top = (h * 60 - gridStartMin) * pxPerMin;
                  return (
                    <div
                      key={`hour-${h}`}
                      className="absolute left-0 right-0 pointer-events-none"
                      style={{
                        top: `${top}px`,
                        borderTop: "1px solid hsl(var(--line))",
                      } as CSSProperties}
                    />
                  );
                })}
                {/* Half-hour dashed lines */}
                {hourLabels.slice(0, -1).map(h => {
                  const top = (h * 60 + 30 - gridStartMin) * pxPerMin;
                  return (
                    <div
                      key={`half-${h}`}
                      className="absolute left-0 right-0 pointer-events-none"
                      style={{
                        top: `${top}px`,
                        borderTop: "1px dashed hsl(var(--line-soft))",
                      } as CSSProperties}
                    />
                  );
                })}

                {/* Appointment cards */}
                {stylistAppts.map(appt => {
                  const startMin = minutesFromMidnight(appt.start, TZ);
                  const dur = appt.extendedProps.duration_minutes
                    ?? Math.round((new Date(appt.end).getTime() - new Date(appt.start).getTime()) / 60000);
                  const pos = positionForAppointment(startMin, dur, gridStartMin, slotMin, slotPx);
                  const placement = placementMap.get(appt.id);
                  const totalCols = placement?.totalSubColumns ?? 1;
                  const subCol = placement?.subColumn ?? 0;
                  const widthPct = 100 / totalCols;
                  const leftPct = subCol * widthPct;

                  return (
                    <div
                      key={appt.id}
                      data-appt-card="true"
                      style={{
                        position: "absolute",
                        top: `${pos.top}px`,
                        height: `${pos.height}px`,
                        left: `${leftPct}%`,
                        width: `${widthPct}%`,
                        padding: "2px",
                        zIndex: 2,
                        boxSizing: "border-box",
                      } as CSSProperties}
                      onClick={e => {
                        e.stopPropagation();
                        onAppointmentClick(appt.extendedProps.appointment_id ?? appt.id);
                      }}
                    >
                      <ApptCard
                        extendedProps={appt.extendedProps as Parameters<typeof ApptCard>[0]["extendedProps"]}
                        stylistColor={s.color}
                        start={new Date(appt.start)}
                        end={new Date(appt.end)}
                        mode="day"
                        style={{ height: "100%" }}
                      />
                    </div>
                  );
                })}
              </div>
            );
          })}

          {/* Now line — NowLine positions itself absolutely using topOffset=0 + gridStartMin */}
          {isNowVisible && (
            <NowLine
              pixelsPerMinute={pxPerMin}
              gutterWidth={GUTTER_WIDTH}
              topOffset={0}
              businessStartMinute={gridStartMin}
              mode="gutter-left"
            />
          )}
        </div>
      </div>
    </div>
  );
}
