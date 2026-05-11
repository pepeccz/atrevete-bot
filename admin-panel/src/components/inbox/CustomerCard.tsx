"use client";

import { useEffect, useState } from "react";
import {
  User,
  Phone,
  Calendar,
  Loader2,
  ChevronRight,
  MessageCircle,
  PanelRightClose,
  PanelRightOpen,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { formatDate } from "@/components/shared/format-utils";
import api from "@/lib/api";
import type {
  CustomerDetail,
  CustomerAppointment,
  WhatsappContact,
} from "@/lib/types";
import Link from "next/link";

interface CustomerCardProps {
  /**
   * Customer UUID. If null, renders the WhatsApp-metadata fallback when
   * ``whatsappContact`` carries any info; otherwise an empty placeholder.
   */
  customerId: string | null;
  /**
   * Fallback contact info from the inbound webhook (Chatwoot sender). Shown
   * when ``customerId`` is null. Either field may be null for very old
   * conversations whose webhook ran before sender_phone was persisted.
   */
  whatsappContact?: WhatsappContact | null;
  /** True when the column is rendered in narrow icon-rail mode. */
  collapsed?: boolean;
  /** Toggle handler — flips collapsed state in the parent. */
  onToggleCollapsed?: () => void;
}

/**
 * Right column of the inbox layout: customer information card.
 * Shows contact details, last appointments, and agent notes.
 * Reuses the existing /customers/[id] data contract (api.getCustomerDetail).
 * Supports a collapsed icon-rail mode for more thread real-estate.
 * FR-UI-1.
 */
export function CustomerCard({
  customerId,
  whatsappContact,
  collapsed = false,
  onToggleCollapsed,
}: CustomerCardProps) {
  const [customer, setCustomer] = useState<CustomerDetail | null>(null);
  const [appointments, setAppointments] = useState<CustomerAppointment[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!customerId) {
      setCustomer(null);
      setAppointments([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    Promise.all([
      api.getCustomerDetail(customerId),
      api.getCustomerAppointments(customerId, 1, 5),
    ])
      .then(([cust, appts]) => {
        if (cancelled) return;
        setCustomer(cust);
        setAppointments(appts.items);
      })
      .catch(() => {
        // Graceful degradation — card is informational only
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [customerId]);

  const waName = whatsappContact?.name?.trim() || null;
  const waPhone = whatsappContact?.phone?.trim() || null;
  const fullName = customer
    ? [customer.first_name, customer.last_name].filter(Boolean).join(" ")
    : "";
  const displayInitials = (customer ? fullName : waName ?? "??")
    .slice(0, 2)
    .toUpperCase();

  // ─── Collapsed icon rail ────────────────────────────────────────────────
  if (collapsed) {
    return (
      <div className="flex flex-col h-full border-l border-gold/40 bg-gold-soft/20 items-center py-2 gap-1">
        {onToggleCollapsed && (
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={onToggleCollapsed}
            title="Expandir ficha del cliente"
          >
            <PanelRightOpen className="h-4 w-4" />
          </Button>
        )}
        {/* Customer initials chip */}
        {(customerId || waName || waPhone) && (
          <div
            title={customer ? fullName : waName ?? "Sin nombre"}
            className={
              customerId
                ? "h-8 w-8 mt-1 rounded-full flex items-center justify-center bg-gold-soft text-gold-dark text-[10px] font-bold"
                : "h-8 w-8 mt-1 rounded-full flex items-center justify-center bg-muted text-muted-foreground text-[10px] font-bold"
            }
          >
            {displayInitials || "??"}
          </div>
        )}
        {/* Phone hint icon (tooltip) */}
        {waPhone && !customer && (
          <div
            title={waPhone}
            className="h-8 w-8 rounded-md flex items-center justify-center text-muted-foreground"
          >
            <Phone className="h-3.5 w-3.5" />
          </div>
        )}
      </div>
    );
  }

  // ─── Expanded: empty placeholder ─────────────────────────────────────────
  if (!customerId) {
    const hasAnyWaInfo = Boolean(waName || waPhone);

    if (!hasAnyWaInfo) {
      return (
        <div className="flex flex-col h-full border-l border-gold/40 bg-gold-soft/10">
          <CardToggleHeader onToggleCollapsed={onToggleCollapsed} />
          <div className="flex flex-1 flex-col items-center justify-center text-sm text-muted-foreground gap-2 p-4">
            <User className="h-8 w-8 opacity-30" />
            <span>Cliente no identificado</span>
          </div>
        </div>
      );
    }

    return (
      <div className="flex flex-col h-full border-l border-gold/40 bg-gold-soft/10">
        <CardToggleHeader onToggleCollapsed={onToggleCollapsed} />
        <ScrollArea className="flex-1">
          <div className="p-4 space-y-5">
            {/* Header — unidentified, with WhatsApp metadata */}
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted text-muted-foreground font-bold text-sm flex-shrink-0">
                {(waName ?? "??").slice(0, 2).toUpperCase()}
              </div>
              <div className="min-w-0">
                <p className="font-semibold text-sm truncate">
                  {waName ?? "Sin nombre"}
                </p>
                <p className="text-xs text-muted-foreground truncate">
                  Sin identificar
                </p>
              </div>
            </div>

            <Separator />

            {/* Contact from WhatsApp */}
            <div className="space-y-2">
              <p className="text-[11px] font-bold tracking-widest text-muted-foreground uppercase">
                Contacto (WhatsApp)
              </p>
              {waPhone ? (
                <div className="flex items-center gap-2 text-sm">
                  <Phone className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
                  <span>{waPhone}</span>
                </div>
              ) : (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Phone className="h-3.5 w-3.5 flex-shrink-0" />
                  <span>Teléfono no disponible</span>
                </div>
              )}
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <MessageCircle className="h-3.5 w-3.5 flex-shrink-0" />
                <span>
                  Fuente: metadatos de WhatsApp (sin cliente vinculado)
                </span>
              </div>
            </div>
          </div>
        </ScrollArea>
      </div>
    );
  }

  // ─── Expanded: loading ───────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex flex-col h-full border-l border-gold/40 bg-gold-soft/10">
        <CardToggleHeader onToggleCollapsed={onToggleCollapsed} />
        <div className="flex items-center justify-center flex-1">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  // ─── Expanded: error loading customer ───────────────────────────────────
  if (!customer) {
    return (
      <div className="flex flex-col h-full border-l border-gold/40 bg-gold-soft/10">
        <CardToggleHeader onToggleCollapsed={onToggleCollapsed} />
        <div className="flex flex-1 flex-col items-center justify-center text-sm text-muted-foreground gap-2 p-4">
          <User className="h-8 w-8 opacity-30" />
          <span>Error al cargar cliente</span>
        </div>
      </div>
    );
  }

  // ─── Expanded: full customer detail ─────────────────────────────────────
  return (
    <div className="flex flex-col h-full border-l border-gold/40 bg-gold-soft/10">
      <CardToggleHeader onToggleCollapsed={onToggleCollapsed} />
      <ScrollArea className="flex-1">
        <div className="p-4 space-y-5">
          {/* Header */}
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gold-soft text-gold-dark font-bold text-sm flex-shrink-0">
                {fullName.slice(0, 2).toUpperCase() || "??"}
              </div>
              <div className="min-w-0">
                <p className="font-semibold text-sm truncate">
                  {fullName || "Sin nombre"}
                </p>
                {customer.preferred_stylist_name && (
                  <p className="text-xs text-muted-foreground truncate">
                    Estilista preferida: {customer.preferred_stylist_name}
                  </p>
                )}
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon"
              asChild
              className="h-7 w-7 flex-shrink-0"
            >
              <Link href={`/customers/${customerId}`} title="Ver perfil completo">
                <ChevronRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>

          <Separator />

          {/* Contact */}
          <div className="space-y-2">
            <p className="text-[11px] font-bold tracking-widest text-muted-foreground uppercase">
              Contacto
            </p>
            <div className="flex items-center gap-2 text-sm">
              <Phone className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
              <span>{customer.phone}</span>
            </div>
            {customer.last_service_date && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Calendar className="h-3.5 w-3.5 flex-shrink-0" />
                <span>Último servicio: {formatDate(customer.last_service_date)}</span>
              </div>
            )}
          </div>

          {/* Agent notes */}
          {customer.memories?.agent_notes && (
            <>
              <Separator />
              <div className="space-y-1.5">
                <p className="text-[11px] font-bold tracking-widest text-muted-foreground uppercase">
                  Notas del agente
                </p>
                <p className="text-sm text-foreground/80 whitespace-pre-wrap">
                  {customer.memories.agent_notes}
                </p>
              </div>
            </>
          )}

          {/* Recent appointments */}
          {appointments.length > 0 && (
            <>
              <Separator />
              <div className="space-y-2">
                <p className="text-[11px] font-bold tracking-widest text-muted-foreground uppercase">
                  Últimas citas
                </p>
                <div className="space-y-2">
                  {appointments.map((appt) => (
                    <div
                      key={appt.id}
                      className="text-xs rounded-md border border-line p-2 bg-muted/30 space-y-0.5"
                    >
                      <div className="flex items-center justify-between gap-1">
                        <span className="font-medium truncate">
                          {appt.service_names.join(", ")}
                        </span>
                        <Badge
                          variant={
                            appt.status === "completed" ? "secondary" : "outline"
                          }
                          className="text-[10px] px-1 py-0 flex-shrink-0"
                        >
                          {appt.status}
                        </Badge>
                      </div>
                      <p className="text-muted-foreground">
                        {formatDate(appt.start_time)} · {appt.stylist_name}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

/** Tiny header strip shown at the top of every expanded variant. */
function CardToggleHeader({
  onToggleCollapsed,
}: {
  onToggleCollapsed?: () => void;
}) {
  if (!onToggleCollapsed) return null;
  return (
    <div className="flex items-center justify-end px-2 pt-2">
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7"
        onClick={onToggleCollapsed}
        title="Contraer ficha del cliente"
      >
        <PanelRightClose className="h-4 w-4" />
      </Button>
    </div>
  );
}
