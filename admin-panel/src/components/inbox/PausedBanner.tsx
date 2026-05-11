"use client";

import { BotOff, RotateCcw, Loader2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { usePermission } from "@/hooks/use-permission";
import { toast } from "sonner";
import api from "@/lib/api";

interface PausedBannerProps {
  conversationId: string;
  /** ISO string of when the bot was paused. Displayed as context. */
  pausedAt: string | null;
  /** Called after a successful resume so the parent can refresh state. */
  onResumed: () => void;
}

/**
 * Persistent sticky banner shown on paused conversations.
 * "Reanudar bot" calls POST /api/admin/conversations/{id}/resume.
 * FR-UI-5, SC-6.
 */
export function PausedBanner({ conversationId, pausedAt, onResumed }: PausedBannerProps) {
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

  return (
    <div className="flex items-center gap-3 px-4 py-2.5 bg-amber-50 border-b border-amber-200 text-amber-800">
      <BotOff className="h-4 w-4 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <span className="text-sm font-medium">
          Bot pausado{pausedLabel ? ` desde ${pausedLabel}` : ""}
        </span>
        <span className="text-xs text-amber-600 ml-2">
          Los mensajes del cliente se guardan pero no llegan al bot.
        </span>
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
