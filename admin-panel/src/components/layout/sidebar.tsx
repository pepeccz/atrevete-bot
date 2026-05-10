"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  AlertTriangle,
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
  Sun,
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

const configNav: NavItem[] = [
  { title: "Configuración del Salón", href: "/settings",      icon: Settings },
  { title: "Conversaciones",          href: "/conversations", icon: MessageSquare, badge: 4 },
  { title: "Escalaciones",            href: "/escalations",   icon: AlertTriangle, badge: 2 },
];

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
          const isActive = pathname === item.href;

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

// ── Theme toggle (light-only, Oscuro visually disabled) ───────────────────────

function ThemeToggleLightOnly({ isCollapsed }: { isCollapsed: boolean }) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 px-3 py-2 text-ink-mute text-[13px] font-medium",
        isCollapsed && "justify-center px-1"
      )}
    >
      <Sun className="h-4 w-4 flex-shrink-0" />
      {!isCollapsed && (
        <>
          <span className="flex-1">Modo claro</span>
          {/* Toggle pill — dark side visually disabled */}
          <Tooltip>
            <TooltipTrigger asChild>
              <span
                className="relative w-8 h-[18px] rounded-pill border border-line bg-line cursor-not-allowed"
                aria-label="Modo oscuro — próximamente"
                role="img"
              >
                {/* thumb locked to left (light side) */}
                <span className="absolute left-[2px] top-[2px] w-[13px] h-[13px] rounded-full bg-white shadow-sm" />
              </span>
            </TooltipTrigger>
            <TooltipContent side="right">Próximamente</TooltipContent>
          </Tooltip>
        </>
      )}
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

  const initials = user?.username
    ? user.username.slice(0, 2).toUpperCase()
    : "A";

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
          items={gestionNav}
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

      {/* Footer: theme toggle + account row */}
      <div className="border-t border-line">
        {/* Theme toggle */}
        <div className={cn("px-2 pt-2", isCollapsed && "px-1")}>
          <ThemeToggleLightOnly isCollapsed={isCollapsed} />
        </div>

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
                  {user?.username || "Admin"}
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
                  {user?.username || "Admin"}
                </p>
                <p className="text-[11.5px] text-ink-mute mt-0.5">
                  Administrador
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
