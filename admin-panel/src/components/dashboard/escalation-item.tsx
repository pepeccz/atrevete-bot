import Link from "next/link";
import { AlertCircle, CheckCircle } from "lucide-react";

interface EscalationItemProps {
  customerName: string;
  reason: string;
  relativeTime: string;
  isLast?: boolean;
  /** When provided, wraps the item in a Next.js Link for navigation. */
  href?: string;
  /** Whether the current user can resolve escalations. When false, the resolve button is absent. */
  canResolve?: boolean;
  /** Called when the user clicks the resolve button. Must be provided alongside canResolve. */
  onResolve?: (e: React.MouseEvent) => void;
}

export function EscalationItem({
  customerName,
  reason,
  relativeTime,
  isLast = false,
  href,
  canResolve = false,
  onResolve,
}: EscalationItemProps) {
  const containerClass = `flex items-start gap-[10px] px-[18px] py-3 ${!isLast ? "border-b border-[hsl(var(--line-soft))]" : ""}`;
  const interactiveClass =
    "transition-colors hover:bg-[hsl(var(--gold-soft))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold cursor-pointer";

  const body = (
    <>
      {/* Alert icon circle */}
      <div
        className="flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-full"
        style={{
          background: "hsl(var(--status-cancel-bg))",
          color: "hsl(var(--status-cancel))",
        }}
        aria-hidden="true"
      >
        <AlertCircle className="h-[14px] w-[14px]" />
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-bold text-ink">{customerName}</div>
        <div className="mt-[2px] text-[11.5px] leading-[1.35] text-ink-soft line-clamp-2">
          {reason}
        </div>
        <div className="mt-1 text-[11px] text-ink-mute">{relativeTime}</div>
      </div>

      {/* Resolve button — rendered absent when user lacks permission */}
      {canResolve && onResolve && (
        <button
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onResolve(e);
          }}
          className="shrink-0 flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium text-[hsl(var(--status-confirm))] hover:bg-[hsl(var(--status-confirm-bg))] transition-colors"
          aria-label="Resolver escalación"
          title="Resolver escalación"
        >
          <CheckCircle className="h-[13px] w-[13px]" />
          Resolver
        </button>
      )}
    </>
  );

  return href ? (
    <Link href={href} className={`${containerClass} ${interactiveClass}`}>
      {body}
    </Link>
  ) : (
    <div className={containerClass}>{body}</div>
  );
}
