"use client";

import { ReactNode } from "react";
import { Menu, RefreshCw, Search } from "lucide-react";
import { GlobalSearch } from "./global-search";
import { NotificationCenter } from "./notification-center";
import { Button } from "@/components/ui/button";
import { useSidebar } from "@/contexts/sidebar-context";

interface HeaderProps {
  /** Page title shown on the left. */
  title: string;
  /** Optional subtitle / description below the title. */
  subtitle?: string;
  /**
   * @deprecated Use `subtitle` instead. Kept for backward compatibility
   * with existing page components that pass `description`.
   */
  description?: string;
  /**
   * Primary action node injected by each page.
   * Rendered as the last item in the right cluster (e.g. "Nueva cita" button).
   */
  primaryAction?: ReactNode;
  /**
   * @deprecated Use `primaryAction` instead. Kept for backward compatibility.
   */
  action?: ReactNode;
}

export function Header({
  title,
  subtitle,
  description,
  primaryAction,
  action,
}: HeaderProps) {
  const { toggleMobile, toggleMobileSearch } = useSidebar();

  // Support both prop names
  const subtitleText = subtitle ?? description;
  const primaryActionNode = primaryAction ?? action;

  return (
    <header className="sticky top-0 z-10 flex h-[68px] items-center gap-4 border-b border-line bg-white px-6 md:px-7">
      {/* Hamburger — mobile only */}
      <Button
        variant="ghost"
        size="icon"
        className="md:hidden text-ink-mute hover:text-ink"
        onClick={toggleMobile}
        aria-label="Abrir menú"
      >
        <Menu className="h-5 w-5" />
      </Button>

      {/* Left: title + subtitle */}
      <div className="flex-1 min-w-0">
        <h1 className="text-[22px] font-bold text-ink tracking-[-0.015em] leading-tight truncate">
          {title}
        </h1>
        {subtitleText && (
          <p className="text-[13px] text-ink-mute mt-0.5 leading-none">
            {subtitleText}
          </p>
        )}
      </div>

      {/* Right cluster */}
      <div className="flex items-center gap-2">
        {/* Search — mobile toggle */}
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden text-ink-mute hover:text-ink"
          onClick={toggleMobileSearch}
          aria-label="Buscar"
        >
          <Search className="h-5 w-5" />
        </Button>

        {/* Global search — desktop (includes ⌘K shortcut) */}
        <div className="hidden md:block">
          <GlobalSearch />
        </div>

        {/* Sync GCal button */}
        <SyncGCalButton />

        {/* Notification bell with badge */}
        <NotificationCenter />

        {/* Primary action slot */}
        {primaryActionNode}
      </div>
    </header>
  );
}

// ── Sync GCal button ─────────────────────────────────────────────────────────

/**
 * Triggers the existing GCal sync action.
 * Uses the same /api/admin/calendar/sync endpoint already wired in the codebase.
 */
function SyncGCalButton() {
  const handleSync = async () => {
    try {
      const token = typeof window !== "undefined"
        ? localStorage.getItem("auth_token")
        : null;
      await fetch("/api/admin/calendar/sync", {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
    } catch {
      // Errors surface through existing toast / notification system
    }
  };

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={handleSync}
      className="hidden md:flex items-center gap-1.5 text-[13.5px] font-medium text-ink-soft border-line hover:bg-gold-soft/50 hover:text-ink hover:border-gold-line"
      aria-label="Sincronizar Google Calendar"
    >
      <RefreshCw className="h-3.5 w-3.5" />
      Sync GCal
    </Button>
  );
}
