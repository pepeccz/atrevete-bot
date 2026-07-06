"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import api from "@/lib/api";
import type { CustomerDetail, CustomerAppointment } from "@/lib/types";

interface UseCustomerCardDataResult {
  customer: CustomerDetail | null;
  appointments: CustomerAppointment[];
  loading: boolean;
  fetchError: boolean;
  /** Re-runs the fetch for the current customerId. Wired to CustomerCard's onRetry. */
  reload: () => void;
}

/**
 * Fetches customer detail + recent appointments for the inbox CustomerCard.
 *
 * Extracted from CustomerCard (container→presentational lift, PR-3, ADR-4) so
 * a single fetch feeds both the inline (desktop) and Sheet-drawer
 * (tablet/mobile) card instances without duplicate network calls. Preserves
 * the original `reqId` stale-response guard exactly.
 */
export function useCustomerCardData(customerId: string | null): UseCustomerCardDataResult {
  const [customer, setCustomer] = useState<CustomerDetail | null>(null);
  const [appointments, setAppointments] = useState<CustomerAppointment[]>([]);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState(false);
  const reqId = useRef(0);

  const load = useCallback(async () => {
    if (!customerId) {
      setCustomer(null);
      setAppointments([]);
      setFetchError(false);
      return;
    }
    const myReq = ++reqId.current;
    setLoading(true);
    setFetchError(false);
    try {
      const [cust, appts] = await Promise.all([
        api.getCustomerDetail(customerId),
        api.getCustomerAppointments(customerId, 1, 3),
      ]);
      if (myReq !== reqId.current) return; // stale response — a newer request is in flight
      setCustomer(cust);
      setAppointments(appts.items);
    } catch (err) {
      if (myReq !== reqId.current) return;
      console.error("[useCustomerCardData] load failed:", err);
      setFetchError(true);
    } finally {
      if (myReq === reqId.current) setLoading(false);
    }
  }, [customerId]);

  useEffect(() => {
    load();
  }, [load]);

  return { customer, appointments, loading, fetchError, reload: load };
}
