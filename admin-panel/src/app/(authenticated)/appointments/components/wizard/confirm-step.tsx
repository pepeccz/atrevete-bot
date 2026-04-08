"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { format } from "date-fns";
import { es } from "date-fns/locale";
import { User, Scissors, Calendar } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import type { Customer, Service } from "@/lib/types";
import type { WizardSlot } from "./types";
import { ConfirmStepSchema, type ConfirmStepValues } from "./schemas";

interface ConfirmStepProps {
  customer: Customer;
  services: Service[];
  slot: WizardSlot;
  firstName: string;
  lastName: string;
  notes: string;
  sendNotification: boolean;
  onFirstNameChange: (firstName: string) => void;
  onLastNameChange: (lastName: string) => void;
  onNotesChange: (notes: string) => void;
  onSendNotificationChange: (sendNotification: boolean) => void;
  /** Called by AppointmentWizard to retrieve validated values on submit */
  onFormReady?: (getValues: () => ConfirmStepValues | null) => void;
}

export function ConfirmStep({
  customer,
  services,
  slot,
  firstName,
  lastName,
  notes,
  sendNotification,
  onFirstNameChange,
  onLastNameChange,
  onNotesChange,
  onSendNotificationChange,
  onFormReady,
}: ConfirmStepProps) {
  const totalDuration = services.reduce(
    (sum, s) => sum + s.duration_minutes,
    0
  );

  const form = useForm<ConfirmStepValues>({
    resolver: zodResolver(ConfirmStepSchema),
    defaultValues: {
      first_name: firstName,
      last_name: lastName,
      notes: notes,
      send_notification: sendNotification,
    },
  });

  // Sync parent state → form when props change (e.g. after customer selection)
  useEffect(() => {
    form.setValue("first_name", firstName);
    form.setValue("last_name", lastName);
    form.setValue("notes", notes);
    form.setValue("send_notification", sendNotification);
  }, [firstName, lastName, notes, sendNotification, form]);

  // Expose getValues to parent so wizard can validate before submit
  useEffect(() => {
    if (onFormReady) {
      onFormReady(() => {
        const values = form.getValues();
        const result = ConfirmStepSchema.safeParse(values);
        if (!result.success) {
          // Trigger validation UI
          form.trigger();
          return null;
        }
        return result.data;
      });
    }
  }, [form, onFormReady]);

  return (
    <div className="space-y-4">
      <div className="p-4 bg-muted rounded-lg space-y-3">
        <div className="flex items-start gap-3">
          <User className="h-5 w-5 text-muted-foreground mt-0.5" />
          <div>
            <p className="text-sm text-muted-foreground">Cliente</p>
            <p className="font-medium">
              {customer.first_name} {customer.last_name || ""}
            </p>
            <p className="text-sm text-muted-foreground">{customer.phone}</p>
          </div>
        </div>

        <div className="flex items-start gap-3">
          <Scissors className="h-5 w-5 text-muted-foreground mt-0.5" />
          <div>
            <p className="text-sm text-muted-foreground">Servicios</p>
            <div className="flex flex-wrap gap-1 mt-1">
              {services.map((s) => (
                <Badge key={s.id} variant="secondary">
                  {s.name}
                </Badge>
              ))}
            </div>
            <p className="text-sm text-muted-foreground mt-1">
              Duración total: {totalDuration} min
            </p>
          </div>
        </div>

        <div className="flex items-start gap-3">
          <Calendar className="h-5 w-5 text-muted-foreground mt-0.5" />
          <div>
            <p className="text-sm text-muted-foreground">Fecha y hora</p>
            <p className="font-medium">
              {format(new Date(slot.full_datetime), "EEEE d 'de' MMMM, HH:mm", {
                locale: es,
              })}
            </p>
            <p className="text-sm text-muted-foreground">
              hasta {slot.end_time}
            </p>
          </div>
        </div>

        <div className="flex items-start gap-3">
          <User className="h-5 w-5 text-muted-foreground mt-0.5" />
          <div>
            <p className="text-sm text-muted-foreground">Estilista</p>
            <p className="font-medium">{slot.stylist_name}</p>
          </div>
        </div>
      </div>

      {/* Appointment Name Section — react-hook-form */}
      <Form {...form}>
        <div className="space-y-4 border-t pt-4">
          <div>
            <p className="text-sm font-medium">Nombre para la cita</p>
            <p className="text-xs text-muted-foreground">
              Por defecto el nombre del cliente. Modificá si la cita es para otra persona.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <FormField
              control={form.control}
              name="first_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Nombre *</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="Nombre"
                      {...field}
                      onChange={(e) => {
                        field.onChange(e);
                        onFirstNameChange(e.target.value);
                      }}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="last_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Apellidos</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="Apellidos (opcional)"
                      {...field}
                      onChange={(e) => {
                        field.onChange(e);
                        onLastNameChange(e.target.value);
                      }}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>

          <FormField
            control={form.control}
            name="notes"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Notas (opcional)</FormLabel>
                <FormControl>
                  <Textarea
                    placeholder="Notas adicionales para la cita..."
                    rows={3}
                    {...field}
                    onChange={(e) => {
                      field.onChange(e);
                      onNotesChange(e.target.value);
                    }}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="send_notification"
            render={({ field }) => (
              <FormItem className="flex items-center justify-between py-2">
                <FormLabel className="text-sm font-medium cursor-pointer">
                  Enviar notificación al cliente
                </FormLabel>
                <FormControl>
                  <Switch
                    checked={field.value}
                    onCheckedChange={(checked) => {
                      field.onChange(checked);
                      onSendNotificationChange(checked);
                    }}
                  />
                </FormControl>
              </FormItem>
            )}
          />
        </div>
      </Form>
    </div>
  );
}
