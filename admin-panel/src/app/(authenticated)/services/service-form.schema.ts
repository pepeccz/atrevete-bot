import { z } from "zod";

export const ServiceFormSchema = z.object({
  name: z.string().min(1, "El nombre es requerido"),
  category: z.enum(["HAIRDRESSING", "AESTHETICS", "BOTH"], {
    errorMap: () => ({ message: "Seleccioná una categoría válida" }),
  }),
  duration_minutes: z
    .number({ invalid_type_error: "La duración debe ser un número" })
    .min(5, "La duración mínima es 5 minutos")
    .max(480, "La duración máxima es 480 minutos"),
  description: z.string().optional(),
  is_active: z.boolean().default(true),
  audience: z.string().nullable().optional(),
});

export type ServiceFormValues = z.infer<typeof ServiceFormSchema>;
