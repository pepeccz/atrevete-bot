"use client";

import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface FetchErrorProps {
  message?: string;
  onRetry: () => void;
}

/**
 * FetchError — shared error state for failed data fetches.
 * Renders a warning icon, a human-readable message, and a retry button.
 *
 * Usage:
 *   <FetchError onRetry={fetchList} />
 *   <FetchError message="No se pudo cargar el hilo." onRetry={fetchThread} />
 */
export function FetchError({
  message = "No se ha podido cargar. Inténtalo de nuevo.",
  onRetry,
}: FetchErrorProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-8 px-4 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-destructive/10 text-destructive">
        <AlertTriangle className="h-6 w-6" strokeWidth={1.5} />
      </div>
      <p className="text-sm text-muted-foreground max-w-xs leading-relaxed">{message}</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        Reintentar
      </Button>
    </div>
  );
}
