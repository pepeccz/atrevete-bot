"use client";

import { useState, useCallback, useEffect } from "react";
import { AlertTriangle, RefreshCw, CheckCircle2, Clock, Zap } from "lucide-react";
import { ColumnDef } from "@tanstack/react-table";
import { format, formatDistanceToNow } from "date-fns";
import { es } from "date-fns/locale";

import { api } from "@/lib/api";
import {
  Escalation,
  EscalationStats,
  EscalationQueryParams,
  ESCALATION_SOURCE_LABELS,
  ESCALATION_STATUS_LABELS,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
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

// ─── Helpers ────────────────────────────────────────────────────────────────

function truncate(str: string | null, max: number): string {
  if (!str) return "—";
  return str.length > max ? str.slice(0, max) + "…" : str;
}

function relativeTime(iso: string): string {
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true, locale: es });
  } catch {
    return iso;
  }
}

function StatusBadge({ status }: { status: Escalation["status"] }) {
  return (
    <Badge variant={status === "triggered" ? "destructive" : "secondary"}>
      {ESCALATION_STATUS_LABELS[status]}
    </Badge>
  );
}

function SourceBadge({
  source,
  isTechnical,
}: {
  source: Escalation["source"];
  isTechnical: boolean;
}) {
  const label = isTechnical ? "Error técnico" : ESCALATION_SOURCE_LABELS[source];
  const variant = isTechnical ? "destructive" : "outline";
  return <Badge variant={variant}>{label}</Badge>;
}

// ─── Page Component ──────────────────────────────────────────────────────────

