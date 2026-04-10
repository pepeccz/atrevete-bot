"use client";

import Link from "next/link";
import Image from "next/image";
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
  Moon,
  Monitor,
  Receipt,
} from "lucide-react";
import { useTheme } from "next-themes";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
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

interface NavItem {
  title: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
}

interface ExternalLinkItem {
  title: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
}

const mainNav: NavItem[] = [
  {
    title: "Dashboard",
    href: "/dashboard",
    icon: LayoutDashboard,
  },
  {
    title: "Calendario",
    href: "/calendar",
    icon: Calendar,
  },
  {
    title: "Citas",
    href: "/appointments",
    icon: Clock,
  },
];

const managementNav: NavItem[] = [
  {
    title: "Clientes",
    href: "/customers",
    icon: Users,
  },
  {
    title: "Estilistas",
    href: "/stylists",
    icon: UserCog,
  },
  {
    title: "Servicios",
    href: "/services",
    icon: Scissors,
  },
];

const configNav: NavItem[] = [
  {
    title: "Configuración del Salón",
    href: "/settings",
    icon: Settings,
  },
  {
    title: "Facturación",
    href: "/settings/billing",
    icon: Receipt,
  },
  {
    title: "Conversaciones",
    href: "/conversations",
    icon: MessageSquare,
  },
  {
    title: "Escalaciones",
    href: "/escalations",
    icon: AlertTriangle,
  },
];

// External links section - opens in new tab
const externalLinks: ExternalLinkItem[] = [
  {
    title: "Chatwoot",
    href: process.env.NEXT_PUBLIC_CHATWOOT_URL || "http://localhost:3000",
    icon: MessageCircle,
  },
];

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
    <div className={cn("py-2", isCollapsed ? "px-2" : "px-3")}>
      {!isCollapsed && (
        <h2 className="mb-2 px-4 text-xs font-semibold tracking-tight text-muted-foreground uppercase">
          {title}
        </h2>
      )}
      <div className="space-y-1">
        {items.map((item) => {
          const Icon = item.icon;
          const isActive = pathname === item.href;

          return (
            <Tooltip key={item.href}>
              <TooltipTrigger asChild>
                <Link href={item.href} onClick={onNavClick}>
                  <Button
                    variant={isActive ? "secondary" : "ghost"}
                    className={cn(
                      "w-full",
                      isCollapsed ? "justify-center px-2" : "justify-start",
                      isActive &&
                        "bg-sidebar-accent text-sidebar-accent-foreground"
                    )}
                  >
                    <Icon
                      className={cn("h-4 w-4", !isCollapsed && "mr-2")}
                    />
                    {!isCollapsed && (
                      <span className="truncate">{item.title}</span>
                    )}
                  </Button>
                </Link>
              </TooltipTrigger>
              {isCollapsed && (
                <TooltipContent side="right">{item.title}</TooltipContent>
              )}
            </Tooltip>
          );
        })}
      </div>
    </div>
  );
}

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
    <div className={cn("py-2", isCollapsed ? "px-2" : "px-3")}>
      {!isCollapsed && (
        <h2 className="mb-2 px-4 text-xs font-semibold tracking-tight text-muted-foreground uppercase">
          {title}
        </h2>
      )}
      <div className="space-y-1">
        {items.map((item) => {
          const Icon = item.icon;

          return (
            <Tooltip key={item.href}>
              <TooltipTrigger asChild>
                <a
                  href={item.href}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Button
                    variant="ghost"
                    className={cn(
                      "w-full",
                      isCollapsed ? "justify-center px-2" : "justify-start"
                    )}
                  >
                    <Icon
                      className={cn("h-4 w-4", !isCollapsed && "mr-2")}
                    />
                    {!isCollapsed && (
                      <>
                        <span className="truncate flex-1">{item.title}</span>
                        <ExternalLink className="h-3 w-3 ml-1 text-muted-foreground" />
                      </>
                    )}
                  </Button>
                </a>
              </TooltipTrigger>
              {isCollapsed && (
                <TooltipContent side="right">
                  {item.title} (abre en nueva pestaña)
                </TooltipContent>
              )}
            </Tooltip>
          );
        })}
      </div>
    </div>
  );
}

/** Botón compacto de cambio de tema (claro / oscuro / sistema) */
function ThemeToggle({ isCollapsed }: { isCollapsed: boolean }) {
  const { theme, setTheme } = useTheme();

  const nextTheme = theme === "light" ? "dark" : theme === "dark" ? "system" : "light";
  const Icon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;
  const label =
    theme === "light" ? "Modo claro" : theme === "dark" ? "Modo oscuro" : "Según sistema";

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size={isCollapsed ? "icon" : "sm"}
          onClick={() => setTheme(nextTheme)}
          className={cn(
            "text-muted-foreground hover:text-foreground transition-colors",
            isCollapsed ? "h-8 w-8" : "w-full justify-start gap-2 px-2 h-8"
          )}
          aria-label={`Cambiar tema: ${label}`}
        >
          <Icon className="h-4 w-4 flex-shrink-0" />
          {!isCollapsed && <span className="text-xs">{label}</span>}
        </Button>
      </TooltipTrigger>
      {isCollapsed && (
        <TooltipContent side="right">{label}</TooltipContent>
      )}
    </Tooltip>
  );
}

