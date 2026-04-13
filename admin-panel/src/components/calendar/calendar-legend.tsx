"use client";

import { HOLIDAY_COLOR, STATUS_MAP } from "./calendar-constants";

interface Stylist {
  id: string;
  name: string;
  category: string;
  is_active: boolean;
  color?: string;
}

interface CalendarLegendProps {
  stylistColors: Record<string, { bg: string; border: string }>;
  stylists: Stylist[];
}

const STATUS_LEGEND_KEYS = ["confirmed", "pending", "cancelled", "completed"] as const;

export function CalendarLegend({ stylistColors: _stylistColors, stylists: _stylists }: CalendarLegendProps) {
  return (
    <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
      <span className="font-medium">Leyenda:</span>
      <div className="flex items-center gap-1">
        <span className="w-3 h-3 rounded border-2 border-dashed border-gray-400" />
        <span>Citas y bloqueos (color por estilista)</span>
      </div>
      <div className="flex items-center gap-1">
        <span className="w-3 h-3 rounded" style={{ backgroundColor: HOLIDAY_COLOR.bg }} />
        <span>Festivos</span>
      </div>

      {/* Separator */}
      <span className="h-4 w-px bg-border" aria-hidden="true" />

      {/* Status indicators */}
      {STATUS_LEGEND_KEYS.map((key) => {
        const config = STATUS_MAP[key];
        return (
          <div key={key} className="flex items-center gap-1">
            <span
              className="w-3 h-3 rounded"
              style={{ borderLeft: `4px solid ${config.color}`, backgroundColor: "transparent" }}
            />
            <span>{config.label}</span>
          </div>
        );
      })}
    </div>
  );
}
