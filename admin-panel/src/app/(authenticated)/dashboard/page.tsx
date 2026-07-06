"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { toast } from "sonner";

import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatCardSkeleton } from "@/components/shared/loading-skeleton";
import { useAuth } from "@/contexts/auth-context";
import { hasPermission } from "@/lib/permissions";
import api from "@/lib/api";

import { DashboardGreeting } from "@/components/dashboard/dashboard-greeting";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { AgendaRow } from "@/components/dashboard/agenda-row";
import { EscalationItem } from "@/components/dashboard/escalation-item";
import { formatEscalationReason } from "@/lib/category-labels";
import { formatRelativeTime } from "@/components/shared/format-utils";
import { ServiceBar } from "@/components/dashboard/service-bar";
import { StylistActivityRow } from "@/components/dashboard/stylist-activity-row";
import { AppointmentWizard } from "@/app/(authenticated)/appointments/components/wizard/appointment-wizard";

import type {
  DashboardKPIs,
  TodayAgendaItem,
  TopServiceItem,
  StylistActivityItem,
  AppointmentTrendPoint,
  Escalation,
  Service,
  Stylist,
  Customer,
} from "@/lib/types";

// Recharts does not support SSR — lazy load chart
const AppointmentsTrendChart = dynamic(
  () =>
    import("@/components/dashboard/appointments-trend-chart").then(
      (m) => m.AppointmentsTrendChart
    ),
  { ssr: false, loading: () => <Skeleton className="h-[132px] w-full" /> }
);

// ─── Skeleton helpers ────────────────────────────────────────────────────────

function AgendaSkeleton() {
  return (
    <div className="flex flex-col gap-2 p-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="h-4 w-12" />
          <Skeleton className="h-8 w-1 rounded-full" />
          <div className="flex-1 space-y-1">
            <Skeleton className="h-3 w-32" />
            <Skeleton className="h-3 w-48" />
          </div>
          <Skeleton className="h-6 w-20 rounded-full" />
        </div>
      ))}
    </div>
  );
}

function EscalationSkeleton() {
  return (
    <div className="flex flex-col gap-2 p-4">
      {Array.from({ length: 2 }).map((_, i) => (
        <div key={i} className="flex items-start gap-3">
          <Skeleton className="h-[30px] w-[30px] rounded-full" />
          <div className="flex-1 space-y-1">
            <Skeleton className="h-3 w-28" />
            <Skeleton className="h-3 w-48" />
            <Skeleton className="h-3 w-16" />
          </div>
        </div>
      ))}
    </div>
  );
}

function ServiceBarSkeleton() {
  return (
    <div className="flex flex-col gap-3 px-[18px] py-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="space-y-1">
          <div className="flex justify-between">
            <Skeleton className="h-3 w-28" />
            <Skeleton className="h-3 w-6" />
          </div>
          <Skeleton className="h-[6px] w-full rounded-full" />
        </div>
      ))}
    </div>
  );
}

// ─── KPI formatting helpers ──────────────────────────────────────────────────

function formatRate(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "—";
  return `${Math.round(rate * 100)}%`;
}

function formatOccupation(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "0%";
  return `${Math.round(rate * 100)}%`;
}

// ─── Page component ──────────────────────────────────────────────────────────

