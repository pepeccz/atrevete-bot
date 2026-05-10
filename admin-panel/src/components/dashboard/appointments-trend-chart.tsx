"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { AppointmentTrendPoint } from "@/lib/types";

interface AppointmentsTrendChartProps {
  data: AppointmentTrendPoint[];
}

/** Format ISO date as "L", "M", "X", "J", "V", "S", "D" */
function dayLabel(isoDate: string): string {
  const labels = ["D", "L", "M", "X", "J", "V", "S"];
  const d = new Date(isoDate + "T12:00:00"); // noon to avoid TZ edge cases
  return labels[d.getDay()];
}

/** Returns true if the ISO date string is today */
function isToday(isoDate: string): boolean {
  const today = new Date().toISOString().slice(0, 10);
  return isoDate === today;
}

const GOLD = "hsl(38, 43%, 51%)";
const GOLD_SOFT = "hsl(41, 56%, 90%)";
const GOLD_LINE = "hsl(40, 47%, 83%)";

export function AppointmentsTrendChart({ data }: AppointmentsTrendChartProps) {
  const total = data.reduce((sum, p) => sum + p.count, 0);

  if (data.length === 0) {
    return (
      <div className="flex h-[132px] items-center justify-center text-[13px] text-ink-mute">
        Sin datos
      </div>
    );
  }

  return (
    <div className="px-[18px] pb-[18px] pt-[14px]">
      <ResponsiveContainer width="100%" height={132}>
        <BarChart data={data} barCategoryGap="20%" margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="date"
            tickFormatter={dayLabel}
            tick={{ fontSize: 10.5, fontWeight: 600, fill: "hsl(30, 11%, 53%)" }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis hide />
          <Tooltip
            cursor={false}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const point = payload[0].payload as AppointmentTrendPoint;
              return (
                <div className="rounded-card-sm border border-[hsl(var(--line))] bg-white px-2 py-1 text-[11.5px] shadow-sm">
                  <span className="font-semibold text-ink">{point.count} citas</span>
                  <span className="ml-1 text-ink-mute">{point.date}</span>
                </div>
              );
            }}
          />
          <Bar dataKey="count" radius={[4, 4, 0, 0]}>
            {data.map((entry) => (
              <Cell
                key={entry.date}
                fill={isToday(entry.date) ? GOLD : GOLD_SOFT}
                stroke={isToday(entry.date) ? "hsl(35, 49%, 36%)" : GOLD_LINE}
                strokeWidth={1}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="mt-1 text-right text-[11px] text-ink-mute">
        Total: {total} citas
      </div>
    </div>
  );
}
