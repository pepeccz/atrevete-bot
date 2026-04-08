"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Calendar,
  CheckCircle2,
  XCircle,
  RefreshCw,
  LogOut,
  ExternalLink,
  Plus,
  Pencil,
  Trash2,
  Loader2,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Header } from "@/components/layout/header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { toast } from "sonner";
import api, { ApiRequestError } from "@/lib/api";
import type { GoogleCalendar } from "@/lib/types";

// Common European timezones for the selector
const COMMON_TIMEZONES = [
  "Europe/Madrid",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Europe/Rome",
  "Europe/Lisbon",
  "Europe/Amsterdam",
  "Europe/Brussels",
  "Europe/Warsaw",
  "Europe/Bucharest",
  "America/New_York",
  "America/Chicago",
  "America/Los_Angeles",
  "America/Argentina/Buenos_Aires",
  "America/Bogota",
  "America/Mexico_City",
  "Asia/Tokyo",
  "Asia/Shanghai",
  "UTC",
];

// ─── Create Calendar Dialog ──────────────────────────────────────────────────

interface CreateCalendarDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}

function CreateCalendarDialog({ open, onOpenChange, onCreated }: CreateCalendarDialogProps) {
  const [summary, setSummary] = useState("");
  const [description, setDescription] = useState("");
  const [timeZone, setTimeZone] = useState("Europe/Madrid");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset form when dialog opens
  useEffect(() => {
    if (open) {
      setSummary("");
      setDescription("");
      setTimeZone("Europe/Madrid");
      setError(null);
    }
  }, [open]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!summary.trim()) {
      setError("El nombre del calendario es obligatorio");
      return;
    }

    setLoading(true);
    try {
      await api.createGoogleCalendar({
        summary: summary.trim(),
        ...(description.trim() ? { description: description.trim() } : {}),
        ...(timeZone ? { timeZone } : {}),
      });
      toast.success("Calendario creado correctamente");
      onOpenChange(false);
      onCreated();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Error desconocido";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Crear nuevo calendario</DialogTitle>
            <DialogDescription>
              Se creará un nuevo calendario secundario en tu cuenta de Google.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            {error && (
              <div className="rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2 text-sm text-destructive">
                {error}
              </div>
            )}

            <div className="space-y-1.5">
              <Label htmlFor="create-summary">
                Nombre <span className="text-destructive">*</span>
              </Label>
              <Input
                id="create-summary"
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                placeholder="Ej: Calendario de María"
                disabled={loading}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="create-description">Descripción (opcional)</Label>
              <Textarea
                id="create-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Descripción del calendario..."
                rows={3}
                disabled={loading}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="create-timezone">Zona horaria</Label>
              <Select value={timeZone} onValueChange={setTimeZone} disabled={loading}>
                <SelectTrigger id="create-timezone">
                  <SelectValue placeholder="Selecciona zona horaria" />
                </SelectTrigger>
                <SelectContent>
                  {COMMON_TIMEZONES.map((tz) => (
                    <SelectItem key={tz} value={tz}>
                      {tz}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={loading}
            >
              Cancelar
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Creando...
                </>
              ) : (
                "Crear"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ─── Edit Calendar Dialog ────────────────────────────────────────────────────

interface EditCalendarDialogProps {
  calendar: GoogleCalendar | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: () => void;
}

function EditCalendarDialog({
  calendar,
  open,
  onOpenChange,
  onUpdated,
}: EditCalendarDialogProps) {
  const [summary, setSummary] = useState("");
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Pre-fill form when calendar changes or dialog opens
  useEffect(() => {
    if (open && calendar) {
      setSummary(calendar.summary);
      setDescription(calendar.description ?? "");
      setError(null);
    }
  }, [open, calendar]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!calendar) return;
    setError(null);

    setLoading(true);
    try {
      await api.updateGoogleCalendar(calendar.id, {
        ...(summary.trim() !== calendar.summary ? { summary: summary.trim() } : {}),
        ...(description.trim() !== (calendar.description ?? "")
          ? { description: description.trim() }
          : {}),
      });
      toast.success("Calendario actualizado correctamente");
      onOpenChange(false);
      onUpdated();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Error desconocido";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Editar calendario</DialogTitle>
            <DialogDescription>
              Modificá el nombre o la descripción del calendario.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            {error && (
              <div className="rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2 text-sm text-destructive">
                {error}
              </div>
            )}

            <div className="space-y-1.5">
              <Label htmlFor="edit-summary">Nombre</Label>
              <Input
                id="edit-summary"
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                disabled={loading}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="edit-description">Descripción (opcional)</Label>
              <Textarea
                id="edit-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                disabled={loading}
              />
            </div>

            {calendar?.timeZone && (
              <div className="space-y-1.5">
                <Label>Zona horaria</Label>
                <p className="text-sm text-muted-foreground bg-muted rounded-md px-3 py-2">
                  {calendar.timeZone}
                  <span className="ml-2 text-xs">(no se puede cambiar después de crear)</span>
                </p>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={loading}
            >
              Cancelar
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Guardando...
                </>
              ) : (
                "Guardar cambios"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ─── Delete Calendar AlertDialog ─────────────────────────────────────────────

interface DeleteCalendarDialogProps {
  calendar: GoogleCalendar | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleted: () => void;
}

function DeleteCalendarDialog({
  calendar,
  open,
  onOpenChange,
  onDeleted,
}: DeleteCalendarDialogProps) {
  const [loading, setLoading] = useState(false);
  const [conflictError, setConflictError] = useState<string | null>(null);
  const [conflictStylistNames, setConflictStylistNames] = useState<string[]>([]);

  // Reset on open
  useEffect(() => {
    if (open) {
      setConflictError(null);
      setConflictStylistNames([]);
    }
  }, [open]);

  const handleDelete = async () => {
    if (!calendar) return;
    setConflictError(null);
    setConflictStylistNames([]);
    setLoading(true);

    try {
      await api.deleteGoogleCalendar(calendar.id);
      toast.success("Calendario eliminado correctamente");
      onOpenChange(false);
      onDeleted();
    } catch (err) {
      if (err instanceof ApiRequestError) {
        if (err.status === 409) {
          // Conflict: calendar assigned to stylists — show names if available
          setConflictError(err.message);
          if (err.stylistNames?.length) {
            setConflictStylistNames(err.stylistNames);
          }
          return; // Stay open to show the error
        }
        if (err.status === 403) {
          setConflictError("No se puede eliminar el calendario principal");
          return;
        }
      }
      toast.error(
        `Error al eliminar: ${err instanceof Error ? err.message : "Error desconocido"}`
      );
      onOpenChange(false);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Eliminar calendario</AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="space-y-3">
              <p>
                ¿Estás seguro que querés eliminar el calendario{" "}
                <span className="font-semibold text-foreground">
                  &ldquo;{calendar?.summary}&rdquo;
                </span>
                ? Esta acción no se puede deshacer.
              </p>
              {conflictError && (
                <div className="rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2 text-sm text-destructive space-y-1">
                  <p>{conflictError}</p>
                  {conflictStylistNames.length > 0 && (
                    <ul className="list-disc list-inside pl-1">
                      {conflictStylistNames.map((name) => (
                        <li key={name}>{name}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={loading}>Cancelar</AlertDialogCancel>
          {!conflictError && (
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault();
                handleDelete();
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={loading}
            >
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Eliminando...
                </>
              ) : (
                "Eliminar"
              )}
            </AlertDialogAction>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function GoogleCalendarSettingsPage() {
  const searchParams = useSearchParams();

  // Connection state
  const [status, setStatus] = useState<{ connected: boolean; email: string | null; connected_at: string | null; token_healthy: boolean; scopes: string[] } | null>(null);
  const [calendars, setCalendars] = useState<GoogleCalendar[]>([]);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [loadingCalendars, setLoadingCalendars] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [disconnectDialogOpen, setDisconnectDialogOpen] = useState(false);

  // CRUD dialog state
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [selectedCalendar, setSelectedCalendar] = useState<GoogleCalendar | null>(null);

  const fetchStatus = useCallback(async () => {
    setLoadingStatus(true);
    try {
      const data = await api.getGoogleCalendarStatus();
      setStatus(data);
    } catch (error) {
      toast.error(
        `Error al cargar el estado de Google Calendar: ${error instanceof Error ? error.message : "Error desconocido"}`
      );
    } finally {
      setLoadingStatus(false);
    }
  }, []);

  const fetchCalendars = useCallback(async () => {
    setLoadingCalendars(true);
    try {
      const data = await api.getGoogleCalendars();
      setCalendars(data.calendars);
    } catch {
      // Silently fail — calendars list is informational, not critical
      setCalendars([]);
    } finally {
      setLoadingCalendars(false);
    }
  }, []);

  // Handle ?connected=true and ?error=... params on page load
  useEffect(() => {
    const connected = searchParams.get("connected");
    const error = searchParams.get("error");

    if (connected === "true") {
      toast.success("Google Calendar conectado correctamente");
    } else if (error) {
      const messages: Record<string, string> = {
        state_mismatch: "Error de seguridad: el estado de la solicitud no coincide",
        missing_code: "No se recibio el codigo de autorización de Google",
        token_exchange_failed: "No se pudo intercambiar el codigo por un token",
        missing_state: "Error de seguridad: falta el parametro de estado",
      };
      toast.error(messages[error] ?? `Error al conectar Google Calendar: ${error}`);
    }
  }, [searchParams]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // Load calendars when connected
  useEffect(() => {
    if (status?.connected) {
      fetchCalendars();
    }
  }, [status?.connected, fetchCalendars]);

  const handleConnect = async () => {
    setConnecting(true);
    try {
      const { url, state } = await api.getGoogleCalendarAuthUrl();
      // Persist state in sessionStorage for CSRF validation on callback
      sessionStorage.setItem("google_oauth_state", state);
      window.location.href = url;
    } catch (error) {
      toast.error(
        `No se pudo iniciar la conexion: ${error instanceof Error ? error.message : "Error desconocido"}`
      );
      setConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    setDisconnecting(true);
    try {
      await api.disconnectGoogleCalendar();
      toast.success("Google Calendar desconectado correctamente");
      setCalendars([]);
      await fetchStatus();
    } catch (error) {
      toast.error(
        `Error al desconectar: ${error instanceof Error ? error.message : "Error desconocido"}`
      );
    } finally {
      setDisconnecting(false);
      setDisconnectDialogOpen(false);
    }
  };

  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return "—";
    return new Date(dateStr).toLocaleString("es-ES", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const openEdit = (calendar: GoogleCalendar) => {
    setSelectedCalendar(calendar);
    setEditOpen(true);
  };

  const openDelete = (calendar: GoogleCalendar) => {
    setSelectedCalendar(calendar);
    setDeleteOpen(true);
  };

  return (
    <TooltipProvider>
      <div className="flex flex-col">
        <Header
          title="Google Calendar"
          description="Conecta tu cuenta de Google para sincronizar los calendarios de los estilistas"
          action={
            <Button
              variant="outline"
              onClick={fetchStatus}
              disabled={loadingStatus}
            >
              <RefreshCw
                className={`h-4 w-4 mr-2 ${loadingStatus ? "animate-spin" : ""}`}
              />
              Actualizar
            </Button>
          }
        />

        <div className="flex-1 p-4 md:p-6 space-y-6">
          {/* Connection status card */}
          <Card>
            <CardHeader>
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-blue-500 flex items-center justify-center">
                  <Calendar className="h-5 w-5 text-white" />
                </div>
                <div>
                  <CardTitle>Estado de la conexion</CardTitle>
                  <CardDescription>
                    Conecta tu cuenta de Google para habilitar la seleccion de calendarios en los estilistas
                  </CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {loadingStatus ? (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  <span>Cargando estado...</span>
                </div>
              ) : status?.connected ? (
                <div className="space-y-4">
                  {/* Connected state */}
                  <div className="flex items-start justify-between gap-4">
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <CheckCircle2 className="h-5 w-5 text-green-500" />
                        <Badge variant="secondary" className="bg-green-100 text-green-800 border-green-200">
                          Conectado
                        </Badge>
                        {!status.token_healthy && (
                          <Badge variant="destructive">Token expirado</Badge>
                        )}
                      </div>
                      {status.email && (
                        <p className="text-sm text-muted-foreground">
                          Cuenta:{" "}
                          <span className="font-medium text-foreground">
                            {status.email}
                          </span>
                        </p>
                      )}
                      {status.connected_at && (
                        <p className="text-sm text-muted-foreground">
                          Conectado el: {formatDate(status.connected_at)}
                        </p>
                      )}
                      {status.scopes.length > 0 && (
                        <p className="text-xs text-muted-foreground">
                          Permisos: {status.scopes.join(", ")}
                        </p>
                      )}
                    </div>
                    <Button
                      variant="outline"
                      className="text-destructive border-destructive hover:bg-destructive hover:text-destructive-foreground"
                      onClick={() => setDisconnectDialogOpen(true)}
                      disabled={disconnecting}
                    >
                      <LogOut className="h-4 w-4 mr-2" />
                      Desconectar
                    </Button>
                  </div>
                </div>
              ) : (
                /* Disconnected state */
                <div className="space-y-4">
                  <div className="flex items-center gap-2">
                    <XCircle className="h-5 w-5 text-muted-foreground" />
                    <Badge variant="outline" className="text-muted-foreground">
                      No conectado
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Conecta tu cuenta de Google para poder seleccionar calendarios al crear o editar estilistas.
                    Sin esta conexion, deberas introducir los IDs de calendario manualmente.
                  </p>
                  <Button
                    onClick={handleConnect}
                    disabled={connecting}
                    className="gap-2"
                  >
                    {connecting ? (
                      <>
                        <RefreshCw className="h-4 w-4 animate-spin" />
                        Redirigiendo a Google...
                      </>
                    ) : (
                      <>
                        <ExternalLink className="h-4 w-4" />
                        Conectar Google Calendar
                      </>
                    )}
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Calendar list — shown only when connected */}
          {status?.connected && (
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>Calendarios disponibles</CardTitle>
                    <CardDescription>
                      Lista de calendarios accesibles con tu cuenta de Google.
                      Usa estos IDs al asignar calendarios a los estilistas.
                    </CardDescription>
                  </div>
                  <Button onClick={() => setCreateOpen(true)} className="gap-2">
                    <Plus className="h-4 w-4" />
                    Nuevo Calendario
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                {loadingCalendars ? (
                  <div className="flex items-center gap-2 text-muted-foreground py-4">
                    <RefreshCw className="h-4 w-4 animate-spin" />
                    <span>Cargando calendarios...</span>
                  </div>
                ) : calendars.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-4">
                    No se encontraron calendarios accesibles con esta cuenta.
                  </p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Nombre</TableHead>
                        <TableHead>Descripción</TableHead>
                        <TableHead>Zona horaria</TableHead>
                        <TableHead>ID del Calendario</TableHead>
                        <TableHead>Rol de acceso</TableHead>
                        <TableHead>Color</TableHead>
                        <TableHead className="text-right">Acciones</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {calendars.map((calendar) => (
                        <TableRow key={calendar.id}>
                          <TableCell className="font-medium">
                            <div className="flex items-center gap-2">
                              {calendar.summary}
                              {calendar.primary && (
                                <Badge variant="secondary" className="text-xs">
                                  Principal
                                </Badge>
                              )}
                            </div>
                          </TableCell>
                          <TableCell className="text-muted-foreground text-sm max-w-[200px] truncate">
                            {calendar.description || (
                              <span className="text-muted-foreground/50">—</span>
                            )}
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {calendar.timeZone || "—"}
                          </TableCell>
                          <TableCell>
                            <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">
                              {calendar.id}
                            </code>
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline">{calendar.access_role}</Badge>
                          </TableCell>
                          <TableCell>
                            {calendar.background_color ? (
                              <div className="flex items-center gap-2">
                                <div
                                  className="w-4 h-4 rounded-full border"
                                  style={{
                                    backgroundColor: calendar.background_color,
                                  }}
                                />
                                <span className="text-xs text-muted-foreground">
                                  {calendar.background_color}
                                </span>
                              </div>
                            ) : (
                              <span className="text-muted-foreground text-xs">—</span>
                            )}
                          </TableCell>
                          <TableCell className="text-right">
                            <div className="flex items-center justify-end gap-1">
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    onClick={() => openEdit(calendar)}
                                    className="h-8 w-8"
                                  >
                                    <Pencil className="h-4 w-4" />
                                    <span className="sr-only">Editar</span>
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent>Editar calendario</TooltipContent>
                              </Tooltip>

                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <span>
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      onClick={() => openDelete(calendar)}
                                      disabled={calendar.primary}
                                      className="h-8 w-8 text-destructive hover:text-destructive hover:bg-destructive/10 disabled:opacity-40"
                                    >
                                      <Trash2 className="h-4 w-4" />
                                      <span className="sr-only">Eliminar</span>
                                    </Button>
                                  </span>
                                </TooltipTrigger>
                                <TooltipContent>
                                  {calendar.primary
                                    ? "No se puede eliminar el calendario principal"
                                    : "Eliminar calendario"}
                                </TooltipContent>
                              </Tooltip>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        {/* Disconnect confirmation dialog */}
        <AlertDialog
          open={disconnectDialogOpen}
          onOpenChange={setDisconnectDialogOpen}
        >
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Desconectar Google Calendar</AlertDialogTitle>
              <AlertDialogDescription>
                Se eliminara la conexion con tu cuenta de Google. Los calendarios
                ya asignados a los estilistas no se veran afectados, pero no podras
                seleccionar nuevos calendarios desde el desplegable hasta volver a conectar.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancelar</AlertDialogCancel>
              <AlertDialogAction
                onClick={handleDisconnect}
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              >
                {disconnecting ? (
                  <>
                    <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                    Desconectando...
                  </>
                ) : (
                  "Desconectar"
                )}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {/* Create calendar dialog */}
        <CreateCalendarDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          onCreated={fetchCalendars}
        />

        {/* Edit calendar dialog */}
        <EditCalendarDialog
          calendar={selectedCalendar}
          open={editOpen}
          onOpenChange={setEditOpen}
          onUpdated={fetchCalendars}
        />

        {/* Delete calendar dialog */}
        <DeleteCalendarDialog
          calendar={selectedCalendar}
          open={deleteOpen}
          onOpenChange={setDeleteOpen}
          onDeleted={fetchCalendars}
        />
      </div>
    </TooltipProvider>
  );
}
