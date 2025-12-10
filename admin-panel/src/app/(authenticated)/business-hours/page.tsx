"use client";

import { useEffect, useState, useCallback } from "react";
import { Clock, Check, X } from "lucide-react";

import { Header } from "@/components/layout/header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { toast } from "sonner";
import api from "@/lib/api";
import type { BusinessHours } from "@/lib/types";

const DAY_NAMES = [
  "Lunes",
  "Martes",
  "Miercoles",
  "Jueves",
  "Viernes",
  "Sabado",
  "Domingo",
];

// Format time from hour/minute to HH:MM
function formatTime(hour: number, minute: number): string {
  return `${hour.toString().padStart(2, "0")}:${minute.toString().padStart(2, "0")}`;
}

// Parse HH:MM to {hour, minute}
function parseTime(time: string): { hour: number; minute: number } {
  const [hour, minute] = time.split(":").map(Number);
  return { hour, minute };
}

interface DayRowProps {
  day: BusinessHours;
  onUpdate: (
    id: string,
    data: Partial<BusinessHours>
  ) => Promise<void>;
}

function DayRow({ day, onUpdate }: DayRowProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState({
    is_closed: day.is_closed,
    start_time: formatTime(day.start_hour, day.start_minute),
    end_time: formatTime(day.end_hour, day.end_minute),
  });

  useEffect(() => {
    setFormData({
      is_closed: day.is_closed,
      start_time: formatTime(day.start_hour, day.start_minute),
      end_time: formatTime(day.end_hour, day.end_minute),
    });
  }, [day]);

  const handleSave = async () => {
    setLoading(true);
    try {
      const start = parseTime(formData.start_time);
      const end = parseTime(formData.end_time);

      await onUpdate(day.id, {
        is_closed: formData.is_closed,
        start_hour: start.hour,
        start_minute: start.minute,
        end_hour: end.hour,
        end_minute: end.minute,
      });
      setIsEditing(false);
      toast.success(`Horario de ${DAY_NAMES[day.day_of_week]} actualizado`);
    } catch (error) {
      toast.error("Error al actualizar el horario");
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-between py-4 border-b last:border-b-0">
      <div className="flex items-center gap-4 min-w-[150px]">
        <span className="font-medium w-24">{DAY_NAMES[day.day_of_week]}</span>
        {isEditing ? (
          <div className="flex items-center gap-2">
            <Checkbox
              id={`closed-${day.id}`}
              checked={formData.is_closed}
              onCheckedChange={(checked) =>
                setFormData((prev) => ({ ...prev, is_closed: checked === true }))
              }
            />
            <Label htmlFor={`closed-${day.id}`} className="text-sm cursor-pointer">
              Cerrado
            </Label>
          </div>
        ) : day.is_closed ? (
          <span className="text-red-500 flex items-center gap-1">
            <X className="h-4 w-4" />
            Cerrado
          </span>
        ) : (
          <span className="text-green-500 flex items-center gap-1">
            <Check className="h-4 w-4" />
            Abierto
          </span>
        )}
      </div>

      <div className="flex items-center gap-4">
        {isEditing ? (
          <>
            <div className="flex items-center gap-2">
              <Label className="text-sm">Apertura:</Label>
              <Input
                type="time"
                value={formData.start_time}
                onChange={(e) =>
                  setFormData((prev) => ({ ...prev, start_time: e.target.value }))
                }
                disabled={formData.is_closed}
                className="w-32"
              />
            </div>
            <div className="flex items-center gap-2">
              <Label className="text-sm">Cierre:</Label>
              <Input
                type="time"
                value={formData.end_time}
                onChange={(e) =>
                  setFormData((prev) => ({ ...prev, end_time: e.target.value }))
                }
                disabled={formData.is_closed}
                className="w-32"
              />
            </div>
          </>
        ) : (
          <div className="flex items-center gap-2 text-muted-foreground">
            <Clock className="h-4 w-4" />
            {day.is_closed ? (
              <span>-</span>
            ) : (
              <span>
                {formatTime(day.start_hour, day.start_minute)} -{" "}
                {formatTime(day.end_hour, day.end_minute)}
              </span>
            )}
          </div>
        )}

        {isEditing ? (
          <div className="flex gap-2">
            <Button size="sm" onClick={handleSave} disabled={loading}>
              {loading ? "Guardando..." : "Guardar"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setIsEditing(false);
                setFormData({
                  is_closed: day.is_closed,
                  start_time: formatTime(day.start_hour, day.start_minute),
                  end_time: formatTime(day.end_hour, day.end_minute),
                });
              }}
            >
              Cancelar
            </Button>
          </div>
        ) : (
          <Button size="sm" variant="outline" onClick={() => setIsEditing(true)}>
            Editar
          </Button>
        )}
      </div>
    </div>
  );
}

export default function BusinessHoursPage() {
  const [hours, setHours] = useState<BusinessHours[]>([]);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.list<BusinessHours>("business-hours");
      // API returns {items: [...]} without page info
      const items = res.items || [];
      // Sort by day_of_week
      items.sort((a, b) => a.day_of_week - b.day_of_week);
      setHours(items);
    } catch (error) {
      toast.error("Error al cargar los horarios");
      console.error(error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleUpdate = async (
    id: string,
    data: Partial<BusinessHours>
  ): Promise<void> => {
    await api.update("business-hours", id, data);
    await loadData();
  };

  return (
    <div className="flex flex-col">
      <Header
        title="Horarios"
        description="Configuracion de horarios de apertura del salon"
      />

      <div className="flex-1 p-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Clock className="h-5 w-5" />
              Horarios de Apertura
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
                <span className="ml-2">Cargando horarios...</span>
              </div>
            ) : hours.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                No hay horarios configurados. Contacta al administrador.
              </div>
            ) : (
              <div className="divide-y">
                {hours.map((day) => (
                  <DayRow key={day.id} day={day} onUpdate={handleUpdate} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
