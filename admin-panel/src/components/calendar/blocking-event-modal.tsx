"use client";

import { useState, useEffect, useCallback } from "react";
import { format, parseISO } from "date-fns";
import { es } from "date-fns/locale";
import { CalendarIcon, Trash2, Loader2 } from "lucide-react";
import { RecurrenceSelector, type RecurrenceConfig } from "./recurrence-selector";
import { ConflictWarning, type ConflictInfo } from "./conflict-warning";
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
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

interface Stylist {
  id: string;
  name: string;
  category: string;
}

interface EditingBlockingEvent {
  id: string;
  title: string;
  description: string | null;
  event_type: string;
  start_time: string;
  end_time: string;
  stylist_id: string;
}

type SeriesEditScope = "this_only" | "this_and_future" | "all";

interface BlockingEventModalProps {
  isOpen: boolean;
  onClose: () => void;
  mode: "create" | "edit";
  blockingEvent?: EditingBlockingEvent | null;
  stylistId: string;
  stylistName: string;
  selectedDate: Date | null;
  selectedStartTime?: Date | null;
  selectedEndTime?: Date | null;
  stylists?: Stylist[];
  onSuccess: () => void;
  // For series-aware edits
  editScope?: SeriesEditScope | null;
  overwriteExceptions?: boolean;
}

const EVENT_TYPES = [
  { value: "vacation", label: "Vacaciones", emoji: "🏖️" },
  { value: "meeting", label: "Reunión", emoji: "📅" },
  { value: "break", label: "Descanso", emoji: "☕" },
  { value: "general", label: "Bloqueo general", emoji: "🚫" },
  { value: "personal", label: "Asunto Propio", emoji: "💕" },
];

