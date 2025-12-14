"use client";

import { AlertTriangle } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export interface ConflictInfo {
  date: string;
  stylist_id: string;
  stylist_name: string;
  conflict_type: string;
  conflict_title: string;
  start_time: string;
  end_time: string;
}

interface ConflictWarningProps {
  conflicts: ConflictInfo[];
  maxShow?: number;
}

export function ConflictWarning({ conflicts, maxShow = 5 }: ConflictWarningProps) {
  if (conflicts.length === 0) return null;

  const displayConflicts = conflicts.slice(0, maxShow);
  const remaining = conflicts.length - maxShow;

  // Format date for display
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString("es-ES", {
      weekday: "short",
      day: "numeric",
      month: "short",
    });
  };

  // Get icon for conflict type
  const getConflictIcon = (type: string) => {
    if (type === "appointment") return "📅";
    if (type === "blocking_event") return "🚫";
    return "⚠️";
  };

  return (
    <Alert variant="destructive" className="border-amber-500 bg-amber-50 dark:bg-amber-950/30">
      <AlertTriangle className="h-4 w-4 text-amber-600" />
      <AlertTitle className="text-amber-800 dark:text-amber-200">
        Conflictos detectados ({conflicts.length})
      </AlertTitle>
      <AlertDescription className="text-amber-700 dark:text-amber-300">
        <p className="text-sm mb-2">
          Los siguientes eventos existentes se verán afectados:
        </p>
        <ul className="text-sm space-y-1 max-h-40 overflow-y-auto">
          {displayConflicts.map((c, i) => (
            <li key={i} className="flex items-start gap-2">
              <span>{getConflictIcon(c.conflict_type)}</span>
              <span>
                <strong>{formatDate(c.date)}</strong> - {c.stylist_name}:{" "}
                {c.conflict_title} ({c.start_time}-{c.end_time})
              </span>
            </li>
          ))}
        </ul>
        {remaining > 0 && (
          <p className="text-sm mt-1 italic">
            ... y {remaining} conflictos más.
          </p>
        )}
        <p className="text-sm mt-3 font-medium text-amber-800 dark:text-amber-200">
          El bloqueo tendrá prioridad sobre estos eventos existentes.
        </p>
      </AlertDescription>
    </Alert>
  );
}
