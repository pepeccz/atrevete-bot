"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { format, parseISO } from "date-fns";
import { es } from "date-fns/locale";

interface NotificationsTrendChartProps {
  data: Array<{ date: string; count: number }>;
}

export function NotificationsTrendChart({ data }: NotificationsTrendChartProps) {
  const formattedData = data.map((item) => ({
    ...item,
    dateLabel: format(parseISO(item.date), "d MMM", { locale: es }),
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Tendencia de Notificaciones</CardTitle>
        <CardDescription>Ultimos 30 dias</CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={formattedData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="dateLabel" tick={{ fontSize: 12 }} />
            <YAxis />
            <Tooltip
              labelFormatter={(value) => `Fecha: ${value}`}
              formatter={(value: number) => [value, "Notificaciones"]}
            />
            <Area
              type="monotone"
              dataKey="count"
              stroke="hsl(var(--primary))"
              fill="hsl(var(--primary) / 0.2)"
              strokeWidth={2}
              name="Notificaciones"
            />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
