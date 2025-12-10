"use client";

import { Header } from "@/components/layout/header";
import { Card, CardContent } from "@/components/ui/card";

export default function ConversationsPage() {
  return (
    <div className="flex flex-col">
      <Header
        title="Conversaciones"
        description="Historial de conversaciones con el bot"
      />

      <div className="flex-1 p-6">
        <Card>
          <CardContent className="flex h-[400px] items-center justify-center">
            <div className="text-center text-muted-foreground">
              <p className="text-lg font-medium">Historial de Chats (Fase 2)</p>
              <p className="text-sm mt-2">
                Ver conversaciones archivadas con clientes
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
