"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Stylist } from "@/lib/types";

interface AppointmentFiltersProps {
  stylists: Stylist[];
  stylistId: string;
  status: string;
  onStylistChange: (value: string) => void;
  onStatusChange: (value: string) => void;
  // T10: date-range filter
  startDate: string;
  endDate: string;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
}

export function AppointmentFilters({
  stylists,
  stylistId,
  status,
  onStylistChange,
  onStatusChange,
  startDate,
  endDate,
  onStartDateChange,
  onEndDateChange,
}: AppointmentFiltersProps) {
  return (
    <div className="flex flex-wrap gap-4 mb-6">
      <div className="w-full sm:w-[200px]">
        <Select
          value={stylistId}
          onValueChange={(value) =>
            onStylistChange(value === "all" ? "" : value)
          }
        >
          <SelectTrigger>
            <SelectValue placeholder="Filtrar por estilista" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Todos los estilistas</SelectItem>
            {stylists.map((stylist) => (
              <SelectItem key={stylist.id} value={stylist.id}>
                {stylist.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="w-full sm:w-[200px]">
        <Select
          value={status}
          onValueChange={(value) =>
            onStatusChange(value === "all" ? "" : value)
          }
        >
          <SelectTrigger>
            <SelectValue placeholder="Filtrar por estado" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Todos los estados</SelectItem>
            <SelectItem value="pending">Pendiente</SelectItem>
            <SelectItem value="confirmed">Confirmada</SelectItem>
            <SelectItem value="completed">Completada</SelectItem>
            <SelectItem value="cancelled">Cancelada</SelectItem>
            <SelectItem value="no_show">No asistió</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {/* T10: date-range filter */}
      <div className="flex items-center gap-2">
        <label className="text-sm text-muted-foreground whitespace-nowrap">Desde</label>
        <input
          type="date"
          value={startDate}
          onChange={(e) => onStartDateChange(e.target.value)}
          className="h-9 rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
      </div>
      <div className="flex items-center gap-2">
        <label className="text-sm text-muted-foreground whitespace-nowrap">Hasta</label>
        <input
          type="date"
          value={endDate}
          onChange={(e) => onEndDateChange(e.target.value)}
          className="h-9 rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
      </div>
    </div>
  );
}
