import { ArrowUp, ArrowDown } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface KpiDelta {
  value: string | number;
  direction: "up" | "down" | "neutral";
}

interface KpiCardProps {
  label: string;
  value: string | number;
  delta?: KpiDelta;
  subline?: string;
  className?: string;
}

export function KpiCard({ label, value, delta, subline, className }: KpiCardProps) {
  const isUp = delta?.direction === "up";
  const isNeutral = delta?.direction === "neutral";

  return (
    <Card className={cn("rounded-card-lg shadow-[0_1px_2px_rgba(0,0,0,0.02)]", className)}>
      <CardContent className="px-[18px] py-4">
        {/* Label */}
        <div className="text-[12px] font-semibold uppercase tracking-[0.01em] text-ink-mute">
          {label}
        </div>

        {/* Value + delta row */}
        <div className="mt-2 flex items-baseline gap-[10px]">
          <span className="text-[28px] font-bold leading-none tracking-[-0.025em] text-ink [font-variant-numeric:tabular-nums]">
            {value}
          </span>
          {delta && (
            <span
              className={cn(
                "inline-flex items-center gap-[2px] rounded-pill px-[7px] py-[2px] text-[12.5px] font-bold",
                isNeutral
                  ? "bg-[hsl(var(--status-done-bg))] text-[hsl(var(--status-done))]"
                  : isUp
                  ? "bg-[hsl(var(--status-confirm-bg))] text-[hsl(var(--status-confirm))]"
                  : "bg-[hsl(var(--status-cancel-bg))] text-[hsl(var(--status-cancel))]"
              )}
            >
              {!isNeutral &&
                (isUp ? (
                  <ArrowUp className="h-[11px] w-[11px]" />
                ) : (
                  <ArrowDown className="h-[11px] w-[11px]" />
                ))}
              {delta.value}
            </span>
          )}
        </div>

        {/* Subline */}
        {subline && (
          <p className="mt-[6px] text-[11.5px] text-ink-mute">{subline}</p>
        )}
      </CardContent>
    </Card>
  );
}
