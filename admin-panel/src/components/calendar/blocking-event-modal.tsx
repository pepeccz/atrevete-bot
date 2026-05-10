"use client";

import { useState, useEffect, useCallback } from "react";
import { format, parseISO, addMonths } from "date-fns";
import { es } from "date-fns/locale";
import { CalendarIcon, Trash2, Loader2, Lock } from "lucide-react";
import { RecurrenceSelector, type RecurrenceConfig } from "./recurrence-selector";
import { RecurrencePreviewCalendar } from "./recurrence-preview-calendar";
import { ConflictWarning, type ConflictInfo } from "./conflict-warning";
import { EVENT_TYPES } from "./event-types";
import { expandRecurrence } from "@/lib/recurrence-utils";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import api, { ApiRequestError } from "@/lib/api";

interface Stylist {
  id: string;
  name: string;
  category: string | null;
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

// Category metadata for grouping the multi-stylist checklist
const CATEGORY_LABELS: Record<string, string> = {
  HAIRDRESSING: "Peluquería",
  AESTHETICS: "Estética",
  BOTH: "Mixto",
  __null__: "Sin categoría",
};

// Returns ordered category keys present in a stylist list
function groupStylistsByCategory(
  stylists: Stylist[]
): Array<{ key: string; label: string; list: Stylist[] }> {
  const order = ["HAIRDRESSING", "AESTHETICS", "BOTH"];
  const buckets: Record<string, Stylist[]> = {};

  for (const s of stylists) {
    const key = s.category ?? "__null__";
    if (!buckets[key]) buckets[key] = [];
    buckets[key].push(s);
  }

  const result: Array<{ key: string; label: string; list: Stylist[] }> = [];

  // Known-order categories first
  for (const k of order) {
    if (buckets[k]) {
      result.push({ key: k, label: CATEGORY_LABELS[k], list: buckets[k] });
    }
  }

  // Remaining unknown keys (including __null__)
  for (const k of Object.keys(buckets)) {
    if (!order.includes(k)) {
      result.push({ key: k, label: CATEGORY_LABELS[k] ?? k, list: buckets[k] });
    }
  }

  return result;
}

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

  // Single-event conflict state (S2.8)
  const [singleConflicts, setSingleConflicts] = useState<ConflictInfo[]>([]);
  const [ignoreConflicts, setIgnoreConflicts] = useState(false);

