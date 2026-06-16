"use client";

import { useState } from "react";
import { Bot, BotOff, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { usePermission } from "@/hooks/use-permission";
import api, { ApiRequestError } from "@/lib/api";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

interface BotToggleProps {
  conversationId: string;
  /** Whether atencion_automatica is currently True (bot is active). */
  botEnabled: boolean;
  /** Called after the toggle state changes so parent can refresh. */
  onToggled: (newBotEnabled: boolean) => void;
  /**
   * A-2 (I-2): Called instead of opening a local TakeoverModal.
   * The parent (ConversationThread) owns the single modal instance.
   */
  onRequestPause: (source: "toggle" | "send", pendingText?: string) => void;
}

/**
 * Header control that reflects and toggles the atencion_automatica state.
 *
 * - Bot ON → clicking requests a pause via the parent's single TakeoverModal.
 * - Bot OFF → clicking resumes directly.
 *
 * Permissions: bot:pause / bot:resume (each can be absent independently).
 * FR-UI-3, FR-UI-4, SC-6.
 */
export function BotToggle({ conversationId, botEnabled, onToggled, onRequestPause }: BotToggleProps) {
  const canPause = usePermission("bot:pause");
  const canResume = usePermission("bot:resume");
  const [loading, setLoading] = useState(false);

  const handleClick = () => {
    if (botEnabled) {
      if (!canPause) return;
      // A-2: delegate to parent's single TakeoverModal instead of mounting a local one
      onRequestPause("toggle");
    } else {
      if (!canResume) return;
      handleResume();
    }
  };

  const handleResume = async () => {
    setLoading(true);
    try {
      await api.resumeConversation(conversationId);
      toast.success("Bot reanudado correctamente.");
      onToggled(true);
    } catch (err) {
      if (err instanceof ApiRequestError && err.status === 409) {
        toast.error("La conversación ya está activa — recarga para ver el estado actual.");
      } else if (err instanceof ApiRequestError && err.status === 502) {
        toast.error("No se pudo contactar con Chatwoot. Intenta nuevamente en unos segundos.");
      } else {
        toast.error("Error al reanudar el bot");
      }
    } finally {
      setLoading(false);
    }
  };

  const isDisabled = loading || (botEnabled ? !canPause : !canResume);

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={handleClick}
      disabled={isDisabled}
      className={cn(
        "gap-1.5 text-sm font-medium cursor-pointer",
        botEnabled
          ? "border-green-400 text-green-700 hover:bg-green-50"
          : "border-amber-400 text-amber-700 hover:bg-amber-50"
      )}
      aria-label={botEnabled ? "Pausar bot y tomar control" : "Reanudar bot"}
      title={
        botEnabled
          ? "El bot está activo — hacer clic para pausar y registrar una escalación manual"
          : "El bot está pausado — hacer clic para reanudar"
      }
    >
      {loading ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : botEnabled ? (
        <Bot className="h-3.5 w-3.5" />
      ) : (
        <BotOff className="h-3.5 w-3.5" />
      )}
      {botEnabled ? "Bot activo" : "Bot pausado"}
    </Button>
  );
}
