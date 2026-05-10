interface ServiceBarProps {
  name: string;
  count: number;
  maxCount: number;
}

export function ServiceBar({ name, count, maxCount }: ServiceBarProps) {
  const pct = maxCount > 0 ? Math.min(100, (count / maxCount) * 100) : 0;

  return (
    <div>
      <div className="mb-[5px] flex items-baseline justify-between">
        <span className="text-[12.5px] font-semibold text-ink">{name}</span>
        <span className="text-[12px] font-bold text-ink-soft [font-variant-numeric:tabular-nums]">
          {count}
        </span>
      </div>
      <div
        className="h-[6px] overflow-hidden rounded-pill"
        style={{ background: "hsl(var(--line-soft))" }}
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${name}: ${count} citas`}
      >
        <div
          className="h-full rounded-pill transition-all duration-300"
          style={{
            width: `${pct}%`,
            background: "hsl(var(--gold))",
          }}
        />
      </div>
    </div>
  );
}
