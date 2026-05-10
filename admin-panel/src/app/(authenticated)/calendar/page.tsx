"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Header } from "@/components/layout/header";
import { CalendarView, CalendarViewRef } from "@/components/calendar/calendar-view";
import { CalendarErrorBoundary } from "@/components/calendar/calendar-error-boundary";

type CalendarContextView = "day" | "week" | "month";

function buildSubtitle(view: CalendarContextView, activeStylists: number): string {
  switch (view) {
    case "day":
      return "Vista por estilista";
    case "month":
      return "Vista mensual";
    case "week":
    default: {
      const noun = activeStylists === 1 ? "estilista activo" : "estilistas activos";
      return `Vista semanal · ${activeStylists} ${noun}`;
    }
  }
}

export default function CalendarPage() {
  const calendarRef = useRef<CalendarViewRef>(null);
  const [ctx, setCtx] = useState<{ view: CalendarContextView; activeStylists: number }>({
    view: "week",
    activeStylists: 0,
  });

  const handleContextChange = useCallback(
    (next: { view: CalendarContextView; activeStylists: number }) => setCtx(next),
    [],
  );

  // Refresh the calendar grid when the global Sync GCal action completes.
  useEffect(() => {
    const handler = () => calendarRef.current?.refresh();
    window.addEventListener("atrevete:gcal-synced", handler);
    return () => window.removeEventListener("atrevete:gcal-synced", handler);
  }, []);

  return (
    <div className="flex flex-col">
      <Header
        title="Calendario"
        subtitle={buildSubtitle(ctx.view, ctx.activeStylists)}
      />

      <div className="flex-1 p-4 md:p-6">
        <CalendarErrorBoundary onResetToWeek={() => calendarRef.current?.resetToWeek()}>
          <CalendarView ref={calendarRef} onContextChange={handleContextChange} />
        </CalendarErrorBoundary>
      </div>
    </div>
  );
}
