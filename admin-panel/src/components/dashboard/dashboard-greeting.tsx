import { format } from "date-fns";
import { es } from "date-fns/locale";

interface DashboardGreetingProps {
  firstName?: string;
  appointmentsToday: number;
  pendingEscalations: number;
}

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 13) return "Buenos días";
  if (hour < 20) return "Buenas tardes";
  return "Buenas noches";
}

export function DashboardGreeting({
  firstName,
  appointmentsToday,
  pendingEscalations,
}: DashboardGreetingProps) {
  const greeting = getGreeting();
  const name = firstName ? `, ${firstName}` : "";
  const today = format(new Date(), "EEEE, d 'de' MMMM", { locale: es });
  // Capitalize day name
  const todayLabel = today.charAt(0).toUpperCase() + today.slice(1);

  const summaryParts: string[] = [];
  summaryParts.push(`${appointmentsToday} ${appointmentsToday === 1 ? "cita" : "citas"} hoy`);
  if (pendingEscalations > 0) {
    summaryParts.push(
      `${pendingEscalations} ${pendingEscalations === 1 ? "escalación pendiente" : "escalaciones pendientes"}`
    );
  }

  return (
    <div>
      <h1 className="text-[22px] font-bold leading-tight text-ink tracking-[-0.01em]">
        {greeting}{name}
      </h1>
      <p className="mt-[2px] text-[13px] text-ink-mute">
        {todayLabel} · {summaryParts.join(" · ")}
      </p>
    </div>
  );
}
