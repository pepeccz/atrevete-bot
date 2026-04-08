"use client";

import { ReactNode } from "react";
import { Menu, Search } from "lucide-react";
import { GlobalSearch } from "./global-search";
import { NotificationCenter } from "./notification-center";
import { Button } from "@/components/ui/button";
import { useSidebar } from "@/contexts/sidebar-context";

interface HeaderProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export function Header({ title, description, action }: HeaderProps) {
  const { toggleMobile, toggleMobileSearch } = useSidebar();

  return (
    <header className="sticky top-0 z-10 flex h-16 items-center gap-4 border-b bg-background px-4 md:px-6">
      {/* Botón hamburguesa — solo en móvil */}
      <Button
        variant="ghost"
        size="icon"
        className="md:hidden"
        onClick={toggleMobile}
        aria-label="Abrir menú"
      >
        <Menu className="h-5 w-5" />
      </Button>

      <div className="flex-1">
        <h1 className="text-xl font-semibold">{title}</h1>
        {description && (
          <p className="text-sm text-muted-foreground">{description}</p>
        )}
      </div>

      <div className="flex items-center gap-2 md:gap-4">
        {/* Page action button */}
        {action}

        {/* Botón de búsqueda — solo en móvil */}
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          onClick={toggleMobileSearch}
          aria-label="Buscar"
        >
          <Search className="h-5 w-5" />
        </Button>

        {/* Global Search — escritorio */}
        <GlobalSearch />

        {/* Notifications */}
        <NotificationCenter />
      </div>
    </header>
  );
}
