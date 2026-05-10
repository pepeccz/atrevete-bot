"use client";

import { useEffect, useRef } from "react";
import { Header } from "@/components/layout/header";
import { CalendarView, CalendarViewRef } from "@/components/calendar/calendar-view";
import { CalendarErrorBoundary } from "@/components/calendar/calendar-error-boundary";

export default function CalendarPage() {
  const calendarRef = useRef<CalendarViewRef>(null);

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
        subtitle="Vista de citas por estilista"
      />

      <div className="flex-1 p-4 md:p-6">
        <CalendarErrorBoundary onResetToWeek={() => calendarRef.current?.resetToWeek()}>
          <CalendarView ref={calendarRef} />
        </CalendarErrorBoundary>
      </div>
    </div>
  );
}
