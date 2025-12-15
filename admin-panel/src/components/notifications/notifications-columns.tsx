"use client";

import { ColumnDef } from "@tanstack/react-table";
import {
  AlertTriangle,
  Bell,
  Calendar,
  Check,
  CheckCheck,
  Clock,
  HeartPulse,
  HelpCircle,
  MoreHorizontal,
  Send,
  Star,
  UserX,
  X,
  XCircle,
  Zap,
  Eye,
  EyeOff,
  Trash2,
  ExternalLink,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { es } from "date-fns/locale";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Notification, NotificationType } from "@/lib/types";
import { NOTIFICATION_TYPE_LABELS, NOTIFICATION_CATEGORIES } from "@/lib/types";
import { cn } from "@/lib/utils";

// Icons mapping
const notificationIcons: Record<string, typeof Calendar> = {
  appointment_created: Calendar,
  appointment_cancelled: X,
  appointment_confirmed: Check,
  appointment_completed: CheckCheck,
  confirmation_sent: Send,
  confirmation_received: CheckCheck,
  auto_cancelled: XCircle,
  confirmation_failed: XCircle,
  reminder_sent: Clock,
  escalation_manual: UserX,
  escalation_technical: Zap,
  escalation_auto: AlertTriangle,
  escalation_medical: HeartPulse,
  escalation_ambiguity: HelpCircle,
};

// Colors mapping
const notificationColors: Record<string, string> = {
  appointment_created: "text-green-500",
  appointment_cancelled: "text-red-500",
  appointment_confirmed: "text-blue-500",
  appointment_completed: "text-gray-500",
  confirmation_sent: "text-blue-400",
  confirmation_received: "text-green-500",
  auto_cancelled: "text-red-400",
  confirmation_failed: "text-red-500",
  reminder_sent: "text-amber-500",
  escalation_manual: "text-orange-500",
  escalation_technical: "text-red-600",
  escalation_auto: "text-red-500",
  escalation_medical: "text-purple-500",
  escalation_ambiguity: "text-yellow-500",
};

// Get category from notification type
function getCategory(type: NotificationType): string {
  for (const [category, types] of Object.entries(NOTIFICATION_CATEGORIES)) {
    if ((types as readonly string[]).includes(type)) {
      return category;
    }
  }
  return "otro";
}

// Category badge colors
const categoryBadgeColors: Record<string, string> = {
  citas: "bg-primary/10 text-primary hover:bg-primary/20",
  confirmaciones: "bg-blue-500/10 text-blue-500 hover:bg-blue-500/20",
  escalaciones: "bg-red-500/10 text-red-500 hover:bg-red-500/20",
};

interface NotificationColumnsProps {
  onToggleStar: (id: string) => void;
  onMarkRead: (id: string) => void;
  onMarkUnread: (id: string) => void;
  onDelete: (id: string) => void;
  onNavigateToEntity: (notification: Notification) => void;
}

export function getNotificationColumns({
  onToggleStar,
  onMarkRead,
  onMarkUnread,
  onDelete,
  onNavigateToEntity,
}: NotificationColumnsProps): ColumnDef<Notification>[] {
  return [
    {
      id: "select",
      header: ({ table }) => (
        <Checkbox
          checked={
            table.getIsAllPageRowsSelected() ||
            (table.getIsSomePageRowsSelected() && "indeterminate")
          }
          onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
          aria-label="Seleccionar todas"
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          checked={row.getIsSelected()}
          onCheckedChange={(value) => row.toggleSelected(!!value)}
          aria-label="Seleccionar fila"
        />
      ),
      enableSorting: false,
      enableHiding: false,
    },
    {
      accessorKey: "type",
      header: "Tipo",
      cell: ({ row }) => {
        const type = row.getValue("type") as NotificationType;
        const Icon = notificationIcons[type] || Bell;
        const colorClass = notificationColors[type] || "text-gray-500";
        const category = getCategory(type);

        return (
          <div className="flex items-center gap-2">
            <div className={cn("p-1.5 rounded", colorClass)}>
              <Icon className="h-4 w-4" />
            </div>
            <Badge
              variant="secondary"
              className={cn("text-xs", categoryBadgeColors[category])}
            >
              {NOTIFICATION_TYPE_LABELS[type] || type}
            </Badge>
          </div>
        );
      },
    },
    {
      accessorKey: "title",
      header: "Titulo",
      cell: ({ row }) => {
        const isRead = row.original.is_read;
        return (
          <span className={cn(!isRead && "font-semibold")}>
            {row.getValue("title")}
          </span>
        );
      },
    },
    {
      accessorKey: "message",
      header: "Mensaje",
      cell: ({ row }) => {
        const message = row.getValue("message") as string;
        return (
          <span className="text-muted-foreground line-clamp-1 max-w-[300px]">
            {message}
          </span>
        );
      },
    },
    {
      accessorKey: "created_at",
      header: "Fecha",
      cell: ({ row }) => {
        const date = row.getValue("created_at") as string;
        return (
          <span className="text-muted-foreground text-sm whitespace-nowrap">
            {formatDistanceToNow(new Date(date), {
              addSuffix: true,
              locale: es,
            })}
          </span>
        );
      },
    },
    {
      accessorKey: "is_read",
      header: "Estado",
      cell: ({ row }) => {
        const isRead = row.getValue("is_read") as boolean;
        return (
          <Badge variant={isRead ? "secondary" : "default"}>
            {isRead ? "Leida" : "No leida"}
          </Badge>
        );
      },
    },
    {
      accessorKey: "is_starred",
      header: () => <Star className="h-4 w-4" />,
      cell: ({ row }) => {
        const isStarred = row.getValue("is_starred") as boolean;
        return (
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => onToggleStar(row.original.id)}
          >
            <Star
              className={cn(
                "h-4 w-4",
                isStarred ? "fill-yellow-400 text-yellow-400" : "text-muted-foreground"
              )}
            />
          </Button>
        );
      },
    },
    {
      id: "actions",
      cell: ({ row }) => {
        const notification = row.original;

        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8">
                <MoreHorizontal className="h-4 w-4" />
                <span className="sr-only">Abrir menu</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {notification.entity_id && (
                <>
                  <DropdownMenuItem onClick={() => onNavigateToEntity(notification)}>
                    <ExternalLink className="mr-2 h-4 w-4" />
                    Ver entidad
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                </>
              )}
              {notification.is_read ? (
                <DropdownMenuItem onClick={() => onMarkUnread(notification.id)}>
                  <EyeOff className="mr-2 h-4 w-4" />
                  Marcar como no leida
                </DropdownMenuItem>
              ) : (
                <DropdownMenuItem onClick={() => onMarkRead(notification.id)}>
                  <Eye className="mr-2 h-4 w-4" />
                  Marcar como leida
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onClick={() => onToggleStar(notification.id)}>
                <Star className="mr-2 h-4 w-4" />
                {notification.is_starred ? "Quitar favorita" : "Marcar favorita"}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => onDelete(notification.id)}
                className="text-red-600"
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Eliminar
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        );
      },
    },
  ];
}
