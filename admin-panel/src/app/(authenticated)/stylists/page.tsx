"use client";

import { Header } from "@/components/layout/header";
import { Card, CardContent } from "@/components/ui/card";

export default function StylistsPage() {
  return (
    <div className="flex flex-col">
      <Header
        title="Estilistas"
        description="Gestion de estilistas del salon"
      />

      <div className="flex-1 p-6">
        <Card>
          <CardContent className="flex h-[400px] items-center justify-center">
            <div className="text-center text-muted-foreground">
              <p className="text-lg font-medium">Lista de Estilistas (Fase 3)</p>
              <p className="text-sm mt-2">
                Gestion de perfiles, calendarios de Google vinculados
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
