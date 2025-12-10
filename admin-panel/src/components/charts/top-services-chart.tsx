"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

interface TopServicesChartProps {
  data: Array<{ name: string; count: number }>;
}

export function TopServicesChart({ data }: TopServicesChartProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Servicios Más Solicitados</CardTitle>
        <CardDescription>Top 10 últimos 90 días</CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={data} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" />
            <YAxis dataKey="name" type="category" width={150} />
            <Tooltip />
            <Bar dataKey="count" fill="hsl(var(--primary))" name="Reservas" />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
