"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
import { InvoiceStatusBadge } from "./status-badge";
import { PdfDownloadButton } from "./pdf-download-button";
import { ChevronLeft, ChevronRight, Ban } from "lucide-react";
import { billingApi } from "@/lib/billing-api";
import type { InvoiceListResponse, InvoiceResponse } from "@/lib/types";

function formatEur(value: string): string {
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: "EUR",
  }).format(parseFloat(value));
}

interface Props {
  data: InvoiceListResponse | null;
  loading: boolean;
  page: number;
  onPageChange: (page: number) => void;
  onRefresh: () => void;
}

export function InvoiceHistory({
  data,
  loading,
  page,
  onPageChange,
  onRefresh,
}: Props) {
  const [voidTarget, setVoidTarget] = useState<InvoiceResponse | null>(null);
  const [voiding, setVoiding] = useState(false);

  const handleVoid = async () => {
    if (!voidTarget) return;
    try {
      setVoiding(true);
      await billingApi.voidInvoice(
        voidTarget.id,
        "Anulada desde panel de administración"
      );
      onRefresh();
    } catch (err) {
      console.error("Error voiding invoice:", err);
    } finally {
      setVoiding(false);
      setVoidTarget(null);
    }
  };

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0;

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Historial de Facturas</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="h-12 animate-pulse rounded bg-gray-200"
                />
              ))}
            </div>
          ) : !data || data.invoices.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              No hay facturas generadas aún
            </p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Nº Factura</TableHead>
                    <TableHead>Periodo</TableHead>
                    <TableHead className="text-right">Mantenimiento</TableHead>
                    <TableHead className="text-right">Tokens</TableHead>
                    <TableHead className="text-right">Total</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead className="text-right">Acciones</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.invoices.map((invoice) => (
                    <TableRow key={invoice.id}>
                      <TableCell className="font-mono text-sm">
                        {invoice.invoice_number}
                      </TableCell>
                      <TableCell>{invoice.period_label}</TableCell>
                      <TableCell className="text-right">
                        {formatEur(invoice.maintenance_amount_eur)}
                      </TableCell>
                      <TableCell className="text-right">
                        {formatEur(invoice.token_amount_eur)}
                      </TableCell>
                      <TableCell className="text-right font-medium">
                        {formatEur(invoice.total_amount_eur)}
                      </TableCell>
                      <TableCell>
                        <InvoiceStatusBadge status={invoice.status} />
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <PdfDownloadButton
                            invoiceId={invoice.id}
                            invoiceNumber={invoice.invoice_number}
                            hasPdf={invoice.has_pdf}
                          />
                          {(invoice.status === "issued" ||
                            invoice.status === "overdue") && (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setVoidTarget(invoice)}
                              className="text-red-600 hover:text-red-700"
                            >
                              <Ban className="h-4 w-4" />
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              {totalPages > 1 && (
                <div className="mt-4 flex items-center justify-between">
                  <p className="text-sm text-muted-foreground">
                    Página {page} de {totalPages} · {data.total} facturas
                  </p>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onPageChange(page - 1)}
                      disabled={page <= 1}
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onPageChange(page + 1)}
                      disabled={page >= totalPages}
                    >
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <AlertDialog open={!!voidTarget} onOpenChange={() => setVoidTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Anular factura?</AlertDialogTitle>
            <AlertDialogDescription>
              Se anulará la factura {voidTarget?.invoice_number} (
              {voidTarget?.period_label}). Si hay un cobro pendiente en Stripe,
              se cancelará automáticamente. Esta acción no se puede deshacer.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={voiding}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleVoid}
              disabled={voiding}
              className="bg-red-600 hover:bg-red-700"
            >
              {voiding ? "Anulando..." : "Anular factura"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
