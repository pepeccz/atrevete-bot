import { Badge } from "@/components/ui/badge";
import type { InvoiceStatus, PaymentStatus } from "@/lib/types";

const invoiceStatusConfig: Record<
  InvoiceStatus,
  { label: string; className: string }
> = {
  draft: { label: "Borrador", className: "bg-gray-100 text-gray-700" },
  issued: { label: "Emitida", className: "bg-blue-100 text-blue-700" },
  paid: { label: "Pagada", className: "bg-green-100 text-green-700" },
  overdue: { label: "Vencida", className: "bg-red-100 text-red-700" },
  void: {
    label: "Anulada",
    className: "bg-gray-100 text-gray-500 line-through",
  },
};

const paymentStatusConfig: Record<
  PaymentStatus,
  { label: string; className: string }
> = {
  pending: { label: "Pendiente", className: "bg-yellow-100 text-yellow-700" },
  processing: {
    label: "Procesando",
    className: "bg-blue-100 text-blue-700",
  },
  succeeded: { label: "Completado", className: "bg-green-100 text-green-700" },
  failed: { label: "Fallido", className: "bg-red-100 text-red-700" },
  refunded: {
    label: "Reembolsado",
    className: "bg-purple-100 text-purple-700",
  },
};

export function InvoiceStatusBadge({ status }: { status: InvoiceStatus }) {
  const config = invoiceStatusConfig[status] || invoiceStatusConfig.draft;
  return <Badge className={config.className}>{config.label}</Badge>;
}

export function PaymentStatusBadge({ status }: { status: PaymentStatus }) {
  const config = paymentStatusConfig[status] || paymentStatusConfig.pending;
  return <Badge className={config.className}>{config.label}</Badge>;
}
