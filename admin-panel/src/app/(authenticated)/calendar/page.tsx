"use client";

import { Header } from "@/components/layout/header";
import { CalendarView } from "@/components/calendar/calendar-view";

export default function CalendarPage() {
  return (
    <div className="flex flex-col">
      <Header
        title="Calendario"
        description="Vista de citas por estilista"
      />

      <div className="flex-1 p-6">
        <CalendarView />
      </div>
    </div>
  );
}
