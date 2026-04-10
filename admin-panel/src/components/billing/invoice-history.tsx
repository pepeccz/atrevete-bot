"use client";

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
import { InvoiceStatusBadge } from "./status-badge";
import { PdfDownloadButton } from "./pdf-download-button";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { InvoiceListResponse } from "@/lib/types";

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
}

export function InvoiceHistory({
  data,
  loading,
  page,
  onPageChange,
}: Props) {
  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0;

  return (
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
                  <TableHead className="text-right">Base</TableHead>
                  <TableHead className="text-right">IVA (21%)</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead className="text-right">PDF</TableHead>
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
                      {invoice.subtotal_eur != null
                        ? formatEur(invoice.subtotal_eur)
                        : formatEur(invoice.total_amount_eur)}
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground">
                      {invoice.tax_amount_eur != null
                        ? formatEur(invoice.tax_amount_eur)
                        : "—"}
                    </TableCell>
                    <TableCell className="text-right font-medium">
                      {invoice.gross_amount_eur != null
                        ? formatEur(invoice.gross_amount_eur)
                        : formatEur(invoice.total_amount_eur)}
                    </TableCell>
                    <TableCell>
                      <InvoiceStatusBadge status={invoice.status} />
                    </TableCell>
                    <TableCell className="text-right">
                      <PdfDownloadButton
                        invoiceId={invoice.id}
                        invoiceNumber={invoice.invoice_number}
                        hasPdf={invoice.has_pdf}
                        pdfUrl={invoice.invoice_pdf_url}
                      />
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
  );
}
