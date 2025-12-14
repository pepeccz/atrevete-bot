"use client";

import { useMemo } from "react";
import {
  format,
  startOfMonth,
  endOfMonth,
  eachDayOfInterval,
  getDay,
  addMonths,
  isSameDay,
  isSameMonth,
  isWeekend,
} from "date-fns";
import { es } from "date-fns/locale";
import { cn } from "@/lib/utils";

interface ConflictInfo {
  date: string;
  stylist_id: string;
  stylist_name: string;
  conflict_type: "appointment" | "blocking_event";
  conflict_title: string;
  start_time: string;
  end_time: string;
}

interface RecurrencePreviewCalendarProps {
  /** Array of dates that will be blocked */
  blockedDates: Date[];
  /** Start date (first occurrence) */
  startDate: Date;
  /** End date (last occurrence range) */
  endDate?: Date;
  /** Conflicts from backend preview */
  conflicts?: ConflictInfo[];
  /** Number of months to display */
  monthsToShow?: number;
  /** Maximum blocked dates to highlight (for performance) */
  maxHighlight?: number;
}

/**
 * Mini calendar component showing blocked dates across multiple months.
 * Displays a compact view of which days will be blocked.
 */
export function RecurrencePreviewCalendar({
  blockedDates,
  startDate,
  endDate,
  conflicts = [],
  monthsToShow = 3,
  maxHighlight = 100,
}: RecurrencePreviewCalendarProps) {
  // Create a Set for quick lookup
  const blockedSet = useMemo(() => {
    const set = new Set<string>();
    blockedDates.slice(0, maxHighlight).forEach((d) => {
      set.add(format(d, "yyyy-MM-dd"));
    });
    return set;
  }, [blockedDates, maxHighlight]);

  // Create a Set for conflict dates
  const conflictSet = useMemo(() => {
    const set = new Set<string>();
    conflicts.forEach((c) => {
      // Extract date from ISO string
      const dateStr = c.date.split("T")[0];
      set.add(dateStr);
    });
    return set;
  }, [conflicts]);

  // Generate months to display
  const months = useMemo(() => {
    const result: Date[] = [];
    let current = startOfMonth(startDate);

    for (let i = 0; i < monthsToShow; i++) {
      result.push(current);
      current = addMonths(current, 1);
    }

    return result;
  }, [startDate, monthsToShow]);

  if (blockedDates.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      <div className="text-sm font-medium text-muted-foreground">
        Preview: {blockedDates.length} bloqueo{blockedDates.length !== 1 ? "s" : ""}
        {conflicts.length > 0 && (
          <span className="text-amber-600 ml-2">
            ({conflicts.length} conflicto{conflicts.length !== 1 ? "s" : ""})
          </span>
        )}
      </div>

      <div className="flex gap-4 overflow-x-auto pb-2">
        {months.map((month) => (
          <MiniMonth
            key={format(month, "yyyy-MM")}
            month={month}
            blockedSet={blockedSet}
            conflictSet={conflictSet}
            startDate={startDate}
          />
        ))}
      </div>

      {/* Legend */}
      <div className="flex gap-4 text-xs text-muted-foreground">
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded-full bg-primary" />
          <span>Bloqueado</span>
        </div>
        {conflicts.length > 0 && (
          <div className="flex items-center gap-1">
            <div className="w-3 h-3 rounded-full bg-amber-500" />
            <span>Conflicto</span>
          </div>
        )}
      </div>
    </div>
  );
}

interface MiniMonthProps {
  month: Date;
  blockedSet: Set<string>;
  conflictSet: Set<string>;
  startDate: Date;
}

function MiniMonth({ month, blockedSet, conflictSet, startDate }: MiniMonthProps) {
  const days = useMemo(() => {
    const start = startOfMonth(month);
    const end = endOfMonth(month);
    return eachDayOfInterval({ start, end });
  }, [month]);

  // Get the day of week the month starts on (0=Sunday, adjust for Monday start)
  const startDayOfWeek = useMemo(() => {
    const day = getDay(startOfMonth(month));
    // Convert to Monday-first (0=Monday, 6=Sunday)
    return day === 0 ? 6 : day - 1;
  }, [month]);

  return (
    <div className="flex-shrink-0">
      {/* Month header */}
      <div className="text-xs font-medium text-center mb-1 capitalize">
        {format(month, "MMM yyyy", { locale: es })}
      </div>

      {/* Day headers */}
      <div className="grid grid-cols-7 gap-px text-[10px] text-muted-foreground text-center mb-1">
        {["L", "M", "X", "J", "V", "S", "D"].map((d) => (
          <div key={d} className="w-5">{d}</div>
        ))}
      </div>

      {/* Days grid */}
      <div className="grid grid-cols-7 gap-px">
        {/* Empty cells before first day */}
        {Array.from({ length: startDayOfWeek }).map((_, i) => (
          <div key={`empty-${i}`} className="w-5 h-5" />
        ))}

        {/* Day cells */}
        {days.map((day) => {
          const dateStr = format(day, "yyyy-MM-dd");
          const isBlocked = blockedSet.has(dateStr);
          const hasConflict = conflictSet.has(dateStr);
          const isStart = isSameDay(day, startDate);

          return (
            <div
              key={dateStr}
              className={cn(
                "w-5 h-5 flex items-center justify-center text-[10px] rounded-sm",
                isBlocked && !hasConflict && "bg-primary text-primary-foreground",
                hasConflict && "bg-amber-500 text-white",
                isStart && "ring-1 ring-primary ring-offset-1",
                !isBlocked && !hasConflict && isWeekend(day) && "text-muted-foreground/50"
              )}
              title={
                isBlocked
                  ? hasConflict
                    ? `${format(day, "d MMM", { locale: es })} - Conflicto`
                    : format(day, "d MMM", { locale: es })
                  : undefined
              }
            >
              {day.getDate()}
            </div>
          );
        })}
      </div>
    </div>
  );
}