export default function EscalationsPage() {
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [stats, setStats] = useState<EscalationStats | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [isLoading, setIsLoading] = useState(false);

  // Filtros
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [sourceFilter, setSourceFilter] = useState<string>("");

  // Modal detalle
  const [selectedEscalation, setSelectedEscalation] = useState<Escalation | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  // Confirm resolve
  const [resolveTarget, setResolveTarget] = useState<Escalation | null>(null);
  const [resolveOpen, setResolveOpen] = useState(false);
  const [resolving, setResolving] = useState(false);

  const PAGE_SIZE = 20;

  const fetchEscalations = useCallback(async () => {
    setIsLoading(true);
    try {
      const params: EscalationQueryParams = {
        page,
        page_size: PAGE_SIZE,
        sort_by: "triggered_at",
        sort_order: "desc",
      };
      if (search) params.search = search;
      if (statusFilter) params.status = statusFilter as Escalation["status"];
      if (sourceFilter) params.source = sourceFilter as Escalation["source"];

      const [data, statsData] = await Promise.all([
        api.getEscalations(params),
        api.getEscalationStats(),
      ]);
      setEscalations(data.items);
      setTotal(data.total);
      setStats(statsData);
    } catch (err) {
      console.error("Failed to fetch escalations:", err);
    } finally {
      setIsLoading(false);
    }
  }, [page, search, statusFilter, sourceFilter]);

  useEffect(() => {
    fetchEscalations();
  }, [fetchEscalations]);

  const handleResolve = async () => {
    if (!resolveTarget) return;
    setResolving(true);
    try {
      const updated = await api.resolveEscalation(resolveTarget.id);
      setEscalations((prev) =>
        prev.map((e) => (e.id === updated.id ? updated : e))
      );
      setResolveOpen(false);
      setResolveTarget(null);
      // Refresh stats
      const statsData = await api.getEscalationStats();
      setStats(statsData);
    } catch (err) {
      console.error("Failed to resolve escalation:", err);
    } finally {
      setResolving(false);
    }
  };

  const columns: ColumnDef<Escalation>[] = [
    {
      accessorKey: "status",
      header: "Estado",
      cell: ({ row }) => <StatusBadge status={row.original.status} />,
    },
    {
      accessorKey: "source",
      header: "Tipo",
      cell: ({ row }) => (
        <SourceBadge
          source={row.original.source}
          isTechnical={row.original.is_technical_error}
        />
      ),
    },
    {
      id: "customer",
      header: "Cliente",
      cell: ({ row }) =>
        row.original.customer_name ?? row.original.customer_phone,
    },
    {
      accessorKey: "reason",
      header: "Motivo",
      cell: ({ row }) => truncate(row.original.reason, 50),
    },
    {
      accessorKey: "issue_summary",
      header: "Resumen",
      cell: ({ row }) => truncate(row.original.issue_summary, 50),
    },
    {
      accessorKey: "contact_preference",
      header: "Contacto",
      cell: ({ row }) => row.original.contact_preference ?? "—",
    },
    {
      accessorKey: "triggered_at",
      header: "Fecha",
      cell: ({ row }) => relativeTime(row.original.triggered_at),
    },
    {
      id: "actions",
      header: "Acciones",
      cell: ({ row }) => (
        <div className="flex gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setSelectedEscalation(row.original);
              setDetailOpen(true);
            }}
          >
            Ver
          </Button>
          {row.original.status === "triggered" && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setResolveTarget(row.original);
                setResolveOpen(true);
              }}
            >
              Resolver
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <AlertTriangle className="h-6 w-6 text-orange-500" />
            Escalaciones
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Conversaciones derivadas a atención humana
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchEscalations} disabled={isLoading}>
          <RefreshCw className={`h-4 w-4 mr-2 ${isLoading ? "animate-spin" : ""}`} />
          Actualizar
        </Button>
      </div>

      {/* KPI Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">Total</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">{stats.total}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-1">
                <Clock className="h-3 w-3" /> Pendientes
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold text-orange-500">{stats.pending}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-1">
                <CheckCircle2 className="h-3 w-3" /> Resueltas
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold text-green-600">{stats.resolved}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-1">
                <Zap className="h-3 w-3" /> Errores técnicos
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold text-red-600">{stats.technical_errors}</p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Filtros */}
      <div className="flex flex-wrap gap-3">
        <Input
          placeholder="Buscar por motivo o teléfono…"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          className="max-w-xs"
        />
        <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v === "all" ? "" : v); setPage(1); }}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="Estado" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Todos</SelectItem>
            <SelectItem value="triggered">Pendiente</SelectItem>
            <SelectItem value="resolved">Resuelta</SelectItem>
          </SelectContent>
        </Select>
        <Select value={sourceFilter} onValueChange={(v) => { setSourceFilter(v === "all" ? "" : v); setPage(1); }}>
          <SelectTrigger className="w-44">
            <SelectValue placeholder="Origen" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Todos</SelectItem>
            <SelectItem value="manual">Manual</SelectItem>
            <SelectItem value="auto_error">Error automático</SelectItem>
            <SelectItem value="fallback">Fallback</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Tabla */}
      <Card>
        <CardContent className="pt-4">
          <DataTable
            columns={columns}
            data={escalations}
            isLoading={isLoading}
          />
          {/* Paginación simple */}
          <div className="flex items-center justify-between mt-4 text-sm text-muted-foreground">
            <span>{total} escalaciones en total</span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page === 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Anterior
              </Button>
              <span className="flex items-center px-2">Página {page}</span>
              <Button
                variant="outline"
                size="sm"
                disabled={page * PAGE_SIZE >= total}
                onClick={() => setPage((p) => p + 1)}
              >
                Siguiente
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Modal detalle */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-orange-500" />
              Detalle de escalación
            </DialogTitle>
          </DialogHeader>
          {selectedEscalation && (
            <div className="space-y-4 text-sm">
              <div className="flex gap-2">
                <StatusBadge status={selectedEscalation.status} />
                <SourceBadge
                  source={selectedEscalation.source}
                  isTechnical={selectedEscalation.is_technical_error}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-muted-foreground">Cliente</p>
                  <p className="font-medium">
                    {selectedEscalation.customer_name ?? selectedEscalation.customer_phone}
                  </p>
                </div>
                <div>
                  <p className="text-muted-foreground">Teléfono</p>
                  <p className="font-medium">{selectedEscalation.customer_phone}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Motivo</p>
                  <p className="font-medium">{selectedEscalation.reason}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Preferencia contacto</p>
                  <p className="font-medium">{selectedEscalation.contact_preference ?? "—"}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Fecha</p>
                  <p className="font-medium">
                    {format(new Date(selectedEscalation.triggered_at), "dd/MM/yyyy HH:mm")}
                  </p>
                </div>
                {selectedEscalation.resolved_at && (
                  <div>
                    <p className="text-muted-foreground">Resuelta</p>
                    <p className="font-medium">
                      {format(new Date(selectedEscalation.resolved_at), "dd/MM/yyyy HH:mm")}
                    </p>
                  </div>
                )}
              </div>
              {selectedEscalation.issue_summary && (
                <div>
                  <p className="text-muted-foreground mb-1">Descripción del problema</p>
                  <p className="bg-muted rounded p-2">{selectedEscalation.issue_summary}</p>
                </div>
              )}
              {selectedEscalation.metadata && (
                <div>
                  <p className="text-muted-foreground mb-1">Pipeline ejecutado</p>
                  <div className="bg-muted rounded p-2 space-y-1">
                    {(selectedEscalation.metadata.steps_completed as string[] | undefined)?.map((s) => (
                      <p key={s} className="text-green-600">✓ {s}</p>
                    ))}
                    {(selectedEscalation.metadata.steps_failed as string[] | undefined)?.map((s) => (
                      <p key={s} className="text-red-500">✗ {s}</p>
                    ))}
                  </div>
                </div>
              )}
              {selectedEscalation.status === "triggered" && (
                <Button
                  className="w-full"
                  onClick={() => {
                    setDetailOpen(false);
                    setResolveTarget(selectedEscalation);
                    setResolveOpen(true);
                  }}
                >
                  Marcar como resuelta
                </Button>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* AlertDialog confirmar resolución */}
      <AlertDialog open={resolveOpen} onOpenChange={setResolveOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Marcar como resuelta?</AlertDialogTitle>
            <AlertDialogDescription>
              Esta acción marcará la escalación como resuelta. El cliente ya debería haber sido
              atendido por el equipo.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={resolving}>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleResolve} disabled={resolving}>
              {resolving ? "Resolviendo…" : "Confirmar"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
