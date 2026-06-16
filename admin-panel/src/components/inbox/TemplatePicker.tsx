"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, SendHorizonal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { FetchError } from "@/components/shared/fetch-error";
import api from "@/lib/api";
import type { InboxTemplateDef } from "@/lib/types";
import { toast } from "sonner";

interface TemplatePickerProps {
  conversationId: string;
  /** Called after the template is sent successfully. */
  onSent: () => void;
}

/**
 * Template picker for sending Meta-approved templates outside the 24h window.
 * Shows a disabled state with "Plantillas en aprobación" copy when no templates
 * are approved (R2 from proposal).
 *
 * FR-UI-3, SC-1.
 */
export function TemplatePicker({ conversationId, onSent }: TemplatePickerProps) {
  const [templates, setTemplates] = useState<InboxTemplateDef[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(true);
  const [fetchError, setFetchError] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<InboxTemplateDef | null>(null);
  const [params, setParams] = useState<Record<string, string>>({});
  const [sending, setSending] = useState(false);

  const fetchTemplates = useCallback(async () => {
    setLoadingTemplates(true);
    setFetchError(false);
    try {
      const res = await api.listTemplates();
      setTemplates(res.items);
    } catch {
      setFetchError(true);
      toast.error("No se pudieron cargar las plantillas");
    } finally {
      setLoadingTemplates(false);
    }
  }, []);

  useEffect(() => {
    fetchTemplates();
  }, [fetchTemplates]);

  const approvedTemplates = templates.filter((t) => t.status === "approved");
  const hasApproved = approvedTemplates.length > 0;

  const handleTemplateChange = (name: string) => {
    const tpl = approvedTemplates.find((t) => t.name === name) ?? null;
    setSelectedTemplate(tpl);
    setParams({});
  };

  const handleSend = async () => {
    if (!selectedTemplate) return;
    setSending(true);
    try {
      await api.sendTemplate(conversationId, selectedTemplate.name, params);
      toast.success("Plantilla enviada correctamente");
      setSelectedTemplate(null);
      setParams({});
      onSent();
    } catch {
      toast.error("Error al enviar la plantilla");
    } finally {
      setSending(false);
    }
  };

  const isValid =
    selectedTemplate !== null &&
    selectedTemplate.params.every((p) => (params[p.name] ?? "").trim().length > 0);

  if (loadingTemplates) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground p-3">
        <Loader2 className="h-4 w-4 animate-spin" />
        Cargando plantillas…
      </div>
    );
  }

  if (fetchError) {
    return <FetchError onRetry={fetchTemplates} />;
  }

  if (!hasApproved) {
    return (
      <div className="p-4 bg-muted rounded-lg text-center">
        <p className="text-sm text-muted-foreground font-medium">Plantillas en aprobación</p>
        <p className="text-xs text-muted-foreground mt-1">
          Las plantillas de Meta están pendientes de aprobación (24–72h). Vuelve más tarde.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3 p-3 border rounded-lg bg-muted/40">
      <div className="space-y-1">
        <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Plantilla
        </Label>
        <Select
          value={selectedTemplate?.name ?? ""}
          onValueChange={handleTemplateChange}
        >
          <SelectTrigger className="h-8 text-sm">
            <SelectValue placeholder="Selecciona una plantilla…" />
          </SelectTrigger>
          <SelectContent>
            {approvedTemplates.map((t) => (
              <SelectItem key={t.name} value={t.name}>
                {t.display_name ?? t.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {selectedTemplate && selectedTemplate.params.length > 0 && (
        <div className="space-y-2">
          {selectedTemplate.params.map((p) => (
            <div key={p.name} className="space-y-1">
              <Label htmlFor={`tpl-param-${p.name}`} className="text-xs">
                {p.label}
              </Label>
              <Input
                id={`tpl-param-${p.name}`}
                value={params[p.name] ?? ""}
                onChange={(e) =>
                  setParams((prev) => ({ ...prev, [p.name]: e.target.value }))
                }
                className="h-8 text-sm"
                placeholder={p.label}
              />
            </div>
          ))}
        </div>
      )}

      <Button
        size="sm"
        onClick={handleSend}
        disabled={!isValid || sending}
        className="w-full"
      >
        {sending ? (
          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
        ) : (
          <SendHorizonal className="h-4 w-4 mr-2" />
        )}
        Enviar plantilla
      </Button>
    </div>
  );
}
