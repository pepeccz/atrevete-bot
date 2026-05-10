"use client";

import { ChevronLeft, ChevronRight, Ban, Plus, Minus } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { CalendarView, ZoomLevel } from "./use-calendar-state";

interface CalendarToolbarProps {
  currentDate: Date;
  view: CalendarView;
  zoomLevel: ZoomLevel;
  onNav: (dir: "prev" | "next" | "today") => void;
  onViewChange: (v: CalendarView) => void;
  onZoomChange: (z: ZoomLevel) => void;
  onCreate: () => void;
  onBlock: () => void;
  /** Optional gold pill rendered between date label and view switcher (for day view stats) */
  rightPill?: React.ReactNode;
}

const ZOOM_LEVELS: ZoomLevel[] = ["5min", "15min", "30min", "1h"];

function formatDateRange(date: Date, view: CalendarView): string {
  if (view === "day") {
    return date.toLocaleDateString("es-ES", {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric",
    });
  }

  if (view === "month") {
    return date.toLocaleDateString("es-ES", { month: "long", year: "numeric" });
  }

  // Week view: Mon – Sun of current week
  const dow = date.getDay(); // 0=Sun
  const monday = new Date(date);
  monday.setDate(date.getDate() - ((dow + 6) % 7));
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);

  const monDay = monday.getDate();
  const sunDay = sunday.getDate();
  const monMonth = monday.toLocaleDateString("es-ES", { month: "long" });
  const sunMonth = sunday.toLocaleDateString("es-ES", { month: "long" });
  const year = sunday.getFullYear();

  if (monMonth === sunMonth) {
    return `${monDay} — ${sunDay} ${monMonth} ${year}`;
  }
  return `${monDay} ${monMonth} — ${sunDay} ${sunMonth} ${year}`;
}

function zoomDown(current: ZoomLevel): ZoomLevel {
  const idx = ZOOM_LEVELS.indexOf(current);
  return ZOOM_LEVELS[Math.max(0, idx - 1)];
}

function zoomUp(current: ZoomLevel): ZoomLevel {
  const idx = ZOOM_LEVELS.indexOf(current);
  return ZOOM_LEVELS[Math.min(ZOOM_LEVELS.length - 1, idx + 1)];
}

export function CalendarToolbar({
  currentDate,
  view,
  zoomLevel,
  onNav,
  onViewChange,
  onZoomChange,
  onCreate,
  onBlock,
  rightPill,
}: CalendarToolbarProps) {
  const dateLabel = formatDateRange(currentDate, view);

  return (
    <div className="flex flex-wrap items-center gap-3 px-4 py-3 border-b border-line bg-white rounded-t-[14px]">
      {/* Zone 1 — Navigation */}
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => onNav("prev")}
          aria-label="Semana anterior"
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => onNav("next")}
          aria-label="Semana siguiente"
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 px-3 text-sm font-medium text-ink-soft hover:text-ink"
          onClick={() => onNav("today")}
        >
          Hoy
        </Button>
      </div>

      {/* Divider 1 */}
      <span className="w-px h-6 bg-line flex-shrink-0" />

      {/* Zone 2 — Date label */}
      <span className="text-sm font-semibold text-ink font-jakarta tabular-nums select-none">
        {dateLabel}
      </span>

      {rightPill && <>{rightPill}</>}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Zone 3 — View segmented control */}
      <div className="flex items-center border border-line rounded-[10px] overflow-hidden">
        {(["day", "week", "month"] as CalendarView[]).map((v) => (
          <button
            key={v}
            onClick={() => onViewChange(v)}
            className={[
              "px-3 py-1.5 text-xs font-semibold transition-colors",
              view === v
                ? "bg-gold-soft text-gold-dark"
                : "text-ink-mute hover:text-ink hover:bg-surface-hover",
            ].join(" ")}
          >
            {v === "day" ? "Día" : v === "week" ? "Semana" : "Mes"}
          </button>
        ))}
      </div>

      {/* Divider 2 */}
      <span className="w-px h-6 bg-line flex-shrink-0" />

      {/* Zone 4 — Zoom cluster */}
      <div className="flex items-center gap-0.5 border border-line rounded-[10px] px-2 py-1">
        <Button
          variant="ghost"
          size="icon"
          className="h-5 w-5"
          onClick={() => onZoomChange(zoomDown(zoomLevel))}
          disabled={zoomLevel === ZOOM_LEVELS[0]}
          aria-label="Reducir zoom"
        >
          <Minus className="h-3 w-3" />
        </Button>
        <span className="text-xs font-mono text-ink-mute w-10 text-center select-none">
          {zoomLevel}
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-5 w-5"
          onClick={() => onZoomChange(zoomUp(zoomLevel))}
          disabled={zoomLevel === ZOOM_LEVELS[ZOOM_LEVELS.length - 1]}
          aria-label="Aumentar zoom"
        >
          <Plus className="h-3 w-3" />
        </Button>
      </div>

      {/* Divider 3 */}
      <span className="w-px h-6 bg-line flex-shrink-0" />

      {/* Zone 5 — Actions */}
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          className="h-8 px-3 text-sm"
          onClick={onBlock}
        >
          <Ban className="h-3.5 w-3.5 mr-1.5" />
          Bloquear
        </Button>
        <Button
          variant="default"
          size="sm"
          className="h-8 px-3 text-sm"
          onClick={onCreate}
        >
          <Plus className="h-3.5 w-3.5 mr-1.5" />
          Nueva cita
        </Button>
      </div>
    </div>
  );
}
