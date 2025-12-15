"use client";

import { Clock, Activity, Users, Scissors, CalendarX, Settings2, Bell } from "lucide-react";
import Link from "next/link";
import { Header } from "@/components/layout/header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const configSections = [
  {
    title: "Centro de Notificaciones",
    description: "Historial completo, estadisticas y gestion de notificaciones",
    icon: Bell,
    href: "/settings/notifications",
    color: "bg-amber-500",
  },
  {
    title: "Horarios de Apertura",
    description: "Gestiona los horarios de apertura del salón por día de la semana",
    icon: Clock,
    href: "/business-hours",
    color: "bg-blue-500",
  },
  {
    title: "Estilistas",
    description: "Administra perfiles de estilistas, categorías y calendarios",
    icon: Users,
    href: "/stylists",
    color: "bg-purple-500",
  },
  {
    title: "Servicios",
    description: "Gestiona el catálogo de servicios ofrecidos",
    icon: Scissors,
    href: "/services",
    color: "bg-pink-500",
  },
  {
    title: "Festivos",
    description: "Configura días festivos y cierres especiales del salón",
    icon: CalendarX,
    href: "/holidays",
    color: "bg-red-500",
  },
  {
    title: "Estado del Sistema",
    description: "Monitorea la salud de Redis, PostgreSQL y servicios",
    icon: Activity,
    href: "/system",
    color: "bg-green-500",
  },
  {
    title: "Configuraci\u00f3n del Sistema",
    description: "Ajusta par\u00e1metros del agente, confirmaciones, cache y m\u00e1s",
    icon: Settings2,
    href: "/settings/system",
    color: "bg-orange-500",
  },
];

export default function SettingsPage() {
  return (
    <div className="flex flex-col">
      <Header
        title="Configuración del Salón"
        description="Gestiona todos los aspectos de configuración del salón"
      />

      <div className="flex-1 p-6">
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {configSections.map((section) => {
            const Icon = section.icon;
            return (
              <Card key={section.href}>
                <CardHeader>
                  <div className={`w-12 h-12 rounded-lg ${section.color} flex items-center justify-center mb-4`}>
                    <Icon className="h-6 w-6 text-white" />
                  </div>
                  <CardTitle>{section.title}</CardTitle>
                  <CardDescription>{section.description}</CardDescription>
                </CardHeader>
                <CardContent>
                  <Link href={section.href}>
                    <Button className="w-full">Configurar</Button>
                  </Link>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>
    </div>
  );
}
