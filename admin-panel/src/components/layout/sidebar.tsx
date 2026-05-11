"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import api from "@/lib/api";
import type { ConversationHistory } from "@/lib/types";
import {
  Calendar,
  Users,
  Scissors,
  Clock,
  LayoutDashboard,
  Settings,
  LogOut,
  MessageSquare,
  UserCog,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  MessageCircle,
  Shield,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Sheet,
  SheetContent,
  SheetTitle,
} from "@/components/ui/sheet";
import { useAuth } from "@/contexts/auth-context";
import { useSidebar } from "@/contexts/sidebar-context";
import { usePermission } from "@/hooks/use-permission";

// ── Types ─────────────────────────────────────────────────────────────────────

interface NavItem {
  title: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: number;
}

interface ExternalLinkItem {
  title: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
}

// ── Nav data ──────────────────────────────────────────────────────────────────

const principalNav: NavItem[] = [
  { title: "Dashboard",  href: "/dashboard",    icon: LayoutDashboard },
  { title: "Calendario", href: "/calendar",     icon: Calendar },
  { title: "Citas",      href: "/appointments", icon: Clock },
];

const gestionNav: NavItem[] = [
  { title: "Clientes",   href: "/customers",   icon: Users },
  { title: "Estilistas", href: "/stylists",    icon: UserCog },
  { title: "Servicios",  href: "/services",    icon: Scissors },
];

/**
 * Base config nav without badges — badges are applied dynamically in SidebarContent.
 * "Escalaciones" entry removed: FR-MIGRATE-2. Traffic now flows to
 * /conversations?filter=escalated via the 308 redirect.
 */
const baseConfigNav: NavItem[] = [
  { title: "Configuración del Salón", href: "/settings",      icon: Settings },
  { title: "Conversaciones",          href: "/conversations", icon: MessageSquare },
];

interface BadgeCounts {
  /** Sum of active (unended) conversations + triggered escalations. FR-MIGRATE-2. */
  conversations: number;
}

/**
 * Polls for live counts that drive the sidebar badges. Refreshes on mount,
 * on route change, and every 60s.
 *
 * Conversations badge = active (no ended_at) conversations + escalations with
 * status='triggered'. These are merged into a single badge because the
 * "Escalaciones" nav entry has been removed in favour of the
 * /conversations?filter=escalated tab (FR-MIGRATE-2).
 */
function useSidebarBadgeCounts(pathname: string): BadgeCounts {
  const [counts, setCounts] = useState<BadgeCounts>({ conversations: 0 });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [convRes, escStats] = await Promise.all([
          api.list<ConversationHistory>("conversations", { page_size: 100 }).catch(() => null),
          api.getEscalationStats().catch(() => null),
        ]);
        if (cancelled) return;
        const activeConversations = convRes?.items?.filter((c) => !c.ended_at).length ?? 0;
        const triggeredEscalations = escStats?.pending ?? 0;
        // Merge both counts into the single Conversaciones badge.
        setCounts({ conversations: activeConversations + triggeredEscalations });
      } catch {
        // Silent failure — sidebar badges are decorative, not load-bearing.
      }
    }
    load();
    const id = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [pathname]);

  return counts;
}

const externalLinks: ExternalLinkItem[] = [
  {
    title: "Chatwoot",
    href: process.env.NEXT_PUBLIC_CHATWOOT_URL || "http://localhost:3000",
    icon: MessageCircle,
  },
];

// ── Logo SVG (pyramid logotype — ported from design handoff shared.jsx) ───────

function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden>
      <path d="M16 4 L28 26 L4 26 Z" fill="#b8924b" />
      <path d="M16 4 L16 26" stroke="#fff" strokeWidth="1.2" opacity="0.55" />
      <path d="M16 4 L21 26" stroke="#fff" strokeWidth="0.8" opacity="0.35" />
      <path d="M16 4 L11 26" stroke="#fff" strokeWidth="0.8" opacity="0.35" />
    </svg>
  );
}

// ── Nav section ───────────────────────────────────────────────────────────────

