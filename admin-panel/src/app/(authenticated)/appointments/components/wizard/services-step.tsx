"use client";

import { useState, useMemo } from "react";
import { Search, Clock, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Service } from "@/lib/types";

interface ServicesStepProps {
  services: Service[];
  selectedServices: Service[];
  onToggle: (service: Service) => void;
}

export function ServicesStep({
  services,
  selectedServices,
  onToggle,
}: ServicesStepProps) {
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");

  const filteredServices = useMemo(() => {
    let result = services.filter((s) => s.is_active);

    if (categoryFilter !== "all") {
      result = result.filter((s) => s.category === categoryFilter);
    }

    if (search) {
      const term = search.toLowerCase();
      result = result.filter((s) => s.name.toLowerCase().includes(term));
    }

    return result;
  }, [services, search, categoryFilter]);

  const totalDuration = selectedServices.reduce(
    (sum, s) => sum + s.duration_minutes,
    0
  );

  const selectedIds = new Set(selectedServices.map((s) => s.id));

  return (
    <div className="space-y-4">
      {/* Selected summary */}
      {selectedServices.length > 0 && (
        <div className="p-3 bg-primary/10 rounded-lg">
          <p className="text-sm font-medium">
            {selectedServices.length} servicio(s) seleccionado(s)
          </p>
          <p className="text-sm text-muted-foreground">
            Duración total: {totalDuration} minutos
          </p>
          <div className="flex flex-wrap gap-1 mt-2">
            {selectedServices.map((s) => (
              <Badge
                key={s.id}
                variant="secondary"
                className="cursor-pointer"
                onClick={() => onToggle(s)}
              >
                {s.name}
                <X className="ml-1 h-3 w-3" />
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Buscar servicio..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select value={categoryFilter} onValueChange={setCategoryFilter}>
          <SelectTrigger className="w-[150px]">
            <SelectValue placeholder="Categoría" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Todas</SelectItem>
            <SelectItem value="HAIRDRESSING">Peluquería</SelectItem>
            <SelectItem value="AESTHETICS">Estética</SelectItem>
            <SelectItem value="BOTH">Ambas</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Service list */}
      <ScrollArea className="h-[280px]">
        <div className="space-y-2">
          {filteredServices.map((service) => (
            <div
              key={service.id}
              onClick={() => onToggle(service)}
              className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                selectedIds.has(service.id)
                  ? "border-primary bg-primary/5"
                  : "hover:border-primary/50"
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="flex-1">
                  <p className="font-medium">{service.name}</p>
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Clock className="h-3 w-3" />
                    <span>{service.duration_minutes} min</span>
                    <Badge variant="outline" className="text-xs">
                      {service.category === "HAIRDRESSING"
                        ? "Peluquería"
                        : service.category === "AESTHETICS"
                          ? "Estética"
                          : "Ambas"}
                    </Badge>
                  </div>
                </div>
                <Checkbox checked={selectedIds.has(service.id)} />
              </div>
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}
