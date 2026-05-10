"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle, CreditCard, ExternalLink, Loader2, ShieldCheck } from "lucide-react";
import { billingApi } from "@/lib/billing-api";
import type { StripeStatusResponse } from "@/lib/types";

interface Props {
  stripeStatus: StripeStatusResponse | null;
  loading: boolean;
}

/**
 * Resolve the SEPA mandate badge label and variant from the raw status string.
 * Pure function — no side effects, trivially testable.
 */
export function resolveMandateBadge(
  mandateStatus: string | null
): { label: string; variant: "ok" | "warn" | "neutral" } {
  switch (mandateStatus) {
    case "active":
      return { label: "Configurado", variant: "ok" };
    case "inactive":
      return { label: "Mandato inactivo", variant: "warn" };
    case "requires_action":
      return { label: "Acción requerida", variant: "warn" };
    default:
      return { label: "Estado desconocido", variant: "neutral" };
  }
}

export function PaymentSetup({ stripeStatus, loading }: Props) {
  const [settingUp, setSettingUp] = useState(false);

  const handleSetup = async () => {
    try {
      setSettingUp(true);
      const { checkout_url } = await billingApi.createSetupSession();
      window.location.href = checkout_url;
    } catch (err) {
      console.error("Error creating setup session:", err);
      setSettingUp(false);
    }
  };

  if (loading) {
    return (
      <Card>
        <CardContent className="p-6">
          <div className="h-16 animate-pulse rounded bg-gray-200" />
        </CardContent>
      </Card>
    );
  }

  if (stripeStatus?.configured) {
    const { label, variant } = resolveMandateBadge(stripeStatus.sepa_mandate_status);
    const isWarn = variant === "warn";

    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <CreditCard className="h-5 w-5" />
            Pago Automático — SEPA
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {isWarn ? (
                <AlertTriangle aria-label="Alerta mandato" className="h-8 w-8 text-yellow-500" />
              ) : (
                <ShieldCheck className="h-8 w-8 text-green-600" />
              )}
              <div>
                <p className="font-medium">Domiciliación SEPA activa</p>
                <p className="text-sm text-muted-foreground">
                  Cuenta terminada en ····{stripeStatus.payment_method_last4}
                </p>
                {isWarn && (
                  <p className="mt-1 text-sm text-yellow-700">
                    {stripeStatus.sepa_mandate_status === "inactive"
                      ? "El mandato SEPA ha expirado o fue revocado. Reconfigura el pago."
                      : "Se requiere acción del titular. Reconfigura el pago."}
                  </p>
                )}
              </div>
            </div>
            <div className="flex flex-col items-end gap-2">
              <Badge
                className={
                  variant === "ok"
                    ? "bg-green-100 text-green-700"
                    : variant === "warn"
                      ? "bg-yellow-100 text-yellow-700"
                      : "bg-gray-100 text-gray-600"
                }
              >
                {label}
              </Badge>
              {isWarn && (
                <Button size="sm" variant="outline" onClick={handleSetup} disabled={settingUp}>
                  {settingUp ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <>
                      <ExternalLink className="mr-1 h-3 w-3" />
                      Reconfigurar
                    </>
                  )}
                </Button>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <CreditCard className="h-5 w-5" />
          Pago Automático — SEPA
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-center justify-between">
          <div>
            <p className="font-medium">Pago automático no configurado</p>
            <p className="text-sm text-muted-foreground">
              Configura domiciliación SEPA para cobro automático mensual
            </p>
          </div>
          <Button onClick={handleSetup} disabled={settingUp}>
            {settingUp ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Redirigiendo...
              </>
            ) : (
              <>
                <ExternalLink className="mr-2 h-4 w-4" />
                Configurar pago
              </>
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