/** Contenido de navegación reutilizado en sidebar de escritorio y Sheet móvil */
function SidebarContent({
  isCollapsed,
  onNavClick,
}: {
  isCollapsed: boolean;
  onNavClick?: () => void;
}) {
  const { logout, user } = useAuth();
  const { toggle } = useSidebar();

  return (
    <div
      className={cn(
        "relative flex h-full flex-col border-r bg-sidebar transition-all duration-300 ease-in-out",
        isCollapsed ? "w-16" : "w-64"
      )}
    >
      {/* Floating Toggle Button — solo en escritorio */}
      {!onNavClick && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="icon"
              onClick={toggle}
              className="absolute -right-3 top-20 z-50 h-6 w-6 rounded-full border bg-background shadow-md hover:bg-accent"
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

      {/* Logo/Brand */}
      <div className="flex h-16 items-center border-b px-3">
        <Link
          href="/dashboard"
          onClick={onNavClick}
          className={cn(
            "flex items-center gap-2 overflow-hidden",
            isCollapsed && "justify-center"
          )}
        >
          <Image
            src="/logo.png"
            alt="Atrévete Peluquería"
            width={32}
            height={32}
            className="flex-shrink-0 object-contain"
          />
          {!isCollapsed && (
            <span className="text-lg font-bold text-sidebar-foreground whitespace-nowrap">
              Atrévete Peluquería
            </span>
          )}
        </Link>
      </div>

      {/* Navigation */}
      <div className="flex-1 overflow-y-auto py-4">
        <NavSection title="Principal" items={mainNav} isCollapsed={isCollapsed} onNavClick={onNavClick} />
        <Separator className="my-2" />
        <NavSection title="Gestión" items={managementNav} isCollapsed={isCollapsed} onNavClick={onNavClick} />
        <Separator className="my-2" />
        <NavSection title="Configuración" items={configNav} isCollapsed={isCollapsed} onNavClick={onNavClick} />
        <Separator className="my-2" />
        <ExternalLinksSection title="Herramientas" items={externalLinks} isCollapsed={isCollapsed} />
      </div>

      {/* Tema */}
      <div className={cn("px-3 py-1 border-t pt-2", isCollapsed && "px-2")}>
        <ThemeToggle isCollapsed={isCollapsed} />
      </div>

      {/* Powered by Zanovix */}
      <div className={cn("px-3 py-2", isCollapsed && "px-2")}>
        <a
          href="https://zanovix.com"
          target="_blank"
          rel="noopener noreferrer"
          className={cn(
            "flex items-center text-xs text-muted-foreground hover:text-foreground transition-colors",
            isCollapsed ? "justify-center" : "justify-center"
          )}
        >
          {isCollapsed ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="font-medium">Z</span>
              </TooltipTrigger>
              <TooltipContent side="right">Powered by Zanovix</TooltipContent>
            </Tooltip>
          ) : (
            <span>
              Powered by <span className="font-medium hover:underline">Zanovix</span>
            </span>
          )}
        </a>
      </div>

      {/* User section */}
      <div className="border-t p-2">
        {isCollapsed ? (
          <div className="flex flex-col items-center gap-2">
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary text-primary-foreground text-sm font-medium cursor-default">
                  {user?.username?.charAt(0).toUpperCase() || "A"}
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
                  className="h-8 w-8 text-muted-foreground hover:text-foreground"
                >
                  <LogOut className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">Cerrar sesión</TooltipContent>
            </Tooltip>
          </div>
        ) : (
          <div className="flex items-center gap-3 rounded-lg bg-sidebar-accent p-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary text-primary-foreground text-sm font-medium flex-shrink-0">
              {user?.username?.charAt(0).toUpperCase() || "A"}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-sidebar-foreground truncate">
                {user?.username || "Admin"}
              </p>
              <p className="text-xs text-muted-foreground">Administrador</p>
            </div>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={logout}
                  className="h-8 w-8 text-muted-foreground hover:text-foreground flex-shrink-0"
                >
                  <LogOut className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top">Cerrar sesión</TooltipContent>
            </Tooltip>
          </div>
        )}
      </div>
    </div>
  );
}

export function Sidebar() {
  const { isCollapsed, isMobileOpen, closeMobile } = useSidebar();

  return (
    <TooltipProvider delayDuration={0}>
      {/* Sidebar de escritorio — oculto en móvil */}
      <div className="hidden md:block h-full">
        <SidebarContent isCollapsed={isCollapsed} />
      </div>

      {/* Sheet móvil — visible solo en móvil */}
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
