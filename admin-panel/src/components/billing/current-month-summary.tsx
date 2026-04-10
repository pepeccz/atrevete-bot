import { Card, CardContent } from "@/components/ui/card";
import { Wrench, Bot, Receipt } from "lucide-react";
import type { CurrentEstimateResponse } from "@/lib/types";

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
    {
      title: "Total Estimado",
      value: formatEur(estimate.total_amount_eur),
      description: `Se facturará el ${estimate.next_invoice_date}`,
      icon: Receipt,
      color: "text-green-600",
      bg: "bg-green-50",
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
      </div>
    </div>
  );
}
