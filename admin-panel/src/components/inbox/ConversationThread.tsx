"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, MessageSquare } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { PausedBanner } from "./PausedBanner";
import { Composer } from "./Composer";
import { BotToggle } from "./BotToggle";
import { formatDate } from "@/components/shared/format-utils";
import { useConversationPolling } from "@/hooks/useConversationPolling";
import api from "@/lib/api";
import type { ConversationHistory, ConversationMessage, ConversationHistoryInbox } from "@/lib/types";
import { cn } from "@/lib/utils";

// ─── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: ConversationMessage & { author_username?: string } }) {
  const role = msg.role;
  const isCustomer = role === "user";
  const isAgent = role === "human_agent";
  const isAssistant = role === "assistant";

  const bubbleClass = isCustomer
    ? "bg-primary text-primary-foreground self-end"
    : isAgent
    ? "bg-blue-100 text-blue-900 border border-blue-200 self-end"
    : "bg-muted text-foreground self-start";

  const alignClass = isCustomer || isAgent ? "items-end" : "items-start";

  const roleLabel = isAgent
    ? msg.author_username
      ? `Estilista · ${msg.author_username}`
      : "Estilista"
    : isAssistant
    ? "Bot"
    : null;

  return (
    <div className={cn("flex flex-col gap-0.5 max-w-[80%]", alignClass, isCustomer || isAgent ? "self-end" : "self-start")}>
      {roleLabel && (
        <span className="text-[10px] text-muted-foreground px-1">{roleLabel}</span>
      )}
      <div className={cn("rounded-xl px-3 py-2 text-sm", bubbleClass)}>
        <p className="whitespace-pre-wrap break-words">{msg.content}</p>
      </div>
      {msg.created_at && (
        <span
          className={cn(
            "text-[10px] text-muted-foreground px-1",
            isCustomer || isAgent ? "text-right" : "text-left"
          )}
        >
          {formatDate(msg.created_at)}
        </span>
      )}
    </div>
  );
}

// ─── Component ─────────────────────────────────────────────────────────────────

interface ConversationThreadProps {
  conversationId: string;
}

/**
 * Center column: conversation thread with role-based message styling,
 * PausedBanner, Composer, and BotToggle in the header.
 * Polls at 3s (focused) / 10s (blurred) cadence (FR-UI-1, FR-UI-6).
 */
export function ConversationThread({ conversationId }: ConversationThreadProps) {
  const [conversation, setConversation] = useState<ConversationHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  const inbox = conversation as unknown as ConversationHistoryInbox | null;
  const botEnabled =
    inbox?.atencion_automatica !== false && inbox?.paused_at == null;
  const pausedAt = inbox?.paused_at ?? null;

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  const fetchThread = useCallback(async () => {
    try {
      const data = await api.getConversation(conversationId);
      setConversation(data);
    } catch {
      // Graceful degradation — thread errors are shown as empty state
    } finally {
      setLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    setLoading(true);
    setConversation(null);
    fetchThread();
  }, [conversationId, fetchThread]);

  // Scroll to bottom when messages are loaded/updated.
  useEffect(() => {
    scrollToBottom();
  }, [conversation?.messages, scrollToBottom]);

  useConversationPolling({
    fetchFn: fetchThread,
    mode: "thread",
    enabled: true,
  });

  const handleBotToggled = (newBotEnabled: boolean) => {
    setConversation((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        atencion_automatica: newBotEnabled,
        paused_at: newBotEnabled ? null : new Date().toISOString(),
      } as unknown as ConversationHistory;
    });
  };

  const handleResumed = () => {
    handleBotToggled(true);
    fetchThread();
  };

  const handleMessageSent = () => {
    fetchThread();
  };

  const handleBotPaused = () => {
    handleBotToggled(false);
  };

  const messages: ConversationMessage[] = Array.isArray(conversation?.messages)
    ? (conversation!.messages as ConversationMessage[])
    : [];

  return (
    <div className="flex flex-col h-full">
      {/* Thread header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-line bg-sidebar flex-shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <MessageSquare className="h-4 w-4 text-muted-foreground flex-shrink-0" />
          <span className="text-sm font-medium truncate">
            {conversation?.customer_name ?? "Conversación"}
          </span>
        </div>
        {conversation && (
          <BotToggle
            conversationId={conversationId}
            botEnabled={botEnabled}
            onToggled={handleBotToggled}
          />
        )}
      </div>

      {/* Paused banner */}
      {!botEnabled && !loading && conversation && (
        <PausedBanner
          conversationId={conversationId}
          pausedAt={pausedAt}
          onResumed={handleResumed}
        />
      )}

      {/* Messages scroller */}
      {loading ? (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <ScrollArea className="flex-1">
          <div className="flex flex-col gap-3 p-4">
            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-32 text-sm text-muted-foreground gap-2">
                <MessageSquare className="h-6 w-6 opacity-30" />
                <span>No hay mensajes en esta conversación</span>
              </div>
            ) : (
              messages.map((msg, i) => (
                <MessageBubble
                  key={msg.id ?? i}
                  msg={msg as ConversationMessage & { author_username?: string }}
                />
              ))
            )}
            <div ref={bottomRef} />
          </div>
        </ScrollArea>
      )}

      {/* Composer (window + bot state required) */}
      {!loading && conversation && (
        <div className="flex-shrink-0">
          <WindowStatusComposer
            conversationId={conversationId}
            botEnabled={botEnabled}
            onMessageSent={handleMessageSent}
            onBotPaused={handleBotPaused}
          />
        </div>
      )}
    </div>
  );
}

// ─── Window-status-aware Composer wrapper ──────────────────────────────────────

/**
 * Fetches the 24h window status from the API and passes it to Composer.
 * Separated so the thread itself doesn't need to manage window-status polling.
 */
function WindowStatusComposer({
  conversationId,
  botEnabled,
  onMessageSent,
  onBotPaused,
}: {
  conversationId: string;
  botEnabled: boolean;
  onMessageSent: () => void;
  onBotPaused: () => void;
}) {
  const [windowOpen, setWindowOpen] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getWindowStatus(conversationId)
      .then((res) => {
        if (!cancelled) setWindowOpen(res.window_open);
      })
      .catch(() => {
        if (!cancelled) setWindowOpen(false); // conservative default
      });
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  if (windowOpen === null) {
    return (
      <div className="border-t p-3 flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Verificando ventana de mensajes…
      </div>
    );
  }

  return (
    <Composer
      conversationId={conversationId}
      windowOpen={windowOpen}
      botEnabled={botEnabled}
      onMessageSent={onMessageSent}
      onBotPaused={onBotPaused}
    />
  );
}
