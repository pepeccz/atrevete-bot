"use client";

import { Header } from "@/components/layout/header";
import { Card, CardContent } from "@/components/ui/card";

export default function BusinessHoursPage() {
  return (
    <div className="flex flex-col">
      <Header
        title="Horarios"
        description="Configuracion de horarios de apertura"
      />

      <div className="flex-1 p-6">
        <Card>
          <CardContent className="flex h-[400px] items-center justify-center">
            <div className="text-center text-muted-foreground">
              <p className="text-lg font-medium">Horarios de Apertura (Fase 3)</p>
              <p className="text-sm mt-2">
                Configurar horarios por dia de la semana
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
