"use client";

import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";

interface Stylist {
  id: string;
  name: string;
  category: string;
  is_active: boolean;
  color?: string;
}

interface CalendarFiltersProps {
  stylists: Stylist[];
  selectedStylistIds: string[];
  stylistColors: Record<string, { bg: string; border: string }>;
  onToggle: (id: string) => void;
  onToggleAll: () => void;
}

export function CalendarFilters({
  stylists,
  selectedStylistIds,
  stylistColors,
  onToggle,
  onToggleAll,
}: CalendarFiltersProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Label className="text-sm font-medium">Estilistas:</Label>
        <Button
          variant="ghost"
          size="sm"
          onClick={onToggleAll}
          className="text-xs h-6 px-2"
        >
          {selectedStylistIds.length === stylists.length ? "Ninguno" : "Todos"}
        </Button>
      </div>

      <div className="flex flex-wrap gap-3">
        {stylists.map((stylist) => {
          const color = stylistColors[stylist.id];
          const isSelected = selectedStylistIds.includes(stylist.id);

          return (
            <div key={stylist.id} className="flex items-center gap-2">
              <Checkbox
                id={`stylist-${stylist.id}`}
                checked={isSelected}
                onCheckedChange={() => onToggle(stylist.id)}
                className="border-2"
                style={{
                  borderColor: color?.bg || "#888",
                  backgroundColor: isSelected ? color?.bg : "transparent",
                }}
              />
              <Label
                htmlFor={`stylist-${stylist.id}`}
                className="text-sm cursor-pointer flex items-center gap-1"
              >
                <span
                  className="w-3 h-3 rounded-full inline-block"
                  style={{ backgroundColor: color?.bg || "#888" }}
                />
                {stylist.name}
              </Label>
            </div>
          );
        })}
      </div>
    </div>
  );
}
