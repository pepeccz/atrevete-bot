"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { CreditCard, ExternalLink, Loader2, ShieldCheck } from "lucide-react";
import { billingApi } from "@/lib/billing-api";
import type { StripeStatusResponse } from "@/lib/types";

interface Props {
  stripeStatus: StripeStatusResponse | null;
  loading: boolean;
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

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <CreditCard className="h-5 w-5" />
          Pago Automático — SEPA
        </CardTitle>
      </CardHeader>
      <CardContent>
        {stripeStatus?.configured ? (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <ShieldCheck className="h-8 w-8 text-green-600" />
              <div>
                <p className="font-medium">Domiciliación SEPA activa</p>
                <p className="text-sm text-muted-foreground">
                  Cuenta terminada en ····{stripeStatus.payment_method_last4}
                </p>
              </div>
            </div>
            <Badge className="bg-green-100 text-green-700">Configurado</Badge>
          </div>
        ) : (
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
        )}
      </CardContent>
    </Card>
  );
}
