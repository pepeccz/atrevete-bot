"use client";

import { ReactNode } from "react";
import { GlobalSearch } from "./global-search";
import { NotificationCenter } from "./notification-center";

interface HeaderProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export function Header({ title, description, action }: HeaderProps) {
  return (
    <header className="sticky top-0 z-10 flex h-16 items-center gap-4 border-b bg-background px-6">
      <div className="flex-1">
        <h1 className="text-xl font-semibold">{title}</h1>
        {description && (
          <p className="text-sm text-muted-foreground">{description}</p>
        )}
      </div>

      <div className="flex items-center gap-4">
        {/* Page action button */}
        {action}

        {/* Global Search */}
        <GlobalSearch />

        {/* Notifications */}
        <NotificationCenter />
      </div>
    </header>
  );
}
