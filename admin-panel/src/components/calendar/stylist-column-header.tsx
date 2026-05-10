"use client";

import type { CSSProperties } from "react";
import { deriveStylistPalette } from "@/lib/stylist-colors";

interface StylistColumnHeaderProps {
  stylist: {
    id: string;
    name: string;
    color: string;
  };
  metrics: {
    appointmentsCount: number;
    /** Total booked time in minutes */
    totalMinutes: number;
    /** 0–100 */
    utilizationPct: number;
  };
  /** Optional override for the status dot color (CSS value) */
  statusDotColor?: string;
}

function formatHours(minutes: number): string {
  if (minutes === 0) return "0h";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

/**
 * 84px tall sticky column header for the per-stylist day view.
 *
 * Shows:
 *   - 32px avatar circle with stylist initial (soft bg, text color)
 *   - Stylist name
 *   - "N citas · Xh" summary
 *   - 3px utilization bar (line-soft bg, solid fill = utilizationPct%)
 *   - 8px status dot top-right
 */
export function StylistColumnHeader({
  stylist,
  metrics,
  statusDotColor,
}: StylistColumnHeaderProps) {
  const palette = deriveStylistPalette(stylist.color);
  const initial = stylist.name.charAt(0).toUpperCase();
  const utilizationWidth = `${Math.min(100, Math.max(0, metrics.utilizationPct))}%`;

  const dotColor =
    statusDotColor ??
    (metrics.appointmentsCount > 0
      ? "hsl(var(--status-confirm))"
      : "hsl(var(--ink-faint))");

  return (
    <div
      className="relative flex flex-col items-center justify-center gap-1 px-2 border-b border-r border-line bg-white"
      style={{ height: "84px", position: "sticky", top: 0, zIndex: 5 } as CSSProperties}
    >
      {/* Status dot — top-right corner */}
      <span
        className="absolute top-2 right-2 w-2 h-2 rounded-full flex-shrink-0"
        style={{ backgroundColor: dotColor }}
        aria-hidden="true"
      />

      {/* Avatar circle */}
      <div
        className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0"
        style={{
          backgroundColor: palette.soft,
          color: palette.text,
        }}
        aria-hidden="true"
      >
        {initial}
      </div>

      {/* Name */}
      <div className="text-[13px] font-bold text-ink leading-tight text-center truncate w-full px-1">
        {stylist.name}
      </div>

      {/* Summary */}
      <div className="text-[11px] text-ink-mute leading-tight">
        {metrics.appointmentsCount} {metrics.appointmentsCount === 1 ? "cita" : "citas"} · {formatHours(metrics.totalMinutes)}
      </div>

      {/* Utilization bar */}
      <div
        className="w-full rounded-full overflow-hidden"
        style={{ height: "3px", backgroundColor: "hsl(var(--line-soft))" }}
        role="progressbar"
        aria-valuenow={metrics.utilizationPct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Ocupación ${metrics.utilizationPct}%`}
      >
        <div
          className="h-full rounded-full"
          style={{
            width: utilizationWidth,
            backgroundColor: palette.solid,
            transition: "width 0.3s ease",
          }}
        />
      </div>
    </div>
  );
}
