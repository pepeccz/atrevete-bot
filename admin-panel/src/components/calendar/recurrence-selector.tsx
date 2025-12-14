"use client";

import { useEffect, useMemo } from "react";
import { format, addMonths } from "date-fns";
import { es } from "date-fns/locale";
import { CalendarIcon, AlertTriangle } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  expandRecurrence,
  calculateOccurrenceCount,
} from "@/lib/recurrence-utils";

// Day names in Spanish (short)
const DAY_NAMES = ["L", "M", "X", "J", "V", "S", "D"];
const FULL_DAY_NAMES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];

export interface RecurrenceConfig {
  enabled: boolean;
  frequency: "WEEKLY" | "MONTHLY";
  interval: number;
  daysOfWeek: number[]; // 0=Monday, 6=Sunday
  daysOfMonth: number[];
  count: number; // Calculated from endDate, used by backend
  endDate?: Date; // User-friendly end date
}

interface RecurrenceSelectorProps {
  selectedDate: Date;
  value: RecurrenceConfig;
  onChange: (config: RecurrenceConfig) => void;
}

export function RecurrenceSelector({
  selectedDate,
  value,
  onChange,
}: RecurrenceSelectorProps) {
  // Calculate default end date (1 month from selected date)
  const defaultEndDate = useMemo(() => {
    return addMonths(selectedDate, 1);
  }, [selectedDate]);

  // Calculate occurrences when endDate or pattern changes
  const calculatedDates = useMemo(() => {
    if (!value.enabled || !value.endDate) return [];

    const hasDays = value.frequency === "WEEKLY"
      ? value.daysOfWeek.length > 0
      : value.daysOfMonth.length > 0;

    if (!hasDays) return [];

    return expandRecurrence(
      selectedDate,
      value.endDate,
      {
        frequency: value.frequency,
        interval: value.interval,
        daysOfWeek: value.daysOfWeek,
        daysOfMonth: value.daysOfMonth,
      },
      52
    );
  }, [selectedDate, value.enabled, value.endDate, value.frequency, value.interval, value.daysOfWeek, value.daysOfMonth]);

  // Check if count exceeds limit
  const exceedsLimit = calculatedDates.length > 52;
  const actualCount = Math.min(calculatedDates.length, 52);

  // Update count when dates change
  useEffect(() => {
    if (value.enabled && actualCount !== value.count && actualCount > 0) {
      onChange({
        ...value,
        count: actualCount,
      });
    }
  }, [actualCount, value, onChange]);

  const handleToggle = (enabled: boolean) => {
    onChange({
      ...value,
      enabled,
      // Reset to defaults when enabling
      ...(enabled ? {
        daysOfWeek: [],
        daysOfMonth: [],
        endDate: defaultEndDate,
        count: 0,
      } : {}),
    });
  };

  const handleDayToggle = (dayOfWeek: number) => {
    const newDays = value.daysOfWeek.includes(dayOfWeek)
      ? value.daysOfWeek.filter((d) => d !== dayOfWeek)
      : [...value.daysOfWeek, dayOfWeek].sort();

    onChange({
      ...value,
      daysOfWeek: newDays,
    });
  };

  const handleFrequencyChange = (frequency: "WEEKLY" | "MONTHLY") => {
    onChange({
      ...value,
      frequency,
      daysOfWeek: frequency === "WEEKLY" ? value.daysOfWeek : [],
      daysOfMonth: frequency === "MONTHLY" ? value.daysOfMonth : [],
    });
  };

  const handleIntervalChange = (interval: string) => {
    onChange({
      ...value,
      interval: parseInt(interval, 10),
    });
  };

  const handleEndDateChange = (endDate: Date | undefined) => {
    if (endDate) {
      onChange({
        ...value,
        endDate,
      });
    }
  };

  const handleMonthDayToggle = (day: number) => {
    const newDays = value.daysOfMonth.includes(day)
      ? value.daysOfMonth.filter((d) => d !== day)
      : [...value.daysOfMonth, day].sort((a, b) => a - b);

    onChange({
      ...value,
      daysOfMonth: newDays,
    });
  };

  return (
    <div className="space-y-4 border rounded-lg p-4 bg-muted/30">
      {/* Toggle switch */}
      <div className="flex items-center justify-between">
        <Label htmlFor="recurrence-toggle" className="text-sm font-medium">
          ¿Este bloqueo se repite?
        </Label>
        <Switch
          id="recurrence-toggle"
          checked={value.enabled}
          onCheckedChange={handleToggle}
        />
      </div>

      {value.enabled && (
        <div className="space-y-4">
          {/* Frequency and interval */}
          <div className="flex items-center gap-2 flex-wrap">
            <Label className="text-sm whitespace-nowrap">Repetir cada</Label>
            <Select
              value={value.interval.toString()}
              onValueChange={handleIntervalChange}
            >
              <SelectTrigger className="w-16">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[1, 2, 3, 4].map((n) => (
                  <SelectItem key={n} value={n.toString()}>
                    {n}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={value.frequency}
              onValueChange={(v) => handleFrequencyChange(v as "WEEKLY" | "MONTHLY")}
            >
              <SelectTrigger className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="WEEKLY">semana(s)</SelectItem>
                <SelectItem value="MONTHLY">mes(es)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Days selection for WEEKLY */}
          {value.frequency === "WEEKLY" && (
            <div className="space-y-2">
              <Label className="text-sm">Los días:</Label>
              <div className="flex gap-1">
                {DAY_NAMES.map((name, index) => (
                  <button
                    key={index}
                    type="button"
                    onClick={() => handleDayToggle(index)}
                    className={`
                      flex items-center justify-center w-9 h-9 rounded-md border text-sm font-medium transition-colors
                      ${
                        value.daysOfWeek.includes(index)
                          ? "bg-primary text-primary-foreground border-primary"
                          : "bg-background hover:bg-muted border-input"
                      }
                    `}
                  >
                    {name}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Days selection for MONTHLY */}
          {value.frequency === "MONTHLY" && (
            <div className="space-y-2">
              <Label className="text-sm">Los días del mes:</Label>
              <div className="flex flex-wrap gap-1">
                {Array.from({ length: 31 }, (_, i) => i + 1).map((day) => (
                  <button
                    key={day}
                    type="button"
                    onClick={() => handleMonthDayToggle(day)}
                    className={`
                      flex items-center justify-center w-8 h-8 rounded-md border text-xs font-medium transition-colors
                      ${
                        value.daysOfMonth.includes(day)
                          ? "bg-primary text-primary-foreground border-primary"
                          : "bg-background hover:bg-muted border-input"
                      }
                    `}
                  >
                    {day}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* End Date Picker */}
          <div className="space-y-2">
            <Label className="text-sm">Hasta:</Label>
            <Popover>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  className={cn(
                    "w-full justify-start text-left font-normal",
                    !value.endDate && "text-muted-foreground"
                  )}
                >
                  <CalendarIcon className="mr-2 h-4 w-4" />
                  {value.endDate ? (
                    format(value.endDate, "d 'de' MMMM 'de' yyyy", { locale: es })
                  ) : (
                    <span>Seleccionar fecha fin</span>
                  )}
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-auto p-0" align="start">
                <Calendar
                  mode="single"
                  selected={value.endDate}
                  onSelect={handleEndDateChange}
                  locale={es}
                  disabled={(date) => date <= selectedDate}
                  initialFocus
                />
              </PopoverContent>
            </Popover>
          </div>

          {/* Limit warning */}
          {exceedsLimit && (
            <div className="flex items-start gap-2 text-sm text-amber-600 bg-amber-50 p-2 rounded">
              <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" />
              <span>
                El rango genera más de 52 repeticiones. Se limitará a las primeras 52.
              </span>
            </div>
          )}

          {/* Summary */}
          {(value.daysOfWeek.length > 0 || value.daysOfMonth.length > 0) && actualCount > 0 && (
            <div className="text-sm text-muted-foreground p-2 bg-muted rounded">
              {value.frequency === "WEEKLY" ? (
                <>
                  Se crearán <strong>{actualCount}</strong> bloqueos cada{" "}
                  {value.interval > 1 ? `${value.interval} semanas` : "semana"} los{" "}
                  <strong>
                    {value.daysOfWeek.map((d) => FULL_DAY_NAMES[d]).join(", ")}
                  </strong>
                  {value.endDate && (
                    <>, hasta el <strong>{format(value.endDate, "d 'de' MMMM", { locale: es })}</strong></>
                  )}
                  .
                </>
              ) : (
                <>
                  Se crearán <strong>{actualCount}</strong> bloqueos cada{" "}
                  {value.interval > 1 ? `${value.interval} meses` : "mes"} los días{" "}
                  <strong>{value.daysOfMonth.join(", ")}</strong>
                  {value.endDate && (
                    <>, hasta el <strong>{format(value.endDate, "d 'de' MMMM", { locale: es })}</strong></>
                  )}
                  .
                </>
              )}
            </div>
          )}

          {/* No days selected hint */}
          {value.frequency === "WEEKLY" && value.daysOfWeek.length === 0 && (
            <div className="text-sm text-muted-foreground italic">
              Selecciona al menos un día de la semana
            </div>
          )}
          {value.frequency === "MONTHLY" && value.daysOfMonth.length === 0 && (
            <div className="text-sm text-muted-foreground italic">
              Selecciona al menos un día del mes
            </div>
          )}
        </div>
      )}
    </div>
  );
}
