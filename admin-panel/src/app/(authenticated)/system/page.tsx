"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { Header } from "@/components/layout/header";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
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
  CheckCircle,
  XCircle,
  Loader2,
  RefreshCw,
  Square,
  Trash2,
  Play,
  Pause,
} from "lucide-react";
import { toast } from "sonner";
import api from "@/lib/api";
import type { SystemService, SystemServiceName } from "@/lib/types";

interface HealthStatus {
  status: string;
  redis: string;
  postgres: string;
}

const SERVICE_LABELS: Record<SystemServiceName, { name: string; description: string }> = {
  api: { name: "API (FastAPI)", description: "Webhooks y endpoints REST - Puerto 8000" },
  agent: { name: "Agent (LangGraph)", description: "Orquestador de conversaciones con IA" },
  archiver: { name: "Archiver", description: "Worker que archiva conversaciones a PostgreSQL" },
  "confirmation-worker": { name: "Confirmation Worker", description: "Envio de recordatorios y confirmaciones" },
  "gcal-sync-worker": { name: "GCal Sync Worker", description: "Sincronizacion bidireccional con Google Calendar" },
  postgres: { name: "PostgreSQL", description: "Base de datos principal - Puerto 5432" },
  redis: { name: "Redis Stack", description: "Cache y checkpointing - Puerto 6379" },
};

function StatusIndicator({ status }: { status: string }) {
  if (status === "connected" || status === "healthy" || status === "running") {
    return <CheckCircle className="h-5 w-5 text-green-500" />;
  }
  if (status === "disconnected" || status === "degraded" || status === "exited") {
    return <XCircle className="h-5 w-5 text-red-500" />;
  }
  if (status === "starting" || status === "restarting") {
    return <Loader2 className="h-5 w-5 animate-spin text-yellow-500" />;
  }
  return <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />;
}

function ServiceStatusBadge({ status, health }: { status: string; health: string | null }) {
  const getVariant = () => {
    if (status === "running") {
      if (health === "healthy") return "default";
      if (health === "unhealthy") return "destructive";
      return "secondary";
    }
    if (status === "exited") return "destructive";
    return "outline";
  };

  const getText = () => {
    if (status === "running") {
      if (health === "healthy") return "Healthy";
      if (health === "unhealthy") return "Unhealthy";
      if (health === "starting") return "Starting";
      return "Running";
    }
    return status.charAt(0).toUpperCase() + status.slice(1);
  };

  return <Badge variant={getVariant()}>{getText()}</Badge>;
}

