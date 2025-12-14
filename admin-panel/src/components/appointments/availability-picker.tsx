"use client";

import { useState, useMemo } from "react";
import { format } from "date-fns";
import { Calendar, Search, Scissors, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import api from "@/lib/api";
import type { Stylist, ServiceCategory } from "@/lib/types";

// Types
export interface SelectedSlot {
  time: string;
  end_time: string;
  full_datetime: string;
  stylist_id: string;
  stylist_name: string;
  date: string;
}

interface AvailabilityResult {
  days: Array<{
    date: string;
    day_name: string;
    is_closed: boolean;
    holiday: string | null;
    stylists: Array<{
      id: string;
      name: string;
      category: string;
      slots: Array<{
        time: string;
        end_time: string;
        full_datetime: string;
        stylist_id: string;
      }>;
    }>;
  }>;
  total_duration_minutes: number;
  service_category: string | null;
}

export interface AvailabilityPickerProps {
  serviceIds: string[];
  stylists: Stylist[];
  serviceCategories: ServiceCategory[];
  totalDuration: number;
  selectedSlot: SelectedSlot | null;
  onSlotSelect: (slot: SelectedSlot | null) => void;
  initialStylistId?: string;
  maxHeight?: string;
}

/**
 * Reusable component for searching and selecting available appointment slots.
 * Extracted from the appointment creation wizard for reuse in reschedule modal.
 */
export function AvailabilityPicker({
  serviceIds,
  stylists,
  serviceCategories,
  totalDuration,
  selectedSlot,
  onSlotSelect,
  initialStylistId,
  maxHeight = "220px",
}: AvailabilityPickerProps) {
  const [loading, setLoading] = useState(false);
  const [stylistFilter, setStylistFilter] = useState<string>(
    initialStylistId || "all"
  );
  const [startDate, setStartDate] = useState<string>("");
  const [endDate, setEndDate] = useState<string>("");
  const [availability, setAvailability] = useState<AvailabilityResult | null>(
    null
  );

  // Determine compatible stylists based on service categories
  const compatibleStylists = useMemo(() => {
    const categories = new Set(serviceCategories);
    const needsBoth =
      categories.has("HAIRDRESSING") && categories.has("AESTHETICS");
    const needsAesthetics =
      categories.has("AESTHETICS") && !categories.has("HAIRDRESSING");

    return stylists.filter((s) => {
      if (!s.is_active) return false;
      if (needsBoth) return s.category === "BOTH";
      if (needsAesthetics)
        return s.category === "AESTHETICS" || s.category === "BOTH";
      return s.category === "HAIRDRESSING" || s.category === "BOTH";
    });
  }, [stylists, serviceCategories]);

  // Manual search function
  const handleSearch = async () => {
    if (!startDate || !endDate || serviceIds.length === 0) {
      toast.error("Selecciona fechas y servicios");
      return;
    }

    setLoading(true);
    try {
      const result = await api.searchAvailability(
        serviceIds,
        startDate,
        endDate,
        stylistFilter === "all" ? null : stylistFilter
      );
      setAvailability(result);
      onSlotSelect(null); // Reset slot when searching
    } catch (error) {
      toast.error("Error buscando disponibilidad");
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  // Today's date for min date
  const today = new Date().toISOString().split("T")[0];

  // Calculate max end date (14 days from start)
  const maxEndDate = useMemo(() => {
    if (!startDate) return "";
    const start = new Date(startDate);
    start.setDate(start.getDate() + 14);
    return start.toISOString().split("T")[0];
  }, [startDate]);

  return (
    <div className="space-y-4">
      {/* Date range pickers */}
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>Fecha inicio</Label>
          <Input
            type="date"
            value={startDate}
            onChange={(e) => {
              setStartDate(e.target.value);
              // Auto-set end date if not set or invalid
              if (!endDate || endDate < e.target.value) {
                setEndDate(e.target.value);
              }
            }}
            min={today}
          />
        </div>
        <div className="space-y-2">
          <Label>Fecha fin</Label>
          <Input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            min={startDate || today}
            max={maxEndDate}
          />
        </div>
      </div>

      {/* Stylist filter */}
      <div className="space-y-2">
        <Label>Estilista</Label>
        <Select value={stylistFilter} onValueChange={setStylistFilter}>
          <SelectTrigger>
            <SelectValue placeholder="Todos los estilistas" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Todos los estilistas</SelectItem>
            {compatibleStylists.map((stylist) => (
              <SelectItem key={stylist.id} value={stylist.id}>
                {stylist.name} (
                {stylist.category === "HAIRDRESSING"
                  ? "Peluqueria"
                  : stylist.category === "AESTHETICS"
                    ? "Estetica"
                    : "Ambas"}
                )
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Duration info */}
      <div className="text-sm text-muted-foreground">
        Duracion total: {totalDuration} minutos
      </div>

      {/* Search button */}
      <Button
        onClick={handleSearch}
        disabled={loading || !startDate || !endDate}
        className="w-full"
      >
        {loading ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Buscando...
          </>
        ) : (
          <>
            <Search className="mr-2 h-4 w-4" />
            Buscar Disponibilidad
          </>
        )}
      </Button>

      {/* Availability display */}
      {availability && (
        <ScrollArea className={`h-[${maxHeight}]`} style={{ height: maxHeight }}>
          <div className="space-y-4">
            {availability.days.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                <p>No se encontraron dias disponibles</p>
              </div>
            ) : (
              availability.days.map((day) => (
                <div key={day.date} className="space-y-2">
                  {/* Day header */}
                  <div className="flex items-center gap-2 font-medium">
                    <Calendar className="h-4 w-4" />
                    <span>
                      {day.day_name} {format(new Date(day.date), "d/MM/yyyy")}
                    </span>
                    {day.is_closed && (
                      <Badge variant="secondary">Cerrado</Badge>
                    )}
                    {day.holiday && (
                      <Badge variant="destructive">{day.holiday}</Badge>
                    )}
                  </div>

                  {/* Stylists for this day */}
                  {!day.is_closed && !day.holiday && (
                    <div className="pl-6 space-y-3">
                      {day.stylists.length === 0 ? (
                        <p className="text-sm text-muted-foreground">
                          Sin estilistas disponibles
                        </p>
                      ) : (
                        day.stylists.map((stylist) => (
                          <div key={stylist.id} className="space-y-1">
                            <div className="flex items-center gap-2">
                              <Scissors className="h-3 w-3" />
                              <span className="text-sm font-medium">
                                {stylist.name}
                              </span>
                            </div>

                            {stylist.slots.length === 0 ? (
                              <p className="text-xs text-muted-foreground pl-5">
                                Sin huecos
                              </p>
                            ) : (
                              <div className="flex flex-wrap gap-1 pl-5">
                                {stylist.slots.slice(0, 12).map((slot) => {
                                  const isSelected =
                                    selectedSlot?.full_datetime ===
                                      slot.full_datetime &&
                                    selectedSlot?.stylist_id === stylist.id;
                                  return (
                                    <Button
                                      key={`${stylist.id}-${slot.time}`}
                                      variant={isSelected ? "default" : "outline"}
                                      size="sm"
                                      className="h-7 px-2 text-xs"
                                      onClick={() =>
                                        onSlotSelect({
                                          ...slot,
                                          stylist_id: stylist.id,
                                          stylist_name: stylist.name,
                                          date: day.date,
                                        })
                                      }
                                    >
                                      {slot.time}
                                    </Button>
                                  );
                                })}
                                {stylist.slots.length > 12 && (
                                  <span className="text-xs text-muted-foreground self-center">
                                    +{stylist.slots.length - 12} mas
                                  </span>
                                )}
                              </div>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}
