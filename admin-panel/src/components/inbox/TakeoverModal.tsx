"use client";

import { useState } from "react";
import { BotOff, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import api, { ApiRequestError } from "@/lib/api";
import { toast } from "sonner";

interface TakeoverModalProps {
  open: boolean;
  conversationId: string;
  /** Called after the pause succeeds — parent should proceed with sending the message. */
  onConfirmed: () => void;
  /** Called when the user cancels — parent should abort the send. */
  onCancelled: () => void;
}

/**
 * Modal shown when a user tries to send a message while the bot is ON.
 * Explains that sending will pause the bot and create a manual Escalation.
 * On confirm: calls POST /api/admin/conversations/{id}/pause with source="manual".
 * FR-UI-4, SC-6.
 */
export function TakeoverModal({
  open,
  conversationId,
  onConfirmed,
  onCancelled,
}: TakeoverModalProps) {
  const [loading, setLoading] = useState(false);

  const handleConfirm = async () => {
    setLoading(true);
    try {
      await api.pauseConversation(conversationId, "manual", "Takeover manual desde el panel");
      toast.success("Bot pausado. Puedes enviar tu mensaje ahora.");
      onConfirmed();
    } catch (err) {
      if (err instanceof ApiRequestError && err.status === 409) {
        toast.error("La conversación ya está pausada — recarga para ver el estado actual.");
      } else if (err instanceof ApiRequestError && err.status === 502) {
        toast.error("No se pudo contactar con Chatwoot. Intenta nuevamente en unos segundos.");
      } else {
        toast.error("Error al pausar el bot");
      }
      onCancelled();
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onCancelled()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <BotOff className="h-5 w-5 text-amber-500" />
            ¿Tomar control manualmente?
          </DialogTitle>
          <DialogDescription className="space-y-2 text-sm pt-2">
            <p>
              El bot está activo en esta conversación. Al enviar un mensaje
              desde el panel se pausará el bot automáticamente y se registrará
              una escalación manual.
            </p>
            <p className="font-medium text-foreground">
              Cuando termines de atender al cliente, usa el botón{" "}
              <span className="font-semibold">«Reanudar bot»</span> para que
              el asistente retome el contexto.
            </p>
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={onCancelled} disabled={loading}>
            Cancelar
          </Button>
          <Button onClick={handleConfirm} disabled={loading}>
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Pausando…
              </>
            ) : (
              "Tomar control"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