export default function SystemPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [services, setServices] = useState<SystemService[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Service actions state
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<{
    open: boolean;
    service: SystemServiceName | null;
    action: "restart" | "stop";
  }>({ open: false, service: null, action: "restart" });

  // Logs state
  const [selectedLogService, setSelectedLogService] = useState<SystemServiceName>("api");
  const [logs, setLogs] = useState<string[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [logFilter, setLogFilter] = useState<"all" | "error" | "warning" | "info" | "debug">("all");
  const eventSourceRef = useRef<EventSource | null>(null);
  const logsEndRef = useRef<HTMLDivElement>(null);

  // Helper to detect log level from line content
  const getLogLevel = (line: string): "error" | "warning" | "info" | "debug" => {
    const upper = line.toUpperCase();
    if (upper.includes("ERROR") || upper.includes("CRITICAL") || upper.includes("EXCEPTION")) return "error";
    if (upper.includes("WARNING") || upper.includes("WARN")) return "warning";
    if (upper.includes("DEBUG")) return "debug";
    return "info";
  };

  // Get color class for log level
  const getLogColor = (level: string): string => {
    switch (level) {
      case "error": return "text-red-400";
      case "warning": return "text-yellow-400";
      case "debug": return "text-zinc-500";
      default: return "text-zinc-100";
    }
  };

  // Filter logs by level
  const filteredLogs = logs.filter((line) => {
    if (logFilter === "all") return true;
    return getLogLevel(line) === logFilter;
  });

  // Fetch health status
  const fetchHealth = useCallback(async () => {
    try {
      const data = await api.health();
      setHealth(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error conectando al API");
    }
  }, []);

  // Fetch services status
  const fetchServices = useCallback(async () => {
    try {
      const data = await api.getSystemServices();
      setServices(data.services);
    } catch (err) {
      console.error("Error fetching services:", err);
    }
  }, []);

  // Initial load and periodic refresh
  useEffect(() => {
    async function loadData() {
      setIsLoading(true);
      await Promise.all([fetchHealth(), fetchServices()]);
      setIsLoading(false);
    }
    loadData();

    // Refresh every 30 seconds
    const interval = setInterval(() => {
      fetchHealth();
      fetchServices();
    }, 30000);
    return () => clearInterval(interval);
  }, [fetchHealth, fetchServices]);

  // Start log streaming
  const startLogStream = useCallback(() => {
    // Close existing stream
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const token = api.getToken();
    if (!token) {
      toast.error("No hay sesion activa. Por favor, inicia sesion de nuevo.");
      return;
    }

    const url = `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/admin/system/${selectedLogService}/logs?tail=100&token=${encodeURIComponent(token)}`;

    const eventSource = new EventSource(url);

    eventSource.onopen = () => {
      setIsStreaming(true);
      setLogs([]);
    };

    eventSource.onmessage = (event) => {
      const line = event.data;
      if (line && !line.startsWith("Error:")) {
        setLogs((prev) => {
          const newLogs = [...prev, line];
          // Keep last 500 lines
          if (newLogs.length > 500) {
            return newLogs.slice(-500);
          }
          return newLogs;
        });
      } else if (line.startsWith("Error:")) {
        toast.error(line);
      }
    };

    eventSource.onerror = () => {
      setIsStreaming(false);
      eventSource.close();
    };

    eventSourceRef.current = eventSource;
  }, [selectedLogService]);

  // Stop log streaming
  const stopLogStream = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setIsStreaming(false);
  }, []);

  // Auto-scroll logs
  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  // Restart when service changes
  useEffect(() => {
    if (isStreaming) {
      stopLogStream();
      startLogStream();
    }
  }, [selectedLogService]);

  // Service actions
  const handleServiceAction = async (action: "restart" | "stop") => {
    const service = confirmDialog.service;
    if (!service) return;

    setConfirmDialog({ open: false, service: null, action: "restart" });
    setActionInProgress(service);

    try {
      const result = action === "restart"
        ? await api.restartService(service)
        : await api.stopService(service);

      if (result.success) {
        toast.success(result.message);
        // Refresh services status
        await fetchServices();
      } else {
        toast.error(result.message);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error ejecutando accion");
    } finally {
      setActionInProgress(null);
    }
  };

  const clearLogs = () => {
    setLogs([]);
  };

  return (
    <div className="flex flex-col">
      <Header
        title="Sistema"
        description="Estado y control de los servicios de infraestructura"
        action={
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              fetchHealth();
              fetchServices();
            }}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Actualizar
          </Button>
        }
      />

      <div className="flex-1 space-y-6 p-6">
        {/* Health Status Cards */}
        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Estado General</CardTitle>
              {isLoading ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <StatusIndicator status={health?.status || "unknown"} />
              )}
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold capitalize">
                {isLoading ? "..." : health?.status || "Desconocido"}
              </div>
              <p className="text-xs text-muted-foreground">Estado del API backend</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">PostgreSQL</CardTitle>
              {isLoading ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <StatusIndicator status={health?.postgres || "unknown"} />
              )}
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold capitalize">
                {isLoading ? "..." : health?.postgres || "Desconocido"}
              </div>
              <p className="text-xs text-muted-foreground">Base de datos principal</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Redis</CardTitle>
              {isLoading ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <StatusIndicator status={health?.redis || "unknown"} />
              )}
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold capitalize">
                {isLoading ? "..." : health?.redis || "Desconocido"}
              </div>
              <p className="text-xs text-muted-foreground">Cache y checkpointing</p>
            </CardContent>
          </Card>
        </div>

        {error && (
          <Card className="border-amber-200 bg-amber-50">
            <CardContent className="pt-6">
              <p className="text-sm text-amber-800">
                <strong>Error:</strong> {error}
              </p>
            </CardContent>
          </Card>
        )}

        {/* Services Control */}
        <Card>
          <CardHeader>
            <CardTitle>Control de Servicios</CardTitle>
            <CardDescription>
              Gestiona los contenedores Docker del sistema
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {services.map((service) => {
                const label = SERVICE_LABELS[service.name];
                const isCurrentService = actionInProgress === service.name;
                const canStop = service.name !== "api"; // Can't stop API from panel

                return (
                  <div
                    key={service.name}
                    className="flex items-center justify-between border-b pb-4 last:border-0 last:pb-0"
                  >
                    <div className="flex items-center gap-4">
                      <StatusIndicator status={service.status} />
                      <div>
                        <p className="font-medium">{label?.name || service.name}</p>
                        <p className="text-sm text-muted-foreground">
                          {label?.description || service.container}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <ServiceStatusBadge status={service.status} health={service.health} />
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={isCurrentService}
                        onClick={() =>
                          setConfirmDialog({
                            open: true,
                            service: service.name,
                            action: "restart",
                          })
                        }
                      >
                        {isCurrentService ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <RefreshCw className="h-4 w-4" />
                        )}
                        <span className="ml-1 hidden sm:inline">Reiniciar</span>
                      </Button>
                      {canStop && (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={isCurrentService || service.status !== "running"}
                          onClick={() =>
                            setConfirmDialog({
                              open: true,
                              service: service.name,
                              action: "stop",
                            })
                          }
                        >
                          <Square className="h-4 w-4" />
                          <span className="ml-1 hidden sm:inline">Detener</span>
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })}

              {services.length === 0 && !isLoading && (
                <p className="text-center text-muted-foreground py-4">
                  No se pudieron cargar los servicios
                </p>
              )}

              {isLoading && (
                <div className="flex justify-center py-4">
                  <Loader2 className="h-6 w-6 animate-spin" />
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Logs Section */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Logs en Tiempo Real</CardTitle>
                <CardDescription>
                  Streaming de logs de los contenedores Docker
                </CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <Select
                  value={selectedLogService}
                  onValueChange={(value) => setSelectedLogService(value as SystemServiceName)}
                >
                  <SelectTrigger className="w-[180px]">
                    <SelectValue placeholder="Seleccionar servicio" />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(SERVICE_LABELS).map(([key, label]) => (
                      <SelectItem key={key} value={key}>
                        {label.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select
                  value={logFilter}
                  onValueChange={(value) => setLogFilter(value as typeof logFilter)}
                >
                  <SelectTrigger className="w-[120px]">
                    <SelectValue placeholder="Filtrar" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Todos</SelectItem>
                    <SelectItem value="error">Errores</SelectItem>
                    <SelectItem value="warning">Warnings</SelectItem>
                    <SelectItem value="info">Info</SelectItem>
                    <SelectItem value="debug">Debug</SelectItem>
                  </SelectContent>
                </Select>
                {isStreaming ? (
                  <Button variant="outline" size="sm" onClick={stopLogStream}>
                    <Pause className="mr-2 h-4 w-4" />
                    Pausar
                  </Button>
                ) : (
                  <Button variant="outline" size="sm" onClick={startLogStream}>
                    <Play className="mr-2 h-4 w-4" />
                    Iniciar
                  </Button>
                )}
                <Button variant="ghost" size="sm" onClick={clearLogs}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[400px] w-full rounded-md border bg-zinc-950 p-4">
              <div className="font-mono text-xs">
                {logs.length === 0 ? (
                  <p className="text-zinc-500">
                    {isStreaming
                      ? "Esperando logs..."
                      : "Pulsa 'Iniciar' para ver los logs en tiempo real"}
                  </p>
                ) : filteredLogs.length === 0 ? (
                  <p className="text-zinc-500">
                    No hay logs que coincidan con el filtro seleccionado
                  </p>
                ) : (
                  filteredLogs.map((line, index) => {
                    const level = getLogLevel(line);
                    return (
                      <div
                        key={index}
                        className={`whitespace-pre-wrap break-all hover:bg-zinc-900 py-0.5 ${getLogColor(level)}`}
                      >
                        {line}
                      </div>
                    );
                  })
                )}
                <div ref={logsEndRef} />
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      </div>

      {/* Confirmation Dialog */}
      <AlertDialog
        open={confirmDialog.open}
        onOpenChange={(open) =>
          setConfirmDialog({ ...confirmDialog, open })
        }
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirmDialog.action === "restart"
                ? "Reiniciar servicio"
                : "Detener servicio"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirmDialog.action === "restart" ? (
                <>
                  ¿Estas seguro de que quieres reiniciar{" "}
                  <strong>
                    {confirmDialog.service &&
                      SERVICE_LABELS[confirmDialog.service]?.name}
                  </strong>
                  ? El servicio estara no disponible durante unos segundos.
                </>
              ) : (
                <>
                  ¿Estas seguro de que quieres detener{" "}
                  <strong>
                    {confirmDialog.service &&
                      SERVICE_LABELS[confirmDialog.service]?.name}
                  </strong>
                  ? El servicio quedara inactivo hasta que lo reinicies
                  manualmente.
                </>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => handleServiceAction(confirmDialog.action)}
              className={
                confirmDialog.action === "stop"
                  ? "bg-destructive hover:bg-destructive/90"
                  : ""
              }
            >
              {confirmDialog.action === "restart" ? "Reiniciar" : "Detener"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
