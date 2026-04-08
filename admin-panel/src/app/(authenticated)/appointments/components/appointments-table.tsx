"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { ColumnDef } from "@tanstack/react-table";
import { MoreHorizontal, Calendar, User, Scissors, Clock, Edit } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { DataTable, SortableHeader } from "@/components/ui/data-table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { formatDate } from "@/components/shared/format-utils";
import { StatusBadge } from "@/components/shared/status-badge";
import type { Appointment, AppointmentStatus } from "@/lib/types";

interface AppointmentsTableProps {
  appointments: Appointment[];
  stylistMap: Record<string, string>;
  serviceMap: Record<string, string>;
  isLoading: boolean;
  onDeleteRequest: (id: string) => void;
}

export function AppointmentsTable({
  appointments,
  stylistMap,
  serviceMap,
  isLoading,
  onDeleteRequest,
}: AppointmentsTableProps) {
  const router = useRouter();

  const columns: ColumnDef<Appointment>[] = useMemo(
    () => [
      {
        accessorKey: "start_time",
        header: ({ column }) => (
          <SortableHeader column={column}>
            <Calendar className="mr-2 h-4 w-4" />
            Fecha
          </SortableHeader>
        ),
        cell: ({ row }) => formatDate(row.getValue("start_time")),
      },
      {
        accessorKey: "first_name",
        header: () => (
          <div className="flex items-center">
            <User className="mr-2 h-4 w-4" />
            Cliente
          </div>
        ),
        cell: ({ row }) => {
          const appointment = row.original;
          return `${appointment.first_name} ${appointment.last_name || ""}`.trim();
        },
      },
      {
        accessorKey: "stylist_id",
        header: () => (
          <div className="flex items-center">
            <Scissors className="mr-2 h-4 w-4" />
            Estilista
          </div>
        ),
        cell: ({ row }) =>
          stylistMap[row.getValue("stylist_id") as string] || "-",
      },
      {
        accessorKey: "service_ids",
        header: "Servicios",
        cell: ({ row }) => {
          const serviceIds = row.getValue("service_ids") as string[];
          if (!serviceIds || serviceIds.length === 0) {
            return (
              <span className="text-muted-foreground">Sin servicios</span>
            );
          }

          const resolved = serviceIds.map((id) => serviceMap[id]);
          const validNames = resolved.filter(Boolean);
          const orphanCount = resolved.length - validNames.length;

          if (orphanCount > 0 && validNames.length === 0) {
            return (
              <Badge variant="destructive" className="text-xs">
                {orphanCount} servicio(s) no encontrado(s)
              </Badge>
            );
          }

          if (orphanCount > 0) {
            const names = validNames.join(", ");
            return (
              <div className="flex items-center gap-1">
                <span>
                  {names.length > 25 ? names.substring(0, 25) + "..." : names}
                </span>
                <Badge variant="destructive" className="text-xs">
                  +{orphanCount}
                </Badge>
              </div>
            );
          }

          const names = validNames.join(", ");
          return names.length > 40 ? names.substring(0, 40) + "..." : names;
        },
      },
      {
        accessorKey: "duration_minutes",
        header: () => (
          <div className="flex items-center">
            <Clock className="mr-2 h-4 w-4" />
            Duración
          </div>
        ),
        cell: ({ row }) => `${row.getValue("duration_minutes")} min`,
      },
      {
        accessorKey: "status",
        header: "Estado",
        cell: ({ row }) => (
          <StatusBadge status={row.getValue("status") as AppointmentStatus} />
        ),
      },
      {
        id: "actions",
        cell: ({ row }) => {
          const appointment = row.original;
          return (
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() =>
                  router.push(`/appointments/${appointment.id}`)
                }
              >
                <Edit className="h-4 w-4" />
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" className="h-8 w-8 p-0">
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    onClick={() => onDeleteRequest(appointment.id)}
                    className="text-destructive"
                  >
                    Eliminar
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          );
        },
      },
    ],
    [router, stylistMap, serviceMap, onDeleteRequest]
  );

  return (
    <DataTable
      columns={columns}
      data={appointments}
      isLoading={isLoading}
      searchKey="first_name"
      searchPlaceholder="Buscar por nombre..."
    />
  );
}
