import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface KpiCardProps {
  label: string;
  value: string | number;
  subline?: string;
  className?: string;
}

export function KpiCard({ label, value, subline, className }: KpiCardProps) {
  return (
    <Card
      className={cn("rounded-card-lg shadow-[0_1px_2px_rgba(0,0,0,0.02)]", className)}
      role="article"
      aria-label={`${label}: ${value}${subline ? ` — ${subline}` : ""}`}
    >
      <CardContent className="px-[18px] py-4">
        {/* Label */}
        <div className="text-[12px] font-semibold uppercase tracking-[0.01em] text-ink-mute">
          {label}
        </div>

        {/* Value row */}
        <div className="mt-2 flex items-baseline gap-[10px]">
          <span className="text-[28px] font-bold leading-none tracking-[-0.025em] text-ink [font-variant-numeric:tabular-nums]">
            {value}
          </span>
        </div>

        {/* Subline */}
        {subline && (
          <p className="mt-[6px] text-[11.5px] text-ink-mute">{subline}</p>
        )}
      </CardContent>
    </Card>
  );
}
