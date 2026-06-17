"use client";

/**
 * /conversations — Unified 3-column inbox.
 *
 * Layout:
 *   Left  (w-72) — ConversationList: filter tabs + scrollable conversation list
 *   Center (flex-1) — ConversationThread: active thread with composer
 *   Right  (w-72) — CustomerCard: customer details + recent appointments
 *
 * URL state (query params, no router push):
 *   ?filter=all|bot_on|bot_off|escalated|unread — active filter tab
 *   ?conversation_id=<uuid>                     — selected conversation
 *
 * Replaces the old read-only conversations page. The /escalations route now
 * 308-redirects to /conversations?filter=escalated (FR-MIGRATE-1, SC-5).
 *
 * Access gated by conversations:read permission (FR-UI-1, NFR-1).
 */

import { useCallback, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { MessageSquare } from "lucide-react";

import { Header } from "@/components/layout/header";
import { ConversationList } from "@/components/inbox/ConversationList";
import { ConversationThread } from "@/components/inbox/ConversationThread";
import { CustomerCard } from "@/components/inbox/CustomerCard";
import { usePermission } from "@/hooks/use-permission";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import type { InboxFilter, ConversationHistory, ConversationHistoryInbox } from "@/lib/types";

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Returns true only when `id` is safe to pass directly to the thread-fetch API:
 * either a UUID (e.g. "a1b2c3d4-...") or a redis checkpoint key ("redis:...").
 * Bare Chatwoot numeric ids (e.g. "8") are NOT loadable — they need to be
 * resolved to a UUID by ConversationList first.
 */
function isLoadableConversationId(id: string | null): boolean {
  if (!id) return false;
  if (id.startsWith("redis:")) return true;
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);
}

// ─── Permission gate ───────────────────────────────────────────────────────────

function AccessDenied() {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-4 text-muted-foreground p-8">
      <MessageSquare className="h-12 w-12 opacity-20" />
      <div className="text-center">
        <p className="font-medium">Sin acceso</p>
        <p className="text-sm mt-1">
          No tienes permiso para ver conversaciones.
        </p>
      </div>
    </div>
  );
}

// ─── Empty thread pane ─────────────────────────────────────────────────────────

function EmptyThread() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-muted-foreground">
      <MessageSquare className="h-10 w-10 opacity-20" />
      <p className="text-sm">Selecciona una conversación para ver los mensajes</p>
    </div>
  );
}

// ─── Unavailable thread pane ───────────────────────────────────────────────────

