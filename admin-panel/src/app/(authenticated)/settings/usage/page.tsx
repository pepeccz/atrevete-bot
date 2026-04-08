"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type {
  TokenUsage,
  CurrentMonthUsage,
  TokenPricing,
  TokenUsageList,
} from "@/lib/types";
import { Header } from "@/components/layout/header";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import {
  Coins,
  TrendingUp,
  MessageSquare,
  ArrowUpRight,
  ArrowDownRight,
  Info,
} from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// Month names in Spanish
const MONTH_NAMES = [
  "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
];

function formatNumber(num: number): string {
  if (num >= 1_000_000) {
    return (num / 1_000_000).toFixed(2) + "M";
  }
  if (num >= 1_000) {
    return (num / 1_000).toFixed(1) + "K";
  }
  return num.toLocaleString("es-ES");
}

function formatEur(num: number): string {
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(num);
}

export default function UsagePage() {
  const [loading, setLoading] = useState(true);
  const [currentUsage, setCurrentUsage] = useState<CurrentMonthUsage | null>(null);
  const [history, setHistory] = useState<TokenUsage[]>([]);
  const [pricing, setPricing] = useState<TokenPricing | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      setLoading(true);
      setError(null);
      try {
        const [currentData, historyData, pricingData] = await Promise.all([
          api.getCurrentMonthTokenUsage(),
          api.getTokenUsage(),
          api.getTokenPricing(),
        ]);
        setCurrentUsage(currentData);
        setHistory(historyData.items);
        setPricing(pricingData);
      } catch (err) {
        console.error("Failed to fetch token usage:", err);
        setError("Error al cargar los datos de consumo");
      } finally {
        setLoading(false);
      }
    }

    fetchData();
  }, []);

  if (loading) {
    return (
      <div className="flex flex-col">
        <Header
          title="Consumo de Tokens"
          description="Seguimiento del consumo de tokens del modelo de IA"
        />
        <div className="flex-1 p-4 md:p-6 space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <Card key={i}>
                <CardHeader className="pb-2">
                  <div className="h-4 w-24 bg-muted animate-pulse rounded" />
                </CardHeader>
                <CardContent>
                  <div className="h-8 w-32 bg-muted animate-pulse rounded" />
                </CardContent>
              </Card>
            ))}
          </div>
          <Card>
            <CardHeader>
              <div className="h-6 w-48 bg-muted animate-pulse rounded" />
            </CardHeader>
            <CardContent>
              <div className="h-64 w-full bg-muted animate-pulse rounded" />
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col">
        <Header
          title="Consumo de Tokens"
          description="Seguimiento del consumo de tokens del modelo de IA"
        />
        <div className="flex-1 p-4 md:p-6">
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-12">
              <p className="text-destructive">{error}</p>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  // Calculate previous month comparison
  const previousMonth = history.length > 1 ? history[1] : null;
  const costChange = previousMonth
    ? (currentUsage?.cost_total_eur ?? 0) - previousMonth.cost_total_eur
    : 0;
  const costChangePercent =
    previousMonth && previousMonth.cost_total_eur > 0
      ? (costChange / previousMonth.cost_total_eur) * 100
      : 0;

  return (
    <div className="flex flex-col">
      <Header
        title="Consumo de Tokens"
        description="Seguimiento del consumo de tokens del modelo de IA"
      />

      <div className="flex-1 p-4 md:p-6 space-y-6">
        {/* Current Month Summary Cards */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {/* Total Cost */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Coste Total
              </CardTitle>
              <Coins className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {formatEur(currentUsage?.cost_total_eur ?? 0)}
              </div>
              {previousMonth && (
                <p
                  className={`text-xs flex items-center gap-1 ${
                    costChange >= 0 ? "text-orange-500" : "text-green-500"
                  }`}
                >
                  {costChange >= 0 ? (
                    <ArrowUpRight className="h-3 w-3" />
                  ) : (
                    <ArrowDownRight className="h-3 w-3" />
                  )}
                  {costChangePercent >= 0 ? "+" : ""}
                  {costChangePercent.toFixed(1)}% vs mes anterior
                </p>
              )}
            </CardContent>
          </Card>

          {/* Total Tokens */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Tokens Totales
              </CardTitle>
              <TrendingUp className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {formatNumber(currentUsage?.total_tokens ?? 0)}
              </div>
              <p className="text-xs text-muted-foreground">
                Input: {formatNumber(currentUsage?.input_tokens ?? 0)} | Output:{" "}
                {formatNumber(currentUsage?.output_tokens ?? 0)}
              </p>
            </CardContent>
          </Card>

          {/* Requests */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Peticiones LLM
              </CardTitle>
              <MessageSquare className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {formatNumber(currentUsage?.total_requests ?? 0)}
              </div>
              <p className="text-xs text-muted-foreground">
                {MONTH_NAMES[(currentUsage?.month ?? 1) - 1]} {currentUsage?.year}
              </p>
            </CardContent>
          </Card>

          {/* Pricing Info */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Precios Configurados
              </CardTitle>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger>
                    <Info className="h-4 w-4 text-muted-foreground" />
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>Precios por millon de tokens (configurados en .env)</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </CardHeader>
            <CardContent>
              <div className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Input:</span>
                  <span className="font-medium">
                    {formatEur(pricing?.input_price_per_million ?? 0)}/M
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Output:</span>
                  <span className="font-medium">
                    {formatEur(pricing?.output_price_per_million ?? 0)}/M
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Cost Breakdown for Current Month */}
        <Card>
          <CardHeader>
            <CardTitle>
              Desglose de Costes - {MONTH_NAMES[(currentUsage?.month ?? 1) - 1]}{" "}
              {currentUsage?.year}
            </CardTitle>
            <CardDescription>Detalle del consumo del mes actual</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-muted/50 rounded-lg p-4">
                <div className="text-sm text-muted-foreground mb-1">Coste Input</div>
                <div className="text-xl font-semibold">
                  {formatEur(currentUsage?.cost_input_eur ?? 0)}
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  {formatNumber(currentUsage?.input_tokens ?? 0)} tokens
                </div>
              </div>
              <div className="bg-muted/50 rounded-lg p-4">
                <div className="text-sm text-muted-foreground mb-1">Coste Output</div>
                <div className="text-xl font-semibold">
                  {formatEur(currentUsage?.cost_output_eur ?? 0)}
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  {formatNumber(currentUsage?.output_tokens ?? 0)} tokens
                </div>
              </div>
              <div className="bg-primary/10 rounded-lg p-4">
                <div className="text-sm text-muted-foreground mb-1">Total</div>
                <div className="text-xl font-semibold text-primary">
                  {formatEur(currentUsage?.cost_total_eur ?? 0)}
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  {formatNumber(currentUsage?.total_tokens ?? 0)} tokens totales
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Historical Data Table */}
        <Card>
          <CardHeader>
            <CardTitle>Historial de Consumo</CardTitle>
            <CardDescription>
              Ultimos 12 meses de consumo de tokens
            </CardDescription>
          </CardHeader>
          <CardContent>
            {history.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                No hay datos de consumo registrados
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Periodo</TableHead>
                    <TableHead className="text-right">Input Tokens</TableHead>
                    <TableHead className="text-right">Output Tokens</TableHead>
                    <TableHead className="text-right">Total Tokens</TableHead>
                    <TableHead className="text-right">Peticiones</TableHead>
                    <TableHead className="text-right">Coste</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {history.map((usage, index) => {
                    const isCurrentMonth = index === 0;
                    return (
                      <TableRow key={usage.id}>
                        <TableCell className="font-medium">
                          {MONTH_NAMES[usage.month - 1]} {usage.year}
                          {isCurrentMonth && (
                            <Badge variant="secondary" className="ml-2">
                              Actual
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          {formatNumber(usage.input_tokens)}
                        </TableCell>
                        <TableCell className="text-right">
                          {formatNumber(usage.output_tokens)}
                        </TableCell>
                        <TableCell className="text-right font-medium">
                          {formatNumber(usage.total_tokens)}
                        </TableCell>
                        <TableCell className="text-right">
                          {formatNumber(usage.total_requests)}
                        </TableCell>
                        <TableCell className="text-right font-medium">
                          {formatEur(usage.cost_total_eur)}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
