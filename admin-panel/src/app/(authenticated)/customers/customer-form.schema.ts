import { z } from "zod";

export const CustomerFormSchema = z.object({
  phone: z
    .string()
    .min(1, "El teléfono es requerido")
    .regex(/^\+?[\d\s\-]{7,15}$/, "Ingresá un número de teléfono válido"),
  first_name: z.string().min(1, "El nombre es requerido"),
  last_name: z.string().optional(),
  notes: z.string().optional(),
});

export type CustomerFormValues = z.infer<typeof CustomerFormSchema>;
