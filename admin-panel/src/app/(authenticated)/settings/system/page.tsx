"use client";

import { useState, useEffect } from "react";
import { RefreshCw, Save, RotateCcw, AlertTriangle } from "lucide-react";
import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { toast } from "sonner";
import api from "@/lib/api";
import type { SystemSetting, SettingCategory, SystemServiceName } from "@/lib/types";

// Mapping from setting category to the worker service that needs restart
const CATEGORY_TO_WORKER: Partial<Record<SettingCategory, SystemServiceName>> = {
  confirmation: "confirmation-worker",
  gcal_sync: "gcal-sync-worker",
};

// Category display names and descriptions in Spanish
const CATEGORY_INFO: Record<SettingCategory, { name: string; description: string }> = {
  confirmation: {
    name: "Sistema de Confirmaciones",
    description: "Configuración de horarios y plantillas para confirmaciones y recordatorios de citas",
  },
  booking: {
    name: "Reglas de Reserva",
    description: "Parámetros que controlan cómo se pueden hacer las reservas",
  },
  llm: {
    name: "Modelo de Lenguaje (LLM)",
    description: "Configuración del modelo de IA y parámetros de generación",
  },
  rate_limiting: {
    name: "Límites de Velocidad",
    description: "Protección contra abuso y límites de API",
  },
  cache: {
    name: "Caché y Rendimiento",
    description: "TTL de caché y parámetros de optimización",
  },
  archival: {
    name: "Archivado",
    description: "Configuración de archivado de conversaciones",
  },
  gcal_sync: {
    name: "Sincronización Google Calendar",
    description: "Configuración de la sincronización bidireccional con Google Calendar",
  },
};

// Category order for display
const CATEGORY_ORDER: SettingCategory[] = [
  "confirmation",
  "booking",
  "llm",
  "rate_limiting",
  "cache",
  "archival",
  "gcal_sync",
];

interface SettingInputProps {
  setting: SystemSetting;
  value: string | number | boolean;
  onChange: (value: string | number | boolean) => void;
  disabled?: boolean;
}

