"use client";

import { deriveStylistPalette } from "@/lib/stylist-colors";

interface StylistItem {
  id: string;
  name: string;
  color?: string;
}

export type AppointmentStatus = "confirmed" | "pending" | "cancelled" | "completed" | "no_show";

interface StatusCount {
  status: AppointmentStatus;
  count: number;
}

interface StylistChipFilterProps {
  stylists: StylistItem[];
  active: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: () => void;
  statusCounts?: StatusCount[];
}

const STATUS_LABELS: Record<AppointmentStatus, string> = {
  confirmed: "Confirmada",
  pending: "Pendiente",
  cancelled: "Cancelada",
  completed: "Completada",
  no_show: "No asistió",
};

const STATUS_DOT_CLASS: Record<AppointmentStatus, string> = {
  confirmed: "bg-[hsl(var(--status-confirm))]",
  pending: "bg-[hsl(var(--status-pending))]",
  cancelled: "bg-[hsl(var(--status-cancel))]",
  completed: "bg-[hsl(var(--status-done))]",
  no_show: "bg-[hsl(var(--status-cancel))]",
};

export function StylistChipFilter({
  stylists,
  active,
  onToggle,
  onToggleAll,
  statusCounts = [],
}: StylistChipFilterProps) {
  const allActive = stylists.length > 0 && stylists.every(s => active.has(s.id));

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 border-b border-line bg-white">
      {/* Left side: chips */}
      <div className="flex flex-wrap items-center gap-2">
        {/* Todos chip */}
        <button
          onClick={onToggleAll}
          className={[
            "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition-all border",
            allActive
              ? "bg-[hsl(var(--gold-soft))] text-[hsl(var(--gold-dark))] border-[hsl(var(--gold-line))]"
              : "bg-white text-ink-mute border-line opacity-55 hover:opacity-100",
          ].join(" ")}
          role="checkbox"
          aria-checked={allActive}
          aria-label="Mostrar todos los estilistas"
        >
          Todos
        </button>

        {/* Per-stylist chips */}
        {stylists.map((stylist) => {
          const isActive = active.has(stylist.id);
          const palette = deriveStylistPalette(stylist.color || "#928679");

          return (
            <button
              key={stylist.id}
              onClick={() => onToggle(stylist.id)}
              className={[
                "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition-all border",
                isActive ? "opacity-100" : "bg-white border-line opacity-55 hover:opacity-80",
              ].join(" ")}
              style={
                isActive
                  ? {
                      backgroundColor: palette.soft,
                      color: palette.text,
                      borderColor: palette.solid + "44",
                    }
                  : undefined
              }
              role="checkbox"
              aria-checked={isActive}
              aria-label={`${isActive ? "Ocultar" : "Mostrar"} citas de ${stylist.name}`}
            >
              <span
                className="w-2 h-2 rounded-full flex-shrink-0"
                style={{ backgroundColor: isActive ? palette.solid : "#c4b8a8" }}
              />
              {stylist.name}
            </button>
          );
        })}
      </div>

      {/* Right side: status legend */}
      {statusCounts.length > 0 && (
        <div className="flex items-center gap-4">
          {statusCounts
            .filter((sc) => sc.count > 0)
            .map((sc) => (
              <span key={sc.status} className="inline-flex items-center gap-1.5 text-xs text-ink-mute">
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${STATUS_DOT_CLASS[sc.status]}`} />
                <span className="font-medium text-ink-soft">{STATUS_LABELS[sc.status]}</span>
                <span className="tabular-nums font-semibold text-ink">{sc.count}</span>
              </span>
            ))}
        </div>
      )}
    </div>
  );
}
