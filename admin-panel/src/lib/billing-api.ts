/**
 * Billing API client — separate from main api.ts to avoid bloating it.
 */

import type {
  InvoiceListResponse,
  InvoiceResponse,
  CurrentEstimateResponse,
  StripeStatusResponse,
  SetupSessionResponse,
} from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function billingRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  // Authentication is exclusively via HttpOnly cookie (admin_token).
  // credentials:"include" causes the browser to attach it automatically.
  // No Authorization header is ever set by the client.
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    credentials: "include",
  });

  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      window.location.href = "/login";
    }
    const error = await response.json().catch(() => ({ detail: "Error" }));
    throw new Error(
      typeof error.detail === "string" ? error.detail : `HTTP ${response.status}`
    );
  }

  return response.json();
}

export const billingApi = {
  getInvoices: (page = 1, pageSize = 20) =>
    billingRequest<InvoiceListResponse>(
      `/api/billing/invoices?page=${page}&page_size=${pageSize}`
    ),

  getInvoice: (id: string) =>
    billingRequest<InvoiceResponse>(`/api/billing/invoices/${id}`),

  downloadPdf: async (id: string, invoiceNumber: string, pdfUrl?: string | null) => {
    if (pdfUrl) {
      window.open(pdfUrl, '_blank');
      return;
    }
    // Authentication via HttpOnly cookie (credentials:"include").
    const response = await fetch(
      `${API_BASE_URL}/api/billing/invoices/${id}/pdf`,
      {
        headers: { "Content-Type": "application/json" },
        credentials: "include",
      }
    );
    if (!response.ok) throw new Error("Error descargando PDF");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${invoiceNumber}.pdf`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  generateInvoice: (year: number, month: number) =>
    billingRequest<InvoiceResponse>("/api/billing/invoices/generate", {
      method: "POST",
      body: JSON.stringify({ year, month }),
    }),

  getCurrentEstimate: () =>
    billingRequest<CurrentEstimateResponse>("/api/billing/current-estimate"),

  voidInvoice: (id: string, reason?: string) =>
    billingRequest<InvoiceResponse>(`/api/billing/invoices/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status: "void", reason }),
    }),

  getStripeStatus: () =>
    billingRequest<StripeStatusResponse>("/api/billing/stripe/status"),

  createSetupSession: () =>
    billingRequest<SetupSessionResponse>("/api/billing/stripe/setup-session", {
      method: "POST",
    }),

  getFiscalDetails: () =>
    billingRequest<{
      client_name: string;
      client_nif: string;
      client_address: string;
      provider_name: string;
      provider_nif: string;
      provider_address: string;
      provider_email: string;
    }>("/api/billing/fiscal-details"),

  /**
   * One-time deployment step — invoke via curl only. Do NOT add a UI button.
   *
   * Creates the IVA 21% TaxRate on Stripe and attaches the client NIF to the
   * Stripe Customer. This is idempotent and must be run once after initial
   * deploy with Stripe credentials configured. See CLAUDE.md → Deploy Runbook
   * (billing-wip-completion) for the curl command.
   */
  setupFiscal: () =>
    billingRequest<{ tax_rate_id: string | null; tax_rate_created: boolean; tax_id_attached: boolean }>(
      "/api/billing/setup-fiscal",
      { method: "POST" }
    ),
};