function SettingInput({ setting, value, onChange, disabled }: SettingInputProps) {
  const { value_type, min_value, max_value, allowed_values } = setting;

  if (value_type === "boolean") {
    return (
      <Switch
        checked={value as boolean}
        onCheckedChange={onChange}
        disabled={disabled}
      />
    );
  }

  if (value_type === "enum" && allowed_values) {
    return (
      <Select
        value={String(value)}
        onValueChange={onChange}
        disabled={disabled}
      >
        <SelectTrigger className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {allowed_values.map((option) => (
            <SelectItem key={option} value={option}>
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  if (value_type === "int" || value_type === "float") {
    return (
      <Input
        type="number"
        value={value as number}
        onChange={(e) => {
          const val = value_type === "int"
            ? parseInt(e.target.value, 10)
            : parseFloat(e.target.value);
          if (!isNaN(val)) {
            onChange(val);
          }
        }}
        min={min_value ?? undefined}
        max={max_value ?? undefined}
        step={value_type === "float" ? 0.1 : 1}
        disabled={disabled}
        className="w-full"
      />
    );
  }

  // Default: string input
  return (
    <Input
      type="text"
      value={String(value)}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className="w-full"
    />
  );
}

export default function SystemSettingsPage() {
  const [settings, setSettings] = useState<Record<string, SystemSetting[]>>({});
  const [editedValues, setEditedValues] = useState<Record<string, string | number | boolean>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [restarting, setRestarting] = useState(false);
  const [clearingCache, setClearingCache] = useState(false);
  const [pendingRestartCategories, setPendingRestartCategories] = useState<Set<SettingCategory>>(new Set());

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      setLoading(true);
      const response = await api.getSystemSettings();
      setSettings(response.categories);
      // Initialize edited values with current values
      const initialValues: Record<string, string | number | boolean> = {};
      Object.values(response.categories).flat().forEach((setting) => {
        initialValues[setting.key] = setting.value;
      });
      setEditedValues(initialValues);
    } catch (error) {
      toast.error("No se pudieron cargar los ajustes del sistema");
    } finally {
      setLoading(false);
    }
  };

  const handleValueChange = (key: string, value: string | number | boolean) => {
    setEditedValues((prev) => ({ ...prev, [key]: value }));
  };

  const hasChanges = (key: string): boolean => {
    const original = Object.values(settings).flat().find((s) => s.key === key);
    if (!original) return false;
    return editedValues[key] !== original.value;
  };

  // Find the category a setting belongs to
  const findSettingCategory = (key: string): SettingCategory | null => {
    for (const [category, categorySettings] of Object.entries(settings)) {
      if (categorySettings.some((s) => s.key === key)) {
        return category as SettingCategory;
      }
    }
    return null;
  };

  const handleSave = async (setting: SystemSetting) => {
    if (!hasChanges(setting.key)) return;

    try {
      setSaving(setting.key);
      await api.updateSystemSetting(setting.key, editedValues[setting.key]);

      // Check if this setting requires restart and track the category
      if (setting.requires_restart) {
        const category = findSettingCategory(setting.key);
        if (category) {
          setPendingRestartCategories((prev) => new Set([...prev, category]));
        }
      }

      toast.success(`${setting.label} actualizado correctamente`);

      // Reload settings to get updated values
      await loadSettings();
    } catch (error) {
      toast.error(`No se pudo guardar: ${error instanceof Error ? error.message : "Error desconocido"}`);
    } finally {
      setSaving(null);
    }
  };

  const handleReset = async (setting: SystemSetting) => {
    try {
      setSaving(setting.key);
      await api.resetSystemSetting(setting.key);

      if (setting.requires_restart) {
        const category = findSettingCategory(setting.key);
        if (category) {
          setPendingRestartCategories((prev) => new Set([...prev, category]));
        }
      }

      toast.success(`${setting.label} restaurado al valor por defecto`);

      await loadSettings();
    } catch (error) {
      toast.error("No se pudo restaurar el valor");
    } finally {
      setSaving(null);
    }
  };

  // Get the list of workers that need to be restarted
  const getWorkersToRestart = (): SystemServiceName[] => {
    const workers = new Set<SystemServiceName>();
    for (const category of pendingRestartCategories) {
      const worker = CATEGORY_TO_WORKER[category];
      if (worker) {
        workers.add(worker);
      }
    }
    return Array.from(workers);
  };

  const handleRestartWorkers = async () => {
    const workers = getWorkersToRestart();
    if (workers.length === 0) return;

    try {
      setRestarting(true);
      const results: { worker: string; success: boolean; message: string }[] = [];

      // Restart all affected workers
      for (const worker of workers) {
        try {
          const result = await api.restartService(worker);
          results.push({ worker, success: result.success, message: result.message });
        } catch (error) {
          results.push({
            worker,
            success: false,
            message: error instanceof Error ? error.message : "Error desconocido",
          });
        }
      }

      // Check results
      const allSuccess = results.every((r) => r.success);
      const failedWorkers = results.filter((r) => !r.success);

      if (allSuccess) {
        setPendingRestartCategories(new Set());
        toast.success(
          workers.length === 1
            ? `Worker reiniciado correctamente`
            : `${workers.length} workers reiniciados correctamente`
        );
      } else {
        toast.error(
          `Error reiniciando: ${failedWorkers.map((r) => r.worker).join(", ")}`
        );
      }
    } catch (error) {
      toast.error("No se pudieron reiniciar los workers");
    } finally {
      setRestarting(false);
    }
  };

  const handleClearCache = async () => {
    try {
      setClearingCache(true);
      const result = await api.clearSystemCache();

      if (result.success) {
        toast.success(result.message);
        // Reload settings to show fresh data
        await loadSettings();
      } else {
        toast.error(result.message);
      }
    } catch (error) {
      toast.error(
        `Error al limpiar cache: ${error instanceof Error ? error.message : "Error desconocido"}`
      );
    } finally {
      setClearingCache(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col">
        <Header
          title="Configuración del Sistema"
          description="Cargando ajustes..."
        />
        <div className="flex-1 p-6 flex items-center justify-center">
          <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      <Header
        title="Configuración del Sistema"
        description="Ajusta los parámetros del bot, confirmaciones, caché y más"
        action={
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={handleClearCache}
              disabled={clearingCache || loading}
            >
              <RotateCcw className={`h-4 w-4 mr-2 ${clearingCache ? "animate-spin" : ""}`} />
              Refrescar Sistema
            </Button>
            <Button variant="outline" onClick={loadSettings} disabled={loading}>
              <RefreshCw className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`} />
              Recargar
            </Button>
            {pendingRestartCategories.size > 0 && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button variant="destructive" disabled={restarting}>
                    <AlertTriangle className="h-4 w-4 mr-2" />
                    Reiniciar Workers ({getWorkersToRestart().length})
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Reiniciar Workers</AlertDialogTitle>
                    <AlertDialogDescription asChild>
                      <div className="space-y-2">
                        <p>Algunos cambios requieren reiniciar los siguientes workers para aplicarse:</p>
                        <ul className="list-disc list-inside">
                          {getWorkersToRestart().map((worker) => (
                            <li key={worker} className="font-medium">{worker}</li>
                          ))}
                        </ul>
                        <p className="text-sm">Durante el reinicio (aprox. 30 segundos por worker) algunos servicios no estarán disponibles.</p>
                      </div>
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancelar</AlertDialogCancel>
                    <AlertDialogAction onClick={handleRestartWorkers}>
                      {restarting ? (
                        <>
                          <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                          Reiniciando...
                        </>
                      ) : (
                        "Reiniciar ahora"
                      )}
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
          </div>
        }
      />

      <div className="flex-1 p-6">
        <Accordion type="multiple" defaultValue={["confirmation"]} className="space-y-4">
          {CATEGORY_ORDER.map((category) => {
            const categorySettings = settings[category] || [];
            if (categorySettings.length === 0) return null;

            const info = CATEGORY_INFO[category];
            const hasRestartSettings = categorySettings.some((s) => s.requires_restart);

            return (
              <AccordionItem key={category} value={category} className="border rounded-lg">
                <AccordionTrigger className="px-6 hover:no-underline">
                  <div className="flex items-center gap-3">
                    <span className="font-semibold">{info.name}</span>
                    <Badge variant="secondary">{categorySettings.length}</Badge>
                    {hasRestartSettings && (
                      <Badge variant="outline" className="text-orange-600 border-orange-300">
                        Requiere reinicio
                      </Badge>
                    )}
                  </div>
                </AccordionTrigger>
                <AccordionContent className="px-6 pb-4">
                  <p className="text-sm text-muted-foreground mb-4">{info.description}</p>
                  <div className="space-y-6">
                    {categorySettings.map((setting) => (
                      <div key={setting.key} className="grid gap-2">
                        <div className="flex items-center justify-between">
                          <Label htmlFor={setting.key} className="font-medium">
                            {setting.label}
                            {setting.requires_restart && (
                              <Badge variant="outline" className="ml-2 text-xs text-orange-600 border-orange-300">
                                Reinicio
                              </Badge>
                            )}
                          </Label>
                          <div className="flex gap-2">
                            {hasChanges(setting.key) && (
                              <Button
                                size="sm"
                                onClick={() => handleSave(setting)}
                                disabled={saving === setting.key}
                              >
                                {saving === setting.key ? (
                                  <RefreshCw className="h-4 w-4 animate-spin" />
                                ) : (
                                  <Save className="h-4 w-4" />
                                )}
                              </Button>
                            )}
                            {editedValues[setting.key] !== setting.default_value && (
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => handleReset(setting)}
                                disabled={saving === setting.key}
                                title="Restaurar valor por defecto"
                              >
                                <RotateCcw className="h-4 w-4" />
                              </Button>
                            )}
                          </div>
                        </div>
                        {setting.description && (
                          <p className="text-xs text-muted-foreground">{setting.description}</p>
                        )}
                        <div className="flex items-center gap-4">
                          <div className="flex-1">
                            <SettingInput
                              setting={setting}
                              value={editedValues[setting.key]}
                              onChange={(value) => handleValueChange(setting.key, value)}
                              disabled={saving === setting.key}
                            />
                          </div>
                          {setting.min_value !== null && setting.max_value !== null && (
                            <span className="text-xs text-muted-foreground whitespace-nowrap">
                              {setting.min_value} - {setting.max_value}
                            </span>
                          )}
                        </div>
                        {setting.updated_at && (
                          <p className="text-xs text-muted-foreground">
                            Última modificación: {new Date(setting.updated_at).toLocaleString("es-ES")}
                            {setting.updated_by && ` por ${setting.updated_by}`}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </AccordionContent>
              </AccordionItem>
            );
          })}
        </Accordion>
      </div>
    </div>
  );
}
