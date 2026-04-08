import { z } from "zod";

// Step 1: Customer selection
export const CustomerStepSchema = z.object({
  customer_id: z.string().min(1, "Debés seleccionar un cliente"),
});

// Step 1b: Create new customer inline form
export const NewCustomerSchema = z.object({
  phone: z
    .string()
    .min(1, "El teléfono es requerido")
    .regex(/^\+?[\d\s\-]{7,15}$/, "Ingresá un número de teléfono válido"),
  first_name: z.string().min(1, "El nombre es requerido"),
  last_name: z.string().optional(),
});

// Step 2: Service selection
export const ServiceStepSchema = z.object({
  service_ids: z
    .array(z.string())
    .min(1, "Debés seleccionar al menos un servicio"),
});

// Step 3: Slot selection
export const SlotStepSchema = z.object({
  slot: z
    .object({
      time: z.string(),
      end_time: z.string(),
      full_datetime: z.string(),
      stylist_id: z.string(),
      stylist_name: z.string(),
      date: z.string(),
    })
    .nullable()
    .refine((val) => val !== null, { message: "Debés seleccionar un horario" }),
});

// Step 4: Confirm — appointment name + optional notes + notification
export const ConfirmStepSchema = z.object({
  first_name: z.string().min(1, "El nombre es requerido"),
  last_name: z.string().optional(),
  notes: z.string().optional(),
  send_notification: z.boolean().default(true),
});

export type CustomerStepValues = z.infer<typeof CustomerStepSchema>;
export type NewCustomerValues = z.infer<typeof NewCustomerSchema>;
export type ServiceStepValues = z.infer<typeof ServiceStepSchema>;
export type SlotStepValues = z.infer<typeof SlotStepSchema>;
export type ConfirmStepValues = z.infer<typeof ConfirmStepSchema>;
