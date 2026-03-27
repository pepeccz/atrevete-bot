"use client";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { TagInput } from "@/components/ui/tag-input";
import type { ServiceMetadata } from "@/lib/types";

// ---------- helpers ----------

const EMPTY_METADATA: ServiceMetadata = {
  family: null,
  audience: null,
  disambiguation_tags: [],
  ask_if_missing: [],
  variant: null,
  hair_length: null,
  hair_density: null,
  combo_recommendations: [],
};

// Normalize metadata to ensure all array fields are always arrays
const normalizeMetadata = (meta: ServiceMetadata | null | undefined): ServiceMetadata => {
  // Handle null/undefined by returning empty metadata
  if (!meta || typeof meta !== "object") {
    return EMPTY_METADATA;
  }

  // Arrays are guaranteed by ServiceMetadata type, but use Array.isArray as final safety check
  return {
    family: meta.family ?? null,
    audience: meta.audience ?? null,
    disambiguation_tags: Array.isArray(meta.disambiguation_tags)
      ? meta.disambiguation_tags
      : [],
    ask_if_missing: Array.isArray(meta.ask_if_missing)
      ? meta.ask_if_missing
      : [],
    variant: meta.variant ?? null,
    hair_length: meta.hair_length ?? null,
    hair_density: meta.hair_density ?? null,
    combo_recommendations: Array.isArray(meta.combo_recommendations)
      ? meta.combo_recommendations
      : [],
  };
};

const isPopulated = (meta: ServiceMetadata | null | undefined): boolean => {
  // Always safe to call normalizeMetadata since it handles null/undefined
  const normalized = normalizeMetadata(meta);

  // Check if any fields have meaningful values
  // All array fields are guaranteed to be arrays after normalization
  return !!(
    normalized.family ||
    normalized.audience ||
    normalized.variant ||
    normalized.hair_length ||
    normalized.hair_density ||
    (Array.isArray(normalized.disambiguation_tags) &&
      normalized.disambiguation_tags.length > 0) ||
    (Array.isArray(normalized.ask_if_missing) &&
      normalized.ask_if_missing.length > 0) ||
    (Array.isArray(normalized.combo_recommendations) &&
      normalized.combo_recommendations.length > 0)
  );
};

const VALID_ASK_IF_MISSING = ["hair_density", "hair_length"] as const;
type AskIfMissingValue = (typeof VALID_ASK_IF_MISSING)[number];

// ---------- props ----------

interface ServiceMetadataFormProps {
  value: ServiceMetadata | null;
  onChange: (value: ServiceMetadata) => void;
  disabled?: boolean;
}

// ---------- component ----------

