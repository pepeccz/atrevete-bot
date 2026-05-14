"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, MessageSquare, Paperclip, Download } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { PausedBanner } from "./PausedBanner";
import { Composer } from "./Composer";
import { BotToggle } from "./BotToggle";
import { AttachmentLightbox } from "./AttachmentLightbox";
import { formatDate } from "@/components/shared/format-utils";
import { useConversationPolling } from "@/hooks/useConversationPolling";
import { useLightbox } from "@/hooks/useLightbox";
import api from "@/lib/api";
import type { Attachment, ConversationHistory, ConversationMessage, ConversationHistoryInbox } from "@/lib/types";
import { cn } from "@/lib/utils";

// ─── Attachment helpers ────────────────────────────────────────────────────────

/** Format bytes as a human-readable string in KB or MB (Spanish units). */
function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Truncate a filename to at most `max` characters. */
function truncateFilename(name: string, max = 30): string {
  return name.length > max ? `${name.slice(0, max - 1)}…` : name;
}

interface AttachmentRenderProps {
  attachment: Attachment;
  /** Called when this image thumbnail is clicked. */
  onImageClick?: () => void;
}

/** Renders a single attachment inline inside a message bubble. */
function AttachmentRender({ attachment, onImageClick }: AttachmentRenderProps) {
  const { file_type, url, thumb_url, filename, size_bytes } = attachment;

  if (file_type === "image") {
    const src = thumb_url ?? url;
    const label = filename ? truncateFilename(filename) : null;
    return (
      <div className="flex flex-col gap-1 mt-1">
        <button
          type="button"
          onClick={onImageClick}
          className="focus:outline-none focus:ring-2 focus:ring-primary/50 rounded-lg"
          aria-label={label ?? "Ver imagen"}
        >
          <img
            src={src}
            alt={label ?? "Imagen"}
            className="rounded-lg object-cover cursor-pointer hover:opacity-90 transition-opacity"
            style={{ maxWidth: "240px", maxHeight: "200px" }}
            draggable={false}
          />
        </button>
        {label && (
          <span className="text-[10px] text-muted-foreground truncate max-w-[240px]">
            {label}
          </span>
        )}
      </div>
    );
  }

  if (file_type === "audio") {
    return (
      <div className="mt-1">
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <audio controls src={url} className="max-w-[240px] h-8" />
      </div>
    );
  }

  // Default: file / document chip.
  const chipLabel = filename ? truncateFilename(filename) : "Archivo";
  const sizeLabel = size_bytes != null ? formatSize(size_bytes) : null;

  return (
    <div className="mt-1 flex items-center gap-1.5 rounded-lg border border-border bg-background/70 px-2.5 py-1.5 text-xs">
      <Paperclip className="h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" />
      <span className="truncate max-w-[160px]" title={filename ?? undefined}>
        {chipLabel}
      </span>
      {sizeLabel && (
        <span className="text-muted-foreground flex-shrink-0">{sizeLabel}</span>
      )}
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        download={filename ?? true}
        className="ml-1 flex items-center gap-0.5 text-primary hover:underline flex-shrink-0"
        aria-label="Descargar archivo"
      >
        <Download className="h-3 w-3" />
        Descargar
      </a>
    </div>
  );
}

// ─── Message bubble ────────────────────────────────────────────────────────────

interface MessageBubbleProps {
  msg: ConversationMessage & { author_username?: string };
  /** Index into the conversation-wide image list for each image attachment. */
  imageIndexMap: Map<string, number>;
  onImageClick: (globalIdx: number) => void;
}

function MessageBubble({ msg, imageIndexMap, onImageClick }: MessageBubbleProps) {
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

  // PR-1: delivery failure indicator
  const failedDelivery = msg.delivery_failed === true;

  // PR-3b: sort attachments by position
  const attachments = (msg.attachments ?? []).slice().sort((a, b) => a.position - b.position);

  return (
    <div className={cn("flex flex-col gap-0.5 max-w-[80%]", alignClass, isCustomer || isAgent ? "self-end" : "self-start")}>
      {roleLabel && (
        <span className="text-[10px] text-muted-foreground px-1">{roleLabel}</span>
      )}
      <div className={cn("rounded-xl px-3 py-2 text-sm", bubbleClass)}>
        {msg.content && (
          <p className="whitespace-pre-wrap break-words">{msg.content}</p>
        )}
        {/* PR-3b: render attachments below the text content */}
        {attachments.map((att) => (
          <AttachmentRender
            key={att.id}
            attachment={att}
            onImageClick={
              att.file_type === "image"
                ? () => {
                    const idx = imageIndexMap.get(att.id);
                    if (idx !== undefined) onImageClick(idx);
                  }
                : undefined
            }
          />
        ))}
      </div>
      <div className={cn("flex items-center gap-1 px-1", isCustomer || isAgent ? "justify-end" : "justify-start")}>
        {msg.created_at && (
          <span className="text-[10px] text-muted-foreground">
            {formatDate(msg.created_at)}
          </span>
        )}
        {/* PR-1: red triangle + tooltip for undelivered messages */}
        {failedDelivery && (
          <span
            title="No entregado"
            className="text-[10px] text-red-500 cursor-default"
            aria-label="No entregado"
          >
            ▲
          </span>
        )}
      </div>
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
    // PR-1: mark all messages read when a conversation is selected (REQ-2, Scenario 2.4)
    api.markRead(conversationId).catch(() => {
      // Non-critical — silently ignore mark-read errors
    });
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

  // PR-3b: build a conversation-wide list of image attachments and a lookup map
  // (attachment.id → global index) so the lightbox can navigate across all images.
  const allImages: Attachment[] = [];
  const imageIndexMap = new Map<string, number>();
  for (const msg of messages) {
    for (const att of msg.attachments ?? []) {
      if (att.file_type === "image") {
        imageIndexMap.set(att.id, allImages.length);
        allImages.push(att);
      }
    }
  }

  const lightbox = useLightbox(allImages);

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
                  imageIndexMap={imageIndexMap}
                  onImageClick={lightbox.open}
                />
              ))
            )}
            <div ref={bottomRef} />
          </div>
        </ScrollArea>
      )}

      {/* PR-3b: image lightbox portal */}
      {lightbox.isOpen && allImages.length > 0 && (
        <AttachmentLightbox
          attachments={allImages}
          initialIndex={lightbox.currentIndex}
          currentIndex={lightbox.currentIndex}
          onClose={lightbox.close}
          onNext={lightbox.next}
          onPrev={lightbox.prev}
        />
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
