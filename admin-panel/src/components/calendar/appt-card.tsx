"use client";

import type { CSSProperties } from "react";
import { Repeat } from "lucide-react";
import { deriveStylistPalette } from "@/lib/stylist-colors";
import { formatTimeRange } from "@/lib/calendar-time";
import { getEventTypeMeta } from "./event-types";

export interface CalendarEventExtended {
  appointment_id?: string;
  blocking_event_id?: string;
  holiday_id?: string;
  customer_id?: string;
  stylist_id?: string;
  status?: string;
  duration_minutes?: number;
  notes?: string | null;
  description?: string | null;
  title?: string;
  event_type?: string;
  type: "appointment" | "blocking_event" | "holiday";
  recurring_series_id?: string | null;
  occurrence_index?: number | null;
  customer_name?: string;
  service_names?: string[];
}

interface ApptCardProps {
  /** The event extended props from FullCalendar (or raw event data in day mode) */
  extendedProps: CalendarEventExtended;
  /** Raw hex color of the stylist */
  stylistColor: string;
  /** Start time as Date */
  start: Date | null;
  /** End time as Date */
  end: Date | null;
  /** week mode: constrained inside FC, day mode: absolutely positioned */
  mode?: "week" | "day";
  style?: CSSProperties;
  onClick?: () => void;
}

function formatTime(date: Date | null): string {
  if (!date) return "";
  return date.toLocaleTimeString("es-ES", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

const STATUS_DOT_COLORS: Record<string, string> = {
  confirmed: "hsl(var(--status-confirm))",
  pending: "hsl(var(--status-pending))",
  cancelled: "hsl(var(--status-cancel))",
  completed: "hsl(var(--status-done))",
  no_show: "hsl(var(--status-cancel))",
};

export function ApptCard({
  extendedProps,
  stylistColor,
  start,
  end,
  mode = "week",
  style,
  onClick,
}: ApptCardProps) {
  const isBlocking = extendedProps.type === "blocking_event";
  const palette = deriveStylistPalette(stylistColor);

  if (isBlocking) {
    return <BlockingCard
      extendedProps={extendedProps}
      palette={palette}
      start={start}
      end={end}
      mode={mode}
      style={style}
      onClick={onClick}
    />;
  }

  const status = extendedProps.status || "pending";
  const isCancelled = status === "cancelled" || status === "no_show";
  const duration = extendedProps.duration_minutes || 0;
  const dotColor = STATUS_DOT_COLORS[status] || STATUS_DOT_COLORS.pending;

  const showService = mode === "day" || duration >= 60;
  const serviceNames = extendedProps.service_names || [];
  const serviceText = serviceNames.join(", ");
  const customerName = extendedProps.customer_name || extendedProps.description || "";

  return (
    <div
      onClick={onClick}
      className="overflow-hidden rounded-[8px] h-full w-full cursor-pointer select-none transition-opacity hover:opacity-90"
      style={{
        backgroundColor: isCancelled ? "#ffffff" : palette.soft,
        borderLeft: `3px solid ${palette.solid}`,
        opacity: isCancelled ? 0.55 : 1,
        boxShadow: isCancelled ? `inset 0 0 0 1px hsl(var(--line))` : "none",
        padding: "6px 8px",
        ...style,
      }}
    >
      {/* Line 1: status dot · time (range in day mode, single in week) · duration */}
      <div
        className="flex items-center gap-1.5 text-[11px] font-bold tabular-nums"
        style={{ color: palette.text }}
      >
        <span
          className="w-1.5 h-1.5 rounded-full flex-shrink-0"
          style={{ backgroundColor: dotColor }}
        />
        {mode === "day" && start && end ? (
          <span>{formatTimeRange(start.toISOString(), end.toISOString(), "Europe/Madrid")}</span>
        ) : (
          <>
            <span>{formatTime(start)}</span>
            {duration > 0 && (
              <span className="ml-auto text-[10px] font-medium opacity-70">
                {formatDuration(duration)}
              </span>
            )}
          </>
        )}
      </div>

      {/* Line 2: customer name */}
      <div
        className="text-[12px] font-bold leading-tight mt-0.5 truncate"
        style={{
          color: "hsl(var(--ink))",
          textDecoration: isCancelled ? "line-through" : "none",
        }}
      >
        {customerName}
      </div>

      {/* Line 3: service (if long enough) */}
      {showService && serviceText && (
        <div
          className="text-[11px] leading-tight mt-0.5"
          style={{
            color: "hsl(var(--ink-mute))",
            overflow: "hidden",
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical" as const,
          } as CSSProperties}
        >
          {serviceText}
        </div>
      )}
    </div>
  );
}

interface BlockingCardProps {
  extendedProps: CalendarEventExtended;
  palette: ReturnType<typeof deriveStylistPalette>;
  start: Date | null;
  end: Date | null;
  mode: "week" | "day";
  style?: CSSProperties;
  onClick?: () => void;
}

function BlockingCard({ extendedProps, palette, start, end, mode, style, onClick }: BlockingCardProps) {
  const meta = getEventTypeMeta(extendedProps.event_type ?? "general");
  const label =
    extendedProps.title ||
    extendedProps.description ||
    meta.label ||
    "Bloqueo";
  const TypeIcon = meta.Icon;

  return (
    <div
      onClick={onClick}
      className="relative overflow-hidden rounded-[8px] h-full w-full cursor-pointer select-none transition-opacity hover:opacity-90"
      style={{
        // Diagonal gray hatching — visually distinct from the soft pastel of an appointment.
        backgroundImage: `repeating-linear-gradient(135deg, hsl(var(--surface-muted)) 0px, hsl(var(--surface-muted)) 6px, hsl(var(--line-soft)) 6px, hsl(var(--line-soft)) 12px)`,
        borderLeft: `3px dashed ${palette.solid}`,
        padding: "6px 8px",
        ...style,
      }}
      aria-label={`Bloqueo: ${label}`}
    >
      {extendedProps.recurring_series_id && (
        <Repeat
          className="absolute top-1 right-1 h-3 w-3 opacity-70"
          style={{ color: "hsl(var(--ink-soft))" }}
          aria-label="Bloqueo recurrente"
        />
      )}
      <div
        className="flex items-center gap-1.5 text-[11px] font-bold tabular-nums uppercase tracking-wide"
        style={{ color: "hsl(var(--ink-soft))" }}
      >
        <TypeIcon className="h-3 w-3 flex-shrink-0" />
        {mode === "day" && start && end ? (
          <span>{formatTimeRange(start.toISOString(), end.toISOString(), "Europe/Madrid")}</span>
        ) : (
          <span>{formatTime(start)}</span>
        )}
      </div>
      <div
        className="text-[12px] font-semibold leading-tight mt-0.5 truncate"
        style={{ color: "hsl(var(--ink-soft))" }}
      >
        {label}
      </div>
    </div>
  );
}

