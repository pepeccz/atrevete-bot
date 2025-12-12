"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Header } from "@/components/layout/header";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Calendar, Users, Clock, TrendingUp, Bell, Check, X, CheckCheck } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { es } from "date-fns/locale";
import api from "@/lib/api";
import type { Notification, NotificationsListResponse } from "@/lib/types";
import { cn } from "@/lib/utils";
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

// Notification icon mapping
const notificationIcons: Record<string, typeof Calendar> = {
  appointment_created: Calendar,
  appointment_cancelled: X,
  appointment_confirmed: Check,
  appointment_completed: CheckCheck,
};

const notificationColors: Record<string, string> = {
  appointment_created: "text-green-500",
  appointment_cancelled: "text-red-500",
  appointment_confirmed: "text-blue-500",
  appointment_completed: "text-gray-500",
};

export default function DashboardPage() {
  const router = useRouter();
  const [kpis, setKpis] = useState<KPIs | null>(null);
  const [chartData, setChartData] = useState<ChartData | null>(null);
  const [notifications, setNotifications] = useState<NotificationsListResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchNotifications = useCallback(async () => {
    try {
      const response = await api.getNotifications(5, false); // Solo no leídas, máximo 5
      setNotifications(response);
    } catch (error) {
      console.error("Failed to fetch notifications:", error);
    }
  }, []);

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

  // Fetch notifications and set up polling
  useEffect(() => {
    fetchNotifications();
    const interval = setInterval(fetchNotifications, 30000); // Poll every 30 seconds
    return () => clearInterval(interval);
  }, [fetchNotifications]);

  const handleNotificationClick = async (notification: Notification) => {
    // Mark as read
    try {
      await api.markNotificationRead(notification.id);
      fetchNotifications(); // Refresh
    } catch (error) {
      console.error("Failed to mark notification as read:", error);
    }
    // Navigate to appointment
    if (notification.entity_type === "appointment" && notification.entity_id) {
      router.push(`/appointments?highlight=${notification.entity_id}`);
    }
  };

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

        {/* Notifications Widget */}
        {notifications && notifications.unread_count > 0 && (
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <div>
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Bell className="h-4 w-4" />
                  Notificaciones Recientes
                </CardTitle>
                <CardDescription>
                  {notifications.unread_count} sin leer
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {notifications.items.slice(0, 5).map((notification) => {
                  const Icon = notificationIcons[notification.type] || Bell;
                  const colorClass = notificationColors[notification.type] || "text-gray-500";
                  return (
                    <button
                      key={notification.id}
                      onClick={() => handleNotificationClick(notification)}
                      className="w-full flex items-start gap-3 p-2 rounded-md hover:bg-accent text-left transition-colors"
                    >
                      <div className={cn("mt-0.5", colorClass)}>
                        <Icon className="h-4 w-4" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium">{notification.title}</p>
                        <p className="text-xs text-muted-foreground line-clamp-1">
                          {notification.message}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {formatDistanceToNow(new Date(notification.created_at), {
                            addSuffix: true,
                            locale: es,
                          })}
                        </p>
                      </div>
                    </button>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        )}

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
