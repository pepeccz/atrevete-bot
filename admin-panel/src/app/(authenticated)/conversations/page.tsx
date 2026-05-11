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
import type { InboxFilter, ConversationHistory, ConversationHistoryInbox } from "@/lib/types";

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
  const [activeWhatsappContact, setActiveWhatsappContact] = useState<
    import("@/lib/types").WhatsappContact | null
  >(null);

  // Sync URL → state when browser back/forward or external link changes params
  useEffect(() => {
    setActiveFilter(filterParam);
    setActiveConversationId(convIdParam);
  }, [filterParam, convIdParam]);

  // Fetch customer_id + whatsapp_contact for the active conversation to
  // populate CustomerCard. whatsapp_contact is the fallback contact info
  // shown when no Customer row is linked yet.
  useEffect(() => {
    if (!activeConversationId) {
      setActiveCustomerId(null);
      setActiveWhatsappContact(null);
      return;
    }
    let cancelled = false;
    api
      .getConversation(activeConversationId)
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
  }, [activeConversationId]);

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

  const handleSelectConversation = (id: string) => {
    setActiveConversationId(id);
    updateUrl(undefined, id);
  };

  if (!canRead) return <AccessDenied />;

  return (
    <div className="flex flex-col h-full">
      <Header
        title="Conversaciones"
        description="Bandeja de entrada — gestiona conversaciones con clientes"
      />

      {/* 3-column grid — fills remaining height */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Left — conversation list */}
        <div className="w-72 flex-shrink-0 overflow-hidden">
          <ConversationList
            activeFilter={activeFilter}
            activeConversationId={activeConversationId}
            onFilterChange={handleFilterChange}
            onSelectConversation={handleSelectConversation}
          />
        </div>

        {/* Center — active thread */}
        <div className="flex-1 min-w-0 overflow-hidden border-r border-line">
          {activeConversationId ? (
            <ConversationThread conversationId={activeConversationId} />
          ) : (
            <EmptyThread />
          )}
        </div>

        {/* Right — customer card */}
        <div className="w-72 flex-shrink-0 overflow-hidden">
          <CustomerCard
            customerId={activeCustomerId}
            whatsappContact={activeWhatsappContact}
          />
        </div>
      </div>
    </div>
  );
}
