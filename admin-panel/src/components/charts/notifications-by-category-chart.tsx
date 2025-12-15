"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";

interface NotificationsByCategoryChartProps {
  data: Record<string, number>;
}

const CATEGORY_COLORS: Record<string, string> = {
  citas: "hsl(var(--primary))",
  confirmaciones: "hsl(210, 70%, 50%)",
  escalaciones: "hsl(0, 70%, 50%)",
};

const CATEGORY_LABELS: Record<string, string> = {
  citas: "Citas",
  confirmaciones: "Confirmaciones",
  escalaciones: "Escalaciones",
};

export function NotificationsByCategoryChart({ data }: NotificationsByCategoryChartProps) {
  const chartData = Object.entries(data).map(([category, count]) => ({
    name: CATEGORY_LABELS[category] || category,
    count,
    category,
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Notificaciones por Categoria</CardTitle>
        <CardDescription>Total historico por tipo</CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" />
            <YAxis />
            <Tooltip />
            <Bar dataKey="count" name="Total">
              {chartData.map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={CATEGORY_COLORS[entry.category] || "hsl(var(--muted))"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
