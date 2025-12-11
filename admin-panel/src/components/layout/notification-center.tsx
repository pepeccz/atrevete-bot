"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Bell, Check, CheckCheck, Calendar, X } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { es } from "date-fns/locale";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import api from "@/lib/api";
import type { Notification, NotificationsListResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

const POLL_INTERVAL = 30000; // 30 seconds

const notificationIcons: Record<string, typeof Calendar> = {
  appointment_created: Calendar,
  appointment_cancelled: X,
  appointment_confirmed: Check,
  appointment_completed: CheckCheck,
};

const notificationColors: Record<string, string> = {
  appointment_created: "text-green-500",
  appointment_cancelled: "text-red-500",
  appointment_confirmed: "text-blue-500",
  appointment_completed: "text-gray-500",
};

function NotificationItem({
  notification,
  onRead,
  onClick,
}: {
  notification: Notification;
  onRead: (id: string) => void;
  onClick: (notification: Notification) => void;
}) {
  const Icon = notificationIcons[notification.type] || Bell;
  const colorClass = notificationColors[notification.type] || "text-gray-500";

  return (
    <button
      onClick={() => onClick(notification)}
      className={cn(
        "w-full flex items-start gap-3 p-3 rounded-md hover:bg-accent text-left transition-colors",
        !notification.is_read && "bg-accent/50"
      )}
    >
      <div className={cn("mt-0.5", colorClass)}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="flex-1 min-w-0">
        <p
          className={cn("text-sm", !notification.is_read && "font-semibold")}
        >
          {notification.title}
        </p>
        <p className="text-xs text-muted-foreground line-clamp-2">
          {notification.message}
        </p>
        <p className="text-xs text-muted-foreground mt-1">
          {formatDistanceToNow(new Date(notification.created_at), {
            addSuffix: true,
            locale: es,
          })}
        </p>
      </div>
      {!notification.is_read && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRead(notification.id);
          }}
          className="p-1 hover:bg-background rounded"
          title="Marcar como leida"
        >
          <Check className="h-3 w-3 text-muted-foreground" />
        </button>
      )}
    </button>
  );
}

export function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<NotificationsListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const fetchNotifications = useCallback(async () => {
    try {
      const response = await api.getNotifications(20, true);
      setData(response);
    } catch (error) {
      console.error("Failed to fetch notifications:", error);
    }
  }, []);

  // Initial fetch and polling
  useEffect(() => {
    fetchNotifications();

    const interval = setInterval(fetchNotifications, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [fetchNotifications]);

  // Refresh when popover opens
  useEffect(() => {
    if (open) {
      fetchNotifications();
    }
  }, [open, fetchNotifications]);

  const handleMarkRead = async (id: string) => {
    try {
      await api.markNotificationRead(id);
      setData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          items: prev.items.map((n) =>
            n.id === id ? { ...n, is_read: true } : n
          ),
          unread_count: Math.max(0, prev.unread_count - 1),
        };
      });
    } catch (error) {
      console.error("Failed to mark notification as read:", error);
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await api.markAllNotificationsRead();
      setData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          items: prev.items.map((n) => ({ ...n, is_read: true })),
          unread_count: 0,
        };
      });
    } catch (error) {
      console.error("Failed to mark all as read:", error);
    }
  };

  const handleClick = async (notification: Notification) => {
    if (!notification.is_read) {
      await handleMarkRead(notification.id);
    }

    // Navigate to entity
    if (notification.entity_type === "appointment" && notification.entity_id) {
      setOpen(false);
      router.push(`/appointments?highlight=${notification.entity_id}`);
    }
  };

  const unreadCount = data?.unread_count ?? 0;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" className="relative">
          <Bell className="h-5 w-5" />
          {unreadCount > 0 && (
            <span className="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-primary text-[10px] text-primary-foreground">
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="end">
        <div className="flex items-center justify-between px-4 py-3 border-b">
          <h4 className="font-semibold text-sm">Notificaciones</h4>
          {unreadCount > 0 && (
            <button
              onClick={handleMarkAllRead}
              className="text-xs text-primary hover:underline"
            >
              Marcar todas como leidas
            </button>
          )}
        </div>

        <ScrollArea className="max-h-96">
          {loading && !data && (
            <div className="p-4 text-center text-sm text-muted-foreground">
              Cargando...
            </div>
          )}

          {data && data.items.length === 0 && (
            <div className="p-8 text-center text-sm text-muted-foreground">
              <Bell className="h-8 w-8 mx-auto mb-2 opacity-50" />
              No hay notificaciones
            </div>
          )}

          {data && data.items.length > 0 && (
            <div className="p-2">
              {data.items.map((notification) => (
                <NotificationItem
                  key={notification.id}
                  notification={notification}
                  onRead={handleMarkRead}
                  onClick={handleClick}
                />
              ))}
            </div>
          )}
        </ScrollArea>
      </PopoverContent>
    </Popover>
  );
}
