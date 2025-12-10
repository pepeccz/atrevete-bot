"use client";

import { useEffect, useState } from "react";
import { Header } from "@/components/layout/header";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Calendar, Users, Clock, TrendingUp } from "lucide-react";
import api from "@/lib/api";
import { AppointmentTrendChart } from "@/components/charts/appointments-trend-chart";
import { TopServicesChart } from "@/components/charts/top-services-chart";
import { HoursWorkedChart } from "@/components/charts/hours-worked-chart";
import { CustomerGrowthChart } from "@/components/charts/customer-growth-chart";
import { StylistPerformanceChart } from "@/components/charts/stylist-performance-chart";

interface KPIs {
  appointments_this_month: number;
  total_customers: number;
  avg_appointment_duration: number;
  total_hours_booked: number;
}

interface ChartData {
  appointmentsTrend: Array<{ date: string; count: number }>;
  topServices: Array<{ name: string; count: number }>;
  hoursWorked: Array<{ month: string; hours: number }>;
  customerGrowth: Array<{ month: string; count: number }>;
  stylistPerformance: Array<{ name: string; appointments: number; hours: number }>;
}

function KPICard({
  title,
  value,
  description,
  icon: Icon,
}: {
  title: string;
  value: string | number;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        <p className="text-xs text-muted-foreground">{description}</p>
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const [kpis, setKpis] = useState<KPIs | null>(null);
  const [chartData, setChartData] = useState<ChartData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      try {
        // Fetch KPIs
        const kpisData = await api.getDashboardKPIs();
        setKpis(kpisData);

        // Fetch all chart data in parallel
        const [
          appointmentsTrend,
          topServices,
          hoursWorked,
          customerGrowth,
          stylistPerformance,
        ] = await Promise.all([
          api.getAppointmentsTrend(),
          api.getTopServices(),
          api.getHoursWorked(),
          api.getCustomerGrowth(),
          api.getStylistPerformance(),
        ]);

        setChartData({
          appointmentsTrend,
          topServices,
          hoursWorked,
          customerGrowth,
          stylistPerformance,
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando datos");
        // Use mock data if API not ready
        setKpis({
          appointments_this_month: 0,
          total_customers: 0,
          avg_appointment_duration: 0,
          total_hours_booked: 0,
        });
        setChartData({
          appointmentsTrend: [],
          topServices: [],
          hoursWorked: [],
          customerGrowth: [],
          stylistPerformance: [],
        });
      } finally {
        setIsLoading(false);
      }
    }

    fetchData();
  }, []);

  return (
    <div className="flex flex-col">
      <Header
        title="Dashboard"
        description="Vista general del salon"
      />

      <div className="flex-1 space-y-6 p-6">
        {/* KPI Cards */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <KPICard
            title="Citas este mes"
            value={isLoading ? "..." : kpis?.appointments_this_month ?? 0}
            description="Total de citas agendadas"
            icon={Calendar}
          />
          <KPICard
            title="Clientes totales"
            value={isLoading ? "..." : kpis?.total_customers ?? 0}
            description="Clientes registrados"
            icon={Users}
          />
          <KPICard
            title="Duracion promedio"
            value={
              isLoading
                ? "..."
                : `${kpis?.avg_appointment_duration ?? 0} min`
            }
            description="Tiempo promedio por cita"
            icon={Clock}
          />
          <KPICard
            title="Horas reservadas"
            value={isLoading ? "..." : kpis?.total_hours_booked ?? 0}
            description="Horas totales este mes"
            icon={TrendingUp}
          />
        </div>

        {error && (
          <Card className="border-amber-200 bg-amber-50">
            <CardContent className="pt-6">
              <p className="text-sm text-amber-800">
                <strong>Nota:</strong> {error}
              </p>
            </CardContent>
          </Card>
        )}

        {/* Charts Row 1 */}
        <div className="grid gap-4 md:grid-cols-2">
          {isLoading ? (
            <>
              <Card>
                <CardHeader>
                  <CardTitle>Tendencia de Citas</CardTitle>
                  <CardDescription>Cargando...</CardDescription>
                </CardHeader>
                <CardContent className="h-[300px] flex items-center justify-center">
                  <div className="text-muted-foreground">Cargando datos...</div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle>Servicios Populares</CardTitle>
                  <CardDescription>Cargando...</CardDescription>
                </CardHeader>
                <CardContent className="h-[300px] flex items-center justify-center">
                  <div className="text-muted-foreground">Cargando datos...</div>
                </CardContent>
              </Card>
            </>
          ) : (
            <>
              <AppointmentTrendChart data={chartData?.appointmentsTrend ?? []} />
              <TopServicesChart data={chartData?.topServices ?? []} />
            </>
          )}
        </div>

        {/* Charts Row 2 */}
        <div className="grid gap-4 md:grid-cols-2">
          {isLoading ? (
            <>
              <Card>
                <CardHeader>
                  <CardTitle>Horas Trabajadas</CardTitle>
                  <CardDescription>Cargando...</CardDescription>
                </CardHeader>
                <CardContent className="h-[300px] flex items-center justify-center">
                  <div className="text-muted-foreground">Cargando datos...</div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle>Crecimiento de Clientes</CardTitle>
                  <CardDescription>Cargando...</CardDescription>
                </CardHeader>
                <CardContent className="h-[300px] flex items-center justify-center">
                  <div className="text-muted-foreground">Cargando datos...</div>
                </CardContent>
              </Card>
            </>
          ) : (
            <>
              <HoursWorkedChart data={chartData?.hoursWorked ?? []} />
              <CustomerGrowthChart data={chartData?.customerGrowth ?? []} />
            </>
          )}
        </div>

        {/* Chart Row 3 */}
        {!isLoading && chartData?.stylistPerformance && (
          <StylistPerformanceChart data={chartData.stylistPerformance} />
        )}
      </div>
    </div>
  );
}
