import { deriveStylistPalette } from "@/lib/stylist-colors";
import { cn } from "@/lib/utils";

type StylistStatus = "on" | "idle" | "off";

interface StylistActivityRowProps {
  name: string;
  color: string;
  appointmentsToday: number;
  hoursToday: number;
  utilizationPct: number;
  statusDot?: StylistStatus;
  isLast?: boolean;
}

const STATUS_CONFIG: Record<
  StylistStatus,
  { label: string; pillBg: string; textColor: string; dotColor: string }
> = {
  on: {
    label: "Atendiendo",
    pillBg: "bg-[hsl(var(--status-confirm-bg))]",
    textColor: "text-[hsl(var(--status-confirm))]",
    dotColor: "bg-[hsl(var(--status-confirm))]",
  },
  idle: {
    label: "En pausa",
    pillBg: "bg-[hsl(var(--status-pending-bg))]",
    textColor: "text-[hsl(var(--status-pending-fg,var(--status-pending)))]",
    dotColor: "bg-[hsl(var(--status-pending))]",
  },
  off: {
    label: "Fuera",
    pillBg: "bg-[hsl(var(--line-soft))]",
    textColor: "text-ink-mute",
    dotColor: "bg-ink-mute",
  },
};

export function StylistActivityRow({
  name,
  color,
  appointmentsToday,
  hoursToday,
  utilizationPct,
  statusDot = "off",
  isLast = false,
}: StylistActivityRowProps) {
  const palette = deriveStylistPalette(color);
  const statusCfg = STATUS_CONFIG[statusDot];
  const pct = Math.min(100, utilizationPct);

  return (
    <div
      className={cn(
        "flex items-center gap-3 px-[14px] py-3",
        !isLast && "border-b border-[hsl(var(--line-soft))]"
      )}
    >
      {/* Avatar */}
      <div
        className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-full text-[13px] font-bold"
        style={{ background: palette.soft, color: palette.text }}
        aria-hidden="true"
      >
        {name[0]}
      </div>

      {/* Name + stats */}
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-bold text-ink">{name}</div>
        <div className="mt-[1px] text-[11.5px] text-ink-mute">
          {appointmentsToday} citas · {hoursToday.toFixed(1)}h
        </div>
        {/* Utilization bar */}
        <div
          className="mt-[4px] h-[3px] w-full overflow-hidden rounded-pill"
          style={{ background: "hsl(var(--line-soft))" }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Ocupación de ${name}: ${pct.toFixed(0)}%`}
        >
          <div
            className="h-full rounded-pill"
            style={{ width: `${pct}%`, background: palette.solid }}
          />
        </div>
      </div>

      {/* Status badge */}
      <span
        className={cn(
          "inline-flex items-center gap-[5px] rounded-pill px-[9px] py-[3px] text-[11.5px] font-semibold",
          statusCfg.pillBg,
          statusCfg.textColor
        )}
      >
        <span className={cn("h-[5px] w-[5px] rounded-full", statusCfg.dotColor)} />
        {statusCfg.label}
      </span>
    </div>
  );
}
