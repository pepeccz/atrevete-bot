"use client";

import { useState, useEffect } from "react";
import { format } from "date-fns";
import { es } from "date-fns/locale";
import { CalendarIcon } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
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
import { cn } from "@/lib/utils";
import api from "@/lib/api";

interface Stylist {
  id: string;
  name: string;
  category: string;
}

interface CreateBlockingEventModalProps {
  isOpen: boolean;
  onClose: () => void;
  stylistId: string;
  stylistName: string;
  selectedDate: Date | null;
  selectedStartTime?: Date | null;
  selectedEndTime?: Date | null;
  stylists?: Stylist[];
  onSuccess: () => void;
}

const EVENT_TYPES = [
  { value: "vacation", label: "Vacaciones", emoji: "🏖️" },
  { value: "meeting", label: "Reunión", emoji: "📅" },
  { value: "break", label: "Descanso", emoji: "☕" },
  { value: "general", label: "Bloqueo general", emoji: "🚫" },
  { value: "personal", label: "Asunto Propio", emoji: "💕" },
];

export function CreateBlockingEventModal({
  isOpen,
  onClose,
  stylistId: initialStylistId,
  stylistName: initialStylistName,
  selectedDate,
  selectedStartTime,
  selectedEndTime,
  stylists = [],
  onSuccess,
}: CreateBlockingEventModalProps) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [eventType, setEventType] = useState("general");
  const [blockingDate, setBlockingDate] = useState<Date | undefined>(
    selectedDate || new Date()
  );
  // Multi-select: array of stylist IDs
  const [selectedStylistIds, setSelectedStylistIds] = useState<string[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Calculate default times from drag selection or use defaults
  const getDefaultStartTime = () => {
    if (selectedStartTime) {
      return format(selectedStartTime, "HH:mm");
    }
    return "09:00";
  };

  const getDefaultEndTime = () => {
    if (selectedEndTime) {
      return format(selectedEndTime, "HH:mm");
    }
    return "14:00";
  };

  const [startTime, setStartTime] = useState(getDefaultStartTime());
  const [endTime, setEndTime] = useState(getDefaultEndTime());

  // Reset form when modal opens with new data
  useEffect(() => {
    if (isOpen) {
      setBlockingDate(selectedDate || new Date());
      setStartTime(getDefaultStartTime());
      setEndTime(getDefaultEndTime());
      // Default: select all stylists if more than one, otherwise just the initial one
      if (stylists.length > 1) {
        setSelectedStylistIds(stylists.map(s => s.id));
      } else if (stylists.length === 1) {
        setSelectedStylistIds([stylists[0].id]);
      } else {
        setSelectedStylistIds([initialStylistId]);
      }
      setTitle("");
      setDescription("");
      setEventType("general");
      setError(null);
    }
  }, [isOpen, selectedDate, selectedStartTime, selectedEndTime, initialStylistId, stylists]);

  // Toggle individual stylist selection
  const toggleStylist = (stylistId: string) => {
    setSelectedStylistIds(prev => {
      if (prev.includes(stylistId)) {
        return prev.filter(id => id !== stylistId);
      } else {
        return [...prev, stylistId];
      }
    });
  };

  // Toggle all stylists
  const toggleAll = (checked: boolean) => {
    if (checked) {
      setSelectedStylistIds(stylists.map(s => s.id));
    } else {
      setSelectedStylistIds([]);
    }
  };

  const allSelected = stylists.length > 0 && selectedStylistIds.length === stylists.length;
  const someSelected = selectedStylistIds.length > 0 && selectedStylistIds.length < stylists.length;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!title.trim()) {
      setError("El título es requerido");
      return;
    }

    if (!blockingDate) {
      setError("Selecciona una fecha");
      return;
    }

    if (selectedStylistIds.length === 0) {
      setError("Selecciona al menos un estilista");
      return;
    }

    // Build datetime strings
    const dateStr = format(blockingDate, "yyyy-MM-dd");
    const startDateTime = `${dateStr}T${startTime}:00`;
    const endDateTime = `${dateStr}T${endTime}:00`;

    // Validate end time is after start time
    if (endTime <= startTime) {
      setError("La hora de fin debe ser posterior a la hora de inicio");
      return;
    }

    setIsSubmitting(true);

    try {
      await api.createBlockingEvent({
        stylist_ids: selectedStylistIds,
        title: title.trim(),
        description: description.trim() || undefined,
        start_time: startDateTime,
        end_time: endDateTime,
        event_type: eventType,
      });

      onSuccess();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al crear el evento");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>Crear evento de bloqueo</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Stylist multi-select */}
          {stylists.length > 1 ? (
            <div className="space-y-2">
              <Label>Estilistas</Label>
              <div className="border rounded-md p-3 space-y-2">
                {/* Select all checkbox */}
                <div className="flex items-center gap-2 pb-2 border-b">
                  <Checkbox
                    id="select-all"
                    checked={allSelected}
                    onCheckedChange={(checked) => toggleAll(checked === true)}
                    className={someSelected ? "data-[state=checked]:bg-primary/50" : ""}
                  />
                  <Label htmlFor="select-all" className="font-medium cursor-pointer">
                    Todos los estilistas
                  </Label>
                </div>

                {/* Individual stylists */}
                <div className="space-y-2 max-h-32 overflow-y-auto">
                  {stylists.map((stylist) => (
                    <div key={stylist.id} className="flex items-center gap-2">
                      <Checkbox
                        id={`stylist-${stylist.id}`}
                        checked={selectedStylistIds.includes(stylist.id)}
                        onCheckedChange={() => toggleStylist(stylist.id)}
                      />
                      <Label
                        htmlFor={`stylist-${stylist.id}`}
                        className="cursor-pointer text-sm"
                      >
                        {stylist.name}
                      </Label>
                    </div>
                  ))}
                </div>
              </div>
              {selectedStylistIds.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  {selectedStylistIds.length} estilista{selectedStylistIds.length !== 1 ? "s" : ""} seleccionado{selectedStylistIds.length !== 1 ? "s" : ""}
                </p>
              )}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">
              Estilista: <strong>{stylists[0]?.name || initialStylistName}</strong>
            </div>
          )}

          {/* Date picker */}
          <div className="space-y-2">
            <Label>Fecha</Label>
            <Popover>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  className={cn(
                    "w-full justify-start text-left font-normal",
                    !blockingDate && "text-muted-foreground"
                  )}
                >
                  <CalendarIcon className="mr-2 h-4 w-4" />
                  {blockingDate ? (
                    format(blockingDate, "EEEE, d 'de' MMMM 'de' yyyy", { locale: es })
                  ) : (
                    <span>Seleccionar fecha</span>
                  )}
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-auto p-0" align="start">
                <Calendar
                  mode="single"
                  selected={blockingDate}
                  onSelect={setBlockingDate}
                  locale={es}
                  initialFocus
                />
              </PopoverContent>
            </Popover>
          </div>

          {/* Title */}
          <div className="space-y-2">
            <Label htmlFor="title">Título *</Label>
            <Input
              id="title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Ej: Vacaciones de verano"
              maxLength={200}
            />
          </div>

          {/* Event Type */}
          <div className="space-y-2">
            <Label htmlFor="event-type">Tipo de evento</Label>
            <Select value={eventType} onValueChange={setEventType}>
              <SelectTrigger id="event-type">
                <SelectValue placeholder="Selecciona el tipo" />
              </SelectTrigger>
              <SelectContent>
                {EVENT_TYPES.map((type) => (
                  <SelectItem key={type.value} value={type.value}>
                    {type.emoji} {type.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Time range */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="start-time">Hora inicio</Label>
              <Input
                id="start-time"
                type="time"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="end-time">Hora fin</Label>
              <Input
                id="end-time"
                type="time"
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
              />
            </div>
          </div>

          {/* Description */}
          <div className="space-y-2">
            <Label htmlFor="description">Descripción (opcional)</Label>
            <Textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Añade notas o detalles..."
              rows={3}
            />
          </div>

          {/* Error message */}
          {error && (
            <div className="text-sm text-red-500 bg-red-50 p-2 rounded">
              {error}
            </div>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              disabled={isSubmitting}
            >
              Cancelar
            </Button>
            <Button
              type="submit"
              disabled={isSubmitting || selectedStylistIds.length === 0}
            >
              {isSubmitting
                ? "Creando..."
                : selectedStylistIds.length > 1
                ? `Crear bloqueo (${selectedStylistIds.length})`
                : "Crear bloqueo"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
