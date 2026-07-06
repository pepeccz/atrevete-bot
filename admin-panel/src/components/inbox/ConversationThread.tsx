"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, Info, Loader2, MessageSquare, Paperclip, Download, MoreHorizontal } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { toast } from "sonner";
import { PausedBanner } from "./PausedBanner";
import { Composer } from "./Composer";
import { BotToggle } from "./BotToggle";
import { TakeoverModal } from "./TakeoverModal";
import { AttachmentLightbox } from "./AttachmentLightbox";
import { formatDate } from "@/components/shared/format-utils";
import { FetchError } from "@/components/shared/fetch-error";
import { useConversationPolling } from "@/hooks/useConversationPolling";
import { useLightbox } from "@/hooks/useLightbox";
import api from "@/lib/api";
import type { Attachment, ConversationHistory, ConversationMessage, ConversationHistoryInbox, InboxWindowStatusResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

// A-1: threshold (px) below which the user is considered "near bottom"
const NEAR_BOTTOM_THRESHOLD = 100;

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

  // Visual convention: customer messages on the LEFT (incoming from the
  // outside world), our side (bot + operator) on the RIGHT. The operator
  // gets the brand color (high visibility); the bot gets a softer blue.
  const onRight = isAgent || isAssistant;

  const bubbleClass = isCustomer
    ? "bg-muted text-foreground self-start"
    : isAgent
    ? "bg-primary text-primary-foreground self-end"
    : "bg-blue-100 text-blue-900 border border-blue-200 self-end";

  const alignClass = onRight ? "items-end" : "items-start";

  // R4: use "Equipo · {username}" for operator messages — avoids hardcoding
  // "Estilista" when the author might be admin or reception staff.
  const roleLabel = isAgent
    ? msg.author_username
      ? `Equipo · ${msg.author_username}`
      : "Equipo"
    : isAssistant
    ? "Bot"
    : null;

  // PR-1: delivery failure indicator
  const failedDelivery = msg.delivery_failed === true;

  // PR-3b: sort attachments by position
  const attachments = (msg.attachments ?? []).slice().sort((a, b) => a.position - b.position);

  return (
    <div className={cn("flex flex-col gap-0.5 max-w-[80%]", alignClass, onRight ? "self-end" : "self-start")}>
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
      <div className={cn("flex items-center gap-1 px-1", onRight ? "justify-end" : "justify-start")}>
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
  /** Called with the deleted conversation's ID after a successful delete. */
  onDeleted?: (conversationId: string) => void;
  /**
   * PR-3 (responsive master-detail): back-to-list handler, shown as a
   * chevron button visible only below the `md` breakpoint (mobile
   * single-column push-nav). Omit to hide the button entirely (desktop/tablet).
   */
  onBack?: () => void;
  /**
   * PR-3: opens the customer-card Sheet drawer, shown as an info button
   * visible only below the `xl` breakpoint (mobile + tablet, where the
   * customer card is not rendered inline). Omit to hide the button (desktop).
   */
  onOpenCustomer?: () => void;
}

/**
 * Center column: conversation thread with role-based message styling,
 * PausedBanner, Composer, and BotToggle in the header.
 * Polls at 3s (focused) / 10s (blurred) cadence (FR-UI-1, FR-UI-6).
 */
export function ConversationThread({
  conversationId,
  onDeleted,
  onBack,
  onOpenCustomer,
}: ConversationThreadProps) {
  const [conversation, setConversation] = useState<ConversationHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const hadErrorRef = useRef(false);

  // C1: container ref scopes the scroll-area viewport query to this component's subtree
  const containerRef = useRef<HTMLDivElement>(null);

  // A-1: refs for near-bottom-gated auto-scroll
  const scrollRootRef = useRef<HTMLElement | null>(null);
  const isNearBottomRef = useRef(true);
  const prevMsgCountRef = useRef(0);
  // W3: explicit first-load flag (replaces fragile prevMsgCountRef.current === 0 inference)
  const hasLoadedOnceRef = useRef(false);

  // A-2: single TakeoverModal lifted up from BotToggle + Composer
  const [takeover, setTakeover] = useState<{
    open: boolean;
    source: "toggle" | "send";
    pendingText?: string;
  } | null>(null);
  // Callback ref so Composer can receive the "confirmed" signal without re-renders
  const onTakeoverConfirmedForComposerRef = useRef<(() => void) | null>(null);

  const inbox = conversation as unknown as ConversationHistoryInbox | null;
  const botEnabled =
    inbox?.atencion_automatica !== false && inbox?.paused_at == null;
  const pausedAt = inbox?.paused_at ?? null;

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  const fetchThread = useCallback(async () => {
    setFetchError(false);
    try {
      const data = await api.getConversation(conversationId);
      hadErrorRef.current = false;
      setConversation(data);
    } catch (err) {
      console.error("[ConversationThread] fetchThread failed:", err);
      setFetchError(true);
      if (!hadErrorRef.current) {
        toast.error("No se pudo cargar el hilo de mensajes");
        hadErrorRef.current = true;
      }
    } finally {
      setLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    setLoading(true);
    setConversation(null);
    // A-1: reset scroll-tracking state on conversation change
    isNearBottomRef.current = true;
    prevMsgCountRef.current = 0;
    // W3: reset first-load flag so the new conversation scrolls to bottom on first fetch
    hasLoadedOnceRef.current = false;
    fetchThread();
    // PR-1: mark all messages read when a conversation is selected (REQ-2, Scenario 2.4)
    api.markRead(conversationId).catch(() => {
      // Non-critical — silently ignore mark-read errors
    });
  }, [conversationId, fetchThread]);

  // C1 / A-1: attach onScroll to the Radix ScrollArea viewport scoped to THIS
  // component's subtree (containerRef). Using document.querySelector would match
  // the first [data-radix-scroll-area-viewport] in the DOM — which may belong to
  // CustomerCard or another nested ScrollArea — causing a wrong-viewport bug.
  useEffect(() => {
    const root = containerRef.current;
    if (!root) return;
    const scrollArea = root.querySelector<HTMLElement>(
      "[data-radix-scroll-area-viewport]"
    );
    if (!scrollArea) return;
    scrollRootRef.current = scrollArea;

    const handleScroll = () => {
      const el = scrollRootRef.current;
      if (!el) return;
      isNearBottomRef.current =
        el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_THRESHOLD;
    };

    scrollArea.addEventListener("scroll", handleScroll, { passive: true });
    return () => scrollArea.removeEventListener("scroll", handleScroll);
  }, [loading]); // re-attach after loading (ScrollArea renders only after load)

  // W3 / A-1: near-bottom-gated auto-scroll. Uses an explicit hasLoadedOnceRef
  // instead of prevMsgCountRef.current === 0 so a transient empty-fetch that
  // resets count to 0 does not re-arm the unconditional first-load scroll.
  useEffect(() => {
    const msgCount = Array.isArray(conversation?.messages)
      ? conversation!.messages.length
      : 0;
    const isFirstLoad = !hasLoadedOnceRef.current;
    const hasNewMessages = msgCount > prevMsgCountRef.current;

    if (isFirstLoad || (hasNewMessages && isNearBottomRef.current)) {
      scrollToBottom();
    }
    if (isFirstLoad && msgCount > 0) {
      hasLoadedOnceRef.current = true;
    }
    prevMsgCountRef.current = msgCount;
  }, [conversation?.messages, scrollToBottom]);

  useConversationPolling({
    fetchFn: fetchThread,
    mode: "thread",
    enabled: true,
  });

  // W2: memoized so handleTakeoverConfirmed can safely reference it in its dep array
  const handleBotToggled = useCallback((newBotEnabled: boolean) => {
    setConversation((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        atencion_automatica: newBotEnabled,
        paused_at: newBotEnabled ? null : new Date().toISOString(),
      } as unknown as ConversationHistory;
    });
  }, []);

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

  // A-2 / W1: single pause entry-point called by BotToggle and Composer.
  // Guards re-entrancy (ignores new requests while modal is already open).
  // For source==='toggle', clears any pending send callback (a toggle pause must
  // never carry a lingering 'send' callback from a previous interaction).
  const handleRequestPause = useCallback(
    (source: "toggle" | "send", pendingText?: string) => {
      // W1: ignore if modal is already open (prevent double-pause race)
      if (takeover?.open) return;
      if (source === "toggle") {
        // W1: a toggle pause must never carry a stale send callback
        onTakeoverConfirmedForComposerRef.current = null;
      }
      setTakeover({ open: true, source, pendingText });
    },
    [takeover?.open]
  );

  // A-2 / W2: TakeoverModal confirmed — run pause path then signal Composer if needed.
  // handleBotToggled is stable (useCallback []) so including it in deps is safe.
  const handleTakeoverConfirmed = useCallback(() => {
    handleBotToggled(false);
    setTakeover(null);
    // For source==='send', signal Composer to proceed with the pending send
    if (onTakeoverConfirmedForComposerRef.current) {
      onTakeoverConfirmedForComposerRef.current();
      onTakeoverConfirmedForComposerRef.current = null;
    }
  }, [handleBotToggled]);

  const handleDeleteConfirm = async () => {
    setDeleting(true);
    try {
      await api.deleteConversation(conversationId);
      toast.success("Conversación eliminada correctamente");
      onDeleted?.(conversationId);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Error al eliminar la conversación";
      toast.error(message);
    } finally {
      setDeleting(false);
      setDeleteDialogOpen(false);
    }
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

  const customerName = conversation?.customer_name ?? "esta conversación";

  return (
    <div ref={containerRef} className="flex flex-col h-full">
      {/* Thread header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-line bg-sidebar flex-shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          {onBack && (
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 -ml-1.5 flex-shrink-0 md:hidden"
              onClick={onBack}
              aria-label="Volver a la lista de conversaciones"
              title="Volver"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
          )}
          <MessageSquare className="h-4 w-4 text-muted-foreground flex-shrink-0" />
          <span className="text-sm font-medium truncate">
            {conversation?.customer_name ?? "Conversación"}
          </span>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          {onOpenCustomer && (
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 xl:hidden"
              onClick={onOpenCustomer}
              aria-label="Ver cliente"
              title="Ver cliente"
            >
              <Info className="h-4 w-4" />
            </Button>
          )}
          {conversation && (
            <BotToggle
              conversationId={conversationId}
              botEnabled={botEnabled}
              onToggled={handleBotToggled}
              onRequestPause={handleRequestPause}
            />
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8">
                <MoreHorizontal className="h-4 w-4" />
                <span className="sr-only">Más opciones</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {/* "Abrir en Chatwoot" deferred — needs NEXT_PUBLIC_CHATWOOT_ACCOUNT_ID config + confirmed Chatwoot URL pattern. */}
              <DropdownMenuItem
                className="text-destructive focus:text-destructive focus:bg-destructive/10"
                onClick={() => setDeleteDialogOpen(true)}
              >
                Eliminar conversación
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Delete confirmation dialog */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar conversación</AlertDialogTitle>
            <AlertDialogDescription>
              ¿Eliminar conversación de {customerName}? Esta acción es irreversible y borra todos los mensajes asociados.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteConfirm}
              disabled={deleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleting ? "Eliminando…" : "Eliminar"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Paused banner — R3a: pass escalation reason/source for context */}
      {!botEnabled && !loading && conversation && (
        <PausedBanner
          conversationId={conversationId}
          pausedAt={pausedAt}
          escalationReason={inbox?.escalation_reason ?? null}
          escalationSource={inbox?.escalation_source ?? null}
          onResumed={handleResumed}
        />
      )}

      {/* Messages scroller */}
      {loading ? (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : fetchError && !conversation ? (
        <div className="flex-1 flex items-center justify-center">
          <FetchError onRetry={fetchThread} />
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
            onRequestPause={handleRequestPause}
            onTakeoverConfirmedRef={onTakeoverConfirmedForComposerRef}
          />
        </div>
      )}

      {/* A-2: single TakeoverModal instance — owned by ConversationThread */}
      <TakeoverModal
        open={takeover?.open ?? false}
        conversationId={conversationId}
        onConfirmed={handleTakeoverConfirmed}
        onCancelled={() => {
          // W1: clear the send callback on cancel so a cancelled 'send' takeover
          // cannot leak its callback into a later 'toggle' confirm.
          onTakeoverConfirmedForComposerRef.current = null;
          setTakeover(null);
        }}
      />
    </div>
  );
}

// ─── Window-status-aware Composer wrapper ──────────────────────────────────────

// ─── Window status label ───────────────────────────────────────────────────────

function WindowStatusLabel({ status }: { status: InboxWindowStatusResponse }) {
  if (!status.window_open) {
    return (
      <p className="text-xs text-muted-foreground px-3 pt-2 pb-0">
        Ventana cerrada — solo plantillas aprobadas pueden enviarse
      </p>
    );
  }
  const hours = status.hours_until_close;
  if (hours !== null && hours < 1) {
    return (
      <p className="text-xs text-amber-500 px-3 pt-2 pb-0">
        Ventana abierta · cierra en menos de 1h
      </p>
    );
  }
  const rounded = hours !== null ? Math.round(hours) : null;
  return (
    <p className="text-xs text-muted-foreground px-3 pt-2 pb-0">
      {rounded !== null ? `Ventana abierta · quedan ${rounded}h` : "Ventana abierta"}
    </p>
  );
}

/**
 * Fetches the 24h window status from the API and passes it to Composer.
 * Re-fetches on every poll tick (matching thread cadence: 3s focused / 10s blurred)
 * so the window-status row stays up to date without a manual page refresh.
 * Separated so the thread itself doesn't need to manage window-status polling.
 */
function WindowStatusComposer({
  conversationId,
  botEnabled,
  onMessageSent,
  onBotPaused,
  onRequestPause,
  onTakeoverConfirmedRef,
}: {
  conversationId: string;
  botEnabled: boolean;
  onMessageSent: () => void;
  onBotPaused: () => void;
  onRequestPause: (source: "toggle" | "send", pendingText?: string) => void;
  onTakeoverConfirmedRef: React.MutableRefObject<(() => void) | null>;
}) {
  const [windowStatus, setWindowStatus] = useState<InboxWindowStatusResponse | null>(null);
  const isFocusedRef = useRef<boolean>(
    typeof document !== "undefined" ? document.hasFocus() : true
  );

  const fetchWindowStatus = useCallback(async () => {
    try {
      const res = await api.getWindowStatus(conversationId);
      setWindowStatus(res);
    } catch {
      // Conservative default: treat window as closed to avoid accidental sends.
      setWindowStatus((prev) => prev ?? { window_open: false, last_user_message_at: null, hours_until_close: null });
    }
  }, [conversationId]);

  useEffect(() => {
    // Fetch immediately on mount / conversationId change.
    fetchWindowStatus();
  }, [fetchWindowStatus]);

  useEffect(() => {
    // Poll window status on the same cadence as the thread polling hook
    // (3s focused / 10s blurred). Uses an independent setInterval because
    // useConversationPolling does not expose a tick callback.
    const getInterval = () => (isFocusedRef.current ? 3_000 : 10_000);

    let timeoutId: ReturnType<typeof setTimeout> | null = null;

    const schedule = () => {
      timeoutId = setTimeout(async () => {
        if (typeof document !== "undefined" && document.hidden) {
          schedule();
          return;
        }
        await fetchWindowStatus();
        schedule();
      }, getInterval());
    };

    const handleFocus = () => { isFocusedRef.current = true; };
    const handleBlur = () => { isFocusedRef.current = false; };
    const handleVisibilityChange = () => {
      if (!document.hidden) {
        if (timeoutId !== null) { clearTimeout(timeoutId); timeoutId = null; }
        fetchWindowStatus().then(schedule);
      }
    };

    if (typeof window !== "undefined") {
      window.addEventListener("focus", handleFocus);
      window.addEventListener("blur", handleBlur);
      document.addEventListener("visibilitychange", handleVisibilityChange);
    }

    schedule();

    return () => {
      if (timeoutId !== null) clearTimeout(timeoutId);
      if (typeof window !== "undefined") {
        window.removeEventListener("focus", handleFocus);
        window.removeEventListener("blur", handleBlur);
        document.removeEventListener("visibilitychange", handleVisibilityChange);
      }
    };
  }, [fetchWindowStatus]);

  if (windowStatus === null) {
    return (
      <div className="border-t p-3 flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Verificando ventana de mensajes…
      </div>
    );
  }

  return (
    <div className="border-t border-border">
      <WindowStatusLabel status={windowStatus} />
      <Composer
        conversationId={conversationId}
        windowOpen={windowStatus.window_open}
        botEnabled={botEnabled}
        onMessageSent={onMessageSent}
        onBotPaused={onBotPaused}
        onRequestPause={onRequestPause}
        onTakeoverConfirmedRef={onTakeoverConfirmedRef}
      />
    </div>
  );
}
