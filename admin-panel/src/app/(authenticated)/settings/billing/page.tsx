"use client";

import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Plus, Loader2 } from "lucide-react";
import { billingApi } from "@/lib/billing-api";
import { CurrentMonthSummary } from "@/components/billing/current-month-summary";
import { InvoiceHistory } from "@/components/billing/invoice-history";
import { PaymentSetup } from "@/components/billing/payment-setup";
import type {
  CurrentEstimateResponse,
  InvoiceListResponse,
  StripeStatusResponse,
} from "@/lib/types";

export default function BillingPage() {
  const searchParams = useSearchParams();

  const [estimate, setEstimate] = useState<CurrentEstimateResponse | null>(
    null
  );
  const [invoices, setInvoices] = useState<InvoiceListResponse | null>(null);
  const [stripeStatus, setStripeStatus] = useState<StripeStatusResponse | null>(
    null
  );
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);

  // Generate invoice dialog
  const [showGenerate, setShowGenerate] = useState(false);
  const [genYear, setGenYear] = useState(new Date().getFullYear());
  const [genMonth, setGenMonth] = useState(new Date().getMonth()); // prev month
  const [generating, setGenerating] = useState(false);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [est, inv, stripe] = await Promise.all([
        billingApi.getCurrentEstimate(),
        billingApi.getInvoices(page),
        billingApi.getStripeStatus(),
      ]);
      setEstimate(est);
      setInvoices(inv);
      setStripeStatus(stripe);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error cargando datos");
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Handle Stripe redirect callback
  useEffect(() => {
    const stripeSetup = searchParams.get("stripe_setup");
    if (stripeSetup === "success") {
      billingApi.getStripeStatus().then(setStripeStatus);
    }
  }, [searchParams]);

  const handleGenerate = async () => {
    try {
      setGenerating(true);
      await billingApi.generateInvoice(genYear, genMonth);
      setShowGenerate(false);
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error generando factura");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="flex-1 overflow-auto">
      <Header title="Facturación" />
      <div className="space-y-6 p-6">
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {error}
            <Button
              variant="link"
              className="ml-2 text-red-700"
              onClick={loadData}
            >
              Reintentar
            </Button>
          </div>
        )}

        {/* Current month estimate */}
        <CurrentMonthSummary estimate={estimate} loading={loading} />

        {/* Invoice history with generate button */}
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Facturas</h2>
          <Dialog open={showGenerate} onOpenChange={setShowGenerate}>
            <DialogTrigger asChild>
              <Button size="sm">
                <Plus className="mr-2 h-4 w-4" />
                Generar factura
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Generar factura</DialogTitle>
                <DialogDescription>
                  Selecciona el periodo para generar la factura manualmente.
                </DialogDescription>
              </DialogHeader>
              <div className="grid gap-4 py-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="year">Año</Label>
                    <Input
                      id="year"
                      type="number"
                      min={2024}
                      max={2030}
                      value={genYear}
                      onChange={(e) => setGenYear(parseInt(e.target.value))}
                    />
                  </div>
                  <div>
                    <Label htmlFor="month">Mes</Label>
                    <Input
                      id="month"
                      type="number"
                      min={1}
                      max={12}
                      value={genMonth}
                      onChange={(e) => setGenMonth(parseInt(e.target.value))}
                    />
                  </div>
                </div>
              </div>
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => setShowGenerate(false)}
                >
                  Cancelar
                </Button>
                <Button onClick={handleGenerate} disabled={generating}>
                  {generating ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Generando...
                    </>
                  ) : (
                    "Generar"
                  )}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>

        <InvoiceHistory
          data={invoices}
          loading={loading}
          page={page}
          onPageChange={setPage}
          onRefresh={loadData}
        />

        {/* Payment setup */}
        <PaymentSetup stripeStatus={stripeStatus} loading={loading} />
      </div>
    </div>
  );
}
