"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Phone,
  User,
  Calendar,
  BarChart3,
  MessageSquare,
  Info,
  CalendarOff,
  Brain,
  Clock,
} from "lucide-react";
import { toast } from "sonner";
import { format, parseISO } from "date-fns";
import { es } from "date-fns/locale";

import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
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
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { StatusBadge } from "@/components/shared/status-badge";
import { EmptyState } from "@/components/shared/empty-state";
import { formatDate, formatDuration } from "@/components/shared/format-utils";
import api from "@/lib/api";
import type {
  CustomerDetail,
  CustomerAppointment,
  CustomerMemories,
  AppointmentStatus,
} from "@/lib/types";

// ─── Helpers ────────────────────────────────────────────────────────────────

function formatAppointmentDate(isoString: string): string {
  try {
    return format(parseISO(isoString), "d MMM yyyy HH:mm", { locale: es });
  } catch {
    return isoString;
  }
}

const EMPTY_MEMORIES: CustomerMemories = {
  preferred_stylist_name: null,
  preferred_stylist_id: null,
  no_preference_stylist: null,
  typical_services: null,
  typical_day_of_week: null,
  typical_time_of_day: null,
  agent_notes: null,
  visit_count: null,
  last_visit_date: null,
  last_stylist_name: null,
};

function memoriesFromCustomer(customer: CustomerDetail): CustomerMemories {
  if (!customer.memories) return { ...EMPTY_MEMORIES };
  return { ...EMPTY_MEMORIES, ...customer.memories };
}

// ─── Page Skeleton ───────────────────────────────────────────────────────────

