"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Check, X, AlertTriangle, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

interface PendingAppointment {
  id: string;
  first_name: string;
  last_name: string | null;
  start_time: string;
  duration_minutes: number;
  status: string;
  stylist?: { id: string; name: string } | null;
  services?: { id: string; name: string }[];
}

export function PendingActionsCard() {
  const [appointments, setAppointments] = useState<PendingAppointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState<string | null>(null);

  const fetchPendingActions = async () => {
    try {
      const data = await api.getPendingActions();
      setAppointments(data.items);
    } catch (error) {
      console.error("Error fetching pending actions:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPendingActions();
  }, []);

  const handleMarkStatus = async (id: string, status: "completed" | "no_show") => {
    setUpdating(id);
    try {
      await api.update("appointments", id, { status });
      toast.success(
        status === "completed"
          ? "Cita marcada como completada"
          : "Cita marcada como no asistida"
      );
      // Remove from list
      setAppointments((prev) => prev.filter((a) => a.id !== id));
    } catch (error) {
      toast.error("Error al actualizar la cita");
      console.error("Error updating appointment:", error);
    } finally {
      setUpdating(null);
    }
  };

  if (loading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center p-6">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (appointments.length === 0) {
    return null; // No mostrar si no hay acciones pendientes
  }

  return (
    <Card className="border-orange-200 bg-orange-50">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-orange-700">
          <AlertTriangle className="h-5 w-5" />
          Acciones Pendientes ({appointments.length})
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-orange-600 mb-4">
          Estas citas ya pasaron y requieren que indiques si se completaron o si el cliente no asistio.
        </p>
        <div className="space-y-3">
          {appointments.map((appt) => (
            <div
              key={appt.id}
              className="flex items-center justify-between p-3 bg-white rounded-lg border"
            >
              <div className="flex-1 min-w-0">
                <div className="font-medium truncate">
                  {appt.first_name}
                  {appt.last_name && ` ${appt.last_name}`}
                </div>
                <div className="text-sm text-muted-foreground">
                  {new Date(appt.start_time).toLocaleDateString("es-ES", {
                    weekday: "short",
                    day: "numeric",
                    month: "short",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                  {appt.stylist && ` - ${appt.stylist.name}`}
                </div>
                {appt.services && appt.services.length > 0 && (
                  <div className="text-xs text-muted-foreground mt-1 truncate">
                    {appt.services.map((s) => s.name).join(", ")}
                  </div>
                )}
              </div>
              <div className="flex gap-2 ml-4">
                <Button
                  size="sm"
                  variant="outline"
                  className="text-green-600 hover:bg-green-50 hover:text-green-700 hover:border-green-300"
                  onClick={() => handleMarkStatus(appt.id, "completed")}
                  disabled={updating === appt.id}
                >
                  {updating === appt.id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <>
                      <Check className="h-4 w-4 mr-1" />
                      Completada
                    </>
                  )}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="text-orange-600 hover:bg-orange-50 hover:text-orange-700 hover:border-orange-300"
                  onClick={() => handleMarkStatus(appt.id, "no_show")}
                  disabled={updating === appt.id}
                >
                  {updating === appt.id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <>
                      <X className="h-4 w-4 mr-1" />
                      No asistio
                    </>
                  )}
                </Button>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
