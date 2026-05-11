"use client";

import { useCallback, useState } from "react";
import { MessageSquare, Bot, BotOff, AlertTriangle, Inbox, Mail } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConversationPolling } from "@/hooks/useConversationPolling";
import { formatDate } from "@/components/shared/format-utils";
import api from "@/lib/api";
import type { InboxFilter, ConversationHistoryInbox } from "@/lib/types";
import type { ConversationHistory } from "@/lib/types";

// ─── Filter tabs config ────────────────────────────────────────────────────────

interface FilterTab {
  id: InboxFilter;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const FILTER_TABS: FilterTab[] = [
  { id: "all",       label: "Todas",    icon: Inbox },
  { id: "bot_on",    label: "Bot ON",   icon: Bot },
  { id: "bot_off",   label: "Bot OFF",  icon: BotOff },
  { id: "escalated", label: "Escaladas", icon: AlertTriangle },
  { id: "unread",    label: "Sin leer", icon: Mail },
];

function matchesFilter(conv: ConversationHistory, filter: InboxFilter): boolean {
  const inbox = conv as unknown as ConversationHistoryInbox;
  switch (filter) {
    case "all": return true;
    case "bot_on":
      return inbox.atencion_automatica === true || inbox.atencion_automatica == null;
    case "bot_off":
      return inbox.atencion_automatica === false || inbox.paused_at != null;
    case "escalated":
      // Server-side filtering by status='triggered' — we do a best-effort
      // client-side check using paused_at as a proxy until backend adds filter param.
      return inbox.paused_at != null && inbox.atencion_automatica === false;
    case "unread":
      // Unread: conversations with ended_at = null (active but not yet handled)
      return !conv.ended_at;
    default:
      return true;
  }
}

// ─── Conversation list item ────────────────────────────────────────────────────

function ConvItem({
  conv,
  isActive,
  onClick,
}: {
  conv: ConversationHistory;
  isActive: boolean;
  onClick: () => void;
}) {
  const inbox = conv as unknown as ConversationHistoryInbox;
  const botPaused = inbox.paused_at != null || inbox.atencion_automatica === false;
  const name = conv.customer_name ?? "Cliente desconocido";

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full text-left px-3 py-3 rounded-lg transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold",
        isActive && "bg-gold-soft border border-gold/30"
      )}
    >
      <div className="flex items-start gap-2.5">
        <div className="flex-shrink-0 mt-0.5">
          {botPaused ? (
            <BotOff className="h-4 w-4 text-amber-500" />
          ) : (
            <MessageSquare className="h-4 w-4 text-green-600" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-1">
            <span className="text-sm font-medium truncate">{name}</span>
            {botPaused && (
              <Badge variant="outline" className="text-[10px] px-1 py-0 border-amber-400 text-amber-700 flex-shrink-0">
                Pausado
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5 truncate">
            {conv.message_count} mensajes
            {conv.started_at ? ` · ${formatDate(conv.started_at)}` : ""}
          </p>
          {conv.summary && (
            <p className="text-xs text-muted-foreground mt-0.5 truncate opacity-75">
              {conv.summary.slice(0, 60)}
            </p>
          )}
        </div>
      </div>
    </button>
  );
}

// ─── Component ─────────────────────────────────────────────────────────────────

interface ConversationListProps {
  activeFilter: InboxFilter;
  activeConversationId: string | null;
  onFilterChange: (filter: InboxFilter) => void;
  onSelectConversation: (id: string) => void;
}

/**
 * Left column of the inbox: filter tabs + scrollable conversation list.
 * Polls at 30-60s cadence (FR-UI-2, FR-UI-6).
 */
export function ConversationList({
  activeFilter,
  activeConversationId,
  onFilterChange,
  onSelectConversation,
}: ConversationListProps) {
  const [conversations, setConversations] = useState<ConversationHistory[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchList = useCallback(async () => {
    try {
      const res = await api.list<ConversationHistory>("conversations", { page_size: 100 });
      setConversations(res.items);
    } catch {
      // Silent — list is decorative-enough to degrade gracefully
    } finally {
      setLoading(false);
    }
  }, []);

  const unreadCount = conversations.filter((c) => !c.ended_at).length;

  useConversationPolling({
    fetchFn: fetchList,
    mode: "list",
    unreadCount,
    enabled: true,
  });

  const filtered = conversations.filter((c) => matchesFilter(c, activeFilter));

  return (
    <div className="flex flex-col h-full border-r border-line">
      {/* Filter tabs */}
      <div className="px-2 pt-3 pb-2 border-b border-line flex flex-wrap gap-1">
        {FILTER_TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeFilter === tab.id;
          return (
            <Button
              key={tab.id}
              variant={isActive ? "default" : "ghost"}
              size="sm"
              onClick={() => onFilterChange(tab.id)}
              className={cn(
                "h-7 px-2.5 text-[12px] gap-1",
                isActive ? "bg-gold text-white hover:bg-gold/90" : "text-ink-soft"
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {tab.label}
            </Button>
          );
        })}
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {loading ? (
          <div className="flex items-center justify-center h-20 text-sm text-muted-foreground">
            Cargando…
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-sm text-muted-foreground gap-2">
            <Inbox className="h-6 w-6 opacity-40" />
            <span>No hay conversaciones</span>
          </div>
        ) : (
          filtered.map((conv) => (
            <ConvItem
              key={conv.id}
              conv={conv}
              isActive={conv.id === activeConversationId}
              onClick={() => onSelectConversation(conv.id)}
            />
          ))
        )}
      </div>
    </div>
  );
}
