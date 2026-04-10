"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Building2, Mail } from "lucide-react";
import { billingApi } from "@/lib/billing-api";

interface BillingDetailsData {
  client_name: string;
  client_nif: string;
  client_address: string;
  provider_name: string;
  provider_nif: string;
  provider_address: string;
  provider_email: string;
}

export function BillingDetails() {
  const [details, setDetails] = useState<BillingDetailsData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    billingApi
      .getFiscalDetails()
      .then(setDetails)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Card>
        <CardContent className="p-6">
          <div className="h-24 animate-pulse rounded bg-gray-200" />
        </CardContent>
      </Card>
    );
  }

  if (!details) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <Building2 className="h-5 w-5" />
          Datos de Facturación
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid gap-6 md:grid-cols-2">
          {/* Client (Pilar) */}
          <div className="space-y-2">
            <h3 className="text-sm font-medium text-muted-foreground">
              Tu empresa
            </h3>
            <p className="font-medium">{details.client_name}</p>
            <p className="text-sm text-muted-foreground">
              NIF: {details.client_nif}
            </p>
            <p className="text-sm text-muted-foreground">
              {details.client_address}
            </p>
          </div>

          {/* Provider (Zanovix) */}
          <div className="space-y-2">
            <h3 className="text-sm font-medium text-muted-foreground">
              Proveedor
            </h3>
            <p className="font-medium">{details.provider_name}</p>
            <p className="text-sm text-muted-foreground">
              NIF: {details.provider_nif}
            </p>
            <p className="text-sm text-muted-foreground">
              {details.provider_address}
            </p>
            <p className="flex items-center gap-1 text-sm text-muted-foreground">
              <Mail className="h-3 w-3" />
              {details.provider_email}
            </p>
          </div>
        </div>

        <p className="mt-4 text-xs text-muted-foreground">
          Si necesitas modificar tus datos de facturación, contacta con{" "}
          <a
            href={`mailto:${details.provider_email}`}
            className="text-primary underline"
          >
            {details.provider_email}
          </a>
        </p>
      </CardContent>
    </Card>
  );
}