function PageSkeleton() {
  return (
    <div className="flex flex-col">
      <div className="sticky top-0 z-10 h-16 border-b bg-background px-4 md:px-6 flex items-center">
        <Skeleton className="h-6 w-48" />
      </div>
      <div className="flex-1 p-4 md:p-6 space-y-6">
        <Skeleton className="h-10 w-64" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-5 w-32" />
              </CardHeader>
              <CardContent className="space-y-3">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-4 w-1/2" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function CustomerDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  // Customer state
  const [customer, setCustomer] = useState<CustomerDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Policy version state (fetched from backend to avoid hardcoding)
  const [currentPolicyVersion, setCurrentPolicyVersion] = useState<string | null>(null);

  // Appointments state
  const [appointments, setAppointments] = useState<CustomerAppointment[]>([]);
  const [appointmentsPage, setAppointmentsPage] = useState(1);
  const [hasMoreAppointments, setHasMoreAppointments] = useState(false);
  const [isLoadingAppts, setIsLoadingAppts] = useState(false);

  // Memories form state
  const [memories, setMemories] = useState<CustomerMemories>({ ...EMPTY_MEMORIES });
  const [isSaving, setIsSaving] = useState(false);
  const [clearDialogOpen, setClearDialogOpen] = useState(false);

  // Notes form state
  const [notes, setNotes] = useState<string>("");
  const [isSavingNotes, setIsSavingNotes] = useState(false);

  // Fetch customer detail + first page of appointments + current policy version on mount
  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [customerData, apptData, policyVersion] = await Promise.all([
        api.getCustomerDetail(id),
        api.getCustomerAppointments(id, 1, 20),
        api.getCurrentPolicyVersion().catch(() => null),
      ]);
      setCustomer(customerData);
      setCurrentPolicyVersion(policyVersion);
      setMemories(memoriesFromCustomer(customerData));
      setNotes(customerData.notes ?? "");
      setAppointments(apptData.items);
      setAppointmentsPage(1);
      setHasMoreAppointments(apptData.has_more);
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "Error al cargar el cliente";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [id]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Load more appointments
  const loadMoreAppointments = async () => {
    if (isLoadingAppts || !hasMoreAppointments) return;
    setIsLoadingAppts(true);
    try {
      const nextPage = appointmentsPage + 1;
      const apptData = await api.getCustomerAppointments(id, nextPage, 20);
      setAppointments((prev) => [...prev, ...apptData.items]);
      setAppointmentsPage(nextPage);
      setHasMoreAppointments(apptData.has_more);
    } catch {
      toast.error("Error al cargar más citas");
    } finally {
      setIsLoadingAppts(false);
    }
  };

  // Save notes
  const handleSaveNotes = async () => {
    setIsSavingNotes(true);
    try {
      const updated = await api.update<CustomerDetail>("customers", id, {
        notes: notes.trim() || null,
      } as Partial<CustomerDetail>);
      setCustomer((prev) => (prev ? { ...prev, notes: updated.notes ?? null } : prev));
      setNotes(updated.notes ?? "");
      toast.success("Notas guardadas");
    } catch (err) {
      toast.error(
        `Error al guardar: ${err instanceof Error ? err.message : "Error desconocido"}`
      );
    } finally {
      setIsSavingNotes(false);
    }
  };

  // Save memories
  const handleSaveMemories = async () => {
    setIsSaving(true);
    try {
      const result = await api.updateCustomerMemories(id, memories);
      setMemories({ ...EMPTY_MEMORIES, ...(result.memories ?? {}) });
      toast.success("Memoria actualizada");
    } catch (err) {
      toast.error(
        `Error al guardar: ${err instanceof Error ? err.message : "Error desconocido"}`
      );
    } finally {
      setIsSaving(false);
    }
  };

  // Clear memories
  const handleClearMemories = async () => {
    setClearDialogOpen(false);
    setIsSaving(true);
    try {
      await api.updateCustomerMemories(id, {});
      setMemories({ ...EMPTY_MEMORIES });
      toast.success("Memoria eliminada");
    } catch (err) {
      toast.error(
        `Error al limpiar: ${err instanceof Error ? err.message : "Error desconocido"}`
      );
    } finally {
      setIsSaving(false);
    }
  };

  // ─── Loading ───────────────────────────────────────────────────────────────

  if (isLoading) {
    return <PageSkeleton />;
  }

  // ─── Error ─────────────────────────────────────────────────────────────────

  if (error || !customer) {
    return (
      <div className="flex flex-col">
        <Header title="Cliente" />
        <div className="flex-1 p-4 md:p-6">
          <Card className="max-w-md mx-auto mt-8">
            <CardHeader>
              <CardTitle className="text-destructive">
                Cliente no encontrado
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">
                {error ?? "No se pudo encontrar el cliente solicitado."}
              </p>
              <Button asChild variant="outline">
                <Link href="/customers">
                  <ArrowLeft className="mr-2 h-4 w-4" />
                  Volver a clientes
                </Link>
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  // ─── Helpers ───────────────────────────────────────────────────────────────

  const fullName =
    `${customer.first_name} ${customer.last_name ?? ""}`.trim();

  // ─── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col">
      <Header
        title={fullName}
        description="Detalle de cliente"
        action={
          <Button asChild variant="outline" size="sm">
            <Link href="/customers">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Volver
            </Link>
          </Button>
        }
      />

      <div className="flex-1 p-4 md:p-6">
        <Tabs defaultValue="perfil" className="space-y-4">
          <TabsList>
            <TabsTrigger value="perfil">Perfil</TabsTrigger>
            <TabsTrigger value="citas">Citas</TabsTrigger>
            <TabsTrigger value="memoria">Memoria del bot</TabsTrigger>
          </TabsList>

          {/* ─── Perfil Tab ─────────────────────────────────────────────── */}
          <TabsContent value="perfil">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* Contacto */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Phone className="h-4 w-4" />
                    Contacto
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div>
                    <p className="text-xs text-muted-foreground">Nombre</p>
                    <p className="text-sm font-medium">{fullName}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Teléfono</p>
                    <p className="text-sm font-medium">{customer.phone}</p>
                  </div>
                  {customer.chatwoot_conversation_id && (
                    <div>
                      <p className="text-xs text-muted-foreground">
                        Conversación WhatsApp
                      </p>
                      <p className="text-sm font-medium">
                        #{customer.chatwoot_conversation_id}
                      </p>
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Preferencias */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <User className="h-4 w-4" />
                    Preferencias
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div>
                    <p className="text-xs text-muted-foreground">
                      Estilista preferida
                    </p>
                    <p className="text-sm font-medium">
                      {customer.preferred_stylist_name ?? (
                        <span className="text-muted-foreground">Sin preferencia</span>
                      )}
                    </p>
                  </div>
                </CardContent>
              </Card>

              {/* Actividad */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <BarChart3 className="h-4 w-4" />
                    Actividad
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div>
                    <p className="text-xs text-muted-foreground">
                      Última visita
                    </p>
                    <p className="text-sm font-medium">
                      {customer.last_service_date
                        ? formatDate(customer.last_service_date, false)
                        : "Sin visitas"}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">
                      Cliente desde
                    </p>
                    <p className="text-sm">
                      {formatDate(customer.created_at, false)}
                    </p>
                  </div>
                  {/* Policy acceptance badge — 3 states */}
                  <div>
                    <p className="text-xs text-muted-foreground mb-1">
                      Política de privacidad
                    </p>
                    {customer.policy_accepted_at === null ? (
                      <Badge className="bg-gray-100 text-gray-700 hover:bg-gray-100">
                        Política no aceptada
                      </Badge>
                    ) : customer.policy_version === currentPolicyVersion ? (
                      <Badge className="bg-green-100 text-green-800 hover:bg-green-100">
                        Política v{customer.policy_version} aceptada el{" "}
                        {formatDate(customer.policy_accepted_at, false)}
                      </Badge>
                    ) : (
                      <Badge className="bg-yellow-100 text-yellow-800 hover:bg-yellow-100">
                        Política v{customer.policy_version} aceptada el{" "}
                        {formatDate(customer.policy_accepted_at, false)}{" "}
                        (versión obsoleta)
                      </Badge>
                    )}
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Notas — full width below the info grid */}
            <Card className="mt-4">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Info className="h-4 w-4" />
                  Notas
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <Textarea
                  placeholder="Notas internas sobre el cliente (alergias, preferencias, observaciones, etc.)"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  rows={4}
                  className="resize-y"
                />
                <div className="flex justify-end">
                  <Button
                    onClick={handleSaveNotes}
                    disabled={isSavingNotes || notes === (customer.notes ?? "")}
                    size="sm"
                  >
                    {isSavingNotes ? "Guardando..." : "Guardar notas"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* ─── Citas Tab ──────────────────────────────────────────────── */}
          <TabsContent value="citas">
            {appointments.length === 0 && !isLoadingAppts ? (
              <EmptyState
                icon={CalendarOff}
                title="No hay citas registradas"
                description="Este cliente no tiene citas registradas."
              />
            ) : (
              <Card>
                <CardContent className="pt-4">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-muted-foreground">
                          <th className="text-left py-3 px-4 font-medium">
                            <div className="flex items-center gap-1">
                              <Calendar className="h-4 w-4" />
                              Fecha
                            </div>
                          </th>
                          <th className="text-left py-3 px-4 font-medium">
                            Servicio(s)
                          </th>
                          <th className="text-left py-3 px-4 font-medium">
                            Estilista
                          </th>
                          <th className="text-left py-3 px-4 font-medium">
                            Estado
                          </th>
                          <th className="text-left py-3 px-4 font-medium">
                            <div className="flex items-center gap-1">
                              <Clock className="h-4 w-4" />
                              Duración
                            </div>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {appointments.map((appt) => (
                          <tr
                            key={appt.id}
                            className="border-b hover:bg-muted/50 cursor-pointer transition-colors"
                            onClick={() =>
                              router.push(`/appointments/${appt.id}`)
                            }
                          >
                            <td className="py-3 px-4 whitespace-nowrap">
                              {formatAppointmentDate(appt.start_time)}
                            </td>
                            <td className="py-3 px-4 max-w-[200px]">
                              {appt.service_names.length > 0
                                ? appt.service_names.join(", ")
                                : (
                                  <span className="text-muted-foreground">
                                    Sin servicios
                                  </span>
                                )}
                            </td>
                            <td className="py-3 px-4">{appt.stylist_name}</td>
                            <td className="py-3 px-4">
                              <StatusBadge
                                status={appt.status as AppointmentStatus}
                              />
                            </td>
                            <td className="py-3 px-4 whitespace-nowrap">
                              {formatDuration(appt.duration_minutes)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {hasMoreAppointments && (
                    <div className="flex justify-center pt-4">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={loadMoreAppointments}
                        disabled={isLoadingAppts}
                      >
                        {isLoadingAppts ? "Cargando..." : "Cargar más"}
                      </Button>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* ─── Memoria Tab ────────────────────────────────────────────── */}
          <TabsContent value="memoria">
            <div className="space-y-4 max-w-2xl">
              {/* Info banner */}
              <div className="flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 text-blue-800">
                <Info className="h-5 w-5 mt-0.5 shrink-0" />
                <p className="text-sm">
                  Los cambios en la memoria se guardan en la base de datos. El
                  bot sincronizará estos datos en la próxima conversación.
                </p>
              </div>

              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Brain className="h-4 w-4" />
                    Datos aprendidos por el bot
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-5">
                  {/* Estilista preferida */}
                  <div className="space-y-1.5">
                    <Label htmlFor="mem-preferred-stylist-name">
                      Estilista preferida
                    </Label>
                    <Input
                      id="mem-preferred-stylist-name"
                      value={memories.preferred_stylist_name ?? ""}
                      onChange={(e) =>
                        setMemories((prev) => ({
                          ...prev,
                          preferred_stylist_name: e.target.value || null,
                        }))
                      }
                      placeholder="Ej: Ana"
                    />
                  </div>

                  {/* ID Estilista preferida */}
                  <div className="space-y-1.5">
                    <Label htmlFor="mem-preferred-stylist-id">
                      ID Estilista preferida
                    </Label>
                    <Input
                      id="mem-preferred-stylist-id"
                      value={memories.preferred_stylist_id ?? ""}
                      onChange={(e) =>
                        setMemories((prev) => ({
                          ...prev,
                          preferred_stylist_id: e.target.value || null,
                        }))
                      }
                      placeholder="UUID de la estilista"
                      className="font-mono text-sm"
                    />
                  </div>

                  {/* Sin preferencia de estilista */}
                  <div className="flex items-center gap-3">
                    <Switch
                      id="mem-no-preference"
                      checked={memories.no_preference_stylist ?? false}
                      onCheckedChange={(checked) =>
                        setMemories((prev) => ({
                          ...prev,
                          no_preference_stylist: checked,
                        }))
                      }
                    />
                    <Label htmlFor="mem-no-preference">
                      Sin preferencia de estilista
                    </Label>
                  </div>

                  {/* Servicios habituales */}
                  <div className="space-y-1.5">
                    <Label htmlFor="mem-typical-services">
                      Servicios habituales
                      <span className="ml-1 text-xs text-muted-foreground">
                        (separados por coma)
                      </span>
                    </Label>
                    <Input
                      id="mem-typical-services"
                      value={
                        memories.typical_services
                          ? memories.typical_services.join(", ")
                          : ""
                      }
                      onChange={(e) => {
                        const raw = e.target.value;
                        const parsed = raw
                          ? raw.split(",").map((s) => s.trim()).filter(Boolean)
                          : null;
                        setMemories((prev) => ({
                          ...prev,
                          typical_services: parsed && parsed.length > 0 ? parsed : null,
                        }));
                      }}
                      placeholder="Ej: Corte, Mechas, Tinte"
                    />
                  </div>

                  {/* Día habitual */}
                  <div className="space-y-1.5">
                    <Label htmlFor="mem-typical-day">Día habitual</Label>
                    <Input
                      id="mem-typical-day"
                      value={memories.typical_day_of_week ?? ""}
                      onChange={(e) =>
                        setMemories((prev) => ({
                          ...prev,
                          typical_day_of_week: e.target.value || null,
                        }))
                      }
                      placeholder="Ej: martes"
                    />
                  </div>

                  {/* Horario habitual */}
                  <div className="space-y-1.5">
                    <Label htmlFor="mem-typical-time">Horario habitual</Label>
                    <Select
                      value={memories.typical_time_of_day ?? ""}
                      onValueChange={(value) =>
                        setMemories((prev) => ({
                          ...prev,
                          typical_time_of_day: value || null,
                        }))
                      }
                    >
                      <SelectTrigger id="mem-typical-time">
                        <SelectValue placeholder="Sin preferencia" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="morning">Mañana</SelectItem>
                        <SelectItem value="afternoon">Tarde</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  {/* Notas */}
                  <div className="space-y-1.5">
                    <Label htmlFor="mem-notes">Notas del bot</Label>
                    <Textarea
                      id="mem-notes"
                      value={memories.agent_notes ?? ""}
                      onChange={(e) =>
                        setMemories((prev) => ({
                          ...prev,
                          agent_notes: e.target.value || null,
                        }))
                      }
                      placeholder="Notas aprendidas por el bot..."
                      rows={3}
                    />
                  </div>

                  {/* Cantidad de visitas */}
                  <div className="space-y-1.5">
                    <Label htmlFor="mem-visit-count">Cantidad de visitas</Label>
                    <Input
                      id="mem-visit-count"
                      value={memories.visit_count ?? ""}
                      readOnly
                      className="bg-muted/40 cursor-default"
                    />
                    <p className="text-xs text-muted-foreground">Se calcula automáticamente</p>
                  </div>

                  {/* Última visita */}
                  <div className="space-y-1.5">
                    <Label htmlFor="mem-last-visit">Última visita</Label>
                    <Input
                      id="mem-last-visit"
                      value={memories.last_visit_date ?? ""}
                      readOnly
                      className="bg-muted/40 cursor-default"
                    />
                    <p className="text-xs text-muted-foreground">Se calcula automáticamente</p>
                  </div>

                  {/* Última estilista */}
                  <div className="space-y-1.5">
                    <Label htmlFor="mem-last-stylist">
                      Última estilista
                    </Label>
                    <Input
                      id="mem-last-stylist"
                      value={memories.last_stylist_name ?? ""}
                      readOnly
                      className="bg-muted/40 cursor-default"
                      placeholder="Se actualiza automáticamente"
                    />
                  </div>

                  {/* Action buttons */}
                  <div className="flex items-center gap-3 pt-2">
                    <Button
                      onClick={handleSaveMemories}
                      disabled={isSaving}
                    >
                      {isSaving ? "Guardando..." : "Guardar cambios"}
                    </Button>
                    <Button
                      variant="outline"
                      onClick={() => setClearDialogOpen(true)}
                      disabled={isSaving}
                      className="text-destructive hover:text-destructive"
                    >
                      Limpiar memoria
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </div>
          </TabsContent>
        </Tabs>
      </div>

      {/* Clear memories confirmation */}
      <AlertDialog open={clearDialogOpen} onOpenChange={setClearDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Limpiar memoria del bot</AlertDialogTitle>
            <AlertDialogDescription>
              ¿Estás segura? Esto borrará toda la memoria aprendida del bot para
              esta clienta. El bot comenzará a aprender desde cero en la próxima
              conversación.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleClearMemories}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Limpiar memoria
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
