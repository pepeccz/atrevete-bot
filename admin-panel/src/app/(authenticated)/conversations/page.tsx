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

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { ChevronLeft, MessageSquare } from "lucide-react";

import { Header } from "@/components/layout/header";
import { ConversationList } from "@/components/inbox/ConversationList";
import { ConversationThread } from "@/components/inbox/ConversationThread";
import { CustomerCard } from "@/components/inbox/CustomerCard";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { usePermission } from "@/hooks/use-permission";
import { useSidebar } from "@/contexts/sidebar-context";
import { useCustomerCardData } from "@/hooks/use-customer-card-data";
import { useNotes } from "@/hooks/useNotes";
import { useMediaQuery } from "@/hooks/use-media-query";
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

/**
 * A bare Chatwoot numeric conversation id (e.g. "8"), as opposed to a UUID
 * or a "redis:" key. Since PR-1, `GET /conversations/{id}` accepts this
 * shape directly and resolves it to the underlying ConversationHistory row.
 */
function isBareNumericId(id: string | null): boolean {
  if (!id) return false;
  return /^[0-9]+$/.test(id);
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

// ─── Mobile back-to-list button ────────────────────────────────────────────────

/**
 * Shown only below `md` (mobile single-column push-nav) so a user stuck on a
 * pending/failed deep-link resolve (numeric id in flight or 404) can always
 * return to the list — ConversationThread's own back button only exists once
 * a thread actually mounts, which does not happen in these two states.
 */
function MobileBackButton({ onBack }: { onBack?: () => void }) {
  if (!onBack) return null;
  return (
    <Button
      variant="outline"
      size="sm"
      className="md:hidden gap-1.5"
      onClick={onBack}
    >
      <ChevronLeft className="h-4 w-4" />
      Volver a la lista
    </Button>
  );
}

// ─── Empty thread pane ─────────────────────────────────────────────────────────

function EmptyThread({ onBack }: { onBack?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-muted-foreground">
      <MessageSquare className="h-10 w-10 opacity-20" />
      <p className="text-sm">Selecciona una conversación para ver los mensajes</p>
      <MobileBackButton onBack={onBack} />
    </div>
  );
}

// ─── Unavailable thread pane ───────────────────────────────────────────────────

function UnavailableThread({ onBack }: { onBack?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-muted-foreground">
      <MessageSquare className="h-10 w-10 opacity-20" />
      <div className="text-center">
        <p className="text-sm font-medium">No se encontró esta conversación</p>
        <p className="text-xs mt-1 max-w-xs">
          Puede que ya no exista o que el enlace ya no sea válido.
        </p>
      </div>
      <MobileBackButton onBack={onBack} />
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
  // FR-DEEP-LINK: true only once a bare numeric deep-link id has been
  // confirmed NOT to resolve (404) via the one-shot backend GET below.
  // Distinct from `conversationUnavailable` (which ConversationList derives
  // from its own paginated array and would otherwise flash "unavailable"
  // while this resolve is still in flight).
  const [numericResolveFailed, setNumericResolveFailed] = useState(false);
  const [activeWhatsappContact, setActiveWhatsappContact] = useState<
    import("@/lib/types").WhatsappContact | null
  >(null);
  // Persisted collapse state for the left conversation list and right customer
  // card — matches the main nav rail UX. Both default to expanded; previous
  // session preferences are restored from localStorage.
  const [listCollapsed, setListCollapsed] = useState<boolean>(false);
  const [cardCollapsed, setCardCollapsed] = useState<boolean>(false);
  // PR-3 (ADR-4 responsive master-detail): the customer card renders inline
  // at >=xl and inside this Sheet drawer below xl (tablet/mobile).
  const [cardSheetOpen, setCardSheetOpen] = useState(false);
  // Ref to the mobile list pane — focus is restored here after "back to list"
  // so keyboard/screen-reader users land somewhere sensible post push-nav pop.
  const listContainerRef = useRef<HTMLDivElement>(null);
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

  // FR-DEEP-LINK (frontend fallback, PR-2): notification links carry a bare
  // Chatwoot numeric conversation_id (e.g. from a paused_24h reminder). That
  // conversation may not be on ConversationList's first fetched page, so its
  // own array-scan resolution (ConversationList.tsx) can miss it. As a
  // one-shot fallback, resolve the numeric id directly via the DB-backed
  // `GET /conversations/{id}` (PR-1) and swap the URL/state to the real UUID
  // so every downstream thread action (mark-read, pause/resume, delete)
  // operates on the canonical id — not just the initial render.
  useEffect(() => {
    if (!isBareNumericId(activeConversationId)) {
      setNumericResolveFailed(false);
      return;
    }
    let cancelled = false;
    setNumericResolveFailed(false);
    api
      .getConversation(activeConversationId as string)
      .then((conv: ConversationHistory) => {
        if (cancelled) return;
        setActiveConversationId(conv.id);
        updateUrl(undefined, conv.id);
      })
      .catch(() => {
        if (cancelled) return;
        setNumericResolveFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [activeConversationId, updateUrl]);

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
        setCardSheetOpen(false);
        updateUrl(undefined, null);
      }
      // The list will refetch on its own polling cycle, but trigger immediately
      // by bumping a refresh key (ConversationList re-mounts on key change).
      setListRefreshKey((k) => k + 1);
    },
    [activeConversationId, updateUrl]
  );

  // PR-3 (mobile single-column push-nav): pop back to the list, clearing the
  // active conversation/customer selection and restoring focus to the list pane.
  const handleBack = useCallback(() => {
    setActiveConversationId(null);
    setActiveCustomerId(null);
    setActiveWhatsappContact(null);
    setCardSheetOpen(false);
    updateUrl(undefined, null);
    requestAnimationFrame(() => listContainerRef.current?.focus());
  }, [updateUrl]);

  // PR-3 (ADR-4 CustomerCard container-presentational lift): a SINGLE fetch —
  // owned here — feeds both the inline (desktop) and Sheet-drawer
  // (tablet/mobile) CustomerCard instances via the same `cardProps` object,
  // eliminating the duplicate-fetch risk of two independently-fetching cards.
  const cardData = useCustomerCardData(activeCustomerId);
  const [notesOpen, setNotesOpen] = useState(false);
  const notesHook = useNotes(notesOpen ? activeConversationId : null);
  const toggleNotes = useCallback(() => setNotesOpen((o) => !o), []);

  // PR-3 (useMediaQuery gates BEHAVIOR only, never structural layout — the
  // Sheet's own responsive visibility is CSS/Tailwind on SheetContent).
  // Auto-close the drawer if the viewport grows into the desktop (xl) range
  // where the customer card is shown inline instead, so it can't linger open
  // as a redundant overlay after a resize.
  const isDesktopXl = useMediaQuery("(min-width: 1280px)");
  useEffect(() => {
    if (isDesktopXl && cardSheetOpen) setCardSheetOpen(false);
  }, [isDesktopXl, cardSheetOpen]);

  // PR-4 (acceptance follow-up, tests/e2e/runs/20260706_ui_audit/v2/acceptance_report.md
  // item 9c): at 768px the global nav sidebar's expanded w-64 width plus this
  // route's 2-column layout (list + thread, customer card in a Sheet drawer)
  // together overflow the viewport horizontally (scrollWidth 840 > clientWidth
  // 753); manually collapsing the sidebar to w-16 fixes it. Auto-collapse the
  // sidebar when THIS route is viewed at a narrow (<xl) width.
  //
  // Route-scoped, not global: only /conversations was found to overflow in the
  // audit — other routes keep the user's persisted sidebar preference
  // (`sidebar_collapsed` in localStorage) untouched rather than having it
  // silently overridden on every page load below xl.
  //
  // GATE-REVIEW CORRECTIVE FIX: the first version of this effect derived
  // `isBelowXl` from the `useMediaQuery` HOOK (`!isDesktopXl`). That hook
  // returns `false` on its very first render as an SSR-safe default — PR-3's
  // drawer-close effect above is safe consuming that as `isDesktopXl` because
  // it only acts on the TRUE polarity (a false first-render value is a safe
  // no-op: "don't close the drawer" IS the correct pre-hydration default).
  // This effect needs the OPPOSITE polarity ("is this narrow?"), so the same
  // false-default was wrongly read as "yes, narrow" on EVERY mount —
  // including at 1920px — collapsing the sidebar unconditionally and, via
  // sidebar-context.tsx's own persistence effect, permanently overwriting the
  // user's global `sidebar_collapsed` localStorage preference.
  //
  // Fix: read the REAL viewport directly via `window.matchMedia(...).matches`
  // (guarded for SSR) instead of trusting the hook's first-render value for
  // the below-xl direction — never inverted-polarity-trust the hook. A
  // `matchMedia` "change" listener keeps this correct for the lifetime of the
  // route (only the FIRST hook render lies; this effect doesn't depend on the
  // hook at all here, so there's no polarity trap to reason about).
  //
  // "Borrow, don't steal": when this effect collapses the sidebar, it records
  // (a) that IT did so and (b) the user's prior `isCollapsed` value in a ref.
  // On growing back to >=xl, or on unmount (navigating away), the prior value
  // is restored — UNLESS the user manually toggled the sidebar in the
  // meantime (detected by comparing the CURRENT `isCollapsed` against what we
  // set it to; if it no longer matches, the user intervened, so we leave it
  // alone and clear the ref instead of fighting them).
  const {
    isCollapsed: sidebarCollapsed,
    collapse: collapseSidebar,
    expand: expandSidebar,
  } = useSidebar();
  // Mirrors the latest `sidebarCollapsed` for the mount-only effect below
  // (which intentionally does NOT depend on `sidebarCollapsed` — see comment
  // on its dependency array) to read without re-subscribing the matchMedia
  // listener on every toggle.
  const sidebarCollapsedRef = useRef(sidebarCollapsed);
  useEffect(() => {
    sidebarCollapsedRef.current = sidebarCollapsed;
  }, [sidebarCollapsed]);
  const borrowedSidebarRef = useRef<{ priorCollapsed: boolean; weSetTo: boolean } | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const mql = window.matchMedia("(min-width: 1280px)");

    const restoreIfOwned = () => {
      const borrow = borrowedSidebarRef.current;
      if (!borrow) return;
      // Only restore if nothing else changed `isCollapsed` since we borrowed
      // it — otherwise the user (or something else) intervened; respect that.
      if (sidebarCollapsedRef.current === borrow.weSetTo) {
        if (borrow.priorCollapsed) collapseSidebar();
        else expandSidebar();
      }
      borrowedSidebarRef.current = null;
    };

    const applyForViewport = (isDesktopViewport: boolean) => {
      if (!isDesktopViewport) {
        // Genuinely narrow (real matchMedia read, not the hook's SSR default).
        if (!borrowedSidebarRef.current) {
          borrowedSidebarRef.current = {
            priorCollapsed: sidebarCollapsedRef.current,
            weSetTo: true,
          };
          collapseSidebar();
        }
      } else {
        restoreIfOwned();
      }
    };

    // Initial check — real viewport, never the useMediaQuery hook's
    // SSR-safe-but-misleading first-render value.
    applyForViewport(mql.matches);

    const handleChange = (e: MediaQueryListEvent) => applyForViewport(e.matches);
    mql.addEventListener("change", handleChange);

    return () => {
      mql.removeEventListener("change", handleChange);
      // Navigating away while still narrow (borrowed): give the sidebar back.
      restoreIfOwned();
    };
    // Deliberately NOT depending on `sidebarCollapsed` — that would tear down
    // and rebuild the matchMedia listener on every toggle. `collapseSidebar`/
    // `expandSidebar` are stable (useCallback([]) in sidebar-context.tsx), so
    // this effect only runs once on mount / cleans up once on unmount, and
    // `sidebarCollapsedRef` above always has the latest value for the
    // comparisons that need it.
  }, [collapseSidebar, expandSidebar]);

  const cardProps = {
    customerId: activeCustomerId,
    conversationId: activeConversationId,
    whatsappContact: activeWhatsappContact,
    customer: cardData.customer,
    appointments: cardData.appointments,
    loading: cardData.loading,
    fetchError: cardData.fetchError,
    onRetry: cardData.reload,
    notes: notesHook.notes,
    notesOpen,
    onToggleNotes: toggleNotes,
    addNote: notesHook.addNote,
    editNote: notesHook.editNote,
    removeNote: notesHook.removeNote,
  };

  if (!canRead) return <AccessDenied />;

  return (
    <div className="flex flex-col h-full">
      <Header
        title="Conversaciones"
        description="Bandeja de entrada — gestiona conversaciones con clientes"
      />

      {/*
        Responsive master-detail (ADR-4, CSS-first, selection-state driven —
        NOT route-based, so the URL-SSOT + polling stay on a single page):
          - <md (mobile):    single column; list OR thread pushes on selection
          - md..<xl (tablet): list + thread; customer card is a Sheet drawer
          - >=xl (desktop):   list + thread + customer card, all inline
        ConversationList stays MOUNTED at every breakpoint (only CSS-hidden)
        so polling and its own scroll position survive the mobile push/pop.
      */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Left — conversation list (full-width push on mobile; collapsible icon rail on md+) */}
        <div
          ref={listContainerRef}
          tabIndex={-1}
          className={cn(
            "flex-shrink-0 overflow-hidden transition-[width] duration-150 focus:outline-none",
            activeConversationId ? "hidden md:flex" : "flex w-full",
            listCollapsed ? "md:w-12" : "md:w-72"
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

        {/* Center — active thread (full-width push on mobile once selected) */}
        <div
          className={cn(
            "min-w-0 overflow-hidden border-r border-line",
            activeConversationId ? "flex w-full md:flex-1" : "hidden md:flex md:flex-1"
          )}
        >
          {loadableConversationId ? (
            <ConversationThread
              conversationId={loadableConversationId}
              onDeleted={handleConversationDeleted}
              onBack={handleBack}
              onOpenCustomer={() => setCardSheetOpen(true)}
            />
          ) : activeConversationId && isBareNumericId(activeConversationId) && !numericResolveFailed ? (
            // Numeric deep-link id: the one-shot resolver above is in flight
            // (or ConversationList's array-scan may still resolve it first).
            // Stay neutral here — no "unavailable" flash — until it fails.
            <EmptyThread onBack={handleBack} />
          ) : activeConversationId && (conversationUnavailable || numericResolveFailed) ? (
            <UnavailableThread onBack={handleBack} />
          ) : (
            <EmptyThread />
          )}
        </div>

        {/* Right — customer card: inline icon rail at >=xl */}
        <div
          className={cn(
            "hidden xl:flex flex-shrink-0 overflow-hidden transition-[width] duration-150",
            cardCollapsed ? "xl:w-12" : "xl:w-72"
          )}
        >
          <CustomerCard
            {...cardProps}
            collapsed={cardCollapsed}
            onToggleCollapsed={toggleCardCollapsed}
          />
        </div>

        {/* Right — customer card: Sheet drawer below xl (tablet/mobile),
            opened via the thread header's "Ver cliente" info button. */}
        <Sheet open={cardSheetOpen} onOpenChange={setCardSheetOpen}>
          <SheetContent side="right" className="w-full sm:max-w-sm p-0 xl:hidden">
            <SheetTitle className="sr-only">Ficha del cliente</SheetTitle>
            <CustomerCard {...cardProps} />
          </SheetContent>
        </Sheet>
      </div>
    </div>
  );
}
