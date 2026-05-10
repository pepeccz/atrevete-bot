import { Coffee, Plane, Briefcase, Lock, Heart, type LucideIcon } from "lucide-react";

export interface EventTypeMeta {
  value: string;
  label: string;
  Icon: LucideIcon;
}

export const EVENT_TYPES: EventTypeMeta[] = [
  { value: "break", label: "Descanso", Icon: Coffee },
  { value: "vacation", label: "Vacaciones", Icon: Plane },
  { value: "meeting", label: "Reunión", Icon: Briefcase },
  { value: "general", label: "Bloqueo general", Icon: Lock },
  { value: "personal", label: "Asunto Propio", Icon: Heart },
];

const META_BY_VALUE = new Map(EVENT_TYPES.map((t) => [t.value, t]));

export function getEventTypeMeta(value: string): EventTypeMeta {
  return (
    META_BY_VALUE.get(value) ?? { value, label: value, Icon: Lock }
  );
}
