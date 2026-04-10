"use client";

import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { billingApi } from "@/lib/billing-api";
import { CurrentMonthSummary } from "@/components/billing/current-month-summary";
import { InvoiceHistory } from "@/components/billing/invoice-history";
import { PaymentSetup } from "@/components/billing/payment-setup";
import { BillingDetails } from "@/components/billing/billing-details";
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

        {/* Invoice history */}
        <h2 className="text-lg font-semibold">Facturas</h2>
        <InvoiceHistory
          data={invoices}
          loading={loading}
          page={page}
          onPageChange={setPage}
        />

        {/* Payment setup */}
        <PaymentSetup stripeStatus={stripeStatus} loading={loading} />

        {/* Billing details */}
        <BillingDetails />
      </div>
    </div>
  );
}
