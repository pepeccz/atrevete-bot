import { z } from "zod";

export const StylistFormSchema = z.object({
  name: z.string().min(1, "El nombre del estilista es requerido"),
  category: z.enum(["HAIRDRESSING", "AESTHETICS", "BOTH"], {
    errorMap: () => ({ message: "Seleccioná una categoría válida" }),
  }),
  google_calendar_id: z.string().nullable().optional(),
  is_active: z.boolean().default(true),
  color: z.string().nullable().optional(),
});

export type StylistFormValues = z.infer<typeof StylistFormSchema>;
