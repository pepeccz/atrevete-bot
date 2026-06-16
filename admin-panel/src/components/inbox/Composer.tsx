"use client";

import { useRef, useState } from "react";
import { SendHorizonal, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { usePermission } from "@/hooks/use-permission";
import { TemplatePicker } from "./TemplatePicker";
import api from "@/lib/api";
import { toast } from "sonner";

// ─── Composer State Machine ───────────────────────────────────────────────────
//
// States (FR-UI-3):
//   READY_FREETEXT          window_open=true  + bot_enabled=false  → free-text input enabled
//   READY_TEMPLATE          window_open=false + bot_enabled=false  → template picker shown
//   DISABLED_AWAIT_APPROVAL window_open=false + no approved tpls   → disabled placeholder
//
// When bot_enabled=true (any window_open value):
//   First send attempt intercepts and opens TakeoverModal before calling pause.
//   After pause confirmation the state transitions to READY_FREETEXT.

type ComposerState = "READY_FREETEXT" | "READY_TEMPLATE" | "DISABLED_AWAIT_APPROVAL";

function resolveState(
  windowOpen: boolean,
  botEnabled: boolean,
  templatesAvailable: boolean
): ComposerState {
  if (windowOpen) return "READY_FREETEXT";
  if (templatesAvailable) return "READY_TEMPLATE";
  return "DISABLED_AWAIT_APPROVAL";
}

// ─── Component ────────────────────────────────────────────────────────────────

interface ComposerProps {
  conversationId: string;
  windowOpen: boolean;
  /** Whether atencion_automatica is currently True. */
  botEnabled: boolean;
  /** Called after a message is sent or a template is dispatched so the thread refreshes. */
  onMessageSent: () => void;
  /** Called after the bot is paused via the takeover modal so BotToggle can update. */
  onBotPaused: () => void;
  /**
   * A-2 (I-2): Called to open the parent's single TakeoverModal when the user
   * tries to send while the bot is active. Replaces the local modal mount.
   */
  onRequestPause: (source: "toggle" | "send", pendingText?: string) => void;
  /**
   * A-2 (I-2): Ref set by the parent. When TakeoverModal is confirmed for a
   * "send" source, the parent calls this ref so Composer can proceed with the send.
   */
  onTakeoverConfirmedRef: React.MutableRefObject<(() => void) | null>;
}

/**
 * Composer input with state machine driving UI mode.
 * FR-UI-3, SC-1, SC-6.
 */
export function Composer({
  conversationId,
  windowOpen,
  botEnabled,
  onMessageSent,
  onBotPaused,
  onRequestPause,
  onTakeoverConfirmedRef,
}: ComposerProps) {
  const canWrite = usePermission("conversations:write");
  const canSendTemplate = usePermission("templates:send");
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  /**
   * A-2: After the parent's TakeoverModal confirms, Composer switches to
   * freetext mode for this session via this local override — avoids a
   * round-trip while still reflecting the correct UI immediately.
   */
  const [botPausedLocally, setBotPausedLocally] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Resolved effective bot state (local override after pause via modal)
  const effectiveBotEnabled = botEnabled && !botPausedLocally;

  // Templates available: only matters in template mode; approximated as true
  // unless the TemplatePicker itself surfaces the "in approval" state.
  // We don't eagerly fetch templates here — TemplatePicker does it lazily.
  const templatesAvailable = canSendTemplate;

  const composerState: ComposerState = resolveState(
    windowOpen,
    effectiveBotEnabled,
    templatesAvailable
  );

  const doSend = async (messageText: string) => {
    setSending(true);
    try {
      await api.sendMessage(conversationId, messageText);
      setText("");
      textareaRef.current?.focus();
      onMessageSent();
    } catch {
      toast.error("Error al enviar el mensaje");
    } finally {
      setSending(false);
    }
  };

  const handleSend = async () => {
    if (!text.trim()) return;

    if (effectiveBotEnabled) {
      // A-2: delegate to parent's single TakeoverModal; register a callback so
      // the parent can signal us to proceed with the send after confirmation.
      const pendingText = text.trim();
      onTakeoverConfirmedRef.current = () => {
        setBotPausedLocally(true);
        onBotPaused();
        doSend(pendingText);
      };
      onRequestPause("send", pendingText);
      return;
    }

    doSend(text.trim());
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Ctrl+Enter or Cmd+Enter sends the message.
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSend();
    }
  };

  if (!canWrite && !canSendTemplate) return null;

  if (composerState === "DISABLED_AWAIT_APPROVAL") {
    return (
      <div className="px-4 pb-4 pt-2 bg-muted/60 text-center">
        <p className="text-sm text-muted-foreground font-medium">
          Esta conversación está fuera de la ventana de 24h de Meta.
        </p>
        <p className="text-xs text-muted-foreground mt-1">
          Solo se pueden enviar plantillas aprobadas, y aún no hay ninguna aprobada para este flujo.
        </p>
      </div>
    );
  }

  if (composerState === "READY_TEMPLATE") {
    return (
      <div className="p-3">
        <TemplatePicker
          conversationId={conversationId}
          onSent={onMessageSent}
        />
      </div>
    );
  }

  // READY_FREETEXT (also used when bot is on, to render the interception flow)
  const isDisabled = sending || !canWrite;

  return (
    <>
      <div className="p-3 flex gap-2 items-end">
        <Textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            effectiveBotEnabled
              ? "Escribe un mensaje (pausará el bot automáticamente)…"
              : "Escribe un mensaje… (Ctrl+Enter para enviar)"
          }
          disabled={isDisabled}
          rows={3}
          className="resize-none flex-1 text-sm"
          aria-label="Compositor de mensaje"
        />
        <Button
          onClick={handleSend}
          disabled={isDisabled || !text.trim()}
          size="sm"
          className="h-9"
          aria-label="Enviar mensaje"
        >
          {sending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <SendHorizonal className="h-4 w-4" />
          )}
        </Button>
      </div>

    </>
  );
}
