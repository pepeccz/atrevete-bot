"use client";

import { useEffect, useState, useCallback } from "react";
import { ColumnDef } from "@tanstack/react-table";
import { format } from "date-fns";
import { es } from "date-fns/locale";
import { MessageSquare, User, Clock, Eye, Info, Trash2 } from "lucide-react";

import { Header } from "@/components/layout/header";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { DataTable, SortableHeader } from "@/components/ui/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { toast } from "sonner";
import api from "@/lib/api";
import type { ConversationHistory, ConversationMessage, Customer } from "@/lib/types";

// Format date for display
function formatDate(dateString: string | null): string {
  if (!dateString) return "-";
  try {
    return format(new Date(dateString), "dd/MM/yyyy HH:mm", { locale: es });
  } catch {
    return dateString;
  }
}

// Message bubble component
function MessageBubble({
  role,
  content,
  timestamp,
}: {
  role: string;
  content: string;
  timestamp?: string;
}) {
  const isUser = role === "user" || role === "human";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}>
      <div
        className={`max-w-[80%] rounded-lg px-4 py-2 ${
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-foreground"
        }`}
      >
        <p className="text-sm whitespace-pre-wrap">{content}</p>
        {timestamp && (
          <p
            className={`text-xs mt-1 ${
              isUser ? "text-primary-foreground/70" : "text-muted-foreground"
            }`}
          >
            {formatDate(timestamp)}
          </p>
        )}
      </div>
    </div>
  );
}