function NavSection({
  title,
  items,
  isCollapsed,
  onNavClick,
}: {
  title: string;
  items: NavItem[];
  isCollapsed: boolean;
  onNavClick?: () => void;
}) {
  const pathname = usePathname();

  return (
    <div className={cn("py-1", isCollapsed ? "px-2" : "px-3")}>
      {!isCollapsed && (
        <p className="mb-1 px-3 text-[10.5px] font-bold tracking-[0.14em] text-ink-mute uppercase select-none">
          {title}
        </p>
      )}
      <div className="space-y-0.5">
        {items.map((item) => {
          const Icon = item.icon;
          // /conversations is also "active" when on /escalations (which now 308-redirects
          // there) to keep the sidebar highlight consistent after navigation.
          const isActive =
            pathname === item.href ||
            (item.href === "/conversations" && pathname === "/escalations");

          const inner = (
            <Link href={item.href} onClick={onNavClick} className="block">
              <span
                className={cn(
                  "relative flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-[14px] font-medium transition-colors",
                  isActive
                    ? "bg-gold-soft text-gold-dark font-semibold"
                    : "text-ink-soft hover:bg-gold-soft/50 hover:text-ink"
                )}
              >
                {/* 3px left gold bar for active items */}
                {isActive && (
                  <span
                    className="absolute left-0 top-[6px] bottom-[6px] w-[3px] rounded-full bg-gold"
                    aria-hidden
                  />
                )}
                <Icon className="h-[17px] w-[17px] flex-shrink-0" />
                {!isCollapsed && (
                  <>
                    <span className="flex-1 truncate">{item.title}</span>
                    {item.badge != null && item.badge > 0 && (
                      <span
                        className={cn(
                          "text-[11px] font-bold px-1.5 py-0.5 rounded-pill",
                          isActive
                            ? "bg-white text-gold-dark"
                            : "bg-gold-soft text-gold-dark"
                        )}
                      >
                        {item.badge}
                      </span>
                    )}
                  </>
                )}
              </span>
            </Link>
          );

          if (isCollapsed) {
            return (
              <Tooltip key={item.href}>
                <TooltipTrigger asChild>{inner}</TooltipTrigger>
                <TooltipContent side="right">{item.title}</TooltipContent>
              </Tooltip>
            );
          }

          return <div key={item.href}>{inner}</div>;
        })}
      </div>
    </div>
  );
}

// ── External links section ────────────────────────────────────────────────────

function ExternalLinksSection({
  title,
  items,
  isCollapsed,
}: {
  title: string;
  items: ExternalLinkItem[];
  isCollapsed: boolean;
}) {
  return (
    <div className={cn("py-1", isCollapsed ? "px-2" : "px-3")}>
      {!isCollapsed && (
        <p className="mb-1 px-3 text-[10.5px] font-bold tracking-[0.14em] text-ink-mute uppercase select-none">
          {title}
        </p>
      )}
      <div className="space-y-0.5">
        {items.map((item) => {
          const Icon = item.icon;

          const inner = (
            <a
              href={item.href}
              target="_blank"
              rel="noopener noreferrer"
              className="block"
            >
              <span className="flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-[14px] font-medium text-ink-soft hover:bg-gold-soft/50 hover:text-ink transition-colors">
                <Icon className="h-[17px] w-[17px] flex-shrink-0" />
                {!isCollapsed && (
                  <>
                    <span className="flex-1 truncate">{item.title}</span>
                    <ExternalLink className="h-3 w-3 text-ink-faint" />
                  </>
                )}
              </span>
            </a>
          );

          if (isCollapsed) {
            return (
              <Tooltip key={item.href}>
                <TooltipTrigger asChild>{inner}</TooltipTrigger>
                <TooltipContent side="right">
                  {item.title} (abre en nueva pestaña)
                </TooltipContent>
              </Tooltip>
            );
          }

          return <div key={item.href}>{inner}</div>;
        })}
      </div>
    </div>
  );
}

// ── Sidebar inner content ─────────────────────────────────────────────────────

