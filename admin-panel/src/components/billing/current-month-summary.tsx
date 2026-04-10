import { Card, CardContent } from "@/components/ui/card";
import { Wrench, Bot, Receipt } from "lucide-react";
import type { CurrentEstimateResponse } from "@/lib/types";

function formatEurFixed(value: string): string {
  return `€${parseFloat(value).toFixed(2)}`;
}

function formatEur(value: string): string {
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: "EUR",
  }).format(parseFloat(value));
}

interface Props {
  estimate: CurrentEstimateResponse | null;
  loading: boolean;
}

export function CurrentMonthSummary({ estimate, loading }: Props) {
  if (loading) {
    return (
      <div className="grid gap-4 md:grid-cols-3">
        {[1, 2, 3].map((i) => (
          <Card key={i}>
            <CardContent className="p-6">
              <div className="h-20 animate-pulse rounded bg-gray-200" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  if (!estimate) return null;

  const cards = [
    {
      title: "Mantenimiento",
      value: formatEur(estimate.maintenance_amount_eur),
      description: "Hosting, soporte, actualizaciones",
      icon: Wrench,
      color: "text-blue-600",
      bg: "bg-blue-50",
    },
    {
      title: "Consumo IA",
      value: formatEur(estimate.token_amount_eur),
      description: `${estimate.input_tokens.toLocaleString("es-ES")} entrada · ${estimate.output_tokens.toLocaleString("es-ES")} salida`,
      icon: Bot,
      color: "text-purple-600",
      bg: "bg-purple-50",
    },
  ];

  return (
    <div>
      <p className="mb-3 text-sm text-muted-foreground">
        Estimación para {estimate.period_label} ·{" "}
        {estimate.total_requests.toLocaleString("es-ES")} peticiones LLM
      </p>
      <div className="grid gap-4 md:grid-cols-3">
        {cards.map((card) => (
          <Card key={card.title}>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-muted-foreground">
                    {card.title}
                  </p>
                  <p className="mt-1 text-2xl font-bold">{card.value}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {card.description}
                  </p>
                </div>
                <div className={`rounded-lg p-3 ${card.bg}`}>
                  <card.icon className={`h-5 w-5 ${card.color}`} />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}

        {/* IVA breakdown + Total estimado */}
        <Card className="border-green-200 bg-green-50/30">
          <CardContent className="p-6">
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <p className="text-sm font-medium text-muted-foreground">
                  Total estimado
                </p>
                <p className="mt-1 text-2xl font-bold text-green-700">
                  {formatEurFixed(estimate.gross_amount_eur)}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Se facturará el {estimate.next_invoice_date}
                </p>
                <div className="mt-3 space-y-1 border-t border-green-200 pt-3">
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>Base imponible</span>
                    <span>{formatEurFixed(estimate.subtotal_eur)}</span>
                  </div>
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>IVA (21%)</span>
                    <span>{formatEurFixed(estimate.tax_amount_eur)}</span>
                  </div>
                </div>
              </div>
              <div className="rounded-lg bg-green-100 p-3">
                <Receipt className="h-5 w-5 text-green-600" />
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
