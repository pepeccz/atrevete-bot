"use client";

/**
 * NowLine — manual absolute-positioned now indicator.
 *
 * Used in day view (greenfield grid). In week view we rely on
 * FullCalendar's nowIndicator + CSS overrides in calendar-styles.css.
 *
 * Props:
 *   minuteOfDay   - current minute of day (0-1439)
 *   pixelsPerMinute - px height per minute in the time grid
 *   gutterWidth   - px width of the time gutter column (default 80)
 *   topOffset     - px offset for the grid body top (header height)
 *   mode          - 'gutter-left' | 'gutter-right' — where the time pin appears
 */

import { useState, useEffect } from "react";

interface NowLineProps {
  pixelsPerMinute: number;
  gutterWidth?: number;
  topOffset?: number;
  businessStartMinute?: number;
  mode?: "gutter-left" | "gutter-right";
}

function getCurrentMinuteOfDay(): number {
  const now = new Date();
  return now.getHours() * 60 + now.getMinutes();
}

function formatMinuteOfDay(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

export function NowLine({
  pixelsPerMinute,
  gutterWidth = 80,
  topOffset = 0,
  businessStartMinute = 540, // 09:00
  mode = "gutter-left",
}: NowLineProps) {
  const [minuteOfDay, setMinuteOfDay] = useState<number>(getCurrentMinuteOfDay);

  useEffect(() => {
    const id = setInterval(() => {
      setMinuteOfDay(getCurrentMinuteOfDay());
    }, 60_000);
    return () => clearInterval(id);
  }, []);

  const top = topOffset + (minuteOfDay - businessStartMinute) * pixelsPerMinute;
  const timeLabel = formatMinuteOfDay(minuteOfDay);

  return (
    <div
      className="pointer-events-none absolute left-0 right-0 z-20"
      style={{ top: `${top}px` }}
      role="presentation"
      aria-label={`Hora actual: ${timeLabel}`}
    >
      {/* Red line */}
      <div
        className="absolute h-[2px]"
        style={{
          left: mode === "gutter-left" ? `${gutterWidth}px` : 0,
          right: 0,
          backgroundColor: "hsl(var(--status-cancel))",
        }}
      />

      {/* Time pin */}
      <div
        className="absolute flex items-center justify-center rounded-full text-[10px] font-bold"
        style={{
          left: mode === "gutter-left" ? 4 : undefined,
          right: mode === "gutter-right" ? 4 : undefined,
          top: "-9px",
          height: "18px",
          minWidth: `${gutterWidth - 8}px`,
          backgroundColor: "hsl(var(--status-cancel))",
          color: "#ffffff",
          paddingLeft: 4,
          paddingRight: 4,
        }}
      >
        ahora · {timeLabel}
      </div>
    </div>
  );
}