export default function DashboardPage() {
  const { user } = useAuth();
  const router = useRouter();

  // Permission gate for escalation resolve
  const canResolve = hasPermission(user?.role ?? "", "escalations:resolve");

  const [kpis, setKpis] = useState<DashboardKPIs | null>(null);
  const [agenda, setAgenda] = useState<TodayAgendaItem[] | null>(null);
  const [escalations, setEscalations] = useState<Escalation[] | null>(null);
  const [topServices, setTopServices] = useState<TopServiceItem[] | null>(null);
  const [stylistActivity, setStylistActivity] = useState<StylistActivityItem[] | null>(null);
  const [trendData, setTrendData] = useState<AppointmentTrendPoint[] | null>(null);

  const [kpisLoading, setKpisLoading] = useState(true);
  const [agendaLoading, setAgendaLoading] = useState(true);
  const [escalationsLoading, setEscalationsLoading] = useState(true);
  const [servicesLoading, setServicesLoading] = useState(true);
  const [trendLoading, setTrendLoading] = useState(true);

  const [escalationsError, setEscalationsError] = useState(false);

  // ─── Appointment wizard state (T2.3) ───────────────────────────────────────
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardServices, setWizardServices] = useState<Service[]>([]);
  const [wizardStylists, setWizardStylists] = useState<Stylist[]>([]);
  const [wizardCustomers, setWizardCustomers] = useState<Customer[]>([]);
  const [wizardDataLoaded, setWizardDataLoaded] = useState(false);

  // W5: in-flight guard — tracks escalation ids currently being resolved
  // ref for the skip-check (no re-render needed), state for disabling the button
  const resolvingIds = useRef<Set<string>>(new Set());
  const [resolvingSet, setResolvingSet] = useState<Set<string>>(new Set());

  // Fetch KPIs
  useEffect(() => {
    api
      .getDashboardKPIs()
      .then(setKpis)
      .catch(() => setKpis(null))
      .finally(() => setKpisLoading(false));
  }, []);

  // Fetch today-agenda
  useEffect(() => {
    api
      .getTodayAgenda()
      .then((r) => setAgenda(r.appointments))
      .catch(() => setAgenda([]))
      .finally(() => setAgendaLoading(false));
  }, []);

  // Fetch escalations (graceful degradation on error)
  const fetchEscalations = useCallback(() => {
    setEscalationsError(false);
    api
      .getEscalations({ status: "triggered", page_size: 5 })
      .then((r) => setEscalations(r.items))
      .catch(() => {
        setEscalations(null);
        setEscalationsError(true);
      })
      .finally(() => setEscalationsLoading(false));
  }, []);

  useEffect(() => {
    fetchEscalations();
  }, [fetchEscalations]);

  // Fetch top services + stylist activity + trend in parallel
  useEffect(() => {
    Promise.allSettled([
      api.getTopServices(5),
      api.getStylistActivity(),
      api.getAppointmentsTrend(14),
    ]).then(([servicesResult, activityResult, trendResult]) => {
      setTopServices(
        servicesResult.status === "fulfilled" ? servicesResult.value : []
      );
      setStylistActivity(
        activityResult.status === "fulfilled" ? activityResult.value : []
      );
      setTrendData(
        trendResult.status === "fulfilled" ? trendResult.value : []
      );
      setServicesLoading(false);
      setTrendLoading(false);
    });
  }, []);

  // Lazy-fetch wizard data only when the wizard first opens (T2.3)
  useEffect(() => {
    if (wizardOpen && !wizardDataLoaded) {
      Promise.all([
        api.list<Service>("services", { page_size: 200 }),
        api.list<Stylist>("stylists", { page_size: 100 }),
        api.list<Customer>("customers", { page_size: 500 }),
      ])
        .then(([s, st, c]) => {
          setWizardServices(s.items);
          setWizardStylists(st.items);
          setWizardCustomers(c.items);
          setWizardDataLoaded(true);
        })
        // W2: handle fetch failure so the user knows and can retry by reopening the wizard
        .catch(() => {
          toast.error("No se pudieron cargar los datos del formulario");
          // Keep wizardDataLoaded=false so reopening triggers a fresh attempt
        });
    }
  }, [wizardOpen, wizardDataLoaded]);

  const refreshWizardCustomers = useCallback(async () => {
    await api
      .list<Customer>("customers", { page_size: 500 })
      .then((r) => setWizardCustomers(r.items))
      // S7: suppress unhandled-promise rejection; failure here is non-critical
      .catch(() => {});
  }, []);

  // Re-fetch agenda + KPIs after a wizard booking succeeds (T2.3)
  const handleWizardSuccess = useCallback(() => {
    setWizardOpen(false);
    // Refetch agenda
    api
      .getTodayAgenda()
      .then((r) => setAgenda(r.appointments))
      .catch(() => {});
    // Refetch KPIs
    api
      .getDashboardKPIs()
      .then(setKpis)
      .catch(() => {});
  }, []);

  // Resolve escalation with optimistic update (T2.2)
  const handleResolve = useCallback(
    async (id: string) => {
      // W5: skip if this id is already being resolved (rapid double-click guard)
      if (resolvingIds.current.has(id)) return;
      resolvingIds.current.add(id);
      setResolvingSet((prev) => new Set(prev).add(id));

      // Optimistic removal — counter auto-decrements via derived state
      setEscalations((prev) => (prev ? prev.filter((e) => e.id !== id) : prev));
      try {
        await api.resolveEscalation(id);
      } catch {
        toast.error("Error al resolver la escalación");
        // Restore truth from server
        fetchEscalations();
      } finally {
        resolvingIds.current.delete(id);
        setResolvingSet((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      }
    },
    [fetchEscalations]
  );

  // Derived
  const pendingEscalations =
    escalations?.filter((e) => e.status === "triggered").length ?? 0;
  const appointmentsToday = kpis?.appointments_today ?? 0;
  const maxServiceCount = topServices ? Math.max(...topServices.map((s) => s.count), 1) : 1;

  return (
    <div className="flex flex-col">
      <Header
        title="Dashboard"
        subtitle={`${appointmentsToday} citas hoy · ${pendingEscalations} escalaciones pendientes`}
        primaryAction={
          <Button
            size="sm"
            className="rounded-btn bg-gold text-white hover:bg-gold-dark"
            onClick={() => setWizardOpen(true)}
          >
            <Plus className="mr-1 h-4 w-4" />
            Nueva cita
          </Button>
        }
      />

      <div className="flex-1 space-y-[20px] p-[28px]">
        {/* Greeting */}
        <DashboardGreeting
          firstName={user?.username}
          appointmentsToday={appointmentsToday}
          pendingEscalations={pendingEscalations}
        />

        {/* KPI row — 4 columns */}
        <div className="grid grid-cols-1 gap-[14px] sm:grid-cols-2 lg:grid-cols-4">
          {kpisLoading ? (
            Array.from({ length: 4 }).map((_, i) => <StatCardSkeleton key={i} />)
          ) : (
            <>
              <KpiCard
                label="Tasa de confirmación"
                value={formatRate(kpis?.confirmation_rate_today)}
                subline={
                  kpis?.total_today
                    ? `${kpis.confirmed_today} de ${kpis.total_today} citas`
                    : "Sin citas hoy"
                }
              />
              <KpiCard
                label="Citas hoy"
                value={kpis?.appointments_today ?? 0}
                subline="Total no canceladas"
              />
              <KpiCard
                label="Ocupación"
                value={formatOccupation(kpis?.occupation_today)}
                subline={
                  kpis?.business_minutes_today
                    ? `${kpis.booked_minutes_today} min de ${kpis.business_minutes_today} min`
                    : undefined
                }
              />
              <KpiCard
                label="Nuevos clientes"
                value={kpis?.new_customers_this_week ?? 0}
                subline="Esta semana"
              />
            </>
          )}
        </div>

        {/* Middle row: 1.6fr / 1fr */}
        <div className="grid grid-cols-1 gap-[14px] lg:grid-cols-[1.6fr_1fr]">
          {/* Agenda de hoy */}
          <Card className="rounded-card-lg overflow-hidden">
            <CardHeader className="flex flex-row items-baseline gap-3 border-b border-[hsl(var(--line-soft))] px-[18px] py-4">
              <CardTitle className="flex-1 text-[14px] font-bold text-ink">
                Agenda de hoy
              </CardTitle>
              <span className="text-[12px] text-ink-mute">
                {!agendaLoading && agenda ? `${agenda.length} citas` : ""}
              </span>
            </CardHeader>
            {agendaLoading ? (
              <AgendaSkeleton />
            ) : agenda && agenda.length > 0 ? (
              <div className="flex flex-col">
                {agenda.map((item, idx) => {
                  const time = new Date(item.start_time).toLocaleTimeString("es-ES", {
                    hour: "2-digit",
                    minute: "2-digit",
                  });
                  const serviceName =
                    item.services.map((s) => s.name).join(", ") || "—";
                  return (
                    <AgendaRow
                      key={item.id}
                      time={time}
                      durationMin={item.duration_minutes}
                      stylist={{ name: item.stylist.name, color: item.stylist.color || "#928679" }}
                      customerName={item.customer.name}
                      serviceName={serviceName}
                      status={item.status}
                      isLast={idx === agenda.length - 1}
                      onClick={() => router.push(`/appointments/${item.id}`)}
                    />
                  );
                })}
              </div>
            ) : (
              <CardContent className="flex flex-col items-center justify-center gap-2 py-10 text-center">
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  className="h-8 w-8 text-ink-faint"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={1.5}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                  <line x1="16" y1="2" x2="16" y2="6" />
                  <line x1="8" y1="2" x2="8" y2="6" />
                  <line x1="3" y1="10" x2="21" y2="10" />
                </svg>
                <span className="text-[13px] text-ink-mute">No hay citas hoy</span>
              </CardContent>
            )}
          </Card>

          {/* Right column */}
          <div className="flex flex-col gap-[14px]">
            {/* Necesitan atención */}
            <Card className="rounded-card-lg overflow-hidden border-[hsl(var(--gold-line))]">
              <CardHeader className="flex flex-row items-baseline gap-3 border-b border-[hsl(var(--line-soft))] px-[18px] py-4">
                <CardTitle className="flex-1 text-[14px] font-bold text-ink">
                  Necesitan atención
                </CardTitle>
                {!escalationsLoading && !escalationsError && (
                  <span className="text-[12px] text-ink-mute">
                    {pendingEscalations} pendientes
                  </span>
                )}
              </CardHeader>
              {escalationsLoading ? (
                <EscalationSkeleton />
              ) : escalationsError ? (
                <CardContent className="py-6 text-[13px] text-ink-mute">
                  No disponible
                </CardContent>
              ) : escalations && escalations.length > 0 ? (
                <div className="flex flex-col">
                  {escalations.map((esc, idx) => (
                    <EscalationItem
                      key={esc.id}
                      href={`/conversations?conversation_id=${esc.conversation_id}&filter=escalated`}
                      customerName={esc.customer_name ?? esc.customer_phone}
                      reason={formatEscalationReason(esc.reason)}
                      relativeTime={formatRelativeTime(esc.triggered_at)}
                      isLast={idx === escalations.length - 1}
                      canResolve={canResolve}
                      resolving={resolvingSet.has(esc.id)}
                      onResolve={() => handleResolve(esc.id)}
                    />
                  ))}
                </div>
              ) : (
                <CardContent className="flex flex-col items-center justify-center gap-2 py-8 text-center">
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    className="h-7 w-7 text-[hsl(var(--status-confirm))]"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={1.5}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                    <polyline points="22 4 12 14.01 9 11.01" />
                  </svg>
                  <span className="text-[13px] text-ink-mute">Todo al día</span>
                </CardContent>
              )}
            </Card>

            {/* Top servicios */}
            <Card className="rounded-card-lg overflow-hidden">
              <CardHeader className="border-b border-[hsl(var(--line-soft))] px-[18px] py-4">
                <CardTitle className="text-[14px] font-bold text-ink">
                  Top servicios · esta semana
                </CardTitle>
              </CardHeader>
              {servicesLoading ? (
                <ServiceBarSkeleton />
              ) : topServices && topServices.length > 0 ? (
                <div className="flex flex-col gap-3 px-[18px] py-4">
                  {topServices.map((svc) => (
                    <ServiceBar
                      key={svc.name}
                      name={svc.name}
                      count={svc.count}
                      maxCount={maxServiceCount}
                    />
                  ))}
                </div>
              ) : (
                <CardContent className="flex items-center justify-center py-8 text-[13px] text-ink-mute">
                  Sin datos suficientes esta semana
                </CardContent>
              )}
            </Card>
          </div>
        </div>

        {/* Bottom row: 1fr / 1.4fr */}
        <div className="grid grid-cols-1 gap-[14px] lg:grid-cols-[1fr_1.4fr]">
          {/* Estilistas activos */}
          <Card className="rounded-card-lg overflow-hidden">
            <CardHeader className="border-b border-[hsl(var(--line-soft))] px-[18px] py-4">
              <CardTitle className="text-[14px] font-bold text-ink">
                Estilistas activos
              </CardTitle>
            </CardHeader>
            {servicesLoading ? (
              <div className="flex flex-col gap-2 p-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <Skeleton className="h-[34px] w-[34px] rounded-full" />
                    <div className="flex-1 space-y-1">
                      <Skeleton className="h-3 w-24" />
                      <Skeleton className="h-2 w-32" />
                      <Skeleton className="h-[3px] w-full rounded-full" />
                    </div>
                    <Skeleton className="h-6 w-20 rounded-full" />
                  </div>
                ))}
              </div>
            ) : stylistActivity && stylistActivity.length > 0 ? (
              <div className="flex flex-col">
                {stylistActivity.map((s, idx) => (
                  <StylistActivityRow
                    key={s.id}
                    name={s.name}
                    color={s.color}
                    appointmentsToday={s.appointments_today}
                    hoursToday={s.booked_minutes_today / 60}
                    utilizationPct={s.utilization_pct * 100}
                    statusDot={s.appointments_today > 0 ? "on" : "off"}
                    isLast={idx === stylistActivity.length - 1}
                  />
                ))}
              </div>
            ) : (
              <CardContent className="py-8 text-[13px] text-ink-mute">
                {/* GAP: stylist-activity endpoint not yet shipped */}
                Sin datos de estilistas hoy
              </CardContent>
            )}
          </Card>

          {/* Citas últimos 14 días */}
          <Card className="rounded-card-lg overflow-hidden">
            <CardHeader className="border-b border-[hsl(var(--line-soft))] px-[18px] py-4">
              <div>
                <CardTitle className="text-[14px] font-bold text-ink">
                  Citas últimos 14 días
                </CardTitle>
                <p className="mt-[2px] text-[12px] text-ink-mute">
                  {trendData
                    ? `Total: ${trendData.reduce((s, p) => s + p.count, 0)} citas`
                    : "Cargando..."}
                </p>
              </div>
            </CardHeader>
            {trendLoading ? (
              <Skeleton className="mx-4 my-4 h-[132px]" />
            ) : trendData && trendData.every((p) => p.count === 0) ? (
              <div className="flex items-center justify-center py-8 text-[13px] text-ink-mute">
                Sin datos de los últimos 14 días
              </div>
            ) : (
              <AppointmentsTrendChart data={trendData ?? []} />
            )}
          </Card>
        </div>
      </div>

      {/* Appointment wizard — lazy-loaded data, opens on "Nueva cita" click (T2.3) */}
      <AppointmentWizard
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        onSuccess={handleWizardSuccess}
        services={wizardServices}
        stylists={wizardStylists}
        customers={wizardCustomers}
        refreshCustomers={refreshWizardCustomers}
      />
    </div>
  );
}
