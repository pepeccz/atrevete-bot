import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

// ─── PageSkeleton ────────────────────────────────────────────────────────────
/** Skeleton completo para el área de contenido de una página */
export function PageSkeleton({ sections = 2 }: { sections?: number }) {
  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      {/* Simula una fila de KPI cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <StatCardSkeleton key={i} />
        ))}
      </div>
      {/* Secciones de contenido */}
      {Array.from({ length: sections }).map((_, i) => (
        <TableSkeleton key={i} />
      ))}
    </div>
  );
}

// ─── TableSkeleton ───────────────────────────────────────────────────────────
/** Skeleton que imita la forma de una tabla con filas */
export function TableSkeleton({
  rows = 5,
  columns = 5,
}: {
  rows?: number;
  columns?: number;
}) {
  return (
    <Card>
      <CardContent className="pt-6">
        {/* Barra de búsqueda simulada */}
        <div className="flex items-center py-4">
          <Skeleton className="h-9 w-64" />
        </div>
        {/* Tabla */}
        <div className="rounded-md border">
          {/* Cabecera */}
          <div className="flex items-center gap-4 border-b bg-muted/30 px-4 py-3">
            {Array.from({ length: columns }).map((_, i) => (
              <Skeleton key={i} className="h-4 flex-1" />
            ))}
          </div>
          {/* Filas */}
          {Array.from({ length: rows }).map((_, i) => (
            <div
              key={i}
              className="flex items-center gap-4 border-b px-4 py-3 last:border-0"
            >
              {Array.from({ length: columns }).map((_, j) => (
                <Skeleton
                  key={j}
                  className="h-4 flex-1"
                  style={{ opacity: 1 - j * 0.08 }}
                />
              ))}
            </div>
          ))}
        </div>
        {/* Paginación simulada */}
        <div className="flex items-center justify-between py-4">
          <Skeleton className="h-4 w-24" />
          <div className="flex gap-2">
            <Skeleton className="h-8 w-8" />
            <Skeleton className="h-8 w-8" />
            <Skeleton className="h-8 w-20" />
            <Skeleton className="h-8 w-8" />
            <Skeleton className="h-8 w-8" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ─── CardSkeleton ────────────────────────────────────────────────────────────
/** Skeleton con forma de Card genérica */
export function CardSkeleton() {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-4 w-4 rounded" />
      </CardHeader>
      <CardContent>
        <Skeleton className="h-8 w-20 mb-2" />
        <Skeleton className="h-3 w-32" />
      </CardContent>
    </Card>
  );
}

// ─── StatCardSkeleton ────────────────────────────────────────────────────────
/** Skeleton específico para tarjetas de estadísticas (KPI) del dashboard */
export function StatCardSkeleton() {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-4 w-4 rounded-sm" />
      </CardHeader>
      <CardContent>
        <Skeleton className="h-9 w-16 mb-1" />
        <Skeleton className="h-3 w-36" />
      </CardContent>
    </Card>
  );
}

// ─── ChartSkeleton ───────────────────────────────────────────────────────────
/** Skeleton para gráficas en el dashboard */
export function ChartSkeleton({ title }: { title: string }) {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-3 w-24 mt-1" />
      </CardHeader>
      <CardContent className="h-[300px] flex flex-col gap-3 justify-end pb-4">
        <div className="flex items-end gap-2 h-48">
          {Array.from({ length: 7 }).map((_, i) => (
            <Skeleton
              key={i}
              className="flex-1 rounded-t"
              style={{ height: `${30 + Math.random() * 70}%` }}
            />
          ))}
        </div>
        <Skeleton className="h-3 w-full" />
      </CardContent>
    </Card>
  );
}