  // Recurrence state
  const [recurrence, setRecurrence] = useState<RecurrenceConfig>({
    enabled: false,
    frequency: "WEEKLY",
    interval: 1,
    daysOfWeek: [],
    daysOfMonth: [],
    count: 0,
    endDate: undefined,
  });
  const [preview, setPreview] = useState<{
    total_instances: number;
    dates: string[];
    conflicts: ConflictInfo[];
    instances_with_conflicts: number;
  } | null>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);

  // Convert Date to Madrid time string (HH:MM) for display and form defaults
  const formatTimeInMadrid = (date: Date): string => {
    return new Intl.DateTimeFormat("es-ES", {
      timeZone: "Europe/Madrid",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  };

  const getDefaultStartTime = () => {
    if (selectedStartTime) return formatTimeInMadrid(selectedStartTime);
    return "09:00";
  };

  const getDefaultEndTime = () => {
    if (selectedEndTime) return formatTimeInMadrid(selectedEndTime);
    return "14:00";
  };

  const [startTime, setStartTime] = useState(getDefaultStartTime());
  const [endTime, setEndTime] = useState(getDefaultEndTime());

  // Reset single-event conflicts when key fields change
  const resetConflicts = () => {
    setSingleConflicts([]);
    setIgnoreConflicts(false);
  };

  // Reset form when modal opens with new data
  useEffect(() => {
    if (isOpen) {
      if (mode === "edit" && blockingEvent) {
        setTitle(blockingEvent.title);
        setDescription(blockingEvent.description || "");
        setEventType(blockingEvent.event_type);

        const startDate = parseISO(blockingEvent.start_time);
        const endDate = parseISO(blockingEvent.end_time);

        setBlockingDate(startDate);
        setStartTime(formatTimeInMadrid(startDate));
        setEndTime(formatTimeInMadrid(endDate));
        setSelectedStylistIds([blockingEvent.stylist_id]);
      } else {
        setBlockingDate(selectedDate || new Date());
        setStartTime(getDefaultStartTime());
        setEndTime(getDefaultEndTime());

        if (stylists.length > 1) {
          setSelectedStylistIds(stylists.map((s) => s.id));
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
      resetConflicts();
      if (mode === "create") {
        const defaultEndDate = selectedDate
          ? addMonths(selectedDate, 1)
          : addMonths(new Date(), 1);
        setRecurrence({
          enabled: false,
          frequency: "WEEKLY",
          interval: 1,
          daysOfWeek: [],
          daysOfMonth: [],
          count: 0,
          endDate: defaultEndDate,
        });
        setPreview(null);
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, mode, blockingEvent, selectedDate, selectedStartTime, selectedEndTime, initialStylistId, stylists]);

  // Generate preview when recurrence changes
  const generatePreview = useCallback(async () => {
    if (!recurrence.enabled || !blockingDate || selectedStylistIds.length === 0) {
      setPreview(null);
      return;
    }

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
          days_of_month:
            recurrence.daysOfMonth.length > 0 ? recurrence.daysOfMonth : undefined,
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
    if (mode === "edit") return;
    setSelectedStylistIds((prev) => {
      if (prev.includes(stylistId)) {
        return prev.filter((id) => id !== stylistId);
      } else {
        return [...prev, stylistId];
      }
    });
    resetConflicts();
  };

  // Toggle all stylists (only in create mode)
  const toggleAll = (checked: boolean) => {
    if (mode === "edit") return;
    if (checked) {
      setSelectedStylistIds(stylists.map((s) => s.id));
    } else {
      setSelectedStylistIds([]);
    }
    resetConflicts();
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

    const dateStr = format(blockingDate, "yyyy-MM-dd");
    const startDateTime = `${dateStr}T${startTime}:00`;
    const endDateTime = `${dateStr}T${endTime}:00`;

    if (endTime <= startTime) {
      setError("La hora de fin debe ser posterior a la hora de inicio");
      return;
    }

    setIsSubmitting(true);

    try {
      if (mode === "edit" && blockingEvent) {
        if (editScope && editScope !== "this_only") {
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
          await api.updateBlockingEvent(blockingEvent.id, {
            title: title.trim(),
            description: description.trim() || undefined,
            start_time: startDateTime,
            end_time: endDateTime,
            event_type: eventType,
          });
        }
      } else if (recurrence.enabled) {
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
              days_of_week:
                recurrence.daysOfWeek.length > 0 ? recurrence.daysOfWeek : undefined,
              days_of_month:
                recurrence.daysOfMonth.length > 0 ? recurrence.daysOfMonth : undefined,
              count: recurrence.count,
            },
          },
          preview?.conflicts && preview.conflicts.length > 0
        );
      } else {
        // Single-event create — conflict-check flow (S2.8)
        const payload = {
          stylist_ids: selectedStylistIds,
          title: title.trim(),
          description: description.trim() || undefined,
          start_time: startDateTime,
          end_time: endDateTime,
          event_type: eventType,
        };

        try {
          await api.createBlockingEvent(payload, { ignoreConflicts });
        } catch (apiErr) {
          if (apiErr instanceof ApiRequestError && apiErr.status === 409) {
            const detail = apiErr.detail as { conflicts?: ConflictInfo[] } | null;
            const conflicts = detail?.conflicts ?? [];
            setSingleConflicts(conflicts);
            setIgnoreConflicts(true);
            setIsSubmitting(false);
            return;
          }
          throw apiErr;
        }
      }

      onSuccess();
      onClose();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : `Error al ${mode === "edit" ? "actualizar" : "crear"} el evento`
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!blockingEvent) return;

    setIsSubmitting(true);
    try {
      if (editScope && editScope !== "this_only") {
        await api.deleteBlockingEventWithScope(blockingEvent.id, editScope);
      } else {
        await api.deleteBlockingEvent(blockingEvent.id);
      }
      onSuccess();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al eliminar el evento");
    } finally {
      setIsSubmitting(false);
      setShowDeleteConfirm(false);
    }
  };

  const getEditStylistName = () => {
    if (blockingEvent) {
      const stylist = stylists.find((s) => s.id === blockingEvent.stylist_id);
      return stylist?.name || initialStylistName;
    }
    return initialStylistName;
  };

  // Grouped stylist data for multi-select checklist
  const groupedStylists = groupStylistsByCategory(stylists);

  // Submit button label
  const submitLabel = (() => {
    if (isSubmitting) return mode === "edit" ? "Guardando..." : "Creando...";
    if (singleConflicts.length > 0) return "Crear de todos modos";
    if (mode === "edit") return "Guardar cambios";
    if (recurrence.enabled && preview) return `Crear ${preview.total_instances} bloqueos`;
    if (selectedStylistIds.length > 1) return `Crear bloqueo (${selectedStylistIds.length})`;
    return "Crear bloqueo";
  })();

  return (
    <>
      <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
        {/* S2.3 — fixed 640px width, no conditional jump */}
        <DialogContent className="sm:max-w-[640px] max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {mode === "edit"
                ? editScope === "all"
                  ? "Editar toda la serie"
                  : editScope === "this_and_future"
                  ? "Editar este y siguientes"
                  : "Editar evento de bloqueo"
                : "Crear evento de bloqueo"}
            </DialogTitle>
          </DialogHeader>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* S2.4 — 2-column grid layout */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4">
              {/* LEFT column: Fecha, Hora inicio, Hora fin */}
              <div className="space-y-4">
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
                        onSelect={(d) => {
                          setBlockingDate(d);
                          resetConflicts();
                        }}
                        locale={es}
                        initialFocus
                      />
                    </PopoverContent>
                  </Popover>
                </div>

                {/* Time range */}
                <div className="space-y-2">
                  <Label htmlFor="start-time">Hora inicio</Label>
                  <Input
                    id="start-time"
                    type="time"
                    value={startTime}
                    onChange={(e) => {
                      setStartTime(e.target.value);
                      resetConflicts();
                    }}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="end-time">Hora fin</Label>
                  <Input
                    id="end-time"
                    type="time"
                    value={endTime}
                    onChange={(e) => {
                      setEndTime(e.target.value);
                      resetConflicts();
                    }}
                  />
                </div>
              </div>

              {/* RIGHT column: Estilistas, Tipo, Título, Descripción */}
              <div className="space-y-4">
                {/* Stylist selection */}
                {mode === "edit" ? (
                  // S2.5 — read-only with Lock icon + tooltip
                  <div className="space-y-2">
                    <Label>Estilista</Label>
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="flex items-center gap-1 text-sm text-muted-foreground cursor-default select-none">
                            <Lock className="h-4 w-4 flex-shrink-0" />
                            <strong>{getEditStylistName()}</strong>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>
                          Para reasignar, eliminá y creá un bloqueo nuevo
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                ) : stylists.length > 1 ? (
                  // S2.6 — multi-stylist checklist grouped by category
                  <div className="space-y-2">
                    <Label>Estilistas</Label>
                    <div className="border rounded-md p-3 space-y-3">
                      {/* Master "Todos" toggle */}
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

                      {/* Grouped sections */}
                      <div className="space-y-3 max-h-40 overflow-y-auto">
                        {groupedStylists.map(({ key, label, list }) => (
                          <div key={key}>
                            <div className="text-[10px] uppercase tracking-widest font-semibold text-muted-foreground mb-1">
                              {label}
                            </div>
                            <div className="space-y-1 pl-2">
                              {list.map((stylist) => (
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
                        ))}
                      </div>
                    </div>
                    {selectedStylistIds.length > 0 && (
                      <p className="text-xs text-muted-foreground">
                        {selectedStylistIds.length} estilista
                        {selectedStylistIds.length !== 1 ? "s" : ""} seleccionado
                        {selectedStylistIds.length !== 1 ? "s" : ""}
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="space-y-2">
                    <Label>Estilista</Label>
                    <div className="text-sm text-muted-foreground">
                      <strong>{stylists[0]?.name || initialStylistName}</strong>
                    </div>
                  </div>
                )}

                {/* S2.2 — Event Type with lucide icons */}
                <div className="space-y-2">
                  <Label htmlFor="event-type">Tipo de evento</Label>
                  <Select value={eventType} onValueChange={setEventType}>
                    <SelectTrigger id="event-type">
                      <SelectValue placeholder="Selecciona el tipo" />
                    </SelectTrigger>
                    <SelectContent>
                      {EVENT_TYPES.map((type) => {
                        const Icon = type.Icon;
                        return (
                          <SelectItem key={type.value} value={type.value}>
                            <span className="flex items-center gap-2">
                              <Icon className="h-4 w-4" />
                              {type.label}
                            </span>
                          </SelectItem>
                        );
                      })}
                    </SelectContent>
                  </Select>
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
              </div>

              {/* Recurrence: full-width, create mode only (S2.4) */}
              {mode === "create" && blockingDate && (
                <div className="col-span-full">
                  <RecurrenceSelector
                    selectedDate={blockingDate}
                    value={recurrence}
                    onChange={setRecurrence}
                  />
                </div>
              )}

              {/* Recurrence preview: full-width */}
              {mode === "create" && recurrence.enabled && blockingDate && recurrence.endDate && (
                <div className="col-span-full space-y-3">
                  {(() => {
                    const hasDays =
                      recurrence.frequency === "WEEKLY"
                        ? recurrence.daysOfWeek.length > 0
                        : recurrence.daysOfMonth.length > 0;

                    if (!hasDays) return null;

                    const previewDates = expandRecurrence(
                      blockingDate,
                      recurrence.endDate,
                      {
                        frequency: recurrence.frequency,
                        interval: recurrence.interval,
                        daysOfWeek: recurrence.daysOfWeek,
                        daysOfMonth: recurrence.daysOfMonth,
                      },
                      52
                    );

                    if (previewDates.length === 0) return null;

                    return (
                      <RecurrencePreviewCalendar
                        blockedDates={previewDates}
                        startDate={blockingDate}
                        endDate={recurrence.endDate}
                        conflicts={preview?.conflicts || []}
                        monthsToShow={3}
                      />
                    );
                  })()}

                  {isLoadingPreview && (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Verificando conflictos...
                    </div>
                  )}

                  {!isLoadingPreview && preview && preview.conflicts.length > 0 && (
                    <ConflictWarning conflicts={preview.conflicts} />
                  )}

                  {preview && preview.total_instances > 0 && selectedStylistIds.length > 1 && (
                    <div className="text-xs text-muted-foreground">
                      Total con {selectedStylistIds.length} estilistas:{" "}
                      {preview.total_instances} bloqueos
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* S2.8 — Single-event conflict warning (above footer) */}
            {singleConflicts.length > 0 && (
              <div className="mt-4">
                <ConflictWarning conflicts={singleConflicts} />
              </div>
            )}

            {/* Error message */}
            {error && (
              <div className="text-sm text-red-500 bg-red-50 p-2 rounded">{error}</div>
            )}

            {/* S2.7 — Footer redesign: destructive left, actions right, with border-t */}
            <div className="flex justify-between items-center pt-4 border-t border-border">
              {mode === "edit" && (
                <Button
                  type="button"
                  variant="destructive"
                  onClick={() => setShowDeleteConfirm(true)}
                  disabled={isSubmitting}
                  className="flex-shrink-0"
                >
                  <Trash2 className="h-4 w-4 mr-1" />
                  Eliminar
                </Button>
              )}
              <div className={cn("flex gap-2", mode !== "edit" && "ml-auto")}>
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
                  variant={singleConflicts.length > 0 ? "destructive" : "default"}
                >
                  {submitLabel}
                </Button>
              </div>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {editScope === "all"
                ? "¿Eliminar toda la serie?"
                : editScope === "this_and_future"
                ? "¿Eliminar este y los siguientes bloqueos?"
                : "¿Eliminar este bloqueo?"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {editScope === "all"
                ? `Esta acción no se puede deshacer. Se eliminarán TODOS los bloqueos de la serie "${blockingEvent?.title}".`
                : editScope === "this_and_future"
                ? `Esta acción no se puede deshacer. Se eliminará este bloqueo y todos los siguientes de la serie "${blockingEvent?.title}".`
                : `Esta acción no se puede deshacer. El bloqueo "${blockingEvent?.title}" será eliminado permanentemente.`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isSubmitting}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={isSubmitting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {isSubmitting
                ? "Eliminando..."
                : editScope === "all"
                ? "Eliminar serie"
                : editScope === "this_and_future"
                ? "Eliminar estos"
                : "Eliminar"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
