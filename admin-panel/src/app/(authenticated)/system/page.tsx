"use client";

import { useEffect, useState } from "react";
import { Header } from "@/components/layout/header";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { CheckCircle, XCircle, Loader2 } from "lucide-react";
import api from "@/lib/api";

interface HealthStatus {
  status: string;
  redis: string;
  postgres: string;
}

function StatusIndicator({ status }: { status: string }) {
  if (status === "connected" || status === "healthy") {
    return <CheckCircle className="h-5 w-5 text-green-500" />;
  }
  if (status === "disconnected" || status === "degraded") {
    return <XCircle className="h-5 w-5 text-red-500" />;
  }
  return <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />;
}

export default function SystemPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchHealth() {
      try {
        const data = await api.health();
        setHealth(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error conectando");
      } finally {
        setIsLoading(false);
      }
    }

    fetchHealth();
    // Refresh every 30 seconds
    const interval = setInterval(fetchHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex flex-col">
      <Header
        title="Sistema"
        description="Estado de los servicios de infraestructura"
      />

      <div className="flex-1 space-y-6 p-6">
        {/* Health Status */}
        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                Estado General
              </CardTitle>
              {isLoading ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <StatusIndicator status={health?.status || "unknown"} />
              )}
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold capitalize">
                {isLoading ? "..." : health?.status || "Desconocido"}
              </div>
              <p className="text-xs text-muted-foreground">
                Estado del API backend
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">PostgreSQL</CardTitle>
              {isLoading ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <StatusIndicator status={health?.postgres || "unknown"} />
              )}
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold capitalize">
                {isLoading ? "..." : health?.postgres || "Desconocido"}
              </div>
              <p className="text-xs text-muted-foreground">
                Base de datos principal
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Redis</CardTitle>
              {isLoading ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <StatusIndicator status={health?.redis || "unknown"} />
              )}
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold capitalize">
                {isLoading ? "..." : health?.redis || "Desconocido"}
              </div>
              <p className="text-xs text-muted-foreground">
                Cache y checkpointing
              </p>
            </CardContent>
          </Card>
        </div>

        {error && (
          <Card className="border-amber-200 bg-amber-50">
            <CardContent className="pt-6">
              <p className="text-sm text-amber-800">
                <strong>Error:</strong> {error}
              </p>
            </CardContent>
          </Card>
        )}

        {/* Service Info */}
        <Card>
          <CardHeader>
            <CardTitle>Servicios del Sistema</CardTitle>
            <CardDescription>
              Componentes de la infraestructura
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex items-center justify-between border-b pb-2">
                <div>
                  <p className="font-medium">API (FastAPI)</p>
                  <p className="text-sm text-muted-foreground">
                    Puerto 8000 - Webhooks y endpoints REST
                  </p>
                </div>
                <span className="text-sm text-green-600">Activo</span>
              </div>

              <div className="flex items-center justify-between border-b pb-2">
                <div>
                  <p className="font-medium">Agent (LangGraph)</p>
                  <p className="text-sm text-muted-foreground">
                    Orquestador de conversaciones con IA
                  </p>
                </div>
                <span className="text-sm text-muted-foreground">
                  Ver Docker logs
                </span>
              </div>

              <div className="flex items-center justify-between border-b pb-2">
                <div>
                  <p className="font-medium">Django Admin (Legacy)</p>
                  <p className="text-sm text-muted-foreground">
                    Puerto 8001 - Panel de administracion anterior
                  </p>
                </div>
                <span className="text-sm text-amber-600">Deprecando</span>
              </div>

              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium">Admin Panel (NextJS)</p>
                  <p className="text-sm text-muted-foreground">
                    Puerto 3000 - Este panel
                  </p>
                </div>
                <span className="text-sm text-green-600">Activo</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
