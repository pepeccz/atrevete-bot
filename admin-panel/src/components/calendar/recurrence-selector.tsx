"use client";

import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// Day names in Spanish (short)
const DAY_NAMES = ["L", "M", "X", "J", "V", "S", "D"];
const FULL_DAY_NAMES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];

export interface RecurrenceConfig {
  enabled: boolean;
  frequency: "WEEKLY" | "MONTHLY";
  interval: number;
  daysOfWeek: number[]; // 0=Monday, 6=Sunday
  daysOfMonth: number[];
  count: number;
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
  const handleToggle = (enabled: boolean) => {
    onChange({
      ...value,
      enabled,
      // Reset to defaults when enabling
      ...(enabled ? { daysOfWeek: [], count: 4 } : {}),
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

  const handleCountChange = (count: string) => {
    onChange({
      ...value,
      count: parseInt(count, 10),
    });
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

          {/* Count */}
          <div className="flex items-center gap-2">
            <Label className="text-sm whitespace-nowrap">Durante</Label>
            <Select
              value={value.count.toString()}
              onValueChange={handleCountChange}
            >
              <SelectTrigger className="w-16">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 16, 20, 24, 52].map((n) => (
                  <SelectItem key={n} value={n.toString()}>
                    {n}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className="text-sm text-muted-foreground">repeticiones</span>
          </div>

          {/* Summary */}
          {(value.daysOfWeek.length > 0 || value.daysOfMonth.length > 0) && (
            <div className="text-sm text-muted-foreground p-2 bg-muted rounded">
              {value.frequency === "WEEKLY" ? (
                <>
                  Se crearán bloqueos cada{" "}
                  {value.interval > 1 ? `${value.interval} semanas` : "semana"} los{" "}
                  <strong>
                    {value.daysOfWeek.map((d) => FULL_DAY_NAMES[d]).join(", ")}
                  </strong>
                  , durante <strong>{value.count}</strong> repeticiones.
                </>
              ) : (
                <>
                  Se crearán bloqueos cada{" "}
                  {value.interval > 1 ? `${value.interval} meses` : "mes"} los días{" "}
                  <strong>{value.daysOfMonth.join(", ")}</strong>, durante{" "}
                  <strong>{value.count}</strong> repeticiones.
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
