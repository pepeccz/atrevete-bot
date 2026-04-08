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
}

export function AppointmentFilters({
  stylists,
  stylistId,
  status,
  onStylistChange,
  onStatusChange,
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
    </div>
  );
}
