"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";

interface StylistPerformanceChartProps {
  data: Array<{ name: string; appointments: number; hours: number }>;
}

export function StylistPerformanceChart({ data }: StylistPerformanceChartProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Rendimiento por Estilista</CardTitle>
        <CardDescription>Mes actual</CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" />
            <YAxis yAxisId="left" />
            <YAxis yAxisId="right" orientation="right" />
            <Tooltip />
            <Legend />
            <Bar
              yAxisId="left"
              dataKey="appointments"
              fill="hsl(var(--primary))"
              name="Citas"
            />
            <Bar
              yAxisId="right"
              dataKey="hours"
              fill="hsl(var(--accent))"
              name="Horas"
            />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
