"use client";

import { BotOff, RotateCcw, Loader2 } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { usePermission } from "@/hooks/use-permission";
import { toast } from "sonner";
import api from "@/lib/api";
import { formatEscalationReason } from "@/lib/category-labels";

interface PausedBannerProps {
  conversationId: string;
  /** ISO string of when the bot was paused. Displayed as context. */
  pausedAt: string | null;
  /**
   * R3a: Escalation reason from the triggered Escalation row.
   * E.g. "Manual takeover by admin/stylist", "cancellation_window_exception", etc.
   * When present, shown as a badge so the asistenta knows WHY the bot was paused.
   */
  escalationReason?: string | null;
  /**
   * R3a: Escalation source (manual | safety | cancellation_window_exception | …).
   * Used to render a human-readable label alongside the reason.
   */
  escalationSource?: string | null;
  /** Called after a successful resume so the parent can refresh state. */
  onResumed: () => void;
}

/**
 * Maps escalation source values to human-readable Spanish labels.
 * "manual" = asistenta explicitly took over.
 * Other values come from the bot's escalation_service.py logic.
 */
function escalationSourceLabel(source: string | null | undefined): string {
  switch (source) {
    case "manual":
      return "Atención manual";
    case "auto_error":
      return "Error técnico";
    case "fallback":
      return "Escalación automática";
    default:
      return "Escalación";
  }
}

/**
 * Persistent sticky banner shown on paused conversations.
 * R3a: surfaces escalation reason + source so asistentas know WHY the bot is paused.
 * "Reanudar bot" calls POST /api/admin/conversations/{id}/resume.
 * FR-UI-5, SC-6.
 */
export function PausedBanner({
  conversationId,
  pausedAt,
  escalationReason,
  escalationSource,
  onResumed,
}: PausedBannerProps) {
  const canResume = usePermission("bot:resume");
  const [loading, setLoading] = useState(false);

  const handleResume = async () => {
    setLoading(true);
    try {
      await api.resumeConversation(conversationId);
      toast.success("Bot reanudado. El contexto de la pausa se inyectará en el próximo mensaje.");
      onResumed();
    } catch {
      toast.error("Error al reanudar el bot");
    } finally {
      setLoading(false);
    }
  };

  const pausedLabel = pausedAt
    ? new Date(pausedAt).toLocaleString("es-ES", {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

  const sourceLabel = escalationSourceLabel(escalationSource);

  return (
    <div className="flex items-center gap-3 px-4 py-2.5 bg-amber-50 border-b border-amber-200 text-amber-800">
      <BotOff className="h-4 w-4 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium">
            Bot pausado{pausedLabel ? ` desde ${pausedLabel}` : ""}
          </span>
          {/* R3a: show escalation reason as a badge when available */}
          {escalationSource && (
            <Badge
              variant="outline"
              className="text-[10px] px-1.5 py-0 border-amber-400 text-amber-700 font-normal"
            >
              {sourceLabel}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-1 mt-0.5">
          <span className="text-xs text-amber-600">
            Los mensajes del cliente se guardan pero no llegan al bot.
          </span>
          {escalationReason && escalationSource !== "manual" && (
            <span className="text-xs text-amber-600">
              · {formatEscalationReason(escalationReason)}
            </span>
          )}
        </div>
      </div>
      {canResume && (
        <Button
          variant="outline"
          size="sm"
          onClick={handleResume}
          disabled={loading}
          className="border-amber-400 text-amber-800 hover:bg-amber-100 flex-shrink-0"
        >
          {loading ? (
            <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
          ) : (
            <RotateCcw className="h-3.5 w-3.5 mr-1.5" />
          )}
          Reanudar bot
        </Button>
      )}
    </div>
  );
}
