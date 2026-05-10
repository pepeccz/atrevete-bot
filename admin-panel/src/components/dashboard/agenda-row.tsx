import { MoreHorizontal } from "lucide-react";
import { StatusPill } from "./status-pill";
import { deriveStylistPalette } from "@/lib/stylist-colors";
import type { AppointmentStatus } from "@/lib/types";

interface AgendaRowProps {
  time: string;
  durationMin: number;
  stylist: { name: string; color: string };
  customerName: string;
  serviceName: string;
  status: AppointmentStatus;
  onClick?: () => void;
  isLast?: boolean;
}

export function AgendaRow({
  time,
  durationMin,
  stylist,
  customerName,
  serviceName,
  status,
  onClick,
  isLast = false,
}: AgendaRowProps) {
  const palette = deriveStylistPalette(stylist.color);

  return (
    <div
      className={`flex items-center gap-[14px] px-[18px] py-3 ${!isLast ? "border-b border-[hsl(var(--line-soft))]" : ""}`}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={onClick ? (e) => e.key === "Enter" && onClick() : undefined}
      style={{ cursor: onClick ? "pointer" : "default" }}
    >
      {/* Time */}
      <div className="w-14 shrink-0 text-[14px] font-bold text-ink [font-variant-numeric:tabular-nums]">
        {time}
      </div>

      {/* Stylist color bar */}
      <div
        className="h-8 w-1 shrink-0 rounded-pill"
        style={{ background: palette.solid }}
        aria-hidden="true"
      />

      {/* Content */}
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-bold text-ink truncate">{customerName}</div>
        <div className="mt-[2px] text-[12px] text-ink-mute truncate">
          {serviceName} · {durationMin} min · con {stylist.name}
        </div>
      </div>

      {/* Status pill */}
      <StatusPill status={status} />

      {/* Overflow menu */}
      <MoreHorizontal className="h-4 w-4 shrink-0 text-ink-mute" aria-label="Opciones" />
    </div>
  );
}