function UnavailableThread() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-muted-foreground">
      <MessageSquare className="h-10 w-10 opacity-20" />
      <div className="text-center">
        <p className="text-sm font-medium">Esta conversación ya no está disponible</p>
        <p className="text-xs mt-1 max-w-xs">
          Puede haber expirado o ya fue resuelta. Puedes resolver la escalación desde el panel.
        </p>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ConversationsPage() {
  const canRead = usePermission("conversations:read");
  const searchParams = useSearchParams();
  const router = useRouter();

  // Derive state from URL params
  const filterParam = (searchParams.get("filter") ?? "all") as InboxFilter;
  const convIdParam = searchParams.get("conversation_id") ?? null;

  const [activeFilter, setActiveFilter] = useState<InboxFilter>(filterParam);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(convIdParam);
  const [activeCustomerId, setActiveCustomerId] = useState<string | null>(null);
  const [listRefreshKey, setListRefreshKey] = useState(0);
  const [conversationUnavailable, setConversationUnavailable] = useState(false);
  const [activeWhatsappContact, setActiveWhatsappContact] = useState<
    import("@/lib/types").WhatsappContact | null
  >(null);
  // Persisted collapse state for the left conversation list and right customer
  // card — matches the main nav rail UX. Both default to expanded; previous
  // session preferences are restored from localStorage.
  const [listCollapsed, setListCollapsed] = useState<boolean>(false);
  const [cardCollapsed, setCardCollapsed] = useState<boolean>(false);
  useEffect(() => {
    try {
      if (localStorage.getItem("inbox.listCollapsed") === "1") setListCollapsed(true);
      if (localStorage.getItem("inbox.cardCollapsed") === "1") setCardCollapsed(true);
    } catch {
      // localStorage may be unavailable (SSR, privacy mode) — silently ignore
    }
  }, []);
  const toggleListCollapsed = useCallback(() => {
    setListCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("inbox.listCollapsed", next ? "1" : "0");
      } catch {
        // ignore
      }
      return next;
    });
  }, []);
  const toggleCardCollapsed = useCallback(() => {
    setCardCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("inbox.cardCollapsed", next ? "1" : "0");
      } catch {
        // ignore
      }
      return next;
    });
  }, []);

  // Sync URL → state when browser back/forward or external link changes params
  useEffect(() => {
    setActiveFilter(filterParam);
    setActiveConversationId(convIdParam);
  }, [filterParam, convIdParam]);

  // Derived: the id is safe to pass to the API only once it's a UUID or redis: key.
  // When it's still a raw Chatwoot numeric id (e.g. "8"), ConversationList is
  // resolving it — we stay in the neutral "nothing selected" state to avoid a
  // GET /conversations/8 → 400 and the resulting error flash.
  const loadableConversationId = isLoadableConversationId(activeConversationId)
    ? activeConversationId
    : null;

  // Fetch customer_id + whatsapp_contact for the active conversation to
  // populate CustomerCard. whatsapp_contact is the fallback contact info
  // shown when no Customer row is linked yet.
  // Also clears the unavailable flag whenever a valid loadable id is present
  // (e.g. user clicks a different conversation after an orphan deep-link).
  useEffect(() => {
    if (!loadableConversationId) {
      setActiveCustomerId(null);
      setActiveWhatsappContact(null);
      return;
    }
    // A loadable id means the conversation resolved — clear any prior unavailable flag
    setConversationUnavailable(false);
    let cancelled = false;
    api
      .getConversation(loadableConversationId)
      .then((conv: ConversationHistory) => {
        if (cancelled) return;
        const inbox = conv as unknown as ConversationHistoryInbox;
        setActiveCustomerId(inbox.customer_id ?? null);
        setActiveWhatsappContact(conv.whatsapp_contact ?? null);
      })
      .catch(() => {
        if (cancelled) return;
        setActiveCustomerId(null);
        setActiveWhatsappContact(null);
      });
    return () => {
      cancelled = true;
    };
  }, [loadableConversationId]);

  // Push URL param changes (keeps navigation history for back button)
  const updateUrl = useCallback(
    (newFilter?: InboxFilter, newConvId?: string | null) => {
      const params = new URLSearchParams(searchParams.toString());
      if (newFilter !== undefined) params.set("filter", newFilter);
      if (newConvId !== undefined) {
        if (newConvId) params.set("conversation_id", newConvId);
        else params.delete("conversation_id");
      }
      router.push(`/conversations?${params.toString()}`);
    },
    [router, searchParams]
  );

  const handleFilterChange = (filter: InboxFilter) => {
    setActiveFilter(filter);
    updateUrl(filter, null);
  };

  const handleSelectConversation = useCallback(
    (id: string) => {
      setActiveConversationId(id);
      updateUrl(undefined, id);
    },
    [updateUrl]
  );

  const handleConversationDeleted = useCallback(
    (deletedId: string) => {
      // Clear selection if the deleted conversation was active
      if (activeConversationId === deletedId) {
        setActiveConversationId(null);
        setActiveCustomerId(null);
        setActiveWhatsappContact(null);
        updateUrl(undefined, null);
      }
      // The list will refetch on its own polling cycle, but trigger immediately
      // by bumping a refresh key (ConversationList re-mounts on key change).
      setListRefreshKey((k) => k + 1);
    },
    [activeConversationId, updateUrl]
  );

  if (!canRead) return <AccessDenied />;

  return (
    <div className="flex flex-col h-full">
      <Header
        title="Conversaciones"
        description="Bandeja de entrada — gestiona conversaciones con clientes"
      />

      {/* 3-column grid — fills remaining height */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Left — conversation list (collapsible icon rail) */}
        <div
          className={cn(
            "flex-shrink-0 overflow-hidden transition-[width] duration-150",
            listCollapsed ? "w-12" : "w-72"
          )}
        >
          <ConversationList
            key={listRefreshKey}
            activeFilter={activeFilter}
            activeConversationId={activeConversationId}
            onFilterChange={handleFilterChange}
            onSelectConversation={handleSelectConversation}
            collapsed={listCollapsed}
            onToggleCollapsed={toggleListCollapsed}
            onActiveConversationUnavailable={setConversationUnavailable}
          />
        </div>

        {/* Center — active thread */}
        <div className="flex-1 min-w-0 overflow-hidden border-r border-line">
          {loadableConversationId ? (
            <ConversationThread
              conversationId={loadableConversationId}
              onDeleted={handleConversationDeleted}
            />
          ) : activeConversationId && conversationUnavailable ? (
            <UnavailableThread />
          ) : (
            <EmptyThread />
          )}
        </div>

        {/* Right — customer card (collapsible icon rail) */}
        <div
          className={cn(
            "flex-shrink-0 overflow-hidden transition-[width] duration-150",
            cardCollapsed ? "w-12" : "w-72"
          )}
        >
          <CustomerCard
            customerId={activeCustomerId}
            conversationId={activeConversationId}
            whatsappContact={activeWhatsappContact}
            collapsed={cardCollapsed}
            onToggleCollapsed={toggleCardCollapsed}
          />
        </div>
      </div>
    </div>
  );
}