export function ServiceMetadataForm({
  value,
  onChange,
  disabled = false,
}: ServiceMetadataFormProps) {
  const current = normalizeMetadata(value);
  const defaultOpen = isPopulated(value) ? "metadata" : undefined;

  const update = (partial: Partial<ServiceMetadata>) => {
    onChange({ ...current, ...partial });
  };

  return (
    <Accordion type="single" collapsible defaultValue={defaultOpen}>
      <AccordionItem value="metadata" className="border rounded-md px-3">
        <AccordionTrigger className="text-sm font-medium">
          Configuración de desambiguación
        </AccordionTrigger>
        <AccordionContent>
          <div className="space-y-4 pt-2">
            {/* Row 1: family + audience */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">Familia</Label>
                <Select
                  disabled={disabled}
                  value={current.family ?? "__none__"}
                  onValueChange={(v) =>
                    update({
                      family:
                        v === "__none__"
                          ? null
                          : (v as ServiceMetadata["family"]),
                    })
                  }
                >
                  <SelectTrigger className="h-8 text-sm">
                    <SelectValue placeholder="Sin valor" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">Sin valor</SelectItem>
                    <SelectItem value="haircut">haircut</SelectItem>
                    <SelectItem value="highlights">highlights</SelectItem>
                    <SelectItem value="hairstyle">hairstyle</SelectItem>
                    <SelectItem value="perm">perm</SelectItem>
                    <SelectItem value="color">color</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">Audiencia</Label>
                <Select
                  disabled={disabled}
                  value={current.audience ?? "__none__"}
                  onValueChange={(v) =>
                    update({
                      audience:
                        v === "__none__"
                          ? null
                          : (v as ServiceMetadata["audience"]),
                    })
                  }
                >
                  <SelectTrigger className="h-8 text-sm">
                    <SelectValue placeholder="Sin valor" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">Sin valor</SelectItem>
                    <SelectItem value="adult_female">adult_female</SelectItem>
                    <SelectItem value="adult_male">adult_male</SelectItem>
                    <SelectItem value="baby">baby</SelectItem>
                    <SelectItem value="child_male">child_male</SelectItem>
                    <SelectItem value="child_female">child_female</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Row 2: variant + hair_length + hair_density */}
            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">Variante</Label>
                <Select
                  disabled={disabled}
                  value={current.variant ?? "__none__"}
                  onValueChange={(v) =>
                    update({
                      variant:
                        v === "__none__"
                          ? null
                          : (v as ServiceMetadata["variant"]),
                    })
                  }
                >
                  <SelectTrigger className="h-8 text-sm">
                    <SelectValue placeholder="Sin valor" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">Sin valor</SelectItem>
                    <SelectItem value="standard">standard</SelectItem>
                    <SelectItem value="extra">extra</SelectItem>
                    <SelectItem value="long">long</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">
                  Largo de cabello
                </Label>
                <Select
                  disabled={disabled}
                  value={current.hair_length ?? "__none__"}
                  onValueChange={(v) =>
                    update({
                      hair_length:
                        v === "__none__"
                          ? null
                          : (v as ServiceMetadata["hair_length"]),
                    })
                  }
                >
                  <SelectTrigger className="h-8 text-sm">
                    <SelectValue placeholder="Sin valor" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">Sin valor</SelectItem>
                    <SelectItem value="short_medium">short_medium</SelectItem>
                    <SelectItem value="long">long</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">
                  Densidad de cabello
                </Label>
                <Select
                  disabled={disabled}
                  value={current.hair_density ?? "__none__"}
                  onValueChange={(v) =>
                    update({
                      hair_density:
                        v === "__none__"
                          ? null
                          : (v as ServiceMetadata["hair_density"]),
                    })
                  }
                >
                  <SelectTrigger className="h-8 text-sm">
                    <SelectValue placeholder="Sin valor" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">Sin valor</SelectItem>
                    <SelectItem value="normal">normal</SelectItem>
                    <SelectItem value="extra">extra</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Row 3: disambiguation_tags */}
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">
                Etiquetas de desambiguación
              </Label>
              <TagInput
                value={current.disambiguation_tags}
                onChange={(tags) => update({ disambiguation_tags: tags })}
                placeholder="Agregar etiqueta y presionar Enter..."
                disabled={disabled}
              />
            </div>

            {/* Row 4: ask_if_missing */}
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">
                Preguntar si falta (hair_density / hair_length)
              </Label>
              <TagInput
                value={current.ask_if_missing}
                onChange={(tags) =>
                  update({
                    ask_if_missing: tags.filter((v): v is AskIfMissingValue =>
                      VALID_ASK_IF_MISSING.includes(v as AskIfMissingValue)
                    ),
                  })
                }
                suggestions={VALID_ASK_IF_MISSING.filter(
                  (v) => !current.ask_if_missing.includes(v)
                )}
                disabled={disabled}
              />
            </div>

            {/* Row 5: combo_recommendations */}
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">
                Recomendaciones de combo (nombres de servicios)
              </Label>
              <TagInput
                value={current.combo_recommendations}
                onChange={(tags) => update({ combo_recommendations: tags })}
                placeholder="Nombre del servicio y presionar Enter..."
                disabled={disabled}
              />
            </div>
          </div>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
