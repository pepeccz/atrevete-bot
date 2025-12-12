"use client";

import { useState, useRef } from "react";
import { RefreshCw } from "lucide-react";
import { Header } from "@/components/layout/header";
import { CalendarView, CalendarViewRef } from "@/components/calendar/calendar-view";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import api from "@/lib/api";

export default function CalendarPage() {
  const [syncing, setSyncing] = useState(false);
  const calendarRef = useRef<CalendarViewRef>(null);

  const handleGcalSync = async () => {
    setSyncing(true);
    try {
      const result = await api.triggerGcalSync();
      if (result.success) {
        toast.success(result.message);
        // Refresh calendar data after sync
        calendarRef.current?.refresh();
      } else {
        toast.error(result.message);
      }
    } catch {
      toast.error("Error al sincronizar con Google Calendar");
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="flex flex-col">
      <Header
        title="Calendario"
        description="Vista de citas por estilista"
        action={
          <Button variant="outline" onClick={handleGcalSync} disabled={syncing}>
            <RefreshCw className={`mr-2 h-4 w-4 ${syncing ? "animate-spin" : ""}`} />
            Sync GCal
          </Button>
        }
      />

      <div className="flex-1 p-6">
        <CalendarView ref={calendarRef} />
      </div>
    </div>
  );
}