function SidebarContent({
  isCollapsed,
  onNavClick,
}: {
  isCollapsed: boolean;
  onNavClick?: () => void;
}) {
  const { logout, user } = useAuth();
  const { toggle } = useSidebar();
  const pathname = usePathname();
  const badgeCounts = useSidebarBadgeCounts(pathname);
  const canAccessSettings = usePermission("system:settings");
  const canManageUsers = usePermission("users:manage");

  // "Configuración del Salón" is admin-only (system:settings).
  // "Conversaciones" is shared (conversations:read — both roles). The badge
  // includes active conversations + triggered escalations (FR-MIGRATE-2).
  const configNav: NavItem[] = [
    ...(canAccessSettings ? [baseConfigNav[0]] : []),
    { ...baseConfigNav[1], badge: badgeCounts.conversations },
  ];

  // "Usuarios" is admin-only (users:manage).
  const activeGestionNav: NavItem[] = [
    ...gestionNav,
    ...(canManageUsers ? [{ title: "Usuarios", href: "/users", icon: Shield }] : []),
  ];

  const displayName = user?.display_name || user?.username || "Admin";
  const initials = displayName.slice(0, 2).toUpperCase();
  const roleLabel = user?.role === "admin" ? "Admin" : user?.role === "stylist" ? "Estilista" : "";

  return (
    <div
      className={cn(
        "relative flex h-full flex-col border-r border-line bg-sidebar transition-all duration-300 ease-in-out",
        isCollapsed ? "w-16" : "w-64"
      )}
    >
      {/* Floating collapse/expand toggle — desktop only */}
      {!onNavClick && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="icon"
              onClick={toggle}
              className="absolute -right-3 top-20 z-50 h-6 w-6 rounded-full border border-line bg-background shadow-md hover:bg-gold-soft"
            >
              {isCollapsed ? (
                <ChevronRight className="h-3 w-3" />
              ) : (
                <ChevronLeft className="h-3 w-3" />
              )}
            </Button>
          </TooltipTrigger>
          <TooltipContent side="right">
            {isCollapsed ? "Expandir menú" : "Colapsar menú"}
          </TooltipContent>
        </Tooltip>
      )}

      {/* Brand header */}
      <div className="flex items-center gap-3 px-5 py-5 border-b border-line">
        <Link
          href="/dashboard"
          onClick={onNavClick}
          className={cn("flex items-center gap-3", isCollapsed && "justify-center")}
        >
          <Logo size={28} />
          {!isCollapsed && (
            <div className="flex flex-col leading-none">
              <span className="font-serif text-[20px] text-ink tracking-tight">
                Atrévete
              </span>
              <span className="text-[11px] text-ink-mute tracking-[0.12em] uppercase mt-0.5">
                Peluquería
              </span>
            </div>
          )}
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-3 space-y-4">
        <NavSection
          title="Principal"
          items={principalNav}
          isCollapsed={isCollapsed}
          onNavClick={onNavClick}
        />
        <NavSection
          title="Gestión"
          items={activeGestionNav}
          isCollapsed={isCollapsed}
          onNavClick={onNavClick}
        />
        <NavSection
          title="Configuración"
          items={configNav}
          isCollapsed={isCollapsed}
          onNavClick={onNavClick}
        />
        <ExternalLinksSection
          title="Herramientas"
          items={externalLinks}
          isCollapsed={isCollapsed}
        />
      </nav>

      {/* Footer: account row */}
      <div className="border-t border-line">
        {/* Account row */}
        <div className="p-2 pb-3">
          {isCollapsed ? (
            <div className="flex flex-col items-center gap-2">
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gold-soft text-gold-dark text-sm font-bold cursor-default">
                    {initials}
                  </div>
                </TooltipTrigger>
                <TooltipContent side="right">
                  {displayName}
                </TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={logout}
                    className="h-8 w-8 text-ink-mute hover:text-ink"
                  >
                    <LogOut className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="right">Cerrar sesión</TooltipContent>
              </Tooltip>
            </div>
          ) : (
            <div className="flex items-center gap-2.5 rounded-[10px] bg-white border border-line px-2.5 py-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gold-soft text-gold-dark text-[13px] font-bold flex-shrink-0">
                {initials}
              </div>
              <div className="flex-1 min-w-0 leading-tight">
                <p className="text-[13px] font-semibold text-ink truncate">
                  {displayName}
                </p>
                <p className="text-[11.5px] text-ink-mute mt-0.5">
                  {roleLabel}
                </p>
              </div>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={logout}
                    className="h-8 w-8 text-ink-mute hover:text-ink flex-shrink-0"
                  >
                    <LogOut className="h-[15px] w-[15px]" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="top">Cerrar sesión</TooltipContent>
              </Tooltip>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Public export ─────────────────────────────────────────────────────────────

export function Sidebar() {
  const { isCollapsed, isMobileOpen, closeMobile } = useSidebar();

  return (
    <TooltipProvider delayDuration={0}>
      {/* Desktop sidebar — hidden on mobile */}
      <div className="hidden md:block h-full">
        <SidebarContent isCollapsed={isCollapsed} />
      </div>

      {/* Mobile Sheet */}
      <Sheet open={isMobileOpen} onOpenChange={(open) => !open && closeMobile()}>
        <SheetContent side="left" className="p-0 w-64">
          <SheetTitle className="sr-only">Menú de navegación</SheetTitle>
          <TooltipProvider delayDuration={0}>
            <SidebarContent isCollapsed={false} onNavClick={closeMobile} />
          </TooltipProvider>
        </SheetContent>
      </Sheet>
    </TooltipProvider>
  );
}