// Conversation detail modal
function ConversationDetailModal({
  open,
  onOpenChange,
  conversation,
  customer,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  conversation: ConversationHistory | null;
  customer: Customer | null;
}) {
  if (!conversation) return null;

  // Parse messages from JSON if stored as string
  const messages: ConversationMessage[] = Array.isArray(conversation.messages)
    ? conversation.messages
    : [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <MessageSquare className="h-5 w-5" />
            Conversacion
          </DialogTitle>
          <DialogDescription>
            {customer
              ? `${customer.first_name} ${customer.last_name || ""} - ${customer.phone}`
              : "Cliente no identificado"}
          </DialogDescription>
        </DialogHeader>

        <div className="flex gap-4 text-sm text-muted-foreground mb-4">
          <span>Inicio: {formatDate(conversation.started_at)}</span>
          <span>Fin: {formatDate(conversation.ended_at)}</span>
          <span>{conversation.message_count} mensajes</span>
        </div>

        <ScrollArea className="h-[400px] pr-4">
          <div className="space-y-2">
            {messages.length === 0 ? (
              <p className="text-center text-muted-foreground py-8">
                No hay mensajes en esta conversacion
              </p>
            ) : (
              messages.map((msg, index) => (
                <MessageBubble
                  key={index}
                  role={msg.role}
                  content={msg.content}
                  timestamp={msg.timestamp}
                />
              ))
            )}
          </div>
        </ScrollArea>

        {conversation.summary && (
          <div className="mt-4 p-3 bg-muted rounded-lg">
            <p className="text-sm font-medium mb-1">Resumen:</p>
            <p className="text-sm text-muted-foreground">
              {conversation.summary}
            </p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function ConversationsPage() {
  const [conversations, setConversations] = useState<ConversationHistory[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedConversation, setSelectedConversation] =
    useState<ConversationHistory | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [conversationToDelete, setConversationToDelete] =
    useState<ConversationHistory | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Create customer map for display
  const customerMap = Object.fromEntries(
    customers.map((c) => [c.id, c])
  );

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [conversationsRes, customersRes] = await Promise.all([
        api.list<ConversationHistory>("conversations", { page_size: 100 }),
        api.list<Customer>("customers", { page_size: 200 }),
      ]);

      setConversations(conversationsRes.items);
      setCustomers(customersRes.items);
    } catch (error) {
      toast.error("Error al cargar las conversaciones");
      console.error(error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleViewConversation = async (conversation: ConversationHistory) => {
    // The list endpoint does not return messages — fetch full detail first
    setLoadingDetail(true);
    try {
      const detail = await api.getConversation(conversation.id);
      setSelectedConversation(detail);
      setModalOpen(true);
    } catch (error) {
      toast.error("Error al cargar los mensajes de la conversacion");
      console.error(error);
    } finally {
      setLoadingDetail(false);
    }
  };

  const handleDeleteClick = (conversation: ConversationHistory) => {
    setConversationToDelete(conversation);
    setDeleteDialogOpen(true);
  };

  const handleDelete = async () => {
    if (!conversationToDelete) return;

    setDeleting(true);
    try {
      const result = await api.deleteConversation(conversationToDelete.id);
      if (result.db_deleted) {
        setConversations((prev) =>
          prev.filter((c) => c.id !== conversationToDelete.id)
        );
        toast.success("Conversacion eliminada correctamente");
      } else {
        toast.error(result.error ?? "Error al eliminar la conversacion");
      }
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Error desconocido";
      toast.error(`Error al eliminar la conversacion: ${message}`);
      console.error(error);
    } finally {
      setDeleting(false);
      setDeleteDialogOpen(false);
      setConversationToDelete(null);
    }
  };

  const columns: ColumnDef<ConversationHistory>[] = [
    {
      accessorKey: "customer_id",
      header: () => (
        <div className="flex items-center">
          <User className="mr-2 h-4 w-4" />
          Cliente
        </div>
      ),
      cell: ({ row }) => {
        const customerId = row.getValue("customer_id") as string | null;
        if (!customerId) return "Desconocido";
        const customer = customerMap[customerId];
        if (!customer) return "Desconocido";
        return `${customer.first_name} ${customer.last_name || ""}`.trim();
      },
    },
    {
      accessorKey: "started_at",
      header: ({ column }) => (
        <SortableHeader column={column}>
          <Clock className="mr-2 h-4 w-4" />
          Inicio
        </SortableHeader>
      ),
      cell: ({ row }) => formatDate(row.getValue("started_at")),
    },
    {
      accessorKey: "ended_at",
      header: ({ column }) => (
        <SortableHeader column={column}>Fin</SortableHeader>
      ),
      cell: ({ row }) => formatDate(row.getValue("ended_at")),
    },
    {
      accessorKey: "message_count",
      header: () => (
        <div className="flex items-center">
          <MessageSquare className="mr-2 h-4 w-4" />
          Mensajes
        </div>
      ),
      cell: ({ row }) => (
        <Badge variant="secondary">{row.getValue("message_count")}</Badge>
      ),
    },
    {
      accessorKey: "summary",
      header: "Resumen",
      cell: ({ row }) => {
        const summary = row.getValue("summary") as string | null;
        if (!summary) return "-";
        return summary.length > 50 ? summary.substring(0, 50) + "..." : summary;
      },
    },
    {
      id: "actions",
      cell: ({ row }) => {
        const conversation = row.original;
        return (
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => handleViewConversation(conversation)}
              disabled={loadingDetail}
            >
              <Eye className="mr-2 h-4 w-4" />
              {loadingDetail ? "Cargando..." : "Ver"}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-destructive hover:text-destructive hover:bg-destructive/10"
              onClick={() => handleDeleteClick(conversation)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        );
      },
    },
  ];

  const selectedCustomer =
    selectedConversation?.customer_id
      ? customerMap[selectedConversation.customer_id] ?? null
      : null;

  return (
    <div className="flex flex-col">
      <Header
        title="Conversaciones"
        description="Historial de conversaciones con el bot (solo lectura)"
      />

      <div className="flex-1 p-6 space-y-6">
        {/* Explicacion del sistema de resumen */}
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-start gap-3">
              <Info className="h-5 w-5 text-muted-foreground mt-0.5 flex-shrink-0" />
              <div className="space-y-2">
                <p className="text-sm font-medium">Sistema de Resumen de Conversaciones</p>
                <div className="text-sm text-muted-foreground space-y-2">
                  <p>
                    El bot mantiene solo los <strong>ultimos 10 mensajes</strong> en memoria (ventana FIFO).
                    Cuando una conversacion alcanza <strong>20+ mensajes</strong>, se genera automaticamente
                    un resumen de los mensajes anteriores usando IA.
                  </p>
                  <ul className="list-disc ml-6 space-y-1">
                    <li>Mensajes 1-10: Se mantienen en memoria sin resumen</li>
                    <li>Mensaje 19: Se genera primer resumen de mensajes 1-9</li>
                    <li>Mensaje 29, 39...: Se acumula nuevo resumen al anterior</li>
                  </ul>
                  <p className="text-xs text-muted-foreground/70">
                    El resumen permite al bot mantener contexto de conversaciones largas sin exceder
                    limites de tokens. Las conversaciones se archivan automaticamente despues de 24 horas.
                  </p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Tabla de conversaciones */}
        <Card>
          <CardContent className="pt-6">
            <DataTable
              columns={columns}
              data={conversations}
              isLoading={loading}
            />
          </CardContent>
        </Card>
      </div>

      {/* Conversation Detail Modal */}
      <ConversationDetailModal
        open={modalOpen}
        onOpenChange={setModalOpen}
        conversation={selectedConversation}
        customer={selectedCustomer}
      />

      {/* Delete Confirmation */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar conversacion</AlertDialogTitle>
            <AlertDialogDescription>
              Esta accion no se puede deshacer. La conversacion sera eliminada
              permanentemente junto con todos sus mensajes y el checkpoint de
              Redis asociado.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={deleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleting ? "Eliminando..." : "Eliminar"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
