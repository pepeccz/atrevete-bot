import { z } from "zod";

export const HolidayFormSchema = z.object({
  date: z.string().min(1, "La fecha es requerida"),
  name: z
    .string()
    .min(1, "El nombre del festivo es requerido")
    .max(200, "El nombre no puede superar 200 caracteres"),
});

export type HolidayFormValues = z.infer<typeof HolidayFormSchema>;
