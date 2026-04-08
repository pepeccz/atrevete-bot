import type { Customer, Service } from "@/lib/types";

export interface WizardSlot {
  time: string;
  end_time: string;
  full_datetime: string;
  stylist_id: string;
  stylist_name: string;
  date: string;
}

export interface WizardState {
  step: 1 | 2 | 3 | 4;
  customer: Customer | null;
  selectedServices: Service[];
  startDate: string;
  endDate: string;
  selectedSlot: WizardSlot | null;
  firstName: string;
  lastName: string;
  notes: string;
  sendNotification: boolean;
}
