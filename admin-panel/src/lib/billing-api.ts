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

function getAuthHeaders(): HeadersInit {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("admin_token") : null;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

async function billingRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers: { ...getAuthHeaders(), ...options.headers },
    credentials: "include",
  });

  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      localStorage.removeItem("admin_token");
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

  downloadPdf: async (id: string, invoiceNumber: string) => {
    const token =
      typeof window !== "undefined"
        ? localStorage.getItem("admin_token")
        : null;
    const response = await fetch(
      `${API_BASE_URL}/api/billing/invoices/${id}/pdf`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
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
};