export function BlockingEventModal({
  isOpen,
  onClose,
  mode,
  blockingEvent,
  stylistId: initialStylistId,
  stylistName: initialStylistName,
  selectedDate,
  selectedStartTime,
  selectedEndTime,
  stylists = [],
  onSuccess,
  editScope = null,
  overwriteExceptions = false,
}: BlockingEventModalProps) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [eventType, setEventType] = useState("general");
  const [blockingDate, setBlockingDate] = useState<Date | undefined>(
    selectedDate || new Date()
  );
  const [selectedStylistIds, setSelectedStylistIds] = useState<string[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // Recurrence state
  const [recurrence, setRecurrence] = useState<RecurrenceConfig>({
    enabled: false,
    frequency: "WEEKLY",
    interval: 1,
    daysOfWeek: [],
    daysOfMonth: [],
    count: 4,
  });
  const [preview, setPreview] = useState<{
    total_instances: number;
    dates: string[];
    conflicts: ConflictInfo[];
    instances_with_conflicts: number;
  } | null>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);

  // Extract time as displayed on calendar grid (for CREATE mode)
  // FullCalendar with named timezone uses UTC-coercion: visual time is stored as UTC value
  // Per FullCalendar docs: "use UTC-flavored methods" when using named timezone without plugin
  const getVisualTime = (date: Date): string => {
    const hours = date.getUTCHours().toString().padStart(2, '0');
    const minutes = date.getUTCMinutes().toString().padStart(2, '0');
    return `${hours}:${minutes}`;
  };

  // Convert ISO-parsed Date to Madrid time for display (for EDIT mode)
  // Backend sends proper ISO strings, so we need proper timezone conversion
  const formatTimeInMadrid = (date: Date): string => {
    return new Intl.DateTimeFormat('es-ES', {
      timeZone: 'Europe/Madrid',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    }).format(date);
  };

  // Calculate default times from drag selection or use defaults
  const getDefaultStartTime = () => {
    if (selectedStartTime) {
      return getVisualTime(selectedStartTime);
    }
    return "09:00";
  };

  const getDefaultEndTime = () => {
    if (selectedEndTime) {
      return getVisualTime(selectedEndTime);
    }
    return "14:00";
  };

  const [startTime, setStartTime] = useState(getDefaultStartTime());
  const [endTime, setEndTime] = useState(getDefaultEndTime());

  // Reset form when modal opens with new data
  useEffect(() => {
    if (isOpen) {
      if (mode === "edit" && blockingEvent) {
        // Edit mode: populate from existing event
        setTitle(blockingEvent.title);
        setDescription(blockingEvent.description || "");
        setEventType(blockingEvent.event_type);

        // Parse dates from ISO strings
        const startDate = parseISO(blockingEvent.start_time);
        const endDate = parseISO(blockingEvent.end_time);

        setBlockingDate(startDate);
        setStartTime(formatTimeInMadrid(startDate));
        setEndTime(formatTimeInMadrid(endDate));
        setSelectedStylistIds([blockingEvent.stylist_id]);
      } else {
        // Create mode: use defaults
        setBlockingDate(selectedDate || new Date());
        setStartTime(getDefaultStartTime());
        setEndTime(getDefaultEndTime());

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
      }
      setError(null);
      // Reset recurrence when opening create mode
      if (mode === "create") {
        setRecurrence({
          enabled: false,
          frequency: "WEEKLY",
          interval: 1,
          daysOfWeek: [],
          daysOfMonth: [],
          count: 4,
        });
        setPreview(null);
      }
    }
  }, [isOpen, mode, blockingEvent, selectedDate, selectedStartTime, selectedEndTime, initialStylistId, stylists]);

  // Generate preview when recurrence changes
  const generatePreview = useCallback(async () => {
    if (!recurrence.enabled || !blockingDate || selectedStylistIds.length === 0) {
      setPreview(null);
      return;
    }

    // Need days selected for the pattern to work
    if (recurrence.frequency === "WEEKLY" && recurrence.daysOfWeek.length === 0) {
      setPreview(null);
      return;
    }
    if (recurrence.frequency === "MONTHLY" && recurrence.daysOfMonth.length === 0) {
      setPreview(null);
      return;
    }

    setIsLoadingPreview(true);
    try {
      const result = await api.previewRecurringBlockingEvent({
        stylist_ids: selectedStylistIds,
        title: title || "Preview",
        event_type: eventType,
        start_date: format(blockingDate, "yyyy-MM-dd"),
        start_time: startTime,
        end_time: endTime,
        recurrence: {
          frequency: recurrence.frequency,
          interval: recurrence.interval,
          days_of_week: recurrence.daysOfWeek.length > 0 ? recurrence.daysOfWeek : undefined,
          days_of_month: recurrence.daysOfMonth.length > 0 ? recurrence.daysOfMonth : undefined,
          count: recurrence.count,
        },
      });
      setPreview(result);
    } catch (err) {
      console.error("Failed to generate preview:", err);
      setPreview(null);
    } finally {
      setIsLoadingPreview(false);
    }
  }, [recurrence, blockingDate, selectedStylistIds, title, eventType, startTime, endTime]);

  // Debounce preview generation
  useEffect(() => {
    const timeout = setTimeout(generatePreview, 500);
    return () => clearTimeout(timeout);
  }, [generatePreview]);

  // Toggle individual stylist selection (only in create mode)
  const toggleStylist = (stylistId: string) => {
    if (mode === "edit") return; // Don't allow changing stylist in edit mode
    setSelectedStylistIds(prev => {
      if (prev.includes(stylistId)) {
        return prev.filter(id => id !== stylistId);
      } else {
        return [...prev, stylistId];
      }
    });
  };

  // Toggle all stylists (only in create mode)
  const toggleAll = (checked: boolean) => {
    if (mode === "edit") return;
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
      if (mode === "edit" && blockingEvent) {
        // Update existing blocking event
        if (editScope && editScope !== "this_only") {
          // Use series-aware update
          await api.updateBlockingEventWithScope(
            blockingEvent.id,
            {
              title: title.trim(),
              description: description.trim() || undefined,
              start_time: startDateTime,
              end_time: endDateTime,
              event_type: eventType,
            },
            editScope,
            overwriteExceptions
          );
        } else {
          // Regular single-event update (marks as exception automatically if part of series)
          await api.updateBlockingEvent(blockingEvent.id, {
            title: title.trim(),
            description: description.trim() || undefined,
            start_time: startDateTime,
            end_time: endDateTime,
            event_type: eventType,
          });
        }
      } else if (recurrence.enabled) {
        // Create recurring blocking events
        // Validate recurrence has days selected
        if (recurrence.frequency === "WEEKLY" && recurrence.daysOfWeek.length === 0) {
          setError("Selecciona al menos un día de la semana");
          setIsSubmitting(false);
          return;
        }
        if (recurrence.frequency === "MONTHLY" && recurrence.daysOfMonth.length === 0) {
          setError("Selecciona al menos un día del mes");
          setIsSubmitting(false);
          return;
        }

        await api.createRecurringBlockingEvent(
          {
            stylist_ids: selectedStylistIds,
            title: title.trim(),
            description: description.trim() || undefined,
            event_type: eventType,
            start_date: dateStr,
            start_time: startTime,
            end_time: endTime,
            recurrence: {
              frequency: recurrence.frequency,
              interval: recurrence.interval,
              days_of_week: recurrence.daysOfWeek.length > 0 ? recurrence.daysOfWeek : undefined,
              days_of_month: recurrence.daysOfMonth.length > 0 ? recurrence.daysOfMonth : undefined,
              count: recurrence.count,
            },
          },
          preview?.conflicts && preview.conflicts.length > 0 // ignoreConflicts if there are conflicts
        );
      } else {
        // Create single blocking event
        await api.createBlockingEvent({
          stylist_ids: selectedStylistIds,
          title: title.trim(),
          description: description.trim() || undefined,
          start_time: startDateTime,
          end_time: endDateTime,
          event_type: eventType,
        });
      }

      onSuccess();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Error al ${mode === "edit" ? "actualizar" : "crear"} el evento`);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!blockingEvent) return;

    setIsSubmitting(true);
    try {
      await api.deleteBlockingEvent(blockingEvent.id);
      onSuccess();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al eliminar el evento");
    } finally {
      setIsSubmitting(false);
      setShowDeleteConfirm(false);
    }
  };

  // Get stylist name for edit mode
  const getEditStylistName = () => {
    if (blockingEvent) {
      const stylist = stylists.find(s => s.id === blockingEvent.stylist_id);
      return stylist?.name || initialStylistName;
    }
    return initialStylistName;
  };

  return (
    <>
      <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
        <DialogContent className={cn(
          "sm:max-w-[425px] max-h-[85vh] overflow-y-auto",
          mode === "create" && recurrence.enabled && "sm:max-w-[520px]"
        )}>
          <DialogHeader>
            <DialogTitle>
              {mode === "edit" ? "Editar evento de bloqueo" : "Crear evento de bloqueo"}
            </DialogTitle>
          </DialogHeader>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Stylist selection - different behavior for create vs edit */}
            {mode === "edit" ? (
              <div className="text-sm text-muted-foreground">
                Estilista: <strong>{getEditStylistName()}</strong>
              </div>
            ) : stylists.length > 1 ? (
              <div className="space-y-2">
                <Label>Estilistas</Label>
                <div className="border rounded-md p-3 space-y-2">
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

            {/* Recurrence selector - only in create mode */}
            {mode === "create" && blockingDate && (
              <RecurrenceSelector
                selectedDate={blockingDate}
                value={recurrence}
                onChange={setRecurrence}
              />
            )}

            {/* Preview info and conflicts */}
            {mode === "create" && recurrence.enabled && (
              <div className="space-y-3">
                {isLoadingPreview && (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Calculando fechas...
                  </div>
                )}
                {!isLoadingPreview && preview && (
                  <>
                    <div className="text-sm text-muted-foreground p-2 bg-muted rounded">
                      Se crearán <strong>{preview.total_instances}</strong> bloqueos en total
                      {preview.total_instances > 0 && selectedStylistIds.length > 1 && (
                        <> ({Math.ceil(preview.total_instances / selectedStylistIds.length)} fechas × {selectedStylistIds.length} estilistas)</>
                      )}
                    </div>
                    {preview.conflicts.length > 0 && (
                      <ConflictWarning conflicts={preview.conflicts} />
                    )}
                  </>
                )}
              </div>
            )}

            {/* Error message */}
            {error && (
              <div className="text-sm text-red-500 bg-red-50 p-2 rounded">
                {error}
              </div>
            )}

            <DialogFooter className="gap-2 sm:gap-0">
              {mode === "edit" && (
                <Button
                  type="button"
                  variant="destructive"
                  onClick={() => setShowDeleteConfirm(true)}
                  disabled={isSubmitting}
                  className="mr-auto"
                >
                  <Trash2 className="h-4 w-4 mr-1" />
                  Eliminar
                </Button>
              )}
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
                  ? mode === "edit" ? "Guardando..." : "Creando..."
                  : mode === "edit"
                  ? "Guardar cambios"
                  : recurrence.enabled && preview
                  ? `Crear ${preview.total_instances} bloqueos`
                  : selectedStylistIds.length > 1
                  ? `Crear bloqueo (${selectedStylistIds.length})`
                  : "Crear bloqueo"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Eliminar este bloqueo?</AlertDialogTitle>
            <AlertDialogDescription>
              Esta acción no se puede deshacer. El bloqueo &quot;{blockingEvent?.title}&quot; será eliminado permanentemente.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isSubmitting}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={isSubmitting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {isSubmitting ? "Eliminando..." : "Eliminar"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
