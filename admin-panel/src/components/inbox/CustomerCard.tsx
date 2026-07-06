"use client";

import { useRef, useState } from "react";
import {
  User,
  Phone,
  Calendar,
  Loader2,
  ChevronRight,
  ChevronDown,
  MessageCircle,
  PanelRightClose,
  PanelRightOpen,
  Pencil,
  Trash2,
  Plus,
  StickyNote,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { formatDate } from "@/components/shared/format-utils";
import { FetchError } from "@/components/shared/fetch-error";
import { formatAppointmentStatus } from "@/lib/category-labels";
import type {
  CustomerDetail,
  CustomerAppointment,
  ConversationNote,
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
   * ConversationHistory UUID — used by the parent's useNotes call to scope
   * operator notes to this conversation. PR-2, REQ-4.
   */
  conversationId?: string | null;
  /**
   * Fallback contact info from the inbound webhook (Chatwoot sender). Shown
   * when ``customerId`` is null. Either field may be null for very old
   * conversations whose webhook ran before sender_phone was persisted.
   */
  whatsappContact?: WhatsappContact | null;
  /**
   * PR-3 (ADR-4 container-presentational lift): customer detail + recent
   * appointments now come from the parent's `useCustomerCardData` hook so a
   * single fetch feeds both the inline and Sheet-drawer card instances.
   */
  customer: CustomerDetail | null;
  appointments: CustomerAppointment[];
  loading: boolean;
  fetchError: boolean;
  /** Re-fetches customer + appointments — wired to the parent hook's `reload`. */
  onRetry: () => void;
  /** Operator notes — lifted to the parent's `useNotes` call (PR-3). */
  notes: ConversationNote[];
  notesOpen: boolean;
  onToggleNotes: () => void;
  addNote: (content: string) => Promise<void>;
  editNote: (noteId: string, content: string) => Promise<void>;
  removeNote: (noteId: string) => Promise<void>;
  /** True when the column is rendered in narrow icon-rail mode. */
  collapsed?: boolean;
  /** Toggle handler — flips collapsed state in the parent. */
  onToggleCollapsed?: () => void;
}

/**
 * Right column of the inbox layout: customer information card.
 * Shows contact details, last appointments, and agent notes.
 * Presentational (PR-3, ADR-4) — customer/appointments/notes data and their
 * fetches live in the parent (`page.tsx` + `useCustomerCardData` +
 * `useNotes`), so the SAME props can feed both the inline (desktop) and
 * Sheet-drawer (tablet/mobile) instances without duplicate network calls.
 * Supports a collapsed icon-rail mode for more thread real-estate.
 * FR-UI-1.
 */
export function CustomerCard({
  customerId,
  conversationId = null,
  whatsappContact,
  customer,
  appointments,
  loading,
  fetchError,
  onRetry,
  notes,
  notesOpen,
  onToggleNotes,
  addNote,
  editNote,
  removeNote,
  collapsed = false,
  onToggleCollapsed,
}: CustomerCardProps) {
  // Purely-local draft state — only one CustomerCard instance is ever visible
  // at a time, so invisible-instance draft desync (the other mounted-but-
  // hidden/closed instance) is unobservable.
  const [newNoteContent, setNewNoteContent] = useState("");
  const [addingNote, setAddingNote] = useState(false);
  const [editingNoteId, setEditingNoteId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const newNoteRef = useRef<HTMLTextAreaElement>(null);

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
        {fetchError ? (
          <div className="flex flex-1 items-center justify-center">
            <FetchError onRetry={onRetry} />
          </div>
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center text-sm text-muted-foreground gap-2 p-4">
            <User className="h-8 w-8 opacity-30" />
            <span>Error al cargar cliente</span>
          </div>
        )}
      </div>
    );
  }

  // ─── Helpers ─────────────────────────────────────────────────────────────────
  const totalSpentFormatted = (() => {
    const val = parseFloat(customer.total_spent ?? "0");
    return isNaN(val) ? "0,00 €" : `${val.toFixed(2).replace(".", ",")} €`;
  })();

  const truncatedNotes =
    customer.notes && customer.notes.length > 120
      ? `${customer.notes.slice(0, 120)}…`
      : customer.notes;

  // ─── Expanded: full customer detail ─────────────────────────────────────
  return (
    <div className="flex flex-col h-full border-l border-gold/40 bg-gold-soft/10">
      <CardToggleHeader onToggleCollapsed={onToggleCollapsed} />
      <ScrollArea className="flex-1">
        <div className="p-4 space-y-5">
          {/* Header — name links to /customers/[id] */}
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gold-soft text-gold-dark font-bold text-sm flex-shrink-0">
                {fullName.slice(0, 2).toUpperCase() || "??"}
              </div>
              <div className="min-w-0">
                <Link
                  href={`/customers/${customerId}`}
                  className="font-semibold text-sm truncate hover:underline hover:text-gold-dark transition-colors"
                >
                  {fullName || "Sin nombre"}
                </Link>
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

          {/* Contacto */}
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

          <Separator />

          {/* Política */}
          <div className="space-y-2">
            <p className="text-[11px] font-bold tracking-widest text-muted-foreground uppercase">
              Política
            </p>
            {customer.policy_accepted_at ? (
              <Badge className="bg-green-100 text-green-800 border-green-200 text-xs font-normal">
                Política aceptada el {formatDate(customer.policy_accepted_at, false)}
              </Badge>
            ) : (
              <Badge variant="outline" className="text-muted-foreground text-xs font-normal">
                Política no aceptada
              </Badge>
            )}
          </div>

          <Separator />

          {/* Preferencias */}
          <div className="space-y-2">
            <p className="text-[11px] font-bold tracking-widest text-muted-foreground uppercase">
              Preferencias
            </p>
            <p className="text-sm text-foreground/80">
              {customer.preferred_stylist_name ?? "Sin estilista preferido"}
            </p>
          </div>

          <Separator />

          {/* Última actividad */}
          <div className="space-y-2">
            <p className="text-[11px] font-bold tracking-widest text-muted-foreground uppercase">
              Última actividad
            </p>
            {appointments.length === 0 ? (
              <p className="text-xs text-muted-foreground">Sin citas previas</p>
            ) : (
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
                        {formatAppointmentStatus(appt.status)}
                      </Badge>
                    </div>
                    <p className="text-muted-foreground">
                      {formatDate(appt.start_time)} · {appt.stylist_name}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>

          <Separator />

          {/* Agent notes */}
          {customer.memories?.agent_notes && (
            <>
              <div className="space-y-1.5">
                <p className="text-[11px] font-bold tracking-widest text-muted-foreground uppercase">
                  Notas del agente
                </p>
                <p className="text-sm text-foreground/80 whitespace-pre-wrap">
                  {customer.memories.agent_notes}
                </p>
              </div>
              <Separator />
            </>
          )}

          {/* Notas del cliente */}
          <div className="space-y-1.5">
            <p className="text-[11px] font-bold tracking-widest text-muted-foreground uppercase">
              Notas
            </p>
            {customer.notes ? (
              <p className="text-sm text-foreground/80">
                {truncatedNotes}
                {customer.notes.length > 120 && (
                  <>
                    {" "}
                    <Link
                      href={`/customers/${customerId}`}
                      className="text-xs text-gold-dark hover:underline"
                    >
                      ver más
                    </Link>
                  </>
                )}
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">Sin notas</p>
            )}
          </div>

          <Separator />

          {/* Resumen */}
          <div className="space-y-1.5">
            <p className="text-[11px] font-bold tracking-widest text-muted-foreground uppercase">
              Resumen
            </p>
            <p className="text-sm font-semibold text-foreground">{totalSpentFormatted}</p>
            <p className="text-xs text-muted-foreground">
              Cliente desde {formatDate(customer.created_at, false)}
            </p>
          </div>

          {/* Operator notes panel (PR-2) */}
          {conversationId && (
            <>
              <Separator />
              <div className="space-y-2">
                <button
                  type="button"
                  className="flex items-center gap-1.5 w-full text-left"
                  aria-expanded={notesOpen}
                  aria-controls="notes-panel"
                  onClick={onToggleNotes}
                >
                  <StickyNote className="h-3.5 w-3.5 text-muted-foreground" />
                  <p className="text-[11px] font-bold tracking-widest text-muted-foreground uppercase flex-1">
                    Notas del operador
                  </p>
                  <ChevronDown
                    className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${
                      notesOpen ? "rotate-180" : ""
                    }`}
                  />
                </button>
                {notesOpen && (
                  <div id="notes-panel" className="space-y-2 pt-1">
                    {notes.length === 0 && (
                      <p className="text-xs text-muted-foreground">
                        Sin notas todavía.
                      </p>
                    )}
                    {notes.map((note) => (
                      <div
                        key={note.id}
                        className="text-xs rounded-md border border-line p-2 bg-muted/30 space-y-1"
                      >
                        {editingNoteId === note.id ? (
                          <div className="space-y-1">
                            <Textarea
                              className="w-full text-xs resize-none"
                              rows={3}
                              value={editContent}
                              onChange={(e) => setEditContent(e.target.value)}
                            />
                            <div className="flex gap-1">
                              <Button
                                variant="default"
                                size="sm"
                                className="h-6 text-xs px-2"
                                onClick={async () => {
                                  await editNote(note.id, editContent);
                                  setEditingNoteId(null);
                                }}
                              >
                                Guardar
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 text-xs px-2"
                                onClick={() => setEditingNoteId(null)}
                              >
                                Cancelar
                              </Button>
                            </div>
                          </div>
                        ) : (
                          <>
                            <p className="whitespace-pre-wrap">{note.content}</p>
                            <div className="flex items-center justify-between gap-1 text-[10px] text-muted-foreground">
                              <span>{note.author_name}</span>
                              <div className="flex gap-1">
                                <button
                                  type="button"
                                  title="Editar"
                                  aria-label="Editar nota"
                                  onClick={() => {
                                    setEditingNoteId(note.id);
                                    setEditContent(note.content);
                                  }}
                                >
                                  <Pencil className="h-3 w-3" />
                                </button>
                                <button
                                  type="button"
                                  title="Eliminar"
                                  aria-label="Eliminar nota"
                                  onClick={() => removeNote(note.id)}
                                >
                                  <Trash2 className="h-3 w-3 text-destructive" />
                                </button>
                              </div>
                            </div>
                          </>
                        )}
                      </div>
                    ))}

                    {/* Add note input */}
                    {addingNote ? (
                      <div className="space-y-1">
                        <Textarea
                          ref={newNoteRef}
                          className="w-full text-xs resize-none"
                          rows={3}
                          placeholder="Escribe una nota..."
                          value={newNoteContent}
                          onChange={(e) => setNewNoteContent(e.target.value)}
                          autoFocus
                        />
                        <div className="flex gap-1">
                          <Button
                            variant="default"
                            size="sm"
                            className="h-6 text-xs px-2"
                            disabled={!newNoteContent.trim()}
                            onClick={async () => {
                              await addNote(newNoteContent);
                              setNewNoteContent("");
                              setAddingNote(false);
                            }}
                          >
                            Agregar
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 text-xs px-2"
                            onClick={() => {
                              setAddingNote(false);
                              setNewNoteContent("");
                            }}
                          >
                            Cancelar
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 text-xs px-2 w-full justify-start gap-1"
                        onClick={() => setAddingNote(true)}
                      >
                        <Plus className="h-3 w-3" />
                        Añadir nota
                      </Button>
                    )}
                  </div>
                )}
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
