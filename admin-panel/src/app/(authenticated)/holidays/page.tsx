"use client";

import { useState, useEffect, useCallback } from "react";
import { Calendar, Plus, Trash2, CalendarX } from "lucide-react";
import { Header } from "@/components/layout/header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import api from "@/lib/api";
import type { Holiday } from "@/lib/types";

export default function HolidaysPage() {
  const [holidays, setHolidays] = useState<Holiday[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedYear, setSelectedYear] = useState<number>(
    new Date().getFullYear()
  );

  // Create holiday dialog state
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);
  const [newHoliday, setNewHoliday] = useState({
    date: "",
    name: "",
  });

  // Delete holiday dialog state
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [holidayToDelete, setHolidayToDelete] = useState<Holiday | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  // Load holidays
  const loadHolidays = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getHolidays(selectedYear);
      setHolidays(res.items.sort((a, b) => a.date.localeCompare(b.date)));
    } catch (error) {
      toast.error("Error al cargar los festivos");
      console.error(error);
    } finally {
      setLoading(false);
    }
  }, [selectedYear]);

  useEffect(() => {
    loadHolidays();
  }, [loadHolidays]);

  // Create holiday handler
  const handleCreate = async () => {
    if (!newHoliday.date || !newHoliday.name.trim()) {
      toast.error("Por favor completa todos los campos");
      return;
    }

    setCreateLoading(true);
    try {
      await api.createHoliday({
        date: newHoliday.date,
        name: newHoliday.name.trim(),
        is_all_day: true,
      });
      toast.success("Festivo creado exitosamente");
      setCreateDialogOpen(false);
      setNewHoliday({ date: "", name: "" });
      await loadHolidays();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Error al crear el festivo"
      );
      console.error(error);
    } finally {
      setCreateLoading(false);
    }
  };

  // Delete holiday handler
  const handleDelete = async () => {
    if (!holidayToDelete) return;

    setDeleteLoading(true);
    try {
      await api.deleteHoliday(holidayToDelete.id);
      toast.success("Festivo eliminado exitosamente");
      setDeleteDialogOpen(false);
      setHolidayToDelete(null);
      await loadHolidays();
    } catch (error) {
      toast.error("Error al eliminar el festivo");
      console.error(error);
    } finally {
      setDeleteLoading(false);
    }
  };

  // Format date for display
  const formatDate = (dateString: string): string => {
    const date = new Date(dateString + "T00:00:00");
    return date.toLocaleDateString("es-ES", {
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  };

  // Generate year options (current year ± 2 years)
  const currentYear = new Date().getFullYear();
  const yearOptions = [
    currentYear - 2,
    currentYear - 1,
    currentYear,
    currentYear + 1,
    currentYear + 2,
  ];

  return (
    <div className="flex flex-col">
      <Header
        title="Festivos"
        description="Gestiona los días festivos y cierres especiales del salón"
      />

      <div className="flex-1 p-6">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <CalendarX className="h-5 w-5 text-red-500" />
                Días Festivos
              </CardTitle>
              <div className="flex items-center gap-3">
                <Select
                  value={selectedYear.toString()}
                  onValueChange={(value) => setSelectedYear(parseInt(value))}
                >
                  <SelectTrigger className="w-32">
                    <SelectValue placeholder="Año" />
                  </SelectTrigger>
                  <SelectContent>
                    {yearOptions.map((year) => (
                      <SelectItem key={year} value={year.toString()}>
                        {year}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button onClick={() => setCreateDialogOpen(true)}>
                  <Plus className="mr-2 h-4 w-4" />
                  Agregar Festivo
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
                <span className="ml-2">Cargando festivos...</span>
              </div>
            ) : holidays.length === 0 ? (
              <div className="text-center py-12">
                <CalendarX className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
                <p className="text-muted-foreground">
                  No hay festivos configurados para {selectedYear}
                </p>
                <Button
                  variant="outline"
                  className="mt-4"
                  onClick={() => setCreateDialogOpen(true)}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  Agregar el primer festivo
                </Button>
              </div>
            ) : (
              <div className="space-y-2">
                {holidays.map((holiday) => (
                  <div
                    key={holiday.id}
                    className="flex items-center justify-between p-4 border rounded-lg hover:bg-accent/50 transition-colors"
                  >
                    <div className="flex items-center gap-4">
                      <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-red-100 dark:bg-red-900/20">
                        <Calendar className="h-6 w-6 text-red-600 dark:text-red-400" />
                      </div>
                      <div>
                        <p className="font-medium">{holiday.name}</p>
                        <p className="text-sm text-muted-foreground">
                          {formatDate(holiday.date)}
                        </p>
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => {
                        setHolidayToDelete(holiday);
                        setDeleteDialogOpen(true);
                      }}
                      className="text-destructive hover:text-destructive hover:bg-destructive/10"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Create Holiday Dialog */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Agregar Festivo</DialogTitle>
            <DialogDescription>
              Configura un día festivo donde el salón permanecerá cerrado
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="holiday-date">Fecha</Label>
              <Input
                id="holiday-date"
                type="date"
                value={newHoliday.date}
                onChange={(e) =>
                  setNewHoliday((prev) => ({ ...prev, date: e.target.value }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="holiday-name">Nombre del Festivo</Label>
              <Input
                id="holiday-name"
                placeholder="Ej: Navidad, Año Nuevo, etc."
                value={newHoliday.name}
                onChange={(e) =>
                  setNewHoliday((prev) => ({ ...prev, name: e.target.value }))
                }
                maxLength={200}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setCreateDialogOpen(false);
                setNewHoliday({ date: "", name: "" });
              }}
            >
              Cancelar
            </Button>
            <Button onClick={handleCreate} disabled={createLoading}>
              {createLoading ? "Creando..." : "Crear Festivo"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Holiday Confirmation Dialog */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Eliminar festivo?</AlertDialogTitle>
            <AlertDialogDescription>
              ¿Estás seguro de que deseas eliminar el festivo &quot;
              {holidayToDelete?.name}&quot;? Esta acción no se puede deshacer.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={deleteLoading}
              className="bg-destructive hover:bg-destructive/90"
            >
              {deleteLoading ? "Eliminando..." : "Eliminar"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
